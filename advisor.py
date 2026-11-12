"""The advisor: George asks the other engine for a second opinion on the current work.

Only a line George types starts it: /advisor in a chat, or --advisor on the command line.
The working model has no way to call it: it is not a tool, it is on no card and on no page.

One call, to the other engine, with no session history, no operator pages and no web tools.
The advice is shown to George under a fixed label. It is then saved after the latest exchange as
an advisor_note data message (storage.advisor_note), which the working model reads on its next turn.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import time

import anthropic
from openai import (OpenAI, APIConnectionError, APIStatusError, APITimeoutError,
                    AuthenticationError, PermissionDeniedError, RateLimitError)

import harness as h
from lookup_gate import violation as lookup_violation
from storage import Store, atomic_json, clip_stream, now

TRIGGER = '/advisor'
SYSTEM_PROMPT = ("You are an outside reviewer of another model's work. State the root cause, then the next command or fix. "
                 "At most three short bullets. No greeting, no praise, no reassurance.")
LABEL = 'Advisor ({model}):'
# The packet is refused above this size, before any API call. Nothing is cut to fit. 600,000 characters is about
# 200,000 tokens: it fits the smaller window measured live on 2026-11-11 (gpt-6.1-sol took 380,000 input tokens)
# with room for the answer. Each output stream inside it is clipped by storage.clip_stream, as the working model saw it.
PACKET_CAP_CHARS = 600000
DEFAULT_TURNS = 3
MAX_BULLETS = 3
MAX_ADVICE_CHARS = 16000    # The same ceiling the working model's direct_answer has.
BULLET = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s+', re.MULTILINE)
SENTENCE_END = re.compile(r'(?<=[.!?:])\s+')
CONTINUATION = 'Continue the original task using the recorded execution observation.'


def is_trigger(line):
    """True for a chat line that is /advisor, or that starts with /advisor and a space."""
    return line == TRIGGER or line.startswith(TRIGGER + ' ') or line.startswith(TRIGGER + '\t')


def chat_arguments(line, args):
    """The command-line form of a typed /advisor line. The = keeps a question that starts with a dash intact."""
    return ['--advisor-turns', str(args.advisor_turns), '--advisor=' + line[len(TRIGGER):].strip()]


def add_flags(parser):
    parser.add_argument('--advisor', nargs='?', const='', default=None, metavar='QUESTION',
                        help='Ask the other engine for a second opinion on a saved session; needs -c or --session. In chat: /advisor QUESTION.')
    parser.add_argument('--advisor-turns', type=int, default=DEFAULT_TURNS,
                        help='Exchanges put in the advisor packet (1–50; default 3).')


def validate_args(parser, args):
    if not 1 <= args.advisor_turns <= 50:
        parser.error('--advisor-turns must be between 1 and 50.')
    if args.advisor is None:
        return
    if not (args.continuing or args.session):
        parser.error('--advisor reviews a saved session; add -c or --session NAME.')
    if args.text or args.listen or args.recall is not None or args.chat or args.images or args.files:
        parser.error('--advisor takes only its own question; in chat, type /advisor.')


def other_lane(engine):
    """The engine and model that give the second opinion: always the lane George is not working in."""
    if engine == 'anthropic':
        return 'openai', os.environ.get('OPENAI_MODEL') or h.DEFAULT_MODEL
    return 'anthropic', os.environ.get('ANTHROPIC_MODEL') or h.ANTHROPIC_MODEL


def current_task(turns, first_request):
    """The loop's original task when the latest exchange is a loop step; otherwise the session's first request."""
    if turns and turns[-1].get('loop_step'):
        for exchange in reversed(turns):
            if exchange.get('loop_step') == 1:
                return exchange['normalized_input'], 'loop_original_task'
            if not exchange.get('loop_step'):
                break
    return first_request, 'session_first_request'


def first_request(store, session_id, turns):
    row = store.db.execute("SELECT normalized_input, raw_input FROM history WHERE session_id=? AND status NOT LIKE 'advisor%' "
                           "ORDER BY id LIMIT 1", (session_id,)).fetchone()
    if row is not None:
        return row[0] or row[1]
    return turns[0]['normalized_input']


def packet_exchange(exchange):
    record = {'input': exchange['normalized_input'],
              'input_kind': 'loop_continuation' if exchange['normalized_input'].startswith(CONTINUATION) else 'operator',
              'reply': dict(exchange['reply'])}
    result = exchange.get('execution_result')
    if result is not None:
        clipped = []
        streams = {}
        for name in ('stdout', 'stderr'):
            value = result.get(name, '')
            value = value if isinstance(value, str) else ''
            shown = clip_stream(value)
            if shown != value:
                clipped.append(name)
            streams[name] = shown
        record['command_result'] = {'command': exchange['reply']['execution_payload'], 'approved': result.get('approved'),
                                    'exit_code': result.get('exit_code'), 'timed_out': bool(result.get('timed_out')),
                                    **streams, 'clipped_streams': clipped}
    if exchange.get('advisor_notes'):
        record['earlier_advisor_notes'] = [{'model': note['model'], 'text': note['text']} for note in exchange['advisor_notes']]
    return record


def build_packet(session, store, *, question, turns, working_engine, working_model):
    """The packet text and the task it names. Built by code alone. Raises when it is over the cap."""
    exchanges = session['turns']
    task, kind = current_task(exchanges, first_request(store, session['id'], exchanges))
    packet = {'type': 'advisor_packet', 'working_engine': working_engine, 'working_model': working_model,
              'task': task, 'task_kind': kind,
              'exchanges': [packet_exchange(exchange) for exchange in exchanges[-turns:]],
              'operator_question': question or None}
    text = json.dumps(packet, ensure_ascii=False)
    if len(text) > PACKET_CAP_CHARS:
        fix = 'Use a smaller --advisor-turns.' if len(packet['exchanges']) > 1 else 'The latest exchange alone is over the cap.'
        raise h.HarnessError(f'The advisor packet is {len(text)} characters; the cap is {PACKET_CAP_CHARS}. ' + fix)
    return text, task


def drop_filler(text):
    """Remove canned openers and every sentence that holds blocked filler. Other sentences stay as written."""
    lines = []
    for line in text.split('\n'):
        mark = h._LIST_MARK.match(line)
        head, body = (mark.group(1), line[mark.end():]) if mark else ('', line)
        kept = []
        for sentence in SENTENCE_END.split(body):
            core = sentence.strip()
            opener = h.OPENING_FILLER.match(h.OPENING_MARKUP.sub('', core).strip())
            if opener:
                core = h.OPENING_MARKUP.sub('', core).strip()[opener.end():].lstrip()
            if core and not h.FILLER.search(core):
                kept.append(core if opener else sentence)
        body_kept = ' '.join(part for part in kept if part.strip())
        if body.strip() and not body_kept.strip():
            continue
        lines.append(head + body_kept if body.strip() else line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def clean_advice(text, asked='', allowed_text=''):
    """Every display gate, applied to the advisor's plain text. Returns the text George may see."""
    if h.CONTROLS.search(text):
        raise h.GateError('The advisor reply contains terminal control characters.')
    # Filler first, bullet by bullet, so a canned opener inside a bullet goes and the bullet mark stays.
    cleaned = drop_filler(text)
    cleaned = h.scrub_opening(cleaned) if cleaned else cleaned
    cleaned = h.strip_reassurance(cleaned, asked) if cleaned else cleaned
    if not cleaned.strip():
        raise h.OpeningScrubError('Nothing was left of the advisor reply after cleanup. It was not shown.')
    if len(cleaned) > MAX_ADVICE_CHARS:
        raise h.GateError(f'The advisor reply exceeds {MAX_ADVICE_CHARS} characters.')
    bullets = len(BULLET.findall(cleaned))
    if bullets > MAX_BULLETS:
        raise h.GateError(f'The advisor reply has {bullets} bullets; the limit is {MAX_BULLETS}.')
    if h.claims_completion(cleaned):
        raise h.GateError('The advisor reply reports completed work, but the advisor ran nothing.')
    reason = lookup_violation(cleaned, {'total': 0}, [], allowed_text)
    if reason:
        raise h.GateError('The advisor has no web tools. ' + reason)
    return cleaned


