"""Operator pages: extra system pages read at run time from files the operator already keeps.

The list lives in state/pages.json, which git ignores. Page text is sent word for word. It is
never copied into the repository and never written to the usage log.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import NamedTuple

MAX_PAGE_CHARS = 20000
MAX_TOTAL_CHARS = 40000
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z')
CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
ENTRY_KEYS = {'label', 'path', 'sections'}


class PageError(Exception):
    """A short, user-visible reason why the page list cannot be sent."""


class Page(NamedTuple):
    label: str
    text: str
    sha256: str


def take_sections(text: str, headings: list[str], label: str) -> str:
    """The named sections, in the order named. A section runs from its heading line to the next '## ' line."""
    lines = text.splitlines(keepends=True)
    parts = []
    for heading in headings:
        found = [index for index, line in enumerate(lines) if line.rstrip() == heading]
        if not found:
            raise PageError(f'Page "{label}": heading not found: {heading}')
        if len(found) > 1:
            raise PageError(f'Page "{label}": heading appears more than once: {heading}')
        start = found[0]
        end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith('## ')), len(lines))
        part = ''.join(lines[start:end])
        parts.append(part if part.endswith('\n') else part + '\n')
    return ''.join(parts)


def read_pages(list_path: Path) -> list[Page]:
    """Every page on the list, in listed order. A missing or empty list is an empty result. Nothing is ever cut to fit."""
    try:
        raw = Path(list_path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise PageError('The page list cannot be read.') from exc
    if not raw.strip():
        return []
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        raise PageError('The page list is not valid JSON.') from exc
    if not isinstance(entries, list):
        raise PageError('The page list must be a JSON list of pages.')
    pages, total = [], 0
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not set(entry) <= ENTRY_KEYS:
            raise PageError(f'Page list entry {number} may hold only label, path and sections.')
        label, path, sections = entry.get('label'), entry.get('path'), entry.get('sections')
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            raise PageError(f'Page list entry {number} needs a label of 1 to 32 letters, digits, underscores or hyphens.')
        if any(page.label == label for page in pages):
            raise PageError(f'Page "{label}" is listed twice.')
        if not isinstance(path, str) or not os.path.isabs(path):
            raise PageError(f'Page "{label}" needs an absolute file path.')
        if sections is not None and not (isinstance(sections, list) and sections
                                         and all(isinstance(item, str) and item.strip() for item in sections)):
            raise PageError(f'Page "{label}": sections must be a list of headings.')
        try:
            text = Path(path).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            raise PageError(f'Page "{label}": the file is missing or unreadable.') from exc
        if sections is not None:
            text = take_sections(text, sections, label)
        text = text.strip()
        if not text:
            raise PageError(f'Page "{label}" is empty.')
        if CONTROLS.search(text):
            raise PageError(f'Page "{label}" contains control characters.')
        if len(text) > MAX_PAGE_CHARS:
            raise PageError(f'Page "{label}" exceeds {MAX_PAGE_CHARS} characters.')
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            raise PageError(f'The extra pages together exceed {MAX_TOTAL_CHARS} characters.')
        pages.append(Page(label, text, hashlib.sha256(text.encode('utf-8')).hexdigest()))
    return pages


def cache_marked(count: int, base: int | None = None) -> set[int]:
    """Indexes of the system pages that carry an Anthropic cache marker.

    base is how many pages come before the operator's pages: the frozen prefix, then the tools page
    when there is one. It defaults to two. With no operator pages every page is marked, as before.
    With operator pages there are exactly two markers: the last base page and the last page sent.
    """
    base = min(count, 2 if base is None else base)
    if count <= base:
        return set(range(count))
    return {base - 1, count - 1}


def anthropic_system(system_pages: list[str], base: int | None = None) -> list[dict]:
    """The Anthropic `system` parameter: one text block per page, cache markers per cache_marked()."""
    marked = cache_marked(len(system_pages), base)
    return [{'type': 'text', 'text': page, **({'cache_control': {'type': 'ephemeral'}} if index in marked else {})}
            for index, page in enumerate(system_pages)]
