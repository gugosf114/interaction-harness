"""Build gate_known_good.txt: the sentences no operator gate rule may match.

Two sources:
  1. Accepted answers in history.db files: the installation's own state folder and every saved
     check run under it (pass other folders as arguments).
  2. The positive cases in the existing tests: sentences the built-in checks must keep.

Run it in Debian from the repository folder:
  .venv/bin/python -B build_known_good.py /data/data/com.termux/files/home/interaction-harness/state

Every sentence is run through the gate's own sentence splitter. A sentence the built-in checks reject or
cut is left out, and so is a line that holds a key-shaped string, a mail address or a phone number.
"""
import json
from pathlib import Path
import re
import sqlite3
import sys

import gate_rules
import harness as h
import test_choice_check

OUT = Path(__file__).resolve().parent / 'gate_known_good.txt'
PRIVATE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+|\b\d{3}[-. ]\d{3}[-. ]\d{4}\b|sk-[A-Za-z0-9_-]{8,}|\b[A-Za-z0-9+/_-]{32,}\b')
# Positive cases written into the tests as plain strings: each must pass the gate untouched.
FROM_TESTS = [
    'The owner can read and write the file.',
    'This prints your identity.',
    'Probably a timeout; inspect the log.',
    'The file contains the expected value.',
    'This runs the next step.',
    'The title is Example Domain.',
    'Inspect the result.',
    'Print the page title.',
    'Certainly not.',
    'Maybe the cache is stale.',
    'The log shows the file was created.',
    'No command has run yet, so there is no file listing yet.',
    'Key presence has not been checked.',
    'The file list alone does not show the cause.',
    'It does not show any error.',
    'Restarting does not change the result.',
    'It does not change the outcome of the build.',
    'setup.sh is mode 644, so it is not executable.',
    'I did not check whether pip is installed.',
    'The .env.example file is empty, but setup.sh never uses it.',
    'The mount is read-only, so the write fails with EROFS.',
    'chmod 640 gives the owner read and write access.',
    'This only shows the first 40 lines.',
    'It only reads files that end in .log.',
    'It has not run yet.',
    'Setup was not run.',
    'Three causes:',
    'setup.sh has mode 644.',
    'There is no .env file.',
    'Next step: this prints setup.sh.',
]


def accepted_answers(folders):
    for folder in folders:
        for db in sorted(Path(folder).rglob('history.db')):
            try:
                connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
                rows = connection.execute("SELECT direct_answer FROM history WHERE status='accepted' "
                                          "AND intent IS NOT NULL AND direct_answer IS NOT NULL ORDER BY id").fetchall()
                connection.close()
            except sqlite3.Error:
                continue
            for (answer,) in rows:
                yield answer


def stands(sentence):
    """True when the built-in gate shows the sentence exactly as written."""
    try:
        reply = h.validate_reply(json.dumps({'intent': 'observation', 'cleaned_input': 'x', 'direct_answer': sentence,
                                               'execution_payload': None}), execution_confirmed=True)
    except h.GateError:
        return False
    return reply.direct_answer == sentence


def build(folders):
    seen, lines = set(), []
    candidates = [*FROM_TESTS, *test_choice_check.MISSING_FACT_QUESTIONS, *test_choice_check.PLAIN_CONTENT]
    for answer in candidates + list(accepted_answers(folders)):
        for sentence in gate_rules.sentences(answer):
            key = ' '.join(sentence.split())
            if len(key.split()) < 3 or len(key) > 400 or key in seen or PRIVATE.search(key) or '\x00' in key:
                continue
            if not stands(key):
                continue
            seen.add(key)
            lines.append(key)
    return lines


def main(argv):
    folders = argv[1:] or [str(h.ROOT / 'state')]
    lines = build(folders)
    header = ['# Known-good sentences. No operator gate rule may match one of these lines (gate_rules.py, `rule add`).',
              '# Built by build_known_good.py from accepted answers in history.db and the positive cases in the tests.',
              '# One sentence per line. Add a line by hand when a rule cut something that must stay.']
    OUT.write_text('\n'.join(header + lines) + '\n', encoding='utf-8')
    print(f'{len(lines)} sentences written to {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
