"""Session surgery for the harness: fork, rewind, cut, splice, the golden session, a list and an export.

Standard library only, so the same file runs inside the harness (Debian) and as the `session` and
`sessions` commands in native Termux. Every change takes the same lock a live turn takes.

One exchange here is one message from the operator together with everything the lane did for it:
in --loop runs that is the first model turn and every continuation turn that followed.
History rows in history.db are never touched. Exchanges that leave a session are appended to a
side file next to it (NAME.removed.jsonl), and their fingerprints stay in the session so the
past-chat search does not hand them back.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from storage import NAME, atomic_json, now, private_dir

ROOT = Path(__file__).resolve().parent
GOLDEN_FILE = 'golden-session.json'
LANES = {'anthropic': 'george', 'openai': 'g1'}
DOWNLOADS = '/sdcard/Download'
PHONE_HOME = '/data/data/com.termux/files/home'
CONTINUATION = 'Continue the original task using the recorded execution observation.'


class SessionError(ValueError):
    """A short reason the operator can read."""


def state_dir() -> Path:
    return Path(os.environ.get('HARNESS_STATE_DIR') or ROOT / 'state').expanduser()


def sessions_dir(state) -> Path:
    return Path(state) / 'sessions'


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise SessionError('Session names use 1–64 letters, digits, underscores, or hyphens.')
    return name


def session_file(state, name: str) -> Path:
    return sessions_dir(state) / (check_name(name) + '.json')


def exists(state, name: str) -> bool:
    try:
        return session_file(state, name).is_file()
    except SessionError:
        return False


def read(state, name: str) -> dict:
    path = session_file(state, name)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise SessionError(f'No session named {name}.') from None
    except (OSError, ValueError):
        raise SessionError(f'The session {name} cannot be read.') from None
    if not isinstance(data, dict) or data.get('id') != name or not isinstance(data.get('turns'), list):
        raise SessionError(f'The session {name} is not a valid session file.')
    return data


@contextmanager
def locked(state, name: str):
    """The lock storage.Store.session takes for a live turn."""
    folder = sessions_dir(state)
    private_dir(Path(state))
    private_dir(folder)
    descriptor = os.open(folder / (check_name(name) + '.lock'), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write(state, data: dict) -> None:
    data['updated_at'] = now()
    atomic_json(session_file(state, data['id']), data)


# ---------------------------------------------------------------- exchanges

def groups(turns: list) -> list[list[int]]:
    """Indexes of the model turns in each operator exchange. A loop continuation belongs to the exchange before it."""
    result: list[list[int]] = []
    for index, turn in enumerate(turns):
        step = turn.get('loop_step')
        if result and isinstance(step, int) and step > 1:
            result[-1].append(index)
        else:
            result.append([index])
    return result


def fingerprint(turn: dict) -> str:
    """The same fingerprint recall_notes uses: the operator's words and the answer."""
    asked = turn.get('raw_input') or ''
    answer = (turn.get('reply') or {}).get('direct_answer') or ''
    return hashlib.sha256((asked + '\x00' + answer).encode('utf-8', 'replace')).hexdigest()


def first_line(text: str, width: int = 70) -> str:
    line = next((part.strip() for part in (text or '').splitlines() if part.strip()), '')
    return line if len(line) <= width else line[:width - 1].rstrip() + '…'


def put_aside(state, name: str, turns: list, why: str) -> None:
    """Exchanges that leave a session are kept, one JSON line each, next to the session file."""
    if not turns:
        return
    path = sessions_dir(state) / (name + '.removed.jsonl')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'a') as stream:
        for turn in turns:
            stream.write(json.dumps({'removed_at': now(), 'by': why, 'exchange': turn}, ensure_ascii=False) + '\n')


def remove_groups(state, name: str, first: int, last: int, why: str) -> tuple[dict, list]:
    """Drop operator exchanges first..last (1-based, inclusive). Returns the session and the turns that left."""
    with locked(state, name):
        data = read(state, name)
        parts = groups(data['turns'])
        if not parts:
            raise SessionError(f'The session {name} has no exchange.')
        if not 1 <= first <= last <= len(parts):
            raise SessionError(f'The session {name} has {len(parts)} exchange' + ('' if len(parts) == 1 else 's')
                               + f'; {first} to {last} is outside it.')
        gone = [index for part in parts[first - 1:last] for index in part]
        removed = [data['turns'][index] for index in gone]
        data['turns'] = [turn for index, turn in enumerate(data['turns']) if index not in set(gone)]
        data['rewound'] = sorted(set(data.get('rewound') or []) | {fingerprint(turn) for turn in removed})
        put_aside(state, name, removed, why)
        write(state, data)
    return data, removed


