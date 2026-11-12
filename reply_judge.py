"""The judge: a second model, on the other engine, reads each reply before George sees it.

After a reply passes the local gate, one stateless call goes to the other engine (from george to
gpt-6.1-sol, from g1 to claude-opus-5-5). It carries a fixed prompt and one packet: George's request,
the command results recorded for this request, the past-chat notes the client attached to it, and the reply.
No session history, no operator pages,
no tools. The answer is strict JSON: {"verdict": "pass" | "fail", "reason": "..."}.

A fail gives the working model one corrective retry that carries the judge's reason. The second reply
is shown whatever the judge says about it; George never gets an empty screen because of the judge.
A judge error, a timeout, a refusal or an answer that is not the strict JSON passes the reply through.
The judge has JUDGE_SECONDS (120) to answer; a slow judge never holds a finished reply longer than that.
Every verdict is saved with the turn: history.db column gate_json, and the session exchange under "judge".

/off judge and /on judge flip the switch (switches.json in the lane's state folder). It ships on.
The judge runs only under the command-line entry point (second_gate.switch_on), so unit tests that
import the client never call a model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import anthropic
from openai import APITimeoutError

import advisor
import gate_admin
import gate_rules
import harness as h
from lookup_gate import turn_metadata
from storage import atomic_json, clip_stream

LIVE = False            # second_gate.switch_on sets it for a real command-line run
SWITCH_FILE = 'switches.json'
SWITCH = 'judge'
LOG_NAME = 'judge.jsonl'
# The packet is refused above this size and the reply passes through unjudged. It matches the advisor's cap:
# about 200,000 tokens, inside the smaller window measured live on 2026-11-11.
PACKET_CAP_CHARS = 600000
OLD_STREAM_CHARS = 4000  # when the packet is over the cap, earlier steps keep this much of each end of a stream
MAX_REASON_CHARS = 1000
# The judge's own time ceiling, in seconds. Past it the reply is shown unjudged (status "timeout").
# Live on 2026-11-11, 36 verdicts took 2 to 44 seconds; one, at max effort, thought for 223 seconds over a
# one-line answer that the working model had produced in 12. The lane's --timeout still applies when it is lower.
JUDGE_SECONDS = 120
SCHEMA = {'type': 'object',
          'properties': {'verdict': {'type': 'string', 'enum': ['pass', 'fail']}, 'reason': {'type': 'string'}},
          'required': ['verdict', 'reason'], 'additionalProperties': False}
SYSTEM_PROMPT = """You are the second check on a reply that another model wrote for George, who runs a command-line assistant on his phone. The reply has already passed a filter made of wording patterns. Your job is the four failures that patterns cannot see. George reads the reply only after you have judged it.

The user message is one JSON object, the packet:
- request: what George typed. It is the whole job for this turn.
- command_results: every shell command the client ran for this request so far, in order, each with its exit code and output. tool_uses lists other tool calls the client recorded. Together they are the only record of work done in this turn.
- recall_notes: passages from George's saved past chats that the client found by a keyword search in code and attached to this request before the working model answered; null when it attached none. The working model read them. They are part of this turn's record: a statement about what the past-chat search found is checked against them.
- reply: the reply under review. direct_answer is what George will read. execution_payload, when it is not null, is a shell command the client runs next; the reply is then a step in progress and the final answer comes later.
- context: what the client knows about this turn.

Fail the reply when one of these is true:
1. Wrong question. direct_answer answers a different question than the request asks, or does a different job than the request orders.
2. Unsupported claim. direct_answer states a result of this turn's work, such as what a command printed, what a file holds, a count, or that something worked, and command_results and tool_uses do not show it or they contradict it.
3. Unasked limit. The reply adds a limit, a warning, an off switch or a question that George did not ask for. This covers doing a smaller or more cautious version of the job than the one he ordered, and asking his leave for work he already ordered. A question about a fact the work cannot go on without is fine.
4. Intent in place of work. The reply reports agreement or a plan ("I will...", "Understood", "Good idea") where the request called for the work itself, and execution_payload is null, so nothing will run.

Pass everything else. Tone, length, style and wording are not your concern, and neither is a better way to do the job.

