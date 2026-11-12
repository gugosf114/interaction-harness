"""Operator gate rules kept as data, applied after every built-in check.

The file is state/gate_rules.json in this installation: a JSON list. Each entry holds
  name         short name, lower-case letters, digits and hyphens
  pattern      a regular expression, matched without regard to case, one sentence at a time
  action       "strip_sentence" (cut each sentence that matches) or "reject" (one corrective retry)
  bad          the sentences the rule must match
  date         the day it was added
  history_row  the history.db row of the correction that caused it

add_rule() refuses a rule unless it matches every one of its own bad sentences and matches nothing in
gate_known_good.txt, the shipped file of sentences that must stay. The `rule` command (toolbox/bin/rule)
is the door: rule add, rule list, rule drop, rule test.

Habits that no regular expression can express are checks in code: habit_checks.py. They run here too.

Only the standard library is used, so the Termux-side command and the Debian-side gate share this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import threading

import habit_checks

# The command-line entry point sets this (second_gate.switch_on). A plain import, which is what the
# unit tests do, leaves it off, so tests never read the operator's real rules.
RULES_FILE: Path | None = None
KNOWN_GOOD_FILE = Path(__file__).resolve().parent / 'gate_known_good.txt'
ACTIONS = ('strip_sentence', 'reject')
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,47}\Z')
ENTRY_KEYS = {'name', 'pattern', 'action', 'bad', 'date', 'history_row'}
SLOW_SECONDS = 5.0
_LIST_MARK = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")

# What the gate cut or rejected, newest last. The client drains it after each reply and saves it with the turn.
_fired_local = threading.local()
_cache: dict = {}
_warned: set = set()


class RuleError(Exception):
    """A short, user-visible reason why a rule cannot be added, loaded or used."""


class Rule:
    def __init__(self, entry: dict):
        self.name = entry['name']
        self.pattern = entry['pattern']
        self.action = entry['action']
        self.bad = list(entry['bad'])
        self.date = entry['date']
        self.history_row = entry['history_row']
        self.regex = compile_pattern(self.pattern)

    def entry(self) -> dict:
        return {'name': self.name, 'pattern': self.pattern, 'action': self.action, 'bad': self.bad,
                'date': self.date, 'history_row': self.history_row}


def compile_pattern(pattern: str) -> re.Pattern:
    if not isinstance(pattern, str) or not pattern.strip():
        raise RuleError('The pattern is empty.')
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise RuleError(f'The pattern is not a valid regular expression: {exc}.') from exc


def sentences(text: str) -> list[str]:
    """The sentences of a text, the way the gate reads them: line by line, list marks set aside."""
    found = []
    for line in text.split('\n'):
        mark = _LIST_MARK.match(line)
        body = line[mark.end():] if mark else line
        found.extend(part.strip() for part in _SENTENCE_END.split(body) if part.strip())
    return found


def check_entry(entry, number: int = 0) -> Rule:
    """One entry of the rules file as a Rule. Raises RuleError with the reason when it is malformed."""
    where = f'Rule entry {number}' if number else 'The rule'
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        raise RuleError(f'{where} must hold exactly: name, pattern, action, bad, date, history_row.')
    if not isinstance(entry['name'], str) or not NAME.fullmatch(entry['name']):
        raise RuleError(f'{where} needs a name of 1 to 48 lower-case letters, digits or hyphens.')
    where = f'Rule "{entry["name"]}"'
    if entry['action'] not in ACTIONS:
        raise RuleError(f'{where}: the action must be strip_sentence or reject.')
    if not (isinstance(entry['bad'], list) and entry['bad']
            and all(isinstance(item, str) and item.strip() for item in entry['bad'])):
        raise RuleError(f'{where} needs at least one bad sentence.')
    if type(entry['history_row']) is not int or entry['history_row'] < 1:
        raise RuleError(f'{where} must name the history row that caused it.')
    if not isinstance(entry['date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry['date']):
        raise RuleError(f'{where} needs a date as YYYY-MM-DD.')
    try:
        return Rule(entry)
    except RuleError as exc:
        raise RuleError(f'{where}: {exc}') from exc


def known_good(path: Path | None = None) -> list[str]:
    """The shipped sentences no rule may match. One per line; lines that start with # are notes."""
    path = Path(path or KNOWN_GOOD_FILE)
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleError(f'The known-good sentences cannot be read: {path}') from exc
    return [line.strip() for line in lines if line.strip() and not line.startswith('#')]


def self_test(rule: Rule, good: list[str] | None = None) -> list[str]:
    """Why the rule may not be used; an empty list when it passes its own test."""
    problems = []
    started = time.monotonic()
    for text in rule.bad:
        if not any(rule.regex.search(sentence) for sentence in sentences(text)):
            problems.append('It does not match its own bad sentence: ' + repr(text[:120]))
    hits = [line for line in (known_good() if good is None else good) if rule.regex.search(line)]
    if hits:
        problems.append(f'It matches {len(hits)} known-good sentence' + ('s' if len(hits) > 1 else '') + ': '
                        + '; '.join(repr(line[:120]) for line in hits[:3]))
    if time.monotonic() - started > SLOW_SECONDS:
        problems.append(f'The pattern took more than {SLOW_SECONDS:.0f} seconds on the test sentences.')
    return problems