def rewind(state, name: str, count: int = 1) -> tuple[dict, list]:
    """Drop the last `count` operator exchanges from a session."""
    if count < 1:
        raise SessionError('Rewind takes a count of 1 or more.')
    total = len(groups(read(state, name)['turns']))
    if count > total:
        raise SessionError(f'The session {name} has {total} exchange' + ('' if total == 1 else 's') + f'; cannot rewind {count}.')
    return remove_groups(state, name, total - count + 1, total, 'rewind')


def cut(state, name: str, first: int, last: int) -> tuple[dict, list]:
    return remove_groups(state, name, first, last, 'cut')


def free_name(state, wanted: str) -> str:
    base = wanted[:58]
    name, number = base, 1
    while exists(state, name):
        number += 1
        name = f'{base}-{number}'
    return name


def fork(state, source: str, new: str | None = None) -> tuple[str, int]:
    """A new session that starts as a full copy of `source`. The source file is not written. Returns (name, exchanges)."""
    with locked(state, source):
        original = read(state, source)
    if new is None:
        new = free_name(state, source[:53] + '-fork')
    check_name(new)
    with locked(state, new):
        if exists(state, new):
            raise SessionError(f'A session named {new} already exists.')
        data = copy.deepcopy(original)
        count = len(groups(data['turns']))
        data.update(id=new, created_at=now(),
                    forked_from={'id': source, 'at': now(), 'exchanges': count, 'model_turns': len(data['turns'])})
        write(state, data)
    return new, count


def seed(state, name: str, source: str) -> int | None:
    """Start the new session `name` as a copy of `source`. An existing session is left alone (returns None)."""
    if exists(state, name):
        return None
    return fork(state, source, name)[1]


def splice(state, name: str, other: str, first: int | None = None, last: int | None = None) -> tuple[dict, int]:
    """Append the exchanges of `other` (or its exchanges first..last) to `name`. `other` is not written."""
    if name == other:
        raise SessionError('Splice needs two different sessions.')
    with locked(state, other):
        donor = read(state, other)
    parts = groups(donor['turns'])
    first = 1 if first is None else first
    last = len(parts) if last is None else last
    if not parts or not 1 <= first <= last <= len(parts):
        raise SessionError(f'The session {other} has {len(parts)} exchange' + ('' if len(parts) == 1 else 's')
                           + f'; {first} to {last} is outside it.')
    added = [copy.deepcopy(donor['turns'][index]) for part in parts[first - 1:last] for index in part]
    with locked(state, name):
        data = read(state, name)
        data['turns'].extend(added)
        data.setdefault('spliced', []).append({'from': other, 'exchanges': [first, last], 'at': now()})
        write(state, data)
    return data, last - first + 1


# ---------------------------------------------------------------- the golden session

def golden(state) -> str | None:
    """The session every new chat starts from, or None."""
    try:
        name = json.loads((Path(state) / GOLDEN_FILE).read_text()).get('id')
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and NAME.fullmatch(name) else None


def set_golden(state, name: str | None) -> None:
    path = Path(state) / GOLDEN_FILE
    if name is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    read(state, name)   # it must exist and be readable
    atomic_json(path, {'id': name, 'set_at': now()})


# ---------------------------------------------------------------- list and export

def local_time(stamp) -> str:
    try:
        return datetime.fromisoformat(str(stamp)).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return ''


def lane_of(turns: list) -> str:
    for turn in reversed(turns):
        if turn.get('engine'):
            return LANES.get(turn['engine'], turn['engine']) + (' (' + turn['model'] + ')' if turn.get('model') else '')
    return ''


