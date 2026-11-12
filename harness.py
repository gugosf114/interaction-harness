#!/data/data/com.termux/files/usr/bin/python
"""Structured OpenAI/Anthropic replies with one shared local display gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Literal

# Let both `python harness.py ...` and the short wrapper work from native Termux.
# Only standard-library imports have happened here; compiled clients live in Debian.
if __name__ == '__main__' and sys.executable.startswith('/data/data/com.termux/files/usr/'):
    launcher = Path(__file__).resolve().parent / 'launch.py'
    os.execv(sys.executable, [sys.executable, '-B', str(launcher), 'harness.py', *sys.argv[1:]])

from pages import PageError, anthropic_system, read_pages
from openai import (
    OpenAI, APIConnectionError, APIStatusError, APITimeoutError,
    AuthenticationError, PermissionDeniedError, RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import anthropic
from senses import TurnSenses, SensesError
from attachments import AttachmentError
from lookup_gate import violation as lookup_violation, source_block, urls
from choice_check import violation as choice_violation
from gate_rules import apply as operator_rules
import answer_checks
import mod_switches

ROOT = Path(__file__).resolve().parent
PREFIX_SHA256 = '73d3ce09d43431650591b9ff9c9eb7e5fe3def714e0a49eebdfd7c8fd2fd2854'
DEFAULT_MODEL = 'gpt-6.1-sol'
ANTHROPIC_MODEL = 'claude-opus-5-5'
DEFAULT_EFFORT = 'max'
MAX_OUTPUT_TOKENS = 128000  # highest value both providers accepted in a live call on 2026-11-11
MAX_INPUT_CHARS = 1000000
STATE = Path(os.environ.get('HARNESS_STATE_DIR', str(ROOT / 'state'))).expanduser()


class HarnessError(Exception):
    """A short, user-visible operational failure."""


class GateError(HarnessError):
    """Output that must not reach stdout."""


class OpeningScrubError(GateError):
    """Opening-line removal left no answer; never spend another API call on it."""


class HarnessReply(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: Literal['observation', 'action_request']
    cleaned_input: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    direct_answer: str = Field(min_length=1, max_length=16000)
    execution_payload: str | None

    @model_validator(mode='after')
    def check_intent(self):
        if self.intent == 'observation' and self.execution_payload is not None:
            raise ValueError('An observation cannot contain an execution payload.')
        if not self.cleaned_input.strip() or not self.direct_answer.strip():
            raise ValueError('Required text cannot be whitespace.')
        if self.execution_payload is not None and not self.execution_payload.strip():
            raise ValueError('An execution payload must contain a command or be null.')
        return self


def api_schema():
    """One common wire schema; local Pydantic retains string-length constraints."""
    schema=HarnessReply.model_json_schema()
    def walk(value):
        if isinstance(value,dict):
            minimum=value.pop('minLength',None); maximum=value.pop('maxLength',None)
            if minimum is not None or maximum is not None:
                value['description']=(value.get('description','')+f' Length: {minimum or 0} to {maximum or MAX_INPUT_CHARS} characters.').strip()
            for child in value.values(): walk(child)
        elif isinstance(value,list):
            for child in value: walk(child)
    walk(schema)
    return schema


# A canned opener is filler only when it stands alone: sentence punctuation and a break
# follow it, or the line ends. "Certainly not." and "hello.txt" are content.
_ALONE = r"(?=[!,.:;][*_]*(?:\s|\Z)|\s*(?:\n|\Z))"
# This is a finite wording check, not a claim to recognize every possible hedge.
# A sentence starts at the top, after end punctuation plus whitespace, or on a new line.
# A dot inside a host name or a file name does not start one.
FILLER = re.compile(
    r"(?:\A|(?<=[.!?])\s+|(?<=\n)\s*)(?:[*_#>]+\s*)*(?:"
    r"(?:certainly|sure(?: thing)?|absolutely|of course|no problem|my (?:mistake|bad))" + _ALONE + r"|"
    r"(?:great question|good question|(?:good|nice|great) catch)\b|"
    r"(?:hello|hi|hey)(?:\s+(?:George|there))?" + _ALONE + r"|"
    r"(?:I(?:['’]m| am) (?:happy|glad) to help|(?:happy|glad) to help|I(?:['’]d| would) be happy to)\b|"
    r"(?:sorry|I(?:['’]m| am)(?: (?:so|very|really|truly|deeply))? sorry|I apologize|my apologies|apologies|"
    r"as an AI|as a language model|"
    r"you(?:['’]re| are)(?: (?:absolutely|completely|totally|quite|entirely))? (?:right|correct))\b|"
    r"(?:please note|it(?:'s| is) worth noting)\b|"
    r"(?:I hope (?:this|that|it) (?:helps|clears things up|makes sense)|hope (?:this|that|it) helps|"
    r"let me know if|feel free to|I(?:'d| would) be happy to)\b|"
    r"(?:here(?:'s| is) (?:the|your) (?:answer|response)|let me (?:explain|break this down)|"
    r"before we (?:begin|start)|for (?:your )?safety|use (?:this )?at your own risk|"
    r"this is not (?:legal|medical|financial) advice|always consult (?:a|an) professional|"
    r"nothing (?:has been|was|is) (?:changed|lost|wasted)|rest assured|"
    r"you (?:do not|don't) need to worry)\b"
    r")", re.IGNORECASE,
)
# Reports of finished work: a one-word opening, or a first-person past action.
# Third-person text ("the log shows the file was created") stays content, since log audits need it.
_ADVERBS = r"(?: (?:just|already|also|now|successfully))*"
_ACTIONS = r"ran|executed|created|installed|uninstalled|deleted|finished|completed|verified|audited|checked your|changed your"
COMPLETION_OPENING = re.compile(
    r"\A(?:all\s+)?(?:done|completed|finished|created|installed|deleted|fixed)[.!]", re.IGNORECASE)
COMPLETION_CLAIM = re.compile(
    r"\bI(?:(?:['’]ve| have)" + _ADVERBS + r" (?:run|" + _ACTIONS + r")|" + _ADVERBS + r" (?:" + _ACTIONS + r"))\b"
    r"(?!\s+(?:no|nothing|none|zero)\b)", re.IGNORECASE)
# Earlier in the same sentence, these words make it doubt, denial or a condition, not a report.
NOT_A_REPORT = re.compile(
    r"\b(?:no|not|never|cannot|can['’]t|couldn['’]t|didn['’]t|haven['’]t|hasn['’]t|unable|without|whether|if|"
    r"unless|unknown|unclear|unsure|uncertain|unverified)\b", re.IGNORECASE)
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def claims_completion(answer: str) -> bool:
    """True when the answer reports finished work. Doubt, denial and quoted evidence are not reports."""
    if COMPLETION_OPENING.search(answer):
        return True
    for sentence in SENTENCE_BREAK.split(QUOTED.sub(' ', answer)):
        for claim in COMPLETION_CLAIM.finditer(sentence):
            if not NOT_A_REPORT.search(sentence[:claim.start()]):
                return True
    return False
# Unrequested reassurance: a sentence whose whole job is to say the step is safe.
# "It does not change any files." / "It changes nothing." / "These checks are read-only." / "I did not change anything."
# Removed in code, with no extra API call, unless the operator's own request raised the topic.
_RE_SUBJECT = (r"(?:it|this|that|these|those|they|i|we|"
               r"(?:the|this|these|those|both|all|each)\s+(?:\w+\s+){0,2}(?:commands?|checks?|steps?|scripts?|operations?|actions?))")
_RE_OBJECT = (r"(?:\s+(?:any|the|your|these|those|its|their|either|other|existing))?(?:\s+of)?(?:\s+(?:the|your|these|those))?"
              r"\s+(?:files?|anything|them|it|data|settings?|contents?|state|system|directory|folder|permissions?|"
              r"repo(?:sitory)?|code|disk)\b")
_RE_SECRET = r"\b(?:keys?|secrets?|credentials?|tokens?|passwords?)\b"
_RE_NEG = r"(?:(?:does|do|did|will|would|should|can|could)(?:\s+not|n['’]t)|won['’]t|cannot|can['’]t|never)"
_RE_TAIL = r"[^.!?\n]*"
REASSURANCE_SENTENCE = re.compile(
    r"(?:"
    + _RE_SUBJECT + r"\s+(?:also\s+)?(?:"
        + _RE_NEG + r"\s+(?:change|modify|alter|delete|remove|overwrite|touch|edit|write\s+to|harm|damage|affect)" + _RE_OBJECT + _RE_TAIL + r"|"
        + _RE_NEG + r"\s+(?:show|print|reveal|expose|display|log|leak)\b[^.!?\n]*?" + _RE_SECRET + _RE_TAIL + r"|"
        r"chang(?:es|ed|e)\s+nothing\b" + _RE_TAIL + r"|"
        r"(?:only|just|merely|simply)\s+(?:reads?|inspects?|views?|looks?\s+at)(?:\s+(?:the|these|those|your|both))?\s+(?:files?|them|it)|"
        r"(?:is|are|was|were|stays?|remains?)\s+(?:all\s+|entirely\s+|strictly\s+|purely\s+|fully\s+)?(?:read[- ]only|non[- ]destructive|safe(?:\s+to\s+run)?)\b" + _RE_TAIL
    + r")|"
    r"(?:nothing|no\s+files?|no\s+data)\s+(?:is|are|was|were|has\s+been|have\s+been|will\s+be|gets?)\s+"
    r"(?:changed|modified|deleted|altered|touched|written|removed|overwritten|harmed)\b" + _RE_TAIL
    + r")[.!?:]?", re.IGNORECASE)
REASSURANCE_CLAUSE = re.compile(
    r",?\s+(?:(?:and|but)\s+(?:(?:it|this|they|these)\s+)?" + _RE_NEG
    + r"\s+(?:change|modify|alter|delete|remove|overwrite|touch|edit)" + _RE_OBJECT + r"[^.!?\n,;]*|"
    r"without\s+(?:changing|modifying|altering|touching|deleting|editing)" + _RE_OBJECT + r"[^.!?\n,;]*)", re.IGNORECASE)
# The operator's own request raised it: "don't change anything", "is it safe", "read-only", "do not print the key".
# Then such a sentence is the answer, not decoration. A bare "write a command" or "change to the folder"
# does not count; the request must negate or question a change, or name safety.
_ASK_NEG = r"(?:don['’]?t|do\s+not|never|without|no|not|avoid|must\s+not|should\s+not|shouldn['’]t|mustn['’]t)"
_ASK_CHANGE = r"(?:chang|modif|alter|delet|remov|overwrit|touch|edit|writ|harm|damag|break)\w*"
SAFETY_ASKED = re.compile(
    r"\b" + _ASK_NEG + r"\s+(?:\w+\s+){0,4}?" + _ASK_CHANGE + r"\b|"
    r"\b" + _ASK_NEG + r"\s+(?:\w+\s+){0,4}?(?:print|show|reveal|display|expos|leak|log)\w*\s+(?:\w+\s+){0,6}?(?:keys?|secrets?|credentials?|tokens?|passwords?)\b|"
    r"\b" + _ASK_CHANGE + r"\s+(?:nothing|none|no\s+\w+)\b|"
    r"\b(?:no\s+key|key\s+(?:contents?|values?))\b|"
    r"\bread[- ]only\b|\bnon[- ]destructive\b|"
    r"\b(?:safe|safely|safety|unsafe|risk\w*|danger\w*|harm\w*|destructive)\b|"
    r"\b(?:will|does|did|would|can|could|is|are)\s+(?:it|this|that|they|these)\s+(?:going\s+to\s+)?" + _ASK_CHANGE + r"\b",
    re.IGNORECASE)
_LIST_MARK = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")


def strip_reassurance(text: str, asked: str | None = None) -> str:
    """Drop unrequested safety reassurance; keep every other sentence exactly as written."""
    if asked and SAFETY_ASKED.search(asked):
        return text
    out_lines = []
    for line in text.split('\n'):
        mark = _LIST_MARK.match(line)
        head, body = (mark.group(1), line[mark.end():]) if mark else ('', line)
        kept = []
        for sentence in re.split(r"(?<=[.!?:])\s+", body):
            core = sentence.strip()
            if core and REASSURANCE_SENTENCE.fullmatch(core):
                continue
            kept.append(REASSURANCE_CLAUSE.sub('', sentence))
        new_body = ' '.join(part for part in kept if part.strip())
        if body.strip() and not new_body.strip():
            continue  # the whole line was reassurance
        out_lines.append(head + new_body if body.strip() else line)
    cleaned = '\n'.join(out_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
OPENING_ECHO = re.compile(
    r"^(?:"
    r"you\s+asked\b|you(?:['’]re|\s+are)\s+asking\b|"
    r"your\s+(?:question|request|prompt)(?:\s+(?:is|was))?\s*[:—–-]|"
    r"let\s+me\s+restate\b"
    r")", re.IGNORECASE,
)
# Remove only the canned opening, never the factual sentence after it.
# Probability, missing evidence, and requirements to inspect logs are content.
# The punctuation after an opener must end a word: "hello.txt" and "sure.cfg" are file names.
_OPENER_END = r"(?:[!,.:;](?=[\s*_]|$)\s*|$)"
OPENING_FILLER = re.compile(
    r"^(?:"
    r"(?:certainly|sure(?: thing)?|absolutely|of course|no problem|great question|good question|"
    r"(?:good|nice|great) catch)" + _OPENER_END + r"|"
    r"(?:hello|hi|hey)(?:\s+(?:George|there))?" + _OPENER_END + r"|"
    r"(?:I(?:['’]m| am) (?:happy|glad) to help|(?:happy|glad) to help|"
    r"I(?:['’]d| would) be happy to help)" + _OPENER_END + r"|"
    r"(?:sorry|I(?:['’]m| am)(?: (?:so|very|really|truly|deeply))? sorry|my apologies|apologies|"
    r"my (?:mistake|bad)|I apologize)"
    r"(?: for (?:the |any |my )?(?:confusion|mistake|error|misunderstanding|inconvenience|delay))?"
    r"(?:[!,.:;](?=[\s*_]|$)\s*(?:but\s+)?|\s+but\s+|$)|"
    r"you(?:['’]re| are) right,? my mistake" + _OPENER_END + r"|"
    r"you(?:['’]re| are)(?: (?:absolutely|completely|totally|quite|entirely))? (?:right|correct)"
    r"(?:[!,.:;—–](?=[\s*_]|$)\s*|\s+that\s+|$)|"
    r"as an (?:AI(?: language model)?|language model)" + _OPENER_END + r"|"
    r"it(?:\s+is|['’]s)\s+important\s+to\s+note\s+that(?:\s+|$)|"
    r"(?:please note|it(?:['’]s| is) worth noting)(?: that)?(?:[!,.:;]\s*|\s+|$)|"
    r"here(?:['’]s| is) (?:the|your) (?:answer|response)\s*:\s*|"
    r"for (?:your )?safety(?:[,;:]\s*|$)|"
    r"this is not (?:legal|medical|financial) advice(?:[.!;:]\s*|$)"
    r")", re.IGNORECASE,
)
OPENING_MARKUP = re.compile(r'^(?:(?:\*\*|__)|[>#*-]\s*)+')


def scrub_opening(text: str, input_text: str | None = None) -> str:
    """Strip canned prefixes and prompt echoes; preserve epistemic content."""
    def plain(line):
        return OPENING_MARKUP.sub('', line.strip()).strip()

    def echo_key(value):
        value=plain(value).strip(' \t\r\n\"\'“”‘’`*_')
        return ' '.join(value.casefold().split()).rstrip('?.!:;')

    prompt=echo_key(input_text) if input_text else ''
    lines=text.splitlines(keepends=True)
    first=0
    while first<len(lines):
        line=plain(lines[first])
        if not line:
            first+=1; continue
        if OPENING_ECHO.match(line) or (prompt and echo_key(line)==prompt):
            first+=1; continue
        filler=OPENING_FILLER.match(line)
        if filler:
            remainder=re.sub(r'^(?:\*\*|__)\s*','',line[filler.end():]).lstrip()
            newline='\n' if lines[first].endswith('\n') else ''
            lines[first]=remainder+newline
            if not remainder:first+=1
            continue
        break
    return ''.join(lines[first:]).rstrip()


def load_prefix() -> str:
    try:
        raw = (ROOT / 'prefix_block.txt').read_bytes()
    except OSError as exc:
        raise HarnessError('The frozen prefix file cannot be read.') from exc
    if hashlib.sha256(raw).hexdigest() != PREFIX_SHA256:
        raise HarnessError('The frozen prefix changed. Restore the approved prefix before running.')
    return raw.decode('utf-8')


MAX_TOOLS_CHARS = 8000


def load_tools() -> str | None:
    """The operator's tools page: optional, editable, sent right after the frozen prefix. None when absent."""
    path = ROOT / 'tools_block.txt'
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise HarnessError('The tools page cannot be read.') from exc
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_TOOLS_CHARS:
        raise HarnessError(f'The tools page exceeds {MAX_TOOLS_CHARS} characters.')
    if CONTROLS.search(text):
        raise HarnessError('The tools page contains control characters.')
    return text