What you cannot see: the earlier conversation, George's standing pages (his rules, his profile, his lessons), any attached picture or file, and what the working model's own web lookups returned (context.web_lookups counts the hosted lookups of this turn and context.web_sources lists the addresses they gave; a lookup such as a weather or a price lookup can return no address). A statement that could rest on one of those is not an unsupported claim. When the request points at the earlier conversation ("do that again", "the second one") and context.earlier_conversation is true, you cannot check failure 1; pass on that point.
George's standing rules tell the working model to share a useful idea after the answer, with its confidence and its main catch. An idea offered that way, after the work is done, is not an unasked limit, warning or question, and its catch is not a warning.
context.client_removed lists sentences the client cut from the reply under George's standing rules. Their absence is correct, even when the request asked for them.
A reply whose execution_payload moves the request forward is doing the work. Do not fail it for lacking the final answer.
When you are unsure, pass. A wrong fail costs George a slower answer.

Return only the JSON object. On a fail, reason is one plain sentence for the working model: name the failure and say what the corrected reply must do. On a pass, reason is "ok"."""
CORRECTION = ('A second reviewer on another model read the reply before the operator saw it, and failed it: {reason} '
              'Return a corrected four-field reply for the original request. Do the work the request asks for. '
              'Keep every fact the recorded results support. Do not mention the reviewer.')


def switches(state) -> dict:
    """The saved switches. A missing or unreadable file is an empty set: everything is at its shipped state."""
    try:
        data = json.loads((Path(state) / SWITCH_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_on(state) -> bool:
    """On unless the switches file says exactly false."""
    return switches(state).get(SWITCH) is not False


def set_switch(state, on: bool) -> None:
    """Save the switch. Every other key in the file is kept as it is."""
    data = switches(state)
    data[SWITCH] = bool(on)
    atomic_json(Path(state) / SWITCH_FILE, data)


def turn_exchanges(turns: list, step: int, loop: bool) -> list:
    """The exchanges of this request that came before the reply under review: the earlier steps of this loop run."""
    if loop:
        return list(turns[-(step - 1):]) if step > 1 else []
    return []


def command_result(exchange: dict, number: int, limit: int | None = None) -> dict | None:
    result = exchange.get('execution_result')
    if not isinstance(result, dict):
        return None
    record = {'step': number, 'command': exchange['reply'].get('execution_payload'), 'approved': result.get('approved'),
              'exit_code': result.get('exit_code'), 'timed_out': bool(result.get('timed_out'))}
    clipped = []
    for name in ('stdout', 'stderr'):
        value = result.get(name, '')
        value = value if isinstance(value, str) else ''
        shown = clip_stream(value)
        if limit is not None and len(shown) > 2 * limit:
            shown = (shown[:limit] + f'\n[... {len(shown) - 2 * limit} characters omitted here; the start and the end are kept ...]\n'
                     + shown[-limit:])
        if shown != value:
            clipped.append(name)
        record[name] = shown
    record['clipped_streams'] = clipped
    return record


def tool_receipts(records) -> list:
    """Tool-use receipts as the client recorded them, with very long text fields cut in the middle."""
    def clip(value):
        if isinstance(value, str) and len(value) > 20000:
            return value[:10000] + f'\n[... {len(value) - 20000} characters omitted ...]\n' + value[-10000:]
        if isinstance(value, dict):
            return {key: clip(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clip(item) for item in value]
        return value
    return [clip(record) for record in records or [] if isinstance(record, dict)]


def recall_record(message) -> dict | None:
    """This turn's recall_notes message as data for the packet: the words searched and the passages found."""
    try:
        data = json.loads(message) if isinstance(message, str) else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get('passages'):
        return None
    return {'searched_words': data.get('searched_words'), 'passages': data['passages']}


def build_packet(*, request: str, reply, earlier: list, metadata: dict, loop: bool, step: int,
                 earlier_conversation: bool, attachments: int, removed: list, recall=None) -> str | None:
    """The packet text, or None when it cannot fit under the cap."""
    def assemble(limit):
        results = [record for number, exchange in enumerate(earlier, 1)
                   for record in [command_result(exchange, number, None if number == len(earlier) else limit)] if record]
        uses = [use for exchange in earlier for use in exchange.get('api_tool_uses') or []] + list(metadata.get('api_tool_uses') or [])
        return json.dumps({
            'type': 'judge_packet', 'request': request, 'command_results': results, 'tool_uses': tool_receipts(uses),
            'recall_notes': recall_record(recall), 'reply': reply.model_dump(),
            'context': {'agent_loop': bool(loop), 'model_turn': step, 'earlier_conversation': bool(earlier_conversation),
                        'attachments_you_cannot_see': attachments,
                        'web_sources': [source.get('url') for source in metadata.get('sources') or []][:40],
                        'web_lookups': int((metadata.get('lookup_counts') or {}).get('total') or 0),
                        'client_removed': removed}}, ensure_ascii=False)
    text = assemble(None)
    if len(text) > PACKET_CAP_CHARS:
        text = assemble(OLD_STREAM_CHARS)
    return text if len(text) <= PACKET_CAP_CHARS else None