def read_entries(path: Path) -> list:
    try:
        raw = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleError(f'The rules file cannot be read: {path}') from exc
    if not raw.strip():
        return []
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        raise RuleError(f'The rules file is not valid JSON: {path}') from exc
    if not isinstance(entries, list):
        raise RuleError(f'The rules file must hold one JSON list: {path}')
    return entries


def load(path: Path | None = None) -> tuple[list[Rule], list[str]]:
    """Every usable rule in the file, in file order, and the reason for each entry that was skipped."""
    rules, problems = [], []
    try:
        entries = read_entries(path)
    except RuleError as exc:
        return [], [str(exc)]
    for number, entry in enumerate(entries, 1):
        try:
            rule = check_entry(entry, number)
        except RuleError as exc:
            problems.append(str(exc))
            continue
        if any(other.name == rule.name for other in rules):
            problems.append(f'Rule "{rule.name}" is listed twice; the second one is skipped.')
            continue
        rules.append(rule)
    return rules, problems


def write_entries(path: Path, entries: list) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(entries, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def add_rule(path: Path, *, name: str, pattern: str, action: str, bad: list[str], history_row: int, date: str,
             good: list[str] | None = None) -> Rule:
    """Test the rule, then append it. Nothing is written when the rule is refused."""
    rule = check_entry({'name': name, 'pattern': pattern, 'action': action, 'bad': list(bad), 'date': date,
                        'history_row': history_row})
    entries = read_entries(path)
    if any(isinstance(entry, dict) and entry.get('name') == name for entry in entries):
        raise RuleError(f'A rule named "{name}" exists. Drop it first, or pick another name.')
    problems = self_test(rule, good)
    if problems:
        raise RuleError(f'Rule "{name}" was refused. ' + ' '.join(problems))
    write_entries(path, [*entries, rule.entry()])
    return rule


def drop_rule(path: Path, name: str) -> dict:
    entries = read_entries(path)
    kept = [entry for entry in entries if not (isinstance(entry, dict) and entry.get('name') == name)]
    if len(kept) == len(entries):
        raise RuleError(f'No rule named "{name}".')
    write_entries(path, kept)
    return next(entry for entry in entries if isinstance(entry, dict) and entry.get('name') == name)


def active_rules() -> list[Rule]:
    """The operator's rules for this process. The file is read again whenever it changes on disk."""
    if RULES_FILE is None:
        return []
    try:
        info = os.stat(RULES_FILE)
        stamp = (str(RULES_FILE), info.st_mtime_ns, info.st_size)
    except OSError:
        return []
    if _cache.get('stamp') != stamp:
        rules, problems = load(RULES_FILE)
        _cache.update(stamp=stamp, rules=rules)
        for problem in problems:
            if problem not in _warned:
                _warned.add(problem)
                print('Gate rules: ' + problem, file=sys.stderr)
    return _cache['rules']


def note(kind: str, name: str, action: str, text: str) -> None:
    if not hasattr(_fired_local, 'items'): _fired_local.items = []
    _fired_local.items.append({'kind': kind, 'name': name, 'action': action, 'text': text[:500]})


def drain() -> list[dict]:
    """What fired since the last call, oldest first. The list is emptied."""
    fired = list(getattr(_fired_local, 'items', []))
    _fired_local.items = []
    return fired


def cut_sentences(text: str, matches) -> tuple[str, list[str]]:
    """Remove each sentence for which matches(sentence) is true. Every other sentence stays as written."""
    out_lines, cut = [], []
    for line in text.split('\n'):
        mark = _LIST_MARK.match(line)
        head, body = (mark.group(1), line[mark.end():]) if mark else ('', line)
        kept = []
        for sentence in _SENTENCE_END.split(body):
            if sentence.strip() and matches(sentence.strip()):
                cut.append(sentence.strip())
                continue
            kept.append(sentence)
        new_body = ' '.join(part for part in kept if part.strip())
        if body.strip() and not new_body.strip():
            continue  # the whole line was cut
        out_lines.append(head + new_body if body.strip() else line)
    return re.sub(r"\n{3,}", "\n\n", '\n'.join(out_lines)).strip(), cut


def apply_rules(answer: str, rules: list[Rule]) -> tuple[str, str | None]:
    for rule in rules:
        if rule.action == 'reject':
            for sentence in sentences(answer):
                found = rule.regex.search(sentence)
                if found:
                    note('rule', rule.name, 'reject', sentence)
                    return answer, (f'The reply matches the operator\'s gate rule "{rule.name}": '
                                    + repr(found.group(0)[:100]) + '. Write the reply without it.')
            continue
        cleaned, cut = cut_sentences(answer, lambda sentence, rule=rule: bool(rule.regex.search(sentence)))
        if not cut:
            continue
        if not cleaned:
            note('rule', rule.name, 'reject', answer)
            return answer, (f'Every sentence of the reply matches the operator\'s gate rule "{rule.name}", '
                            'which cuts such sentences. Write the answer without them.')
        for sentence in cut:
            note('rule', rule.name, 'strip_sentence', sentence)
        answer = cleaned
    return answer, None


def apply(answer: str, asked: str | None = None) -> tuple[str, str | None]:
    """The answer after the operator's rules and the code habits, and the reason for a corrective retry, or None."""
    answer, reason = apply_rules(answer, active_rules())
    if reason:
        return answer, reason
    return habit_checks.apply(answer, asked, cut_sentences, note)
