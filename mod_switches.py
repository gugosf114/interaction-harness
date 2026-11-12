"""The lane mods' on/off switches: one JSON file, state/mods.json, read fresh on every use.

Every mod ships on. A name missing from the file is on. `/on NAME` and `/off NAME` in a chat write the file.
This module imports nothing from the harness, so the gate code and the chat code can both use it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

# Name -> one plain line. The order is the order /mods prints.
MODS = {
    'length': 'A yes/no question gets a short answer: 40 words, 120 for any question, 250 otherwise. One retry.',
    'plain-words': 'The answer reads at grade 5 or lower and uses no listed jargon. One retry.',
    'receipts': 'A claim about how WiM behaves needs a WiM code or log read this turn, or the word GUESS. One retry.',
    'no-background': 'A command that detaches (nohup, setsid, disown, a trailing &) is sent back once.',
    'undertaker': 'Lines that are pure filler ("Don\'t worry.", "To be clear.") are removed from the answer.',
    'proof': 'After the answer, a small model marks each line: shown by a command, guess, or no proof.',
    'narrator': 'Before a command runs, one plain sentence says what it does.',
    'tree': 'Keeps the stack of open topics. /where prints it; a closed branch offers the way back.',
    'voice': 'Reads each answer aloud with the phone voice (say). /voice full or /voice short.',
    'voice-v': 'A chat line of just v (or в) opens the phone microphone; what George says becomes the message.',
    'memory-version': 'After each command, any change in the memory notes folder is committed to its git.',
    'reindex': 'When a chat opens, the past-chat search index is brought up to date.',
    'voiceline': 'When a chat opens, the phone call line is started if George wants it (its WANTED file).',
    'autopilot': '/autopilot GOAL runs step after step until done, blocked, 150 steps or 10 hours.',
}
DEFAULTS = {'voice-mode': 'full'}


def path(state) -> Path:
    return Path(state) / 'mods.json'


def load(state) -> dict:
    try:
        data = json.loads(path(state).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(state, data: dict) -> None:
    target = path(state)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.mods-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write('\n')
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def is_on(name: str, state) -> bool:
    return load(state).get(name, True) is not False


def setting(name: str, state):
    return load(state).get(name, DEFAULTS.get(name))


def set_value(name: str, value, state) -> None:
    data = load(state)
    data[name] = value
    save(state, data)