def listing(state) -> list[dict]:
    """Every session, newest first: name, date, lane, exchange count, first line."""
    rows = []
    folder = sessions_dir(state)
    if not folder.is_dir():
        return rows
    for path in folder.glob('*.json'):
        try:
            data = json.loads(path.read_text())
            turns = data['turns']
            if data.get('id') != path.stem or not isinstance(turns, list):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        stamp = data.get('updated_at') or data.get('created_at') or ''
        rows.append({'name': path.stem, 'stamp': stamp, 'date': local_time(stamp), 'lane': lane_of(turns),
                     'exchanges': len(groups(turns)), 'model_turns': len(turns),
                     'first': first_line(turns[0].get('raw_input', '')) if turns else '',
                     'forked_from': (data.get('forked_from') or {}).get('id')})
    rows.sort(key=lambda row: row['stamp'], reverse=True)
    return rows


def listing_text(state) -> str:
    rows = listing(state)
    if not rows:
        return 'No sessions yet.\n'
    marked = golden(state)
    try:
        active = json.loads((Path(state) / 'active-session.json').read_text()).get('id')
    except (OSError, ValueError, AttributeError):
        active = None
    width = max(len(row['name']) for row in rows)
    lanes = max(len(row['lane']) for row in rows)
    lines = []
    for row in rows:
        mark = ('*' if row['name'] == marked else ' ') + ('>' if row['name'] == active else ' ')
        lines.append(f"{mark} {row['date']:16}  {row['name']:{width}}  {row['lane']:{lanes}}  {row['exchanges']:>4}  {row['first']}")
    legend = [f'{len(rows)} session' + ('' if len(rows) == 1 else 's') + '. Columns: date, name, lane, exchanges, first line.']
    if marked:
        legend.append(f'* golden: every new chat starts as a copy of {marked}.')
    if active:
        legend.append(f'> the session -c continues: {active}.')
    return '\n'.join(lines + legend) + '\n'


