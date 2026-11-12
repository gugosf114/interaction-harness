"""Private SQLite history and locked, bounded session files."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid
from lookup_gate import turn_metadata

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
METRIC_COLUMNS = ('input_tokens', 'output_tokens', 'cache_creation_tokens',
                  'cache_hit_requests', 'latency_ms')
FEEDBACK_STREAM_LIMIT = 400000
FEEDBACK_HEAD_CHARS = 100000  # The rest of the limit keeps the end, where errors and tracebacks usually are.


def confirmed_execution(result):
    """The command was approved and ran to an exit code. A failed run still counts; the loop can repair it."""
    return isinstance(result,dict) and result.get('approved') is True and type(result.get('exit_code')) is int


def successful_execution(result):
    """Approved, finished in time and exited 0: the only result that supports a completion claim."""
    return confirmed_execution(result) and result['exit_code']==0 and result.get('timed_out') is not True


def clip_stream(value):
    """Fit one output stream into the feedback limit: keep the start and the end, mark the gap."""
    if len(value)<=FEEDBACK_STREAM_LIMIT:return value
    omitted=len(value)-FEEDBACK_STREAM_LIMIT
    while True:
        # The marker's own length depends on the count, so settle both together.
        marker=f'\n[... {omitted} characters omitted here; the start and the end are kept ...]\n'
        tail=FEEDBACK_STREAM_LIMIT-FEEDBACK_HEAD_CHARS-len(marker)
        actual=len(value)-FEEDBACK_HEAD_CHARS-tail
        if actual==omitted:break
        omitted=actual
    return value[:FEEDBACK_HEAD_CHARS]+marker+value[-tail:]


def execution_observation(exchange):
    """A separate data message; never extend the assistant's four-field object."""
    result=dict(exchange['execution_result'])
    clipped=[]
    for key in ('stdout','stderr'):
        value=result.get(key,'')
        if isinstance(value,str) and len(value)>FEEDBACK_STREAM_LIMIT:
            result[key]=clip_stream(value);clipped.append(key)
    result['feedback_truncated_fields']=clipped
    return json.dumps({'type':'execution_observation','source':'native_termux',
                       'command':exchange['reply']['execution_payload'],'result':result},ensure_ascii=False)


def request_metrics(events):
    """Normalize provider counters; OpenAI's input already includes cache reads."""
    metrics=dict(tokens_used=0,cache_read_tokens=0,
                 **{name:0 for name in METRIC_COLUMNS})
    has_usage=False
    has_latency=False
    for event in events:
        if event.get('elapsed_ms') is not None:
            metrics['latency_ms']+=event['elapsed_ms'];has_latency=True
        usage=event.get('usage') or {}
        if not usage:continue
        has_usage=True
        creation=usage.get('cache_creation_input_tokens',0)
        anthropic_read=usage.get('cache_read_input_tokens',0)
        cached=anthropic_read+(usage.get('input_tokens_details') or {}).get('cached_tokens',0)
        inputs=usage.get('input_tokens',0)+creation+anthropic_read
        outputs=usage.get('output_tokens',0)
        metrics['input_tokens']+=inputs
        metrics['output_tokens']+=outputs
        metrics['cache_creation_tokens']+=creation
        metrics['cache_read_tokens']+=cached
        metrics['cache_hit_requests']+=int(cached>0)
        metrics['tokens_used']+=usage.get('total_tokens',0) or inputs+outputs
    if not has_usage:
        for name in ('input_tokens','output_tokens','cache_creation_tokens','cache_hit_requests'):
            metrics[name]=None
    if not has_latency:metrics['latency_ms']=None
    return metrics


