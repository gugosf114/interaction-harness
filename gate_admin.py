"""Shared ground for the `rule`, `lesson` and `self-update` commands and the client's second gate.

Where things live:
  the installation's state folder (next to the saved keys; HARNESS_STATE_DIR does not move it):
      gate_rules.json   the operator's gate rules        (gate_rules.py)
      lessons.md        the lessons page                 (lessons.py)
      pages.json        the page list that carries it    (pages.py)
  the lane's state folder (HARNESS_STATE_DIR, else the same folder):
      history.db        every turn, and every correction case (status "correction")
      switches.json     /off judge and /on judge

Only the standard library is used: the commands run in native Termux, the client runs in Debian.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
CORRECTION = 'correction'


def config_dir() -> Path:
    return ROOT / 'state'


def lane_state() -> Path:
    return Path(os.environ.get('HARNESS_STATE_DIR') or (ROOT / 'state')).expanduser()


def today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


@contextmanager
def locked(folder: Path):
    """One writer at a time for the files in this folder."""
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(folder / '.second-gate.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def ensure_columns(db: sqlite3.Connection) -> None:
    """history.gate_json holds the judge's verdicts, the rules that fired, and a correction's outcome."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(history)')}
    if 'gate_json' not in columns:
        try:
            with db:
                db.execute('ALTER TABLE history ADD COLUMN gate_json TEXT')
        except sqlite3.OperationalError:
            # Another launch added it between the check and the change.
            if 'gate_json' not in {row[1] for row in db.execute('PRAGMA table_info(history)')}:
                raise


def open_history(path: Path | None = None) -> sqlite3.Connection | None:
    path = Path(path or lane_state() / 'history.db')
    if not path.is_file():
        return None
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def history_row(row_id: int, path: Path | None = None) -> dict | None:
    """The history row with this id, or None. Nothing is added to the gate without one."""
    db = open_history(path)
    if db is None:
        return None
    try:
        row = db.execute('SELECT id, status, session_id, raw_input, normalized_input, cleaned_input, direct_answer '
                         'FROM history WHERE id=?', (row_id,)).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        db.close()


def read_gate(db: sqlite3.Connection, row_id: int) -> dict:
    row = db.execute('SELECT gate_json FROM history WHERE id=?', (row_id,)).fetchone()
    try:
        value = json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def update_gate(db: sqlite3.Connection, row_id: int, **fields) -> dict:
    """Merge fields into the row's gate_json and return the result."""
    ensure_columns(db)
    value = read_gate(db, row_id)
    value.update(fields)
    with db:
        db.execute('UPDATE history SET gate_json=? WHERE id=?', (json.dumps(value, ensure_ascii=False), row_id))
    return value


def record_outcome(row_id: int, outcome: dict, path: Path | None = None) -> None:
    """Write what a correction turned into on its own history row: the lesson line or the rule's name."""
    db = open_history(path)
    if db is None:
        return
    try:
        outcomes = read_gate(db, row_id).get('outcomes', [])
        update_gate(db, row_id, outcomes=[*outcomes, outcome])
    except sqlite3.Error:
        pass
    finally:
        db.close()
