"""Proof marks, rebuilt from the proof-marks mod for the lanes.

After the final answer of a turn, a small model grades each line of it against the command results the
session has seen: g = a command result shows it, y = memory, opinion, plan or guess, r = a hard claim the
results contradict or nothing backs. The answer on stdout is never changed. The marks go to stderr: one count
line, then every red line. The lanes' "colors" are this line, since stdout stays answer-only.
"""
from __future__ import annotations

import json
import re

EVIDENCE_CAP = 60000
SYSTEM = ('You grade each numbered line of an assistant reply for how well EVIDENCE supports the claim the line '
          'actually makes. The evidence is command results from the current work session. Use the whole reply as '
          'context so you can tell a real claim from an example or hypothetical. Reply with JSON only.')
WORD = {'g': 'shown', 'y': 'guess', 'r': 'no proof'}
COLOR = {'g': '\033[32m', 'y': '\033[33m', 'r': '\033[31m'}


def content_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.split('\n') if line.strip()]


def evidence(history: list) -> str:
    """Every execution observation in the request history, newest kept first under the cap, back in order."""
    blocks = [m['content'][:4000] for m in history
              if m.get('role') == 'user' and isinstance(m.get('content'), str) and '"execution_observation"' in m['content']]
    out, total = [], 0
    for block in reversed(blocks):
        if total + len(block) > EVIDENCE_CAP and out:
            break
        out.insert(0, block)
        total += len(block)
    return '\n---\n'.join(out)


def grade_prompt(proof: str, lines: list[str]) -> str:
    numbered = '\n'.join(f'{i}| {line.strip()}' for i, line in enumerate(lines, 1))
    return (f'EVIDENCE - command results from this session, newest last:\n{proof or "(no commands have run this session)"}\n\n'
            f'REPLY LINES - grade each:\n{numbered}\n\n'
            'Grade every line with ONE letter:\n'
            'g = a factual statement the EVIDENCE supports (a value it printed, a file or output it shows). For a claim '
            'that an action was just DONE (pushed, committed, sent, deployed, saved, "it works", "done"), use g ONLY if the '
            'evidence actually shows that action happened.\n'
            'y = anything not proven by the evidence but not false: an opinion, a plan, a question, a heading, OR a '
            'hypothetical / example (often marked by "would", "let\'s say", "for example", "if", "imagine"), OR a general '
            'fact from common knowledge.\n'
            'r = a specific factual claim STATED AS FACT that the evidence directly contradicts, or a concrete done/action '
            'claim stated as fact with no support anywhere. NEVER use r for an example, hypothetical, question, plan, or '
            'opinion. When unsure between y and r, choose y.\n'
            'Return ONLY a JSON object mapping line number to letter, like {"1":"g","2":"y","3":"r"}.')


def parse(raw: str | None, count: int) -> list[str] | None:
    match = re.search(r'\{.*\}', raw or '', re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    marks = []
    for i in range(1, count + 1):
        value = str(obj.get(str(i), 'y')).lower()[:1]
        marks.append(value if value in WORD else 'y')
    return marks


def render(lines: list[str], marks: list[str], color: bool = False) -> str:
    def paint(mark, text):
        return f'{COLOR[mark]}{text}\033[0m' if color else text
    counts = {m: marks.count(m) for m in 'gyr'}
    head = 'proof: ' + ' · '.join(paint(m, f'{counts[m]} {WORD[m]}') for m in 'gyr')
    reds = ['  ' + paint('r', '✗ ' + line.strip()) for line, mark in zip(lines, marks) if mark == 'r']
    return '\n'.join([head, *reds])