def make_client(engine, timeout):
    if engine == 'openai':
        return OpenAI(api_key=h.load_key(engine), base_url='https://api.openai.com/v1', timeout=timeout, max_retries=0)
    return anthropic.Anthropic(api_key=h.load_key(engine), base_url='https://api.anthropic.com', timeout=timeout, max_retries=0)


def send(client, engine, model, effort, messages):
    """One stateless call: the reviewer prompt and the packet. No tools, no pages, no history, no temperature.

    Both providers refuse a temperature setting on these models (checked live on 2026-11-11), so none is sent.
    """
    if engine == 'openai':
        response = client.responses.create(model=model, instructions=SYSTEM_PROMPT, input=messages,
                                           reasoning={'effort': effort}, max_output_tokens=h.MAX_OUTPUT_TOKENS, store=False)
        for output in response.output:
            if getattr(output, 'type', None) == 'message':
                if any(getattr(item, 'type', None) == 'refusal' for item in output.content):
                    return response, 'refusal', ''
        if response.status != 'completed':
            return response, 'incomplete', ''
        return response, None, response.output_text or ''
    response = client.messages.create(model=model, max_tokens=h.MAX_OUTPUT_TOKENS, thinking={'type': 'adaptive'},
                                      output_config={'effort': effort}, system=SYSTEM_PROMPT, messages=messages)
    if response.stop_reason == 'refusal':
        return response, 'refusal', ''
    if response.stop_reason == 'max_tokens':
        return response, 'incomplete', ''
    return response, None, ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')


