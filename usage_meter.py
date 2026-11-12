#!/usr/bin/env python3
"""usage: tokens and calls today, this week and this month for each lane's API account.

Rebuilt for the lanes from the usage-alarm mod's /usage-alarm meter. For the lanes, usage is tokens on two
API accounts: Anthropic (george) and OpenAI (g1). Three sources, each shown on its own:
  1. state/history.db   one row per model turn the lanes saved (tokens summed over its retries)
  2. state/usage.jsonl  one record per API request: lane calls, retries, advisor and mod calls
  3. each provider's own usage report, when a key can read it. Both reports need an admin key:
     state/anthropic-admin-key or ANTHROPIC_ADMIN_KEY, state/openai-admin-key or OPENAI_ADMIN_KEY.
     Without one the lane key is tried, and the provider's own refusal is printed.
Windows are local time on the phone: today from midnight, the week from Monday, the month from the 1st.
Standard library only, so it runs from Termux Python and from Debian Python alike.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
LANES = (('anthropic', 'george', 'Anthropic'), ('openai', 'g1', 'OpenAI'))
WINDOWS = ('today', 'week', 'month')


def window_starts(now: datetime) -> dict:
    """Local-time starts of today, this week (Monday) and this month, as aware datetimes."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {'today': day, 'week': day - timedelta(days=day.weekday()), 'month': day.replace(day=1)}


def zero():
    return {w: {'calls': 0, 'input': 0, 'output': 0, 'cache_read': 0} for w in WINDOWS}


def when(text) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def engine_of(event: dict) -> str | None:
    engine = event.get('engine')
    if engine in ('anthropic', 'openai'):
        return engine
    model = str(event.get('model_requested') or event.get('model') or '')
    return 'anthropic' if model.startswith('claude') else 'openai' if model.startswith(('gpt', 'o')) else None


def event_tokens(usage: dict) -> tuple[int, int, int]:
    """(input, output, cache_read) from one provider usage block, the same sums history.db uses."""
    if not usage:
        return 0, 0, 0
    creation = usage.get('cache_creation_input_tokens') or 0
    read = usage.get('cache_read_input_tokens') or 0
    cached = read + ((usage.get('input_tokens_details') or {}).get('cached_tokens') or 0)
    return (usage.get('input_tokens') or 0) + creation + read, usage.get('output_tokens') or 0, cached


def add(bucket, starts, stamp, calls, inp, out, read):
    for w in WINDOWS:
        if stamp >= starts[w]:
            b = bucket[w]
            b['calls'] += calls; b['input'] += inp; b['output'] += out; b['cache_read'] += read


def from_log(path: Path, starts: dict) -> dict:
    totals = {engine: zero() for engine, _, _ in LANES}
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return totals
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        engine, stamp = engine_of(event), when(event.get('time_utc'))
        if engine not in totals or stamp is None:
            continue
        add(totals[engine], starts, stamp.astimezone(starts['today'].tzinfo), 1, *event_tokens(event.get('usage') or {}))
    return totals


def from_history(path: Path, starts: dict) -> dict:
    totals = {engine: zero() for engine, _, _ in LANES}
    if not path.exists():
        return totals
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    try:
        rows = db.execute('SELECT engine,timestamp,input_tokens,output_tokens,cache_read_tokens,tokens_used FROM history '
                          'WHERE timestamp >= ?', ((starts['month'] - timedelta(days=1)).astimezone(timezone.utc).isoformat(),)).fetchall()
    finally:
        db.close()
    for engine, stamp, inp, out, read, used in rows:
        moment = when(stamp)
        if engine not in totals or moment is None:
            continue
        add(totals[engine], starts, moment.astimezone(starts['today'].tzinfo), 1, inp or 0, out or 0, read or 0)
    return totals


def _get(url: str, headers: dict):
    request = urllib.request.Request(url, headers={**headers, 'User-Agent': 'interaction-harness-usage/1'})
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        try:
            data = json.loads(body)
            error = data.get('error')
            message = error.get('message') if isinstance(error, dict) else error
        except ValueError:
            message = body
        return exc.code, str(message or body)[:300]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, type(exc).__name__


def _key(state: Path, names: tuple[str, ...], env: str) -> tuple[str | None, str]:
    if os.environ.get(env):
        return os.environ[env].strip(), env
    for name in names:
        try:
            return (state / name).read_text().strip(), name
        except OSError:
            continue
    return None, ''


