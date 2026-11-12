"""The per-turn rules stamp: the operator's core rule headlines, sent as the last message of every request.

The headlines are read at run time, word for word, from the operator's own rules file. Their text
never enters the repository, the usage log, the session files or history.db.

The stamp sits after the current request, so everything before it is byte-identical to a request
without it and the cached front of the request does not change. It is never saved with a turn.
On Claude a conversation cache marker sits on the block before the stamp (cache_before_stamp).

/off stamp and /on stamp switch it. The switch lives in switches.json in the state folder. It ships on.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

from pages import PageError, take_sections
from storage import atomic_json

SOURCE = Path('/root/.claude/CLAUDE.md')
HEADING = '## Core interaction contract'
# A rule is a numbered line that opens with a bold headline: "1. **Headline.** The rest of the rule."
HEADLINE = re.compile(r'^\s*\d+[.)]\s+\*\*(.+?)\*\*')
SWITCH = re.compile(r'/(on|off)\s+stamp', re.IGNORECASE)
SWITCH_FILE = 'switches.json'
RECORD_TYPE = 'operator_rules_stamp'
STANDING = ("The operator's core rules, by headline, stamped on every request. They apply to this reply. "
            "This record is not a new request. Answer the message before it.")


class StampError(Exception):
    """A short, user-visible reason why the stamp cannot be sent or switched."""


def headlines(source=SOURCE, heading: str = HEADING) -> list[str]:
    """The bold headline of every numbered rule under the heading, word for word, in file order."""
    try:
        text = Path(source).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise StampError(f'Rules stamp: the file is missing or unreadable: {source}') from exc
    try:
        section = take_sections(text, [heading], 'stamp')
    except PageError as exc:
        raise StampError(f'Rules stamp: no single "{heading}" section in {source}') from exc
    found = [match.group(1).strip() for line in section.splitlines() if (match := HEADLINE.match(line))]
    found = [rule for rule in found if rule]
    if not found:
        raise StampError(f'Rules stamp: no numbered bold rule headline under "{heading}" in {source}')
    return found


def record(rules: list[str]) -> str:
    """The stamp as JSON text. The same rules always give the same bytes."""
    return json.dumps({'type': RECORD_TYPE, 'source': 'operator_rules_file', 'rules': list(rules),
                       'standing': STANDING}, ensure_ascii=False)


def is_stamp(message) -> bool:
    """True for the stamp message. Code that marks or measures the conversation can skip it with this."""
    content = message.get('content') if isinstance(message, dict) else None
    return isinstance(content, str) and content.startswith('{"type": "' + RECORD_TYPE + '"')


def sha256(message) -> str:
    return hashlib.sha256(message['content'].encode('utf-8')).hexdigest()


MAX_MARKERS = 4  # Anthropic's limit of cache markers in one request (checked live on 2026-11-11)


def marker_count(value) -> int:
    """How many cache_control markers a request, or any part of one, holds."""
    if isinstance(value, dict):
        return int('cache_control' in value) + sum(marker_count(child) for child in value.values())
    if isinstance(value, list):
        return sum(marker_count(child) for child in value)
    return 0


def cache_before_stamp(params: dict) -> dict:
    """Anthropic: when the request carries the stamp, a conversation cache marker goes on the block before it.

    The automatic marker (top-level cache_control) lands on the last block of the request. With the stamp
    last, that block is the stamp, and the next request never repeats a stamp at that place, so nothing
    written there would be read back. An explicit marker on the last block of the message before the stamp
    caches exactly the conversation that the next request repeats.

    The automatic marker stays as well while the request has a free marker slot. Inside one model turn the
    request grows behind the stamp (provider tool steps, a paused web lookup), and the automatic marker
    follows that growth, so each step reads the steps before it from cache. Checked live on 2026-11-11:
    two system markers, the explicit one and the automatic one are accepted together, and a third step
    then read 25,269 tokens from cache where the explicit marker alone read 21,627.
    When no slot is free, the automatic marker is given up for the explicit one.
    Without a stamp, or without a top-level marker, the request is left as it is.
    """
    messages = params.get('messages') or []
    control = params.get('cache_control')
    at = next((index for index in range(len(messages) - 1, 0, -1) if is_stamp(messages[index])), None)
    if control is None or at is None:
        return params
    before = dict(messages[at - 1])
    content = before.get('content')
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else [dict(block) for block in content or []]
    if not blocks:
        return params
    if 'cache_control' not in blocks[-1] and marker_count(params) >= MAX_MARKERS:
        del params['cache_control']  # no free slot: the conversation marker matters more than the in-turn one
    blocks[-1] = {**blocks[-1], 'cache_control': dict(control)}
    before['content'] = blocks
    params['messages'] = [*messages[:at - 1], before, *messages[at:]]
    return params


def switches(state) -> dict:
    """The saved switches. A missing file is an empty set: everything is at its shipped state."""
    path = Path(state) / SWITCH_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise StampError(f'The switches file cannot be read: {path}') from exc
    if not isinstance(data, dict):
        raise StampError(f'The switches file must hold one JSON object: {path}')
    return data


def is_on(state) -> bool:
    """On unless the switches file says exactly false."""
    return switches(state).get('stamp') is not False


def set_switch(state, on: bool) -> None:
    """Save the switch. Every other key in the file is kept as it is."""
    data = switches(state)
    data['stamp'] = bool(on)
    atomic_json(Path(state) / SWITCH_FILE, data)


def tail(source, state) -> dict | None:
    """The message to put last in a request, or None when the stamp is off. The source is not read when off."""
    if source is None or not is_on(state):
        return None
    return {'role': 'user', 'content': record(headlines(source))}


def is_switch(text: str) -> bool:
    """True for a typed line that is exactly /on stamp or /off stamp."""
    return bool(SWITCH.fullmatch(text.strip()))


def run_switch(text: str, state) -> int:
    """Flip the switch for a typed /on stamp or /off stamp. No model call. One line on stderr."""
    on = SWITCH.fullmatch(text.strip()).group(1).lower() == 'on'
    try:
        set_switch(state, on)
    except (StampError, OSError) as exc:
        print(str(exc) if isinstance(exc, StampError) else 'The switches file cannot be written.', file=sys.stderr)
        return 2
    print('Stamp on.' if on else 'Stamp off.', file=sys.stderr)
    return 0