def request_advice(packet_text, *, engine, model, effort, timeout, asked='', client=None, log_path=None, events=None):
    """Ask the other engine once. A reply that fails a display gate gets one corrected try, as in the working lane."""
    client = client or make_client(engine, timeout)
    messages = [{'role': 'user', 'content': packet_text}]
    for attempt in (1, 2):
        started = time.monotonic()
        event = {'time_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'advisor', 'engine': engine,
                 'model_requested': model, 'effort': effort, 'attempt': attempt, 'packet_chars': len(packet_text),
                 'packet_sha256': hashlib.sha256(packet_text.encode('utf-8')).hexdigest(), 'status': 'pending'}
        try:
            response, problem, text = send(client, engine, model, effort, messages)
            event['response_id'] = getattr(response, 'id', None)
            event['model_returned'] = getattr(response, 'model', None)
            usage = getattr(response, 'usage', None)
            if usage is not None:
                event['usage'] = usage.model_dump(exclude_none=True)
            if problem == 'refusal':
                event['status'] = 'refusal'
                raise h.HarnessError('The advisor refused this request.')
            if problem == 'incomplete':
                event['status'] = 'incomplete'
                raise h.HarnessError('The advisor reply was incomplete. It was not shown.')
            try:
                advice = clean_advice(text, asked, packet_text)
            except h.OpeningScrubError:
                event['status'] = 'empty_after_scrub'
                raise
            except h.GateError as exc:
                event['status'] = 'gate_rejected'
                event['gate_reason'] = str(exc)
                if attempt == 2:
                    raise h.HarnessError('Both advisor replies failed the output gate. No advice was shown.') from exc
                messages = [*messages, {'role': 'user', 'content': 'Local validation rejected the reply: ' + str(exc) +
                                        ' Return a corrected reply to the same packet. Preserve facts and meaning.'}]
                continue
            event['status'] = 'accepted'
            event['advice_chars'] = len(advice)
            return advice
        except (AuthenticationError, anthropic.AuthenticationError) as exc:
            event['status'] = 'authentication_error'
            raise h.HarnessError("The advisor's API key was rejected.") from exc
        except (PermissionDeniedError, anthropic.PermissionDeniedError) as exc:
            event['status'] = 'permission_error'
            raise h.HarnessError('This API account cannot access the advisor model.') from exc
        except (RateLimitError, anthropic.RateLimitError) as exc:
            event['status'] = 'quota_or_rate_limit'
            raise h.HarnessError("The advisor's API reports a billing quota or rate limit.") from exc
        except (APITimeoutError, anthropic.APITimeoutError) as exc:
            event['status'] = 'timeout'
            raise h.HarnessError('The advisor request timed out.') from exc
        except (APIConnectionError, anthropic.APIConnectionError) as exc:
            event['status'] = 'connection_error'
            raise h.HarnessError('The advisor API connection failed.') from exc
        except (APIStatusError, anthropic.APIStatusError) as exc:
            event['status'] = 'api_error'
            event['http_status'] = exc.status_code
            event['provider_error'] = getattr(exc, 'body', None)
            raise h.HarnessError(f'The advisor API rejected the request (HTTP {exc.status_code}).') from exc
        finally:
            event['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            h.record_event(event, log_path)
            if events is not None:
                events.append(event)
    raise h.HarnessError('No advice was produced.')


def run(args, working_model):
    """--advisor, and /advisor in chat. Shows the advice, saves the note and one history row. Never calls the working model."""
    question = (args.advisor or '').strip()
    typed = TRIGGER + (' ' + question if question else '')
    store = None
    row_id = None
    events = []
    try:
        store = Store(h.STATE)
        session_id = store.select_session(args.session, args.continuing)
        with store.session(session_id, args.turns) as session:
            if not session['turns']:
                raise h.HarnessError('Nothing to review yet: this session has no exchange.')
            packet, task = build_packet(session, store, question=question, turns=args.advisor_turns,
                                        working_engine=args.engine, working_model=working_model)
            engine, model = other_lane(args.engine)
            row_id = store.begin(typed, question, engine, model, session_id)
            advice = request_advice(packet, engine=engine, model=model, effort=args.effort, timeout=args.timeout,
                                    asked=' '.join(part for part in (question, task) if part),
                                    log_path=args.usage_log, events=events)
            sys.stdout.write(LABEL.format(model=model) + '\n' + advice + '\n')
            sys.stdout.flush()
            session['turns'][-1].setdefault('advisor_notes', []).append(
                {'model': model, 'engine': engine, 'text': advice, 'question': question, 'created_at': now()})
            session['updated_at'] = now()
            atomic_json(store.sessions / (session_id + '.json'), session)
            store.finish(row_id, None, events, status='advisor')
            with store.db:
                store.db.execute('UPDATE history SET direct_answer=? WHERE id=?', (advice, row_id))
        return 0
    except KeyboardInterrupt:
        if store and row_id:
            store.finish(row_id, None, events, error='Stopped.', status='advisor_error')
        print('Stopped.', file=sys.stderr)
        return 130
    except (h.HarnessError, ValueError) as exc:
        if store and row_id:
            store.finish(row_id, None, events, error=str(exc), status='advisor_error')
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        message = f'Unexpected advisor error ({type(exc).__name__}).'
        if store and row_id:
            try:
                store.finish(row_id, None, events, error=message, status='advisor_error')
            except Exception:
                pass
        print(message, file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()