def clip(text: str, limit: int = 4000) -> str:
    text = text or ''
    if len(text) <= limit:
        return text
    return text[:limit * 2 // 3] + f'\n[... {len(text) - limit} characters left out ...]\n' + text[-(limit // 3):]


def transcript(data: dict) -> list[dict]:
    """The session as a list of plain parts: who, text, and what kind of part it is."""
    parts = []
    turns = data['turns']
    for number, indexes in enumerate(groups(turns), 1):
        for index in indexes:
            turn = turns[index]
            reply = turn.get('reply') or {}
            model = turn.get('model') or LANES.get(turn.get('engine'), 'lane')
            asked = turn.get('raw_input') or ''
            if index == indexes[0]:
                parts.append({'kind': 'operator', 'who': f'[{number}] George', 'text': asked})
                if turn.get('attachments'):
                    parts.append({'kind': 'note', 'who': 'attached', 'text': '\n'.join(item.get('path', '') for item in turn['attachments'])})
            if turn.get('recall_notes'):
                try:
                    passages = json.loads(turn['recall_notes']).get('passages', [])
                except ValueError:
                    passages = []
                if passages:
                    parts.append({'kind': 'note', 'who': 'past chats shown to the model',
                                  'text': '\n'.join(f"{item.get('date', '')} {item.get('source', '')} {item.get('ref', '')}: "
                                                    f"{item.get('text', '')}" for item in passages)})
            parts.append({'kind': 'answer', 'who': model, 'text': reply.get('direct_answer') or ''})
            if turn.get('sources'):
                parts.append({'kind': 'note', 'who': 'sources',
                              'text': '\n'.join(f"{item.get('title', '')} — {item.get('url', '')}" for item in turn['sources'])})
            if reply.get('execution_payload'):
                parts.append({'kind': 'command', 'who': 'command', 'text': reply['execution_payload']})
            result = turn.get('execution_result')
            if isinstance(result, dict):
                if result.get('approved') is False:
                    parts.append({'kind': 'note', 'who': 'result', 'text': 'declined'})
                else:
                    head = f"exit {result.get('exit_code')}" + (' (timed out)' if result.get('timed_out') else '')
                    streams = '\n'.join(part for part in (clip(result.get('stdout', '')).rstrip(), clip(result.get('stderr', '')).rstrip()) if part)
                    parts.append({'kind': 'output', 'who': head, 'text': streams})
            for note in turn.get('advisor_notes') or []:
                parts.append({'kind': 'note', 'who': f"advisor ({note.get('model', '')})", 'text': note.get('text', '')})
    return parts


def header(data: dict) -> list[str]:
    turns = data['turns']
    lines = [f"Session {data['id']}",
             f"Lane: {lane_of(turns) or 'none yet'}    Exchanges: {len(groups(turns))}    Model turns: {len(turns)}",
             f"Started: {local_time(data.get('created_at'))}    Last change: {local_time(data.get('updated_at') or data.get('created_at'))}"]
    if data.get('forked_from'):
        lines.append(f"Forked from: {data['forked_from'].get('id')} at {local_time(data['forked_from'].get('at'))}")
    return lines


def export_text(data: dict) -> str:
    lines = header(data) + ['']
    for part in transcript(data):
        if part['kind'] == 'operator':
            lines += ['', '=' * 72, part['who'] + ':', part['text'], '']
        elif part['kind'] == 'answer':
            lines += [part['who'] + ':', part['text'], '']
        else:
            body = part['text'].splitlines() or ['']
            lines += [f"  {part['who']}: {body[0]}"] + ['  ' + line for line in body[1:]] + ['']
    return '\n'.join(lines).rstrip('\n') + '\n'


PAGE_STYLE = ('@page{size:Letter;margin:0.8in}body{font-family:DejaVu Sans,sans-serif;font-size:10.5pt;line-height:1.35}'
              'h1{font-size:15pt;margin:0 0 4pt}.meta{color:#444;font-size:9pt;margin:0 0 14pt}'
              '.who{font-weight:bold;margin:10pt 0 2pt}.operator{border-top:1.5pt solid #000;padding-top:8pt;margin-top:14pt}'
              '.operator .who{color:#0b3d91}.text{white-space:pre-wrap;overflow-wrap:anywhere}'
              '.command .text,.output .text{font-family:DejaVu Sans Mono,monospace;font-size:8.5pt;background:#f1f1f1;padding:4pt}'
              '.note,.output,.command{margin-left:14pt}.note .text{font-size:9pt;color:#333}')


def export_html(data: dict) -> str:
    lines = header(data)
    body = [f'<h1>{html.escape(lines[0])}</h1><p class="meta">' + '<br>'.join(html.escape(line) for line in lines[1:]) + '</p>']
    for part in transcript(data):
        body.append(f'<div class="{part["kind"]}"><div class="who">{html.escape(part["who"])}</div>'
                    f'<div class="text">{html.escape(part["text"])}</div></div>')
    return ('<html><head><meta charset="utf-8"><style>' + PAGE_STYLE + '</style></head><body>' + ''.join(body) + '</body></html>')


def pdf_command(page: str, out: str) -> list[str]:
    """weasyprint lives on the Debian side. From native Termux it is reached through proot-distro."""
    if shutil.which('proot-distro'):
        return ['proot-distro', 'login', 'debian', '--', 'weasyprint', '-q', page, out]
    return ['weasyprint', '-q', page, out]


def export_pdf(state, name: str, out: str | None = None, run=subprocess.run) -> tuple[str, int]:
    """Write the session as a readable PDF. Default: /sdcard/Download/session-NAME.pdf. Returns (path, bytes)."""
    data = read(state, name)
    out = os.path.abspath(os.path.expanduser(out)) if out else f'{DOWNLOADS}/session-{name}.pdf'
    if not out.lower().endswith('.pdf'):
        raise SessionError('The PDF path must end in .pdf')
    # The page file must sit where both sides of the phone see it under the same path.
    folder = PHONE_HOME + '/tmp' if os.path.isdir(PHONE_HOME) else tempfile.gettempdir()
    os.makedirs(folder, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', suffix='.html', dir=folder, delete=False, encoding='utf-8') as handle:
        handle.write(export_html(data))
    try:
        done = run(pdf_command(handle.name, out), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        os.unlink(handle.name)
    if done.returncode != 0 or not os.path.isfile(out):
        raise SessionError('The PDF was not written: ' + ((done.stderr or done.stdout or 'weasyprint failed.').strip()[-400:]))
    return out, os.path.getsize(out)


# ---------------------------------------------------------------- the commands

USAGE = '''usage:
  sessions                              every session: date, name, lane, exchanges, first line
  session show NAME                     the session as plain text
  session export NAME [--pdf] [--out PATH]   --pdf writes /sdcard/Download/session-NAME.pdf
  session fork SOURCE [NEWNAME]         a new session that starts as a full copy of SOURCE
  session rewind NAME [N]               drop the last N exchanges (default 1)
  session cut NAME FROM TO              drop exchanges FROM to TO (numbers as in `session show`)
  session splice NAME OTHER [FROM TO]   append the exchanges of OTHER to NAME
  session golden [NAME | --clear]       the session every new chat starts from
One exchange is one message from George and everything the lane did for it.'''


def number(text: str, what: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise SessionError(f'{what} must be a whole number, 1 or more.')
    return int(text)


def plural(count: int, word: str = 'exchange') -> str:
    return f'{count} {word}' + ('' if count == 1 else 's')


def describe(removed: list) -> str:
    firsts = [first_line(turn.get('raw_input', ''), 60) for turn in removed
              if not (turn.get('raw_input') or '').startswith(CONTINUATION)]
    return '\n'.join('  dropped: ' + line for line in firsts)


def command(argv: list[str], state=None, out=sys.stdout) -> int:
    state = Path(state) if state is not None else state_dir()
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(USAGE, file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    try:
        if verb == 'list' and not rest:
            out.write(listing_text(state))
        elif verb == 'show' and len(rest) == 1:
            out.write(export_text(read(state, rest[0])))
        elif verb == 'export' and rest:
            name, flags = rest[0], rest[1:]
            target = None
            if '--out' in flags:
                spot = flags.index('--out')
                if spot + 1 >= len(flags):
                    raise SessionError('--out needs a path.')
                target = flags[spot + 1]
                del flags[spot:spot + 2]
            if set(flags) - {'--pdf'}:
                print(USAGE, file=sys.stderr)
                return 2
            if '--pdf' in flags or (target or '').lower().endswith('.pdf'):
                path, size = export_pdf(state, name, target)
                out.write(f'{path}  {size} bytes\n')
            elif target:
                text = export_text(read(state, name))
                Path(os.path.expanduser(target)).write_text(text, encoding='utf-8')
                out.write(f'{os.path.abspath(os.path.expanduser(target))}  {len(text.encode())} bytes\n')
            else:
                out.write(export_text(read(state, name)))
        elif verb == 'fork' and len(rest) in (1, 2):
            name, count = fork(state, rest[0], rest[1] if len(rest) == 2 else None)
            out.write(f'{name}: a copy of {rest[0]} with {plural(count)}. {rest[0]} is unchanged.\n')
        elif verb == 'rewind' and len(rest) in (1, 2):
            data, removed = rewind(state, rest[0], number(rest[1], 'N') if len(rest) == 2 else 1)
            out.write(f'{rest[0]}: {plural(len(groups(data["turns"])))} left.\n' + (describe(removed) + '\n' if removed else ''))
        elif verb == 'cut' and len(rest) == 3:
            data, removed = cut(state, rest[0], number(rest[1], 'FROM'), number(rest[2], 'TO'))
            out.write(f'{rest[0]}: {plural(len(groups(data["turns"])))} left.\n' + (describe(removed) + '\n' if removed else ''))
        elif verb == 'splice' and len(rest) in (2, 4):
            span = (number(rest[2], 'FROM'), number(rest[3], 'TO')) if len(rest) == 4 else (None, None)
            data, count = splice(state, rest[0], rest[1], *span)
            out.write(f'{rest[0]}: {plural(count)} added from {rest[1]}; {plural(len(groups(data["turns"])))} now.\n')
        elif verb == 'golden' and len(rest) <= 1:
            if not rest:
                name = golden(state)
                out.write((f'{name}\n' if name else 'No golden session is set.\n'))
            elif rest[0] == '--clear':
                set_golden(state, None)
                out.write('Golden session cleared. New chats start empty.\n')
            else:
                set_golden(state, rest[0])
                out.write(f'Golden session: {rest[0]}. Every new chat starts as a copy of it.\n')
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except SessionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'File error: {exc.strerror or exc}', file=sys.stderr)
        return 1
    return 0


def new_session_name() -> str:
    return 'turn-' + uuid.uuid4().hex[:16]


if __name__ == '__main__':
    raise SystemExit(command(sys.argv[1:]))
