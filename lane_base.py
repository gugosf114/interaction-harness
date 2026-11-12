"""The shared half of every extra lane: keys, knob notes, and the gate loop.

A lane module (gemini_lane, openrouter_lane, glm_lane, vertex_lane) supplies one
function, `send(lane, call)`, that makes the provider request and returns a
`Sent`. Everything else here is common: the frozen prefix, the tools page, the
operator's pages, history, the four-field validation, the lookup gate, the
prefill check, and the usage record. Only the wire call differs per provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Callable, Optional

import knobs as knobs_mod


class LaneError(Exception):
    """A short, user-visible lane failure."""


@dataclass(frozen=True)
class Lane:
    engine: str
    shortcut: str
    default_model: str
    send: Callable                    # send(lane, call) -> Sent
    reply_mode: str = 'json'          # 'json': strict four fields; 'wrap': plain text wrapped as an observation
    base_url: str = ''
    key_env: Optional[str] = None
    key_file: Optional[str] = None    # None and key_env None: no key (public endpoint or gcloud token)
    base_env: Optional[str] = None
    base_file: Optional[str] = None
    model_env: Optional[str] = None
    model_file: Optional[str] = None
    web: str = ''                     # name of the provider's hosted web tool, '' when it has none
    images: bool = False
    pdfs: bool = False
    min_timeout: float = 0            # a lane that cold-starts needs at least this many seconds


@dataclass
class Call:
    """One provider request, already assembled by the gate loop."""
    model: str
    effort: str
    timeout: float
    system_pages: list
    base_count: int                   # frozen prefix + tools page; the operator's pages follow
    messages: list                    # user/assistant messages, attachments still as records
    raw_input: str
    schema: dict
    knobs: knobs_mod.Knobs
    web: bool
    web_max: int
    client: object = None
    notes: list = field(default_factory=list)


@dataclass
class Sent:
    raw_json: str
    usage: dict = field(default_factory=dict)
    response_id: Optional[str] = None
    sources: list = field(default_factory=list)
    search: int = 0
    fetch: int = 0
    provider_report: Optional[dict] = None


NO_WEB_NOTE = ('This lane has no hosted web search or page fetch this turn. Never say you searched, '
               'browsed, fetched or looked something up, and never invent a URL. Return the four required fields.')
WEB_NOTE = ('This lane has a hosted web search this turn. Use it when the request needs current facts. '
            'The client prints the sources it records; never write a Sources section, and write a URL only '
            'when it came back from the search. Return the four required fields.')


def lane_note(lane: Lane, web: bool) -> str:
    return WEB_NOTE if (web and lane.web) else NO_WEB_NOTE


# ---- keys, endpoints, models ---------------------------------------------

def key_dir() -> Path:
    # Keys live in this installation's state folder even when HARNESS_STATE_DIR points tests elsewhere.
    import harness as h
    return (h.ROOT / 'state') if os.environ.get('HARNESS_STATE_DIR') else h.STATE


def read_private(path: Path) -> Optional[str]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise LaneError('A saved lane setting must be a private regular file (mode 600).')
    value = path.read_text().strip()
    return value or None


def _setting(env, filename, default):
    if env and os.environ.get(env, '').strip():
        return os.environ[env].strip()
    if filename:
        saved = read_private(key_dir() / filename)
        if saved:
            return saved
    return default


def lane_base_url(lane: Lane) -> str:
    return _setting(lane.base_env, lane.base_file, lane.base_url)


def lane_model(lane: Lane, requested: Optional[str] = None) -> str:
    return requested or _setting(lane.model_env, lane.model_file, lane.default_model)


def needs_key(lane: Lane) -> bool:
    return bool(lane.key_env or lane.key_file)


def lane_key(lane: Lane) -> Optional[str]:
    if not needs_key(lane):
        return None
    value = _setting(lane.key_env, lane.key_file, '')
    if not value:
        raise LaneError(f'No key for the {lane.engine} lane. Export {lane.key_env}, then run '
                        f'python ~/interaction-harness/save_lane_key.py {lane.engine}.')
    if '\n' in value or '\r' in value:
        raise LaneError('The lane key contains a line break.')
    return value


def effort_level(effort: str) -> str:
    """low/medium/high for providers that stop at high."""
    return {'low': 'low', 'medium': 'medium'}.get(effort, 'high')


# ---- knob notes ------------------------------------------------------------

def say_once(call: Call, line: str) -> None:
    if line not in call.notes:
        call.notes.append(line)
        print(line, file=sys.stderr)


def knob_refused(call: Call, lane: Lane, name: str, message: str) -> None:
    say_once(call, f'[{lane.engine}] knob --{name.replace("_", "-")} refused: {" ".join(str(message).split())[:400]}')


def drop_refused(call: Call, lane: Lane, sent_knobs: dict, message: str, tokens: dict) -> Optional[str]:
    """A provider 400 names a field: find which sent knob it is, report it once, and
    return its name so the caller can resend without it. None when no sent knob is named."""
    low = str(message).lower()
    for name in list(sent_knobs):
        if any(token in low for token in tokens.get(name, (name,))):
            knob_refused(call, lane, name, message)
            sent_knobs.pop(name)
            return name
    return None


# ---- raw HTTPS -------------------------------------------------------------

class ProviderHTTPError(Exception):
    def __init__(self, status: int, body: str, headers=None):
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        super().__init__(f'HTTP {status}: {provider_message(body)}')


def provider_message(body: str) -> str:
    """The provider's own error text, from a Google- or Anthropic-shaped error body."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return ' '.join(str(body).split())[:600]
    if isinstance(data, list) and data:
        data = data[0]
    error = data.get('error') if isinstance(data, dict) else None
    if isinstance(error, dict) and error.get('message'):
        return ' '.join(str(error['message']).split())[:600]
    return ' '.join(str(body).split())[:600]