def provider_anthropic(key_dir: Path, starts: dict) -> tuple[dict | None, str]:
    key, source = _key(key_dir, ('anthropic-admin-key', 'anthropic-api-key'), 'ANTHROPIC_ADMIN_KEY')
    if not key:
        return None, 'no key'
    since = starts['month'].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    totals, page = zero(), None
    while True:
        query = {'starting_at': since, 'bucket_width': '1d', 'limit': '31', **({'page': page} if page else {})}
        status, data = _get('https://api.anthropic.com/v1/organizations/usage_report/messages?' + urllib.parse.urlencode(query),
                            {'x-api-key': key, 'anthropic-version': '2023-06-01'})
        if status != 200:
            return None, f'HTTP {status} with {source}: {data}'
        for bucket in data.get('data', []):
            stamp = when(bucket.get('starting_at'))
            for r in bucket.get('results', []):
                creation = sum((r.get('cache_creation') or {}).values())
                read = r.get('cache_read_input_tokens') or 0
                add(totals, starts, stamp.astimezone(starts['today'].tzinfo), 0,
                    (r.get('uncached_input_tokens') or 0) + creation + read, r.get('output_tokens') or 0, read)
        if not data.get('has_more'):
            return totals, 'ok'
        page = data.get('next_page')


def provider_openai(key_dir: Path, starts: dict) -> tuple[dict | None, str]:
    key, source = _key(key_dir, ('openai-admin-key', 'api-key'), 'OPENAI_ADMIN_KEY')
    if not key:
        return None, 'no key'
    since = int(starts['month'].timestamp())
    totals, page = zero(), None
    while True:
        query = {'start_time': str(since), 'bucket_width': '1d', 'limit': '31', **({'page': page} if page else {})}
        status, data = _get('https://api.openai.com/v1/organization/usage/completions?' + urllib.parse.urlencode(query),
                            {'Authorization': 'Bearer ' + key})
        if status != 200:
            return None, f'HTTP {status} with {source}: {data}'
        for bucket in data.get('data', []):
            stamp = datetime.fromtimestamp(bucket.get('start_time', 0), timezone.utc)
            for r in bucket.get('results', []):
                add(totals, starts, stamp.astimezone(starts['today'].tzinfo), r.get('num_model_requests') or 0,
                    r.get('input_tokens') or 0, r.get('output_tokens') or 0, r.get('input_cached_tokens') or 0)
        if not data.get('has_more'):
            return totals, 'ok'
        page = data.get('next_page')


def n(value: int) -> str:
    return f'{value:,}'


def table(title: str, totals: dict, calls_word: str) -> list[str]:
    lines = [title]
    for engine, lane, account in LANES:
        for w in WINDOWS:
            b = totals[engine][w]
            lines.append(f'  {lane:<6} {account:<9} {w:<5}  {n(b["calls"]):>6} {calls_word:<5} in {n(b["input"]):>12}  '
                         f'out {n(b["output"]):>10}  cache read {n(b["cache_read"]):>12}')
    return lines


def report(state: Path, key_dir: Path | None = None, now: datetime | None = None, providers: bool = True) -> str:
    now = now or datetime.now().astimezone()
    starts = window_starts(now)
    lines = [f'Usage at {now.strftime("%Y-%m-%d %H:%M %Z")} · week from {starts["week"]:%a %b %d} · month from {starts["month"]:%b %d}', '']
    lines += table('Usage log (state/usage.jsonl), one call = one API request:', from_log(state / 'usage.jsonl', starts), 'calls')
    lines.append('')
    lines += table('Saved turns (state/history.db), one turn = one model turn:', from_history(state / 'history.db', starts), 'turns')
    if providers:
        key_dir = key_dir or state
        for name, read in (('Anthropic', provider_anthropic), ('OpenAI', provider_openai)):
            lines.append('')
            totals, note = read(key_dir, starts)
            if totals is None:
                lines.append(f'{name} usage report: {note}')
                continue
            lines.append(f'{name} usage report (whole account, all keys):')
            for w in WINDOWS:
                b = totals[w]
                calls = f'{n(b["calls"]):>6} calls ' if name == 'OpenAI' else ''
                lines.append(f'  {w:<5}  {calls}in {n(b["input"]):>12}  out {n(b["output"]):>10}  cache read {n(b["cache_read"]):>12}')
    return '\n'.join(lines) + '\n'


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    providers = '--local' not in argv
    state = Path(os.environ.get('HARNESS_STATE_DIR') or ROOT / 'state').expanduser()
    sys.stdout.write(report(state, ROOT / 'state', providers=providers))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