# The operator's page list. Only the command-line entry point at the bottom of this file sets it.
# A plain import, which is what the unit tests do, leaves it off, so tests never read the real list.
PAGES_FILE: Path | None = None
# The lane mods (answer_checks.py, lane_mods.py). Off on a plain import, so the unit tests see the gate as before;
# the command-line entry point at the bottom of this file switches them on. Each mod then has its own /on and /off.
MODS_ON = False


def load_pages() -> list:
    """The operator's extra pages (state/pages.json), in listed order. Empty when the list is off, missing or empty."""
    if PAGES_FILE is None:
        return []
    try:
        return read_pages(PAGES_FILE)
    except PageError as exc:
        raise HarnessError(str(exc)) from exc


def load_key(engine='openai') -> str:
    if engine not in {'openai','anthropic'}: raise HarnessError('Unknown engine.')
    variable = 'OPENAI_API_KEY' if engine == 'openai' else 'ANTHROPIC_API_KEY'
    value = os.environ.get(variable, '').strip()
    if not value:
        key_state = ROOT / 'state' if os.environ.get('HARNESS_STATE_DIR') else STATE
        path = key_state / ('api-key' if engine == 'openai' else 'anthropic-api-key')
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                raise HarnessError('The saved API key must be a private regular file (mode 600).')
            value = path.read_text().strip()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise HarnessError('The saved API key cannot be read.') from exc
    if not value:
        script = 'export-key.sh' if engine == 'openai' else 'export-anthropic-key.sh'
        raise HarnessError(f'Export {variable} or run the provided {script} setup.')
    if '\n' in value or '\r' in value:
        raise HarnessError('The API key contains a line break.')
    return value