def post_json(url: str, body: dict, headers: dict, timeout: float, opener=None):
    """POST one JSON body; return (payload, response headers). Raises ProviderHTTPError."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', **headers})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as resp:
            return json.loads(resp.read()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raise ProviderHTTPError(exc.code, exc.read().decode('utf-8', 'replace'), exc.headers) from exc


# ---- media -----------------------------------------------------------------

def attachment_bytes(record: dict):
    """Re-read a saved attachment and prove it is unchanged; return (mime, base64 text)."""
    import attachments as att
    import base64
    current = att.describe(record['kind'], record['path'], 'anthropic')
    if current != record:
        raise LaneError('A saved attachment changed; restore it or start a new session.')
    data = Path(record['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise LaneError('Attachment changed while reading.')
    return record['media_type'], base64.b64encode(data).decode('ascii')


def check_media(lane: Lane, messages: list) -> None:
    for message in messages:
        for record in message.get('attachments') or []:
            if record['kind'] == 'image' and not lane.images:
                raise LaneError(f'The {lane.engine} lane takes no image input.')
            if record['kind'] == 'file' and not lane.pdfs:
                raise LaneError(f'The {lane.engine} lane takes no PDF input.')


# ---- the gate loop ---------------------------------------------------------

def prefill_message(prefill: str) -> dict:
    return {'role': 'user', 'content': json.dumps({
        'type': 'answer_opening', 'text': prefill,
        'standing': 'The operator set the first words of direct_answer. Begin direct_answer with exactly this text.'},
        ensure_ascii=False)}


def opens_with(answer: str, prefill: str) -> bool:
    return answer.lstrip().startswith(prefill.strip())


def request_reply(lane: Lane, raw_input, *, client=None, model=None, effort='max', timeout=1800,
                  log_path=None, events=None, history=None, execution_confirmed=False,
                  request_context=None, web=True, web_max=5, attachments=None, knobs=None):
    """Mirror of harness.request_reply for one extra lane. Same pages, same gate."""
    import harness as h
    from lookup_gate import urls, violation
    kb = knobs or knobs_mod.Knobs()
    if len(raw_input) > h.MAX_INPUT_CHARS:
        raise h.HarnessError(f'Input exceeds {h.MAX_INPUT_CHARS} characters.')
    raw_input = raw_input.strip()
    if not raw_input:
        raise h.HarnessError('Input is empty.')
    prefix = h.load_prefix()
    model = lane_model(lane, model)
    tools_page = h.load_tools()
    base_pages = [prefix] + ([tools_page] if tools_page else [])
    extra_pages = h.load_pages()
    system_pages = base_pages + [page.text for page in extra_pages]
    messages = [*(history or []),
                {'role': 'user', 'content': raw_input, **({'attachments': attachments} if attachments else {})}]
    if kb.prefill:
        messages.append(prefill_message(kb.prefill))
    try:
        check_media(lane, messages)
    except LaneError as exc:
        raise h.HarnessError(str(exc)) from exc
    allowed_text = json.dumps(messages, ensure_ascii=False) + ' ' + (request_context or '')
    allowed_urls = sorted(urls(allowed_text))
    use_web = bool(web and lane.web)
    call = Call(model=model, effort=effort, timeout=max(float(timeout), lane.min_timeout),
                system_pages=system_pages, base_count=len(base_pages), messages=messages,
                raw_input=raw_input, schema=h.api_schema(), knobs=kb, web=use_web, web_max=web_max,
                client=client)
    if web and not lane.web:
        say_once(call, f'[{lane.engine}] this lane has no hosted web tool; it answers from the model alone.')
    for attempt in (1, 2):
        started = time.monotonic()
        event = {
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'model_requested': model, 'effort': effort, 'engine': engine_name(lane),
            'prefix_sha256': h.PREFIX_SHA256, 'attempt': attempt,
            'tools_sha256': hashlib.sha256(tools_page.encode('utf-8')).hexdigest() if tools_page else None,
            'pages': [{'label': page.label, 'sha256': page.sha256} for page in extra_pages],
            'input_chars': len(raw_input), 'status': 'pending',
            'lookup_counts': {'total': 0, 'search': 0, 'fetch': 0, 'find': 0,
                              'allowed_urls': allowed_urls, 'provider_reports': []},
            'sources': [],
        }
        try:
            sent = lane.send(lane, call)
            event['response_id'] = sent.response_id
            if sent.usage:
                event['usage'] = sent.usage
            if call.notes:
                event['knob_notes'] = list(call.notes)
            counts = event['lookup_counts']
            counts.update(search=sent.search, fetch=sent.fetch, total=sent.search + sent.fetch)
            if sent.provider_report:
                counts['provider_reports'].append(sent.provider_report)
            from lookup_gate import unique_sources
            event['sources'] = unique_sources(sent.sources)
            if counts['total'] and not use_web:
                raise h.HarnessError('Provider returned a lookup while web was off.')
            try:
                reply = h.validate_reply(sent.raw_json, raw_input, execution_confirmed=execution_confirmed,
                                         request_context=request_context)
                reason = violation(reply.direct_answer, counts, event['sources'], allowed_text)
                if reason:
                    raise h.GateError(reason)
                if kb.prefill and not opens_with(reply.direct_answer, kb.prefill) and attempt == 1:
                    raise h.GateError('direct_answer must begin with the operator-set opening: ' + kb.prefill)
            except h.OpeningScrubError:
                event['status'] = 'empty_after_scrub'
                raise
            except h.GateError as exc:
                event['status'] = 'gate_rejected'
                event['gate_reason'] = str(exc)
                if attempt == 2:
                    raise h.HarnessError('Both replies failed the output gate. No answer was displayed.') from exc
                call.messages = [*call.messages,
                                 {'role': 'assistant', 'content': sent.raw_json or '{}'},
                                 {'role': 'user', 'content': 'Local validation rejected the reply: ' + str(exc) +
                                  ' Return a corrected four-field reply for the original request. Preserve facts and meaning.'}]
                continue
            if kb.prefill and not opens_with(reply.direct_answer, kb.prefill):
                reply = reply.model_copy(update={'direct_answer': knobs_mod.apply_prefill(reply.direct_answer, kb.prefill)})
            event['status'] = 'accepted'
            event['intent'] = reply.intent
            event['answer_chars'] = len(reply.direct_answer)
            event['has_execution_payload'] = reply.execution_payload is not None
            return reply
        except LaneError as exc:
            event['status'] = 'lane_error'
            event['provider_error'] = str(exc)[:1000]
            raise h.HarnessError(str(exc)) from exc
        except h.HarnessError:
            raise
        except Exception as exc:
            event['status'] = 'api_error'
            event['provider_error'] = str(exc)[:1000]
            raise h.HarnessError(f'The {lane.engine} lane call failed ({type(exc).__name__}): {str(exc)[:400]}') from exc
        finally:
            event['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            h.record_event(event, log_path)
            if events is not None:
                events.append(event)
    raise h.HarnessError('No validated reply was produced.')


def engine_name(lane: Lane) -> str:
    return lane.engine


def wrap_text(text: str, raw_input: str) -> str:
    """A plain-text lane's answer as the four-field observation."""
    import harness as h
    cleaned = text.replace('<think></think>', '').strip()
    if not cleaned:
        raise LaneError('The lane returned an empty answer.')
    return json.dumps({'intent': 'observation', 'cleaned_input': raw_input[:h.MAX_INPUT_CHARS],
                       'direct_answer': cleaned, 'execution_payload': None}, ensure_ascii=False)