def send(client, engine: str, model: str, effort: str, packet_text: str):
    """One stateless call: the judge prompt and the packet. No tools, no pages, no history. Strict JSON out."""
    messages = [{'role': 'user', 'content': packet_text}]
    if engine == 'openai':
        response = client.responses.create(
            model=model, instructions=SYSTEM_PROMPT, input=messages, reasoning={'effort': effort},
            max_output_tokens=h.MAX_OUTPUT_TOKENS, store=False,
            text={'format': {'type': 'json_schema', 'name': 'judge_verdict', 'strict': True, 'schema': SCHEMA}})
        for output in response.output:
            if getattr(output, 'type', None) == 'message':
                if any(getattr(item, 'type', None) == 'refusal' for item in output.content):
                    return response, 'refusal', ''
        if response.status != 'completed':
            return response, 'incomplete', ''
        return response, None, response.output_text or ''
    response = client.messages.create(
        model=model, max_tokens=h.MAX_OUTPUT_TOKENS, thinking={'type': 'adaptive'}, system=SYSTEM_PROMPT, messages=messages,
        output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': SCHEMA}})
    if response.stop_reason == 'refusal':
        return response, 'refusal', ''
    if response.stop_reason == 'max_tokens':
        return response, 'incomplete', ''
    return response, None, ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')


def parse_verdict(text: str) -> tuple[str, str]:
    """The verdict and the reason, from strict JSON only. Anything else raises ValueError."""
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'verdict', 'reason'}:
        raise ValueError('wrong fields')
    if value['verdict'] not in ('pass', 'fail') or not isinstance(value['reason'], str):
        raise ValueError('wrong values')
    reason = ' '.join(value['reason'].split())[:MAX_REASON_CHARS]
    if value['verdict'] == 'fail' and not reason:
        raise ValueError('a fail needs a reason')
    if h.CONTROLS.search(reason):
        raise ValueError('control characters')
    return value['verdict'], reason


