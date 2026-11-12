"""Switches the second gate on for a real command-line run.

harness.py calls switch_on() from its `__main__` block, next to the operator's page list. A plain import,
which is what the unit tests do, leaves everything here off, so tests never read the operator's real
rules and never call a judge.

The parts:
  gate_rules.py     the operator's gate rules kept as data (state/gate_rules.json) and the `rule` command
  habit_checks.py   habits no regular expression can express, written as checks in code
  reply_judge.py    the judge on the other engine, with one corrective retry
  corrections.py    /wrong WORDS: a correction becomes a lessons line or a gate rule
  lessons.py        the lessons page (state/lessons.md), listed last in state/pages.json
"""
from pathlib import Path


def switch_on(config_dir) -> None:
    """config_dir is the installation's state folder, where pages.json and the saved keys are."""
    import gate_rules
    gate_rules.RULES_FILE = Path(config_dir) / 'gate_rules.json'
    import reply_judge
    reply_judge.LIVE = True
