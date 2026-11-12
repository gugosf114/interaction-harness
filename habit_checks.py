"""Habits the gate stops that a regular expression cannot express: checks written in code.

A lane adds to this file when George's correction names a habit that `rule add` cannot hold (card self).
Two places to add:

  CUT_SENTENCES  whole sentences that are cut wherever they stand. Compared without regard to case,
                 surrounding marks and end punctuation. Add the sentence, and a test in test_habit_checks.py.
  CHECKS         functions. Each takes (answer, asked) and returns None when the reply stands, or one
                 sentence that says what is wrong; the gate then asks the model for one corrected reply.
                 Write the function, add it to the list, and add a test in test_habit_checks.py.

gate_rules.apply() runs both, after the built-in checks and the operator's rules kept as data.
"""
from __future__ import annotations

import re

# Each entry is one whole sentence. The history row or the date that caused it goes in a comment on its line.
CUT_SENTENCES: list[str] = [
    'Let me know how it goes.',  # 2026-11-12: George asked the gate to cut it from every answer.
]

# Functions (answer, asked) -> reason or None.
CHECKS: list = [
]

_EDGE = ' \t\r\n"\x27“”‘’`*_.!?:;,'


def plain(sentence: str) -> str:
    """A sentence reduced to what is compared: one case, single spaces, no marks at either end."""
    return ' '.join(sentence.casefold().split()).strip(_EDGE)


def apply(answer: str, asked: str | None, cut_sentences, note) -> tuple[str, str | None]:
    """The answer after the code habits, and the reason for a corrective retry, or None."""
    listed = {plain(sentence) for sentence in CUT_SENTENCES}
    listed.discard('')
    if listed:
        cleaned, cut = cut_sentences(answer, lambda sentence: plain(sentence) in listed)
        if cut and not cleaned:
            note('habit', 'CUT_SENTENCES', 'reject', answer)
            return answer, ('Every sentence of the reply is on the list of sentences the operator had cut. '
                            'Write the answer without them.')
        for sentence in cut:
            note('habit', 'CUT_SENTENCES', 'strip_sentence', sentence)
        answer = cleaned if cut else answer
    for check in CHECKS:
        reason = check(answer, asked)
        if reason:
            note('habit', getattr(check, '__name__', 'check'), 'reject', answer)
            return answer, re.sub(r'\s+', ' ', str(reason)).strip()
    return answer, None
