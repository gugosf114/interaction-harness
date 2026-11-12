"""The job queue: one SQLite file. A job is a lane, a session name and a task in words."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time

from .config import MAX_TASK_CHARS, SESSION_NAME, Paths

FINAL = ('done', 'failed', 'stopped', 'interrupted')
LIVE = ('queued', 'starting', 'running')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL, started REAL, finished REAL,
    lane TEXT NOT NULL, session TEXT NOT NULL, task TEXT NOT NULL,
    door TEXT NOT NULL DEFAULT 'cli', reply_to TEXT,
    state TEXT NOT NULL DEFAULT 'queued',
    pid INTEGER, exit_code INTEGER, history_floor INTEGER, history_ceiling INTEGER,
    answer TEXT, error TEXT,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0, delivery TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, id);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


class JobError(Exception):
    """A short, user-visible queue failure."""


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Queue:
    def __init__(self, paths: Paths):
        self.paths = paths.make()
        self._lock = threading.RLock()
        self.db = sqlite3.connect(paths.db, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        os.chmod(paths.db, 0o600)

    def close(self):
        with self._lock:
            self.db.close()

    @staticmethod
    def _job(row):
        if row is None:
            return None
        job = dict(row)
        job['reply_to'] = json.loads(job['reply_to']) if job.get('reply_to') else None
        return job

    def add(self, lane, task, session=None, door='cli', reply_to=None):
        task = (task or '').strip()
        if not task:
            raise JobError('A job needs a task.')
        if len(task) > MAX_TASK_CHARS:
            raise JobError(f'The task exceeds {MAX_TASK_CHARS} characters.')
        if session is not None and not SESSION_NAME.fullmatch(session):
            raise JobError('Session names use 1-64 letters, digits, underscores, or hyphens.')
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                cursor = self.db.execute(
                    'INSERT INTO jobs(created,lane,session,task,door,reply_to) VALUES(?,?,?,?,?,?)',
                    (time.time(), lane, session or '', task, door, json.dumps(reply_to) if reply_to else None))
                job_id = cursor.lastrowid
                if session is None:
                    # A fresh session per job. The random tail keeps it apart from a session of an older queue file.
                    self.db.execute('UPDATE jobs SET session=? WHERE id=?', (f'job-{job_id}-{secrets.token_hex(2)}', job_id))
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        return self.get(job_id)

    def get(self, job_id):
        with self._lock:
            return self._job(self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def list(self, limit=200, states=None, door=None):
        query, values = 'SELECT * FROM jobs', []
        clauses = []
        if states:
            clauses.append('state IN (%s)' % ','.join('?' * len(states)))
            values.extend(states)
        if door:
            clauses.append('door=?')
            values.append(door)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY id DESC LIMIT ?'
        values.append(limit)
        with self._lock:
            return [self._job(row) for row in self.db.execute(query, values)]

    def claim(self):
        """The oldest queued job, moved to 'starting'. None when the queue is empty."""
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
                if row:
                    self.db.execute("UPDATE jobs SET state='starting' WHERE id=?", (row['id'],))
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        return self.get(row['id']) if row else None

    def running(self, job_id, pid, floor):
        with self._lock:
            self.db.execute("UPDATE jobs SET state='running', pid=?, started=?, history_floor=? WHERE id=?",
                            (pid, time.time(), floor, job_id))

    def set_pid(self, job_id, pid):
        with self._lock:
            self.db.execute('UPDATE jobs SET pid=? WHERE id=?', (pid, job_id))

    def finish(self, job_id, state, exit_code=None, answer=None, error=None, ceiling=None):
        if state not in FINAL:
            raise JobError('Unknown final state.')
        with self._lock:
            self.db.execute('UPDATE jobs SET state=?, exit_code=?, answer=?, error=?, history_ceiling=?, finished=? '
                            'WHERE id=? AND state NOT IN (%s)' % ','.join('?' * len(FINAL)),
                            (state, exit_code, answer, error, ceiling, time.time(), job_id, *FINAL))

    def request_stop(self, job_id):
        """Ask a job to stop. A job that has not started is stopped at once. Returns the job, or None."""
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return None
            if job['state'] in FINAL:
                return job
            self.db.execute('UPDATE jobs SET stop_requested=1 WHERE id=?', (job_id,))
            if job['state'] == 'queued':
                self.finish(job_id, 'stopped', error='Stopped before it started.')
        return self.get(job_id)

    def stop_requested(self, job_id) -> bool:
        with self._lock:
            row = self.db.execute('SELECT stop_requested FROM jobs WHERE id=?', (job_id,)).fetchone()
        return bool(row and row[0])

    def to_notify(self):
        with self._lock:
            return [self._job(row) for row in self.db.execute(
                'SELECT * FROM jobs WHERE notified=0 AND state IN (%s) ORDER BY id' % ','.join('?' * len(FINAL)), FINAL)]

    def mark_notified(self, job_id):
        with self._lock:
            self.db.execute('UPDATE jobs SET notified=1 WHERE id=?', (job_id,))

    def to_deliver(self, door=None):
        query = 'SELECT * FROM jobs WHERE delivered=0 AND state IN (%s)' % ','.join('?' * len(FINAL))
        values = list(FINAL)
        if door:
            query += ' AND door=?'
            values.append(door)
        with self._lock:
            return [self._job(row) for row in self.db.execute(query + ' ORDER BY id', values)]

    def mark_delivered(self, job_id, note=''):
        with self._lock:
            self.db.execute('UPDATE jobs SET delivered=1, delivery=? WHERE id=?', (note, job_id))

    def recover(self, alive=pid_alive):
        """After a restart: a job that was running under a process that is gone is marked interrupted. Not replayed."""
        lost = []
        with self._lock:
            for row in self.db.execute("SELECT id, pid, state FROM jobs WHERE state IN ('starting','running')").fetchall():
                if not alive(row['pid']):
                    self.finish(row['id'], 'interrupted', error='The runner process was gone when the service came back.')
                    lost.append(row['id'])
        return lost

    def kv_get(self, key, default=None):
        with self._lock:
            row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def kv_set(self, key, value):
        with self._lock:
            self.db.execute('INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                            (key, json.dumps(value)))


def history_floor(paths: Paths) -> int:
    """The newest row id in history.db right now. 0 when there is no history yet."""
    return _history_scalar(paths, 'SELECT COALESCE(MAX(id),0) FROM history')


def _history_scalar(paths, query, values=()):
    if not paths.history.exists():
        return 0
    try:
        db = sqlite3.connect(f'file:{paths.history}?mode=ro', uri=True, timeout=15)
        try:
            return db.execute(query, values).fetchone()[0] or 0
        finally:
            db.close()
    except sqlite3.Error:
        return 0


def turns(paths: Paths, job) -> list:
    """Every model turn this job wrote to history.db, oldest first, with its command and the command's result."""
    if not paths.history.exists() or job.get('history_floor') is None:
        return []
    query = ('SELECT id, timestamp, engine, model, raw_input, direct_answer, execution_payload, execution_result, status, error, '
             'tokens_used FROM history WHERE session_id=? AND id>?')
    values = [job['session'], job['history_floor']]
    if job.get('history_ceiling'):
        query += ' AND id<=?'
        values.append(job['history_ceiling'])
    try:
        db = sqlite3.connect(f'file:{paths.history}?mode=ro', uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in db.execute(query + ' ORDER BY id', values)]
        finally:
            db.close()
    except sqlite3.Error:
        return []
    # Another job may share the session. This job's turns start at the row that holds its task.
    for index, row in enumerate(rows):
        if (row.get('raw_input') or '').strip() == job['task'].strip():
            rows = rows[index:]
            break
    for row in rows:
        try:
            row['execution_result'] = json.loads(row['execution_result']) if row['execution_result'] else None
        except ValueError:
            row['execution_result'] = None
    return rows


def final_answer(rows) -> str | None:
    """The last answer the model gave in this job."""
    for row in reversed(rows):
        if row.get('direct_answer'):
            return row['direct_answer']
    return None


def first_line(text) -> str:
    for line in (text or '').splitlines():
        line = line.strip()
        if line:
            return line
    return ''
