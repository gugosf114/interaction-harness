"""What the live verifiers share since the lanes got mods and the past-chat search.

Every mod ships on. Four of them act around the answer: `voice` reads it aloud on the phone speaker,
`proof` and `tree` each call a small model and print a line after it, `narrator` prints a line before
a command. A verifier's answers are test strings and its checks compare the terminal with the answer,
so its own state folder starts with those four off. The mods inside the gate (length, plain-words,
receipts, no-background, undertaker) stay on, and the operator's real state folder is never touched.

The usage log also holds records that are not model turns: the past-chat search (`kind: recall`) and
the small-model calls (`kind: mod:...`). A verifier counts model turns with turn_events().
"""
import json

AROUND_THE_ANSWER = ('voice', 'proof', 'tree', 'narrator')
CHECK_LINE = 'answer check: '  # the one stderr line a bounced answer check prints before the retry


def quiet(runtime):
    """Create the verifier's state folder with the four mods off. An existing mods.json is left as it is."""
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = runtime / 'mods.json'
    if not path.exists():
        path.write_text(json.dumps({name: False for name in AROUND_THE_ANSWER}) + '\n')
    return runtime


def turn_events(events):
    """The usage records of model turns. Records with a `kind` (recall, mod:proof, mod:tree) are not turns."""
    return [event for event in events if 'kind' not in event]


def without_check_lines(text):
    """Terminal or stderr text without the 'answer check: ... - asked again' lines; every other line is kept."""
    return ''.join(line for line in text.replace('\r\n', '\n').splitlines(keepends=True) if not line.startswith(CHECK_LINE))