def validate_reply(raw: str, input_text: str | None = None, *, execution_confirmed: bool = False,
                   request_context: str | None = None) -> HarnessReply:
    try:
        reply = HarnessReply.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError) as exc:
        # Never echo the rejected response, which could contain unwanted prose.
        raise GateError('Reply failed the schema or observation/command check.') from exc
    for text in (reply.cleaned_input, reply.direct_answer, reply.execution_payload or ''):
        if CONTROLS.search(text):
            raise GateError('Reply contains terminal control characters.')
    answer = scrub_opening(reply.direct_answer, input_text)
    if not answer:
        raise OpeningScrubError('No substantive answer remains after opening-line cleanup.')
    reply=reply.model_copy(update={'direct_answer':answer})
    filler = FILLER.search(answer)
    if filler:
        raise GateError('Reply contains blocked filler: ' + repr(filler.group(0).strip()[:100]) + '.')
    # The phrases FILLER names are rejected above with feedback. Every other wording of
    # unrequested reassurance is removed here, with no extra API call.
    # request_context is the operator's original task when this turn's input is a loop continuation.
    answer = strip_reassurance(answer, ' '.join(part for part in (input_text, request_context) if part))
    if not answer:
        raise OpeningScrubError('No substantive answer remains after reassurance cleanup.')
    if MODS_ON and mod_switches.is_on('undertaker', STATE):
        answer = answer_checks.undertaker(answer)  # pure filler lines go, every other line stays as written
        if not answer:
            raise OpeningScrubError('No substantive answer remains after filler-line cleanup.')
    reply=reply.model_copy(update={'direct_answer':answer})
    # execution_confirmed means this reply directly follows a command that was approved and exited 0.
    if claims_completion(answer) and not execution_confirmed:
        raise GateError('Reply reports completed work, but no successful command result '
                        '(approved, exit code 0) directly precedes it.')
    if reply.execution_payload is not None and '```' in reply.execution_payload:
        raise GateError('Execution payload must be plain command text, without Markdown fences.')
    # The choice check (choice_check.py): an instruction is carried out, not answered with a request for leave.
    reason = choice_violation(answer, request_context or input_text)
    if reason:
        raise GateError(reason)
    # The operator's rules kept as data and the habit checks kept in code (gate_rules.py), after every built-in check.
    answer, reason = operator_rules(answer, request_context or input_text)
    if reason:
        raise GateError(reason)
    return reply.model_copy(update={'direct_answer': answer})