def ask(packet_text: str, *, engine: str, model: str, effort: str, timeout: float, client=None, log_path=None) -> dict:
    """Ask the judge once. Never raises for a judge failure: the record's status says what happened."""
    started = time.monotonic()
    record = {'engine': engine, 'model': model, 'verdict': None, 'reason': '', 'status': 'pending'}
    event = {'time_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'judge', 'engine': engine, 'model_requested': model,
             'effort': effort, 'packet_chars': len(packet_text),
             'packet_sha256': hashlib.sha256(packet_text.encode('utf-8')).hexdigest()}
    try:
        client = client or advisor.make_client(engine, timeout)
        response, problem, text = send(client, engine, model, effort, packet_text)
        event['response_id'] = getattr(response, 'id', None)
        event['model_returned'] = getattr(response, 'model', None)
        usage = getattr(response, 'usage', None)
        if usage is not None:
            record['usage'] = event['usage'] = usage.model_dump(exclude_none=True)
        if problem:
            record['status'] = problem
        else:
            record['verdict'], record['reason'] = parse_verdict(text)
            record['status'] = 'ok'
    except (APITimeoutError, anthropic.APITimeoutError):
        record['status'] = 'timeout'
    except ValueError:
        record['status'] = 'not_strict_json'
    except h.HarnessError as exc:
        record.update(status='error', error=str(exc))
    except Exception as exc:  # any provider or network failure passes the reply through
        code = getattr(exc, 'status_code', None)
        record.update(status='error', error=type(exc).__name__ + (f' (HTTP {code})' if code else ''))
        body = getattr(exc, 'body', None)
        if body is not None:
            event['provider_error'] = body
    finally:
        record['latency_ms'] = event['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        event['status'], event['verdict'] = record['status'], record['verdict']
        try:
            h.record_event(event, Path(log_path).with_name(LOG_NAME) if log_path else h.STATE / LOG_NAME)
        except OSError:
            pass
    return record


class Second:
    """One per client run. request_reply() is harness.request_reply with the judge behind it."""

    def __init__(self, judge=None):
        self.judge = judge  # a stand-in for ask(), for tests and the live proof
        self.records: list = []
        self.fired: list = []

    def active(self) -> bool:
        return LIVE and is_on(h.STATE)

    def verdict(self, reply, kwargs: dict, turn: dict, events: list) -> dict:
        engine, model = advisor.other_lane(kwargs.get('engine', 'openai'))
        turns, step, loop = turn.get('turns') or [], int(turn.get('step') or 1), bool(turn.get('loop'))
        earlier = turn_exchanges(turns, step, loop)
        # The past-chat notes the client attached to this request: at step 1 they come with the turn, later from the saved step.
        recall = turn.get('recall_notes') or next((exchange['recall_notes'] for exchange in earlier if exchange.get('recall_notes')), None)
        packet = build_packet(
            request=kwargs.get('request_context') or turn['current'], reply=reply, earlier=earlier,
            metadata=turn_metadata(events), loop=loop, step=step,
            earlier_conversation=len(turns) > len(earlier),
            attachments=len(kwargs.get('attachments') or []) + sum(
                len((exchange.get('execution_result') or {}).get('attachments') or []) + len(exchange.get('attachments') or [])
                for exchange in earlier),
            removed=[item['text'] for item in self.fired if item.get('action') == 'strip_sentence'], recall=recall)
        if packet is None:
            return {'engine': engine, 'model': model, 'verdict': None, 'reason': '', 'status': 'packet_over_cap'}
        return (self.judge or ask)(packet, engine=engine, model=model, effort=kwargs.get('effort', h.DEFAULT_EFFORT),
                          timeout=min(float(kwargs.get('timeout', 90)), JUDGE_SECONDS), log_path=kwargs.get('log_path'))

    def request_reply(self, current: str, *, judge_turn: dict | None = None, **kwargs):
        gate_rules.drain()
        self.records, self.fired = [], []
        reply = h.request_reply(current, **kwargs)
        self.fired = gate_rules.drain()
        if judge_turn is None or not self.active():
            return reply
        events = kwargs.get('events')
        events = events if events is not None else []
        turn = {**judge_turn, 'current': current}
        first = self.verdict(reply, kwargs, turn, events)
        self.records.append({**first, 'reply': 1})
        if first['verdict'] != 'fail':
            return reply
        # One corrective retry. The first reply and the judge's reason ride at the tail; the cached front is unchanged.
        asked = {'role': 'user', 'content': current}
        if kwargs.get('attachments'):
            asked['attachments'] = kwargs['attachments']
        retry = {**kwargs, 'attachments': None, 'events': [],
                 'history': [*(kwargs.get('history') or []), asked,
                             {'role': 'assistant', 'content': json.dumps(reply.model_dump(), ensure_ascii=False)}]}
        runtime = kwargs.get('api_runtime')
        if runtime is not None and getattr(runtime, 'has_work', False):
            retry['execution_confirmed'] = bool(runtime.successful_work)
        if judge_turn.get('renew'):
            retry.update(judge_turn['renew']())
        kept_fired = list(self.fired)
        try:
            second = h.request_reply(CORRECTION.format(reason=first['reason']), **retry)
        except h.HarnessError as exc:
            # The corrected reply did not arrive or did not pass the local gate. The first reply stands.
            gate_rules.drain()
            events[:0] = retry['events']
            self.records[-1]['retry_error'] = str(exc)
            return reply
        events.extend(retry['events'])
        self.fired = kept_fired + gate_rules.drain()
        again = self.verdict(second, kwargs, turn, events)
        self.records.append({**again, 'reply': 2})
        return second

    def record(self, store, row_id, exchange: dict) -> None:
        """Save the verdicts and the rules that fired with the turn: the history row and the session exchange."""
        data = {}
        if self.records:
            data['judge'] = exchange['judge'] = self.records
        if self.fired:
            data['rules_fired'] = exchange['gate_rules_fired'] = self.fired
        if not data:
            return
        try:
            gate_admin.update_gate(store.db, row_id, **data)
        except sqlite3.Error:
            print('The judge record could not be saved to history.', file=sys.stderr)


def typed(args) -> int | None:
    """/on judge or /off judge typed as the whole question. None for any other input."""
    if not args.text or args.listen:
        return None
    return chat_switch(' '.join(args.text).strip(), h.STATE)


def chat_switch(line: str, state) -> int | None:
    """/on judge and /off judge. One line on stderr, no model call. None for any other line."""
    words = line.split()
    if len(words) != 2 or words[0] not in ('/on', '/off') or words[1].lower() != SWITCH:
        return None
    try:
        set_switch(state, words[0] == '/on')
    except OSError:
        print('The switches file cannot be written.', file=sys.stderr)
        return 2
    print('judge on.' if words[0] == '/on' else 'judge off.', file=sys.stderr)
    return 0