def now():
    return datetime.now(timezone.utc).isoformat()


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def atomic_json(path, data):
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        private_dir(self.root)
        self.sessions = self.root / 'sessions'
        private_dir(self.sessions)
        db = self.root / 'history.db'
        fd = os.open(db, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd); db.chmod(0o600)
        self.db = sqlite3.connect(db, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, engine TEXT NOT NULL,
            session_id TEXT, raw_input TEXT NOT NULL, cleaned_input TEXT,
            intent TEXT, direct_answer TEXT, execution_payload TEXT,
            tokens_used INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            normalized_input TEXT, model TEXT, status TEXT NOT NULL DEFAULT 'pending',
            error TEXT, execution_result TEXT
        );
        CREATE INDEX IF NOT EXISTS history_session ON history(session_id, id);
        CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
            raw_input, cleaned_input, direct_answer, execution_payload,
            content='history', content_rowid='id', tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS history_insert AFTER INSERT ON history BEGIN
          INSERT INTO history_fts(rowid,raw_input,cleaned_input,direct_answer,execution_payload)
          VALUES(new.id,new.raw_input,new.cleaned_input,new.direct_answer,new.execution_payload);
        END;
        CREATE TRIGGER IF NOT EXISTS history_update AFTER UPDATE ON history BEGIN
          INSERT INTO history_fts(history_fts,rowid,raw_input,cleaned_input,direct_answer,execution_payload)
          VALUES('delete',old.id,old.raw_input,old.cleaned_input,old.direct_answer,old.execution_payload);
          INSERT INTO history_fts(rowid,raw_input,cleaned_input,direct_answer,execution_payload)
          VALUES(new.id,new.raw_input,new.cleaned_input,new.direct_answer,new.execution_payload);
        END;
        ''')
        # Old rows retain NULL for metrics that were never recorded.
        # BEGIN IMMEDIATE serializes first-time migrations in concurrent launches.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns={row[1] for row in self.db.execute('PRAGMA table_info(history)')}
            for name in METRIC_COLUMNS:
                if name not in columns:
                    self.db.execute(f'ALTER TABLE history ADD COLUMN {name} INTEGER')
            for name in ('sources_json','lookup_counts_json','attachments_json'):
                if name not in columns:self.db.execute(f'ALTER TABLE history ADD COLUMN {name} TEXT')

    def close(self):
        self.db.close()

    def begin(self, raw, normalized, engine, model, session_id=None, attachments=None):
        with self.db:
            cur = self.db.execute('INSERT INTO history(timestamp,engine,model,session_id,raw_input,normalized_input) VALUES(?,?,?,?,?,?)',
                                  (now(),engine,model,session_id,raw,normalized))
            idx=cur.lastrowid
            self.db.execute('UPDATE history SET attachments_json=? WHERE id=?',(json.dumps(attachments or []),idx))
            return idx

    def finish(self, row_id, reply=None, events=(), error=None, execution=None, status=None):
        fields = dict(status=status or ('error' if error else 'accepted'), error=error,
                      **request_metrics(events))
        metadata=turn_metadata(events)
        fields.update(sources_json=json.dumps(metadata['sources']),lookup_counts_json=json.dumps(metadata['lookup_counts']))
        if reply:
            fields.update(reply.model_dump())
        if execution is not None: fields['execution_result'] = json.dumps(execution)
        with self.db:
            self.db.execute('UPDATE history SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', [*fields.values(),row_id])

    def recall(self, query, limit=5):
        words = re.findall(r'\w+', query, re.UNICODE)
        if not words: return []
        expression = ' AND '.join('"'+word+'"' for word in words)
        return [dict(r) for r in self.db.execute('''
            SELECT h.* FROM history_fts f JOIN history h ON h.id=f.rowid
            WHERE history_fts MATCH ? AND h.direct_answer IS NOT NULL
            ORDER BY bm25(history_fts), h.id DESC LIMIT ?''', (expression,limit))]

    def follows_successful_execution(self, session_id, row_id):
        """True when the turn directly before this one in its session ran a command that exited 0."""
        row=self.db.execute('''SELECT execution_result FROM history
                WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 1''',(session_id,row_id)).fetchone()
        if row is None or row[0] is None:return False
        try:return successful_execution(json.loads(row[0]))
        except (ValueError,TypeError):return False

    def select_session(self, name=None, continuing=False):
        if continuing:
            try: name = json.loads((self.root/'active-session.json').read_text())['id']
            except (OSError, ValueError, KeyError): raise ValueError('No previous session. Start with --session NAME.')
        name = name or 'turn-' + uuid.uuid4().hex[:16]
        if not NAME.fullmatch(name): raise ValueError('Session names use 1–64 letters, digits, underscores, or hyphens.')
        return name

    @contextmanager
    def session(self, name, turns=6):
        if not NAME.fullmatch(name): raise ValueError('Invalid session name.')
        lock_path = self.sessions/(name+'.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd,'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.sessions/(name+'.json')
            try:
                data = json.loads(path.read_text())
                if data.get('id') != name or not isinstance(data.get('turns'),list): raise ValueError()
            except FileNotFoundError:
                data = {'version':1,'id':name,'created_at':now(),'turns':[]}
            except (ValueError, TypeError):
                raise ValueError('The saved session is invalid; it was not overwritten.')
            data['turns'] = data['turns'][-turns:]
            yield data

    def save_session(self, data, exchange, turns=6):
        data['turns'] = (data['turns']+[exchange])[-turns:]
        data['updated_at'] = now()
        atomic_json(self.sessions/(data['id']+'.json'),data)
        atomic_json(self.root/'active-session.json',{'id':data['id']})


def history_messages(exchanges, max_chars=24000):
    selected, used = [], 0
    for exchange in reversed(exchanges):
        record = dict(exchange['reply'])
        pair = [
            {'role':'user','content':exchange['normalized_input']},
            {'role':'assistant','content':json.dumps(record,ensure_ascii=False)},
        ]
        if exchange.get('attachments'):pair[0]['attachments']=exchange['attachments']
        if exchange.get('sources'):
            pair.append({'role':'user','content':json.dumps({'type':'source_record','sources':exchange['sources']})})
        if exchange.get('execution_result') is not None:
            pair.append({'role':'user','content':execution_observation(exchange)})
        size = sum(len(p['content'])+len(json.dumps(p.get('attachments',[]))) for p in pair)
        if used + size > max_chars: break
        selected.insert(0,pair); used += size
    return [message for pair in selected for message in pair]
