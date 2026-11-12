"""note: the lanes write George's memory notes, in his own format.

  note add NAME "TEXT"    a new note NAME.md in the memory folder, and its one-line pointer in MEMORY.md
  note show NAME          one note
  note list               every note: name and its one-line description

A note file is the same shape as the ones Claude Code writes there: a front block with name,
description and metadata type, then the text. The pointer line is the same shape as the index lines:
"- [Title](NAME.md) — hook". Lane notes go under the heading "## From the lanes" at the end of MEMORY.md.
An existing note is never overwritten. Standard library only: it runs in native Termux and in Debian.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys

ROOTFS = '/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs'
DEBIAN_FOLDER = '/root/.claude/projects/-root/memory'
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
SECTION = '## From the lanes'
MAX_TEXT = 20000
HOOK_CHARS = 90
CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class NoteError(ValueError):
    """A short reason George can read."""


def folder() -> Path:
    """The memory folder: NOTE_DIR when set, else the Debian path, reached from native Termux through the Debian files."""
    chosen = os.environ.get('NOTE_DIR')
    if chosen:
        return Path(chosen)
    if os.path.isdir(DEBIAN_FOLDER) or not os.path.isdir(ROOTFS):
        return Path(DEBIAN_FOLDER)
    return Path(ROOTFS + DEBIAN_FOLDER)


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name) or name.lower() == 'memory':
        raise NoteError('A note name is 1 to 64 small letters, digits or hyphens, starting with a letter or digit. Example: bakery-oven-temps')
    return name


def one_line(text: str) -> str:
    return ' '.join(text.split())


def hook(text: str) -> str:
    line = one_line(text)
    return line if len(line) <= HOOK_CHARS else line[:HOOK_CHARS - 1].rstrip() + '…'


def title(name: str) -> str:
    return name.replace('-', ' ').capitalize()


def note_text(name: str, text: str, today: datetime) -> str:
    stamp = f'{today.month}/{today.day}'
    description = json.dumps(f'{stamp}: {one_line(text)[:300]}', ensure_ascii=False)
    return (f'---\nname: {name}\ndescription: {description}\nmetadata:\n  type: reference\n  origin: harness lane\n'
            f'  created: {today.strftime("%Y-%m-%d %H:%M")}\n---\n\n{text.strip()}\n')


def pointer(name: str, text: str, today: datetime) -> str:
    return f'- [{title(name)}]({name}.md) — {today.month}/{today.day}: {hook(text)}'


def add(name: str, text: str, place: Path | None = None, today: datetime | None = None) -> tuple[Path, str]:
    """Write NAME.md and append its pointer to MEMORY.md. Returns the note path and the pointer line."""
    check_name(name)
    text = (text or '').strip()
    if not text:
        raise NoteError('The note text is empty.')
    if len(text) > MAX_TEXT:
        raise NoteError(f'The note text is over {MAX_TEXT} characters.')
    if CONTROLS.search(text):
        raise NoteError('The note text holds control characters.')
    place = Path(place or folder())
    index = place / 'MEMORY.md'
    if not index.is_file():
        raise NoteError(f'No MEMORY.md in {place}.')
    today = today or datetime.now()
    path = place / (name + '.md')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        raise NoteError(f'A note named {name} already exists. Pick another name, or read it with: note show {name}') from None
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(note_text(name, text, today))
    line = pointer(name, text, today)
    current = index.read_text(encoding='utf-8')
    addition = ('' if current.endswith('\n') or not current else '\n')
    if not any(row.rstrip() == SECTION for row in current.splitlines()):
        addition += f'\n{SECTION}\n'
    # One appended write, so a note written at the same moment by another session is not lost.
    with open(index, 'a', encoding='utf-8') as stream:
        stream.write(addition + line + '\n')
    return path, line


def front(text: str) -> dict:
    """name and description from a note's front block."""
    found = {}
    if text.startswith('---'):
        for row in text.split('\n---', 1)[0].splitlines()[1:]:
            key, _, value = row.partition(':')
            if key in ('name', 'description') and value.strip():
                value = value.strip()
                try:
                    value = json.loads(value) if value.startswith('"') else value
                except ValueError:
                    pass
                found[key] = value
    return found


def show(name: str, place: Path | None = None) -> str:
    path = Path(place or folder()) / (check_name(name) + '.md')
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise NoteError(f'No note named {name}. See: note list') from None


def listing(place: Path | None = None) -> list[tuple[str, str]]:
    place = Path(place or folder())
    rows = []
    for path in sorted(place.glob('*.md')):
        if path.name == 'MEMORY.md':
            continue
        try:
            head = path.read_text(encoding='utf-8')[:3000]
        except (OSError, UnicodeDecodeError):
            continue
        rows.append((path.stem, one_line(str(front(head).get('description', '')))))
    return rows


USAGE = '''usage:
  note add NAME "TEXT"   a new note in George's memory folder, with its pointer line in MEMORY.md
  note show NAME         print one note
  note list              every note: name and description'''


def main(argv=None, out=sys.stdout) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(argv) >= 3 and argv[0] == 'add':
            path, line = add(argv[1], ' '.join(argv[2:]))
            out.write(f'{path}\nMEMORY.md: {line}\n')
        elif len(argv) == 2 and argv[0] == 'show':
            out.write(show(argv[1]))
        elif argv == ['list']:
            rows = listing()
            width = max((len(name) for name, _ in rows), default=0)
            out.write(''.join(f'{name:{width}}  {text[:110]}\n' for name, text in rows))
            out.write(f'{len(rows)} notes in {folder()}\n')
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except NoteError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'File error: {exc.strerror or exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
