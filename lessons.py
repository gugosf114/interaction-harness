"""The lessons page: facts George stated when he corrected an answer.

state/lessons.md holds one dated line per fact. state/pages.json lists the file as its last page
(label "lessons"), so every call on both lanes carries it, after the rules and profile pages.
Each line names the history row of the correction that caused it.

add() appends a line and puts the page on the list; drop() removes a line, and takes the page off
the list when no line is left. A line that would break the page limits in pages.py is refused and
nothing is written, because a page over the limit stops every call.

Only the standard library and pages.py are used, so the Termux-side `lesson` command and the tests share it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

import gate_admin
import pages

FILE = 'lessons.md'
PAGES = 'pages.json'
LABEL = 'lessons'
HEADER = ('# Lessons\n'
          'Facts George stated when he corrected an answer. Each one stands until he says otherwise.\n'
          'Each line: the date, the history row of his correction, the fact.\n')
LINE = re.compile(r'^- (\d{4}-\d{2}-\d{2}) \(row (\d+)\): (.+)$')
CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class LessonError(Exception):
    """A short, user-visible reason why the lessons page was not changed."""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise LessonError(f'Cannot read {path}.') from exc


def restore(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
    else:
        write_text(path, text)


def entries(config: Path) -> list[dict]:
    """Every lesson on the page, in page order, numbered from 1."""
    text = read_or_none(Path(config) / FILE) or ''
    found = []
    for line in text.splitlines():
        match = LINE.match(line)
        if match:
            found.append({'number': len(found) + 1, 'date': match.group(1), 'row': int(match.group(2)),
                          'text': match.group(3), 'line': line})
    return found


def page_list(config: Path) -> list:
    raw = read_or_none(Path(config) / PAGES)
    if raw is None or not raw.strip():
        return []
    try:
        listed = json.loads(raw)
    except ValueError as exc:
        raise LessonError('The page list (pages.json) is not valid JSON. It was not changed.') from exc
    if not isinstance(listed, list):
        raise LessonError('The page list (pages.json) must be a JSON list. It was not changed.')
    return listed


def ensure_page(config: Path, present: bool) -> None:
    """Put the lessons page last on the page list, or take it off the list. Other entries stay as they are."""
    config = Path(config)
    listed = page_list(config)
    others = [entry for entry in listed if not (isinstance(entry, dict) and entry.get('label') == LABEL)]
    wanted = others + ([{'label': LABEL, 'path': str((config / FILE).resolve())}] if present else [])
    if wanted != listed:
        write_text(config / PAGES, json.dumps(wanted, ensure_ascii=False, indent=2) + '\n')


def check_pages(config: Path) -> None:
    try:
        pages.read_pages(Path(config) / PAGES)
    except pages.PageError as exc:
        raise LessonError(str(exc)) from exc


def add(config: Path, text: str, row: int, date: str) -> dict:
    """Append one dated line that names its history row. Returns the new entry."""
    config = Path(config)
    fact = ' '.join((text or '').split())
    if not fact:
        raise LessonError('The lesson is empty.')
    if CONTROLS.search(fact):
        raise LessonError('The lesson contains control characters.')
    if type(row) is not int or row < 1:
        raise LessonError('A lesson names the history row that caused it.')
    with gate_admin.locked(config):
        path = config / FILE
        before, before_list = read_or_none(path), read_or_none(config / PAGES)
        for entry in entries(config):
            if entry['text'].casefold() == fact.casefold():
                raise LessonError(f'That lesson is already on the page, as line {entry["number"]}.')
        body = before if before and before.strip() else HEADER
        line = f'- {date} (row {row}): {fact}'
        try:
            write_text(path, body.rstrip('\n') + '\n' + line + '\n')
            ensure_page(config, True)
            check_pages(config)
        except LessonError:
            restore(path, before)
            restore(config / PAGES, before_list)
            raise
    return entries(config)[-1]


def drop(config: Path, number: int) -> dict:
    """Remove lesson NUMBER (as `lesson list` shows it). The page leaves the list when no lesson is left."""
    config = Path(config)
    with gate_admin.locked(config):
        found = entries(config)
        if not 1 <= number <= len(found):
            raise LessonError(f'No lesson {number}. The page holds {len(found)}.')
        gone = found[number - 1]
        path = config / FILE
        lines = (read_or_none(path) or '').splitlines()
        seen = 0
        for index, line in enumerate(lines):
            if LINE.match(line):
                seen += 1
                if seen == number:
                    del lines[index]
                    break
        write_text(path, '\n'.join(lines) + '\n')
        ensure_page(config, len(found) > 1)
    return gone