def display_text(reply: HarnessReply, sources=()) -> str:
    text = scrub_opening(reply.direct_answer)
    if not text:
        raise OpeningScrubError('No substantive answer remains after opening-line cleanup.')
    block=source_block(sources,text)
    if block:text+='\n\n'+block
    if reply.execution_payload is not None:
        text += '\n\n' + reply.execution_payload.strip()
    return text + '\n'


def record_event(event: dict, log_path: Path | None = None) -> None:
    path = log_path or STATE / 'usage.jsonl'
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'a') as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n')


def request_reply(
    raw_input: str, *, client=None, model: str | None = None, engine: str = 'openai',
    effort: str = DEFAULT_EFFORT, timeout: float = 90,
    log_path: Path | None = None, events: list | None = None, history: list | None = None,
    execution_confirmed: bool = False, request_context: str | None = None,
    web: bool = True, web_max: int = 5, attachments=None, api_runtime=None, native_tool_evidence=None,
    knobs=None,
) -> HarnessReply:
    import extra_lanes
    if extra_lanes.is_lane(engine):
        return extra_lanes.request_reply(
            raw_input, client=client, model=model, engine=engine, effort=effort, timeout=timeout,
            log_path=log_path, events=events, history=history, execution_confirmed=execution_confirmed,
            request_context=request_context, web=web, web_max=web_max, attachments=attachments, knobs=knobs)
    if len(raw_input) > MAX_INPUT_CHARS:
        raise HarnessError(f'Input exceeds {MAX_INPUT_CHARS} characters.')
    raw_input = raw_input.strip()
    if not raw_input:
        raise HarnessError('Input is empty.')
    prefix = load_prefix()
    if engine not in {'openai','anthropic'}: raise HarnessError('Unknown engine.')
    import knobs as knobs_mod
    kb = knobs or knobs_mod.Knobs()
    knob_wire, knob_notes = knobs_mod.resolve_builtin(engine, kb)
    for note in knob_notes:
        print(note, file=sys.stderr)
    model = model or (DEFAULT_MODEL if engine == 'openai' else ANTHROPIC_MODEL)
    if client is None:
        if engine == 'openai':
            client = OpenAI(api_key=load_key(engine), base_url='https://api.openai.com/v1', timeout=timeout, max_retries=0)
        else:
            client = anthropic.Anthropic(api_key=load_key(engine), base_url='https://api.anthropic.com', timeout=timeout, max_retries=0)
    # Stable pages first so provider caches keep hitting: frozen prefix, tools page, then the operator's pages.
    tools_page = load_tools()
    base_pages = [prefix] + ([tools_page] if tools_page else [])
    extra_pages = load_pages()
    system_pages = base_pages + [page.text for page in extra_pages]
    messages = [
        *({'role': 'system', 'content': page} for page in system_pages),
        *(history or []),
        {'role': 'user', 'content': raw_input, **({'attachments':attachments} if attachments else {})},
    ]
    allowed_text=json.dumps(messages[len(system_pages):],ensure_ascii=False)+' '+(request_context or '')
    schema = api_schema()
    senses=TurnSenses(engine,schema,web,web_max,runtime=api_runtime)
    senses.counts['allowed_urls']=sorted(urls(allowed_text))
    for attempt in (1, 2):
        started = time.monotonic()
        event = {
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'model_requested': model, 'effort': effort,
                'engine':engine,
            'prefix_sha256': PREFIX_SHA256, 'attempt': attempt,
            'tools_sha256': hashlib.sha256(tools_page.encode('utf-8')).hexdigest() if tools_page else None,
            'pages': [{'label': page.label, 'sha256': page.sha256} for page in extra_pages],
            'input_chars': len(raw_input), 'status': 'pending',
        }
        try:
            response=senses.send(client,model=model,effort=effort,max_output_tokens=MAX_OUTPUT_TOKENS,
                messages=messages,system_pages=system_pages,schema=schema,prefix_hash=PREFIX_SHA256,
                system_blocks=anthropic_system(system_pages,len(base_pages)),knobs=knob_wire)
            event['response_id'] = response.id
            event['model_returned'] = response.model
            usage = getattr(response, 'usage', None)
            if usage is not None:
                event['usage'] = senses.last_usage or usage.model_dump(exclude_none=True)
            if engine == 'openai':
                for output in response.output:
                    if getattr(output,'type',None) == 'message':
                        if any(getattr(item,'type',None)=='refusal' for item in output.content):
                            event['status']='refusal'; raise HarnessError('The model refused this request.')
                if response.status != 'completed':
                    event['status']='incomplete'; raise HarnessError('The model response was incomplete. No answer was displayed.')
                raw_response = response.output_text
            else:
                if response.stop_reason == 'refusal':
                    event['status']='refusal'; raise HarnessError('The model refused this request.')
                if response.stop_reason == 'max_tokens':
                    event['status']='incomplete'; raise HarnessError('The model response was incomplete. No answer was displayed.')
                blocks=[b for b in response.content if b.type=='tool_use' and b.name=='emit_reply']
                raw_response=json.dumps(blocks[0].input) if len(blocks)==1 else '{}'
            try:
                supported=api_runtime.successful_work if api_runtime and api_runtime.has_work else execution_confirmed
                reply = validate_reply(raw_response, raw_input, execution_confirmed=supported,
                                       request_context=request_context)
                tool_evidence=json.dumps(api_runtime.receipts,ensure_ascii=False) if api_runtime else ''
                reason=lookup_violation(reply.direct_answer,senses.counts,senses.metadata()['sources'],allowed_text+' '+tool_evidence)
                if reason:raise GateError(reason)
                from api_tool_gate import violation as api_tool_violation
                receipts=(api_runtime.receipts if api_runtime else [])+([native_tool_evidence] if native_tool_evidence else [])
                reason=api_tool_violation(reply.direct_answer,receipts)
                if reason:raise GateError(reason)
                # George's answer checks (answer_checks.py): one retry, and a second answer is shown even if it still fails.
                soft=answer_checks.soft_violation(reply,request_context or raw_input,history or [],raw_input,STATE) if MODS_ON else None
                if soft and attempt==1:
                    print('answer check: '+soft.split(' - ',1)[0]+' - asked again',file=sys.stderr,flush=True)
                    raise GateError(soft)
                if soft:event['answer_check_kept']=soft.split(' - ',1)[0]
            except OpeningScrubError:
                event['status']='empty_after_scrub'
                raise
            except GateError as exc:
                event['status'] = 'gate_rejected'
                event['gate_reason'] = str(exc)
                if attempt == 2:
                    raise HarnessError('Both replies failed the output gate. No answer was displayed.') from exc
                messages=senses.repair(messages,response,str(exc))
                continue
            if kb.prefill:
                reply=reply.model_copy(update={'direct_answer':knobs_mod.apply_prefill(reply.direct_answer,kb.prefill)})
            event['status'] = 'accepted'
            event['intent'] = reply.intent
            event['answer_chars'] = len(reply.direct_answer)
            event['has_execution_payload'] = reply.execution_payload is not None
            return reply
        except (SensesError,AttachmentError) as exc:
            event['status']='senses_error'
            raise HarnessError(str(exc)) from exc
        except (AuthenticationError, anthropic.AuthenticationError) as exc:
            event['status'] = 'authentication_error'
            raise HarnessError('The API key was rejected.') from exc
        except (PermissionDeniedError, anthropic.PermissionDeniedError) as exc:
            if api_runtime:api_runtime.api_error(exc)
            event['provider_error']=getattr(exc,'body',None)
            event['status'] = 'permission_error'
            raise HarnessError('This API account cannot access the requested model.') from exc
        except (RateLimitError, anthropic.RateLimitError) as exc:
            event['status'] = 'quota_or_rate_limit'
            raise HarnessError('The API reports a billing quota or rate limit. Check the API account.') from exc
        except (APITimeoutError, anthropic.APITimeoutError) as exc:
            event['status'] = 'timeout'
            raise HarnessError('The API request timed out.') from exc
        except (APIConnectionError, anthropic.APIConnectionError) as exc:
            event['status'] = 'connection_error'
            raise HarnessError('The API connection failed.') from exc
        except (APIStatusError, anthropic.APIStatusError) as exc:
            if api_runtime:api_runtime.api_error(exc)
            event['status'] = 'api_error'
            event['http_status'] = exc.status_code
            event['provider_error'] = getattr(exc,'body',None)
            raise HarnessError(f'The API rejected this request (HTTP {exc.status_code}).') from exc
        finally:
            if api_runtime:api_runtime.close()
            event.update(senses.metadata())
            if native_tool_evidence:event.setdefault('api_tool_uses',[]).append(native_tool_evidence)
            if senses.last_usage:event.setdefault('usage',senses.last_usage)
            event['provider_response_ids']=senses.last_responses
            event['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            record_event(event, log_path)
            if events is not None:
                events.append(event)
    raise HarnessError('No validated reply was produced.')


def main(argv: list[str] | None = None) -> int:
    from cli import main as run_cli
    return run_cli(argv)


if __name__ == '__main__':
    # cli.py imports this file as the module `harness`. Switch the operator's page list on there.
    # It sits in this installation's state folder, next to the saved keys; HARNESS_STATE_DIR does not move it.
    import harness as _client
    _client.PAGES_FILE = _client.ROOT / 'state' / 'pages.json'
    import recall_notes as _recall
    _recall.wire()  # the past-chat search is on only under the command-line entry point, like the page list
    import second_gate as _second_gate
    _second_gate.switch_on(_client.ROOT / 'state')  # the operator's gate rules, the judge, the lessons page
    _client.MODS_ON = True
    raise SystemExit(main())
