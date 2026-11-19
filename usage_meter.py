#!/usr/bin/env python3
"""usage: tokens and calls today, this week and this month for each lane's API account.

Rebuilt for the lanes from the usage-alarm mod's /usage-alarm meter. For the lanes, usage is tokens on two
API accounts: Anthropic (g2) and OpenAI (g1). Three sources, each shown on its own:
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import subprocess

ROOT = Path(__file__).resolve().parent
LANES = (('anthropic', 'g2', 'Anthropic'), ('openai', 'g1', 'OpenAI'))
WINDOWS = ('today', 'week', 'month')


def local_zone():
    name = os.environ.get('TZ', '').lstrip(':')
    if not name:
        try:
            name = subprocess.check_output(['/system/bin/getprop', 'persist.sys.timezone'], text=True,
                                           stderr=subprocess.DEVNULL, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    if name and '..' not in name.split('/'):
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            for root in ('/usr/share/zoneinfo', '/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs/usr/share/zoneinfo'):
                try:
                    with (Path(root) / name).open('rb') as stream:
                        return ZoneInfo.from_file(stream, key=name)
                except (OSError, ValueError):
                    pass
    try:
        with open('/etc/localtime', 'rb') as stream:
            return ZoneInfo.from_file(stream)
    except (OSError, ValueError):
        return timezone.utc


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
    if engine:
        return None  # A Claude model billed through Vertex is not the Anthropic API account.
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


def add(bucket, starts, stamp, calls, inp, out, read, end=None):
    if end is not None and stamp >= end:
        return
    for w in WINDOWS:
        if stamp >= starts[w]:
            b = bucket[w]
            b['calls'] += calls; b['input'] += inp; b['output'] += out; b['cache_read'] += read


def from_log(path: Path, starts: dict, end=None) -> dict:
    totals = {engine: zero() for engine, _, _ in LANES}
    lines = []
    for source in (path, path.with_name('judge.jsonl')):
        try:
            lines.extend(source.read_text(encoding='utf-8', errors='replace').splitlines())
        except OSError:
            continue
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        engine, stamp = engine_of(event), when(event.get('time_utc'))
        if engine not in totals or stamp is None or str(event.get('kind', '')).startswith(('hook:', 'recall')):
            continue
        if event.get('kind') in ('provider_cancel', 'cancel'):
            continue
        calls = max(1, len(set(event.get('provider_response_ids') or [])))
        add(totals[engine], starts, stamp, calls, *event_tokens(event.get('usage') or {}), end=end)
    return totals


def from_history(path: Path, starts: dict, end=None) -> dict:
    totals = {engine: zero() for engine, _, _ in LANES}
    if not path.exists():
        return totals
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(history)')}
        rows = db.execute('SELECT engine,timestamp,input_tokens,output_tokens,cache_read_tokens,tokens_used FROM history '
                          'WHERE timestamp >= ?' + (" AND status NOT IN ('correction','advisor','advisor_error')" if 'status' in columns else ''),
                          ((min(starts.values()) - timedelta(days=1)).astimezone(timezone.utc).isoformat(),)).fetchall()
    finally:
        db.close()
    for engine, stamp, inp, out, read, used in rows:
        moment = when(stamp)
        if engine not in totals or moment is None:
            continue
        add(totals[engine], starts, moment, 1, inp or 0, out or 0, read or 0, end=end)
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


def provider_anthropic(key_dir: Path, starts: dict, end=None) -> tuple[dict | None, str]:
    key, source = _key(key_dir, ('anthropic-admin-key', 'anthropic-api-key'), 'ANTHROPIC_ADMIN_KEY')
    if not key:
        return None, 'no key'
    end = end or datetime.now(timezone.utc)
    totals = zero()
    for window in WINDOWS:
        page = None
        while True:
            query = {'starting_at': starts[window].astimezone(timezone.utc).isoformat(),
                     'ending_at': end.astimezone(timezone.utc).isoformat(), **({'page': page} if page else {})}
            status, data = _get('https://api.anthropic.com/v1/organizations/analytics/usage?' + urllib.parse.urlencode(query),
                               {'x-api-key': key, 'anthropic-version': '2023-06-01',
                                'anthropic-beta': 'analytics-usage-cost-2026-08-24'})
            if status != 200:
                return None, f'HTTP {status} with {source}: {data}'
            for row in data.get('data', []):
                r = row.get('usage') or {}
                read = r.get('cache_read_input_tokens') or 0
                totals[window]['calls'] += r.get('requests') or 0
                totals[window]['input'] += (r.get('uncached_input_tokens') or 0) + sum((r.get('cache_creation') or {}).values()) + read
                totals[window]['output'] += r.get('output_tokens') or 0
                totals[window]['cache_read'] += read
            if not data.get('has_more'):
                break
            next_page = data.get('next_page')
            if not next_page or next_page == page:
                return None, 'Provider returned an invalid page cursor.'
            page = next_page
    return totals, 'ok'


def provider_openai(key_dir: Path, starts: dict, end=None) -> tuple[dict | None, str]:
    key, source = _key(key_dir, ('openai-admin-key', 'api-key'), 'OPENAI_ADMIN_KEY')
    if not key:
        return None, 'no key'
    end = end or datetime.now(timezone.utc)
    totals = zero()
    for window in WINDOWS:
        page = None
        while True:
            query = {'start_time': str(int(starts[window].timestamp())), 'end_time': str(int(end.timestamp())),
                     'bucket_width': '1d', 'limit': '31', **({'page': page} if page else {})}
            status, data = _get('https://api.openai.com/v1/organization/usage/completions?' + urllib.parse.urlencode(query),
                               {'Authorization': 'Bearer ' + key})
            if status != 200:
                return None, f'HTTP {status} with {source}: {data}'
            for bucket in data.get('data', []):
                for r in bucket.get('results', []):
                    totals[window]['calls'] += r.get('num_model_requests') or 0
                    totals[window]['input'] += r.get('input_tokens') or 0
                    totals[window]['output'] += r.get('output_tokens') or 0
                    totals[window]['cache_read'] += r.get('input_cached_tokens') or 0
            if not data.get('has_more'):
                break
            next_page = data.get('next_page')
            if not next_page or next_page == page:
                return None, 'Provider returned an invalid page cursor.'
            page = next_page
    return totals, 'ok'


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
    now = now or datetime.now(local_zone())
    starts = window_starts(now)
    lines = [f'Usage at {now.strftime("%Y-%m-%d %H:%M %Z")} · week from {starts["week"]:%a %b %d} · month from {starts["month"]:%b %d}', '']
    lines += table('Usage logs (usage.jsonl + judge.jsonl), one call = one API request:', from_log(state / 'usage.jsonl', starts, now), 'calls')
    lines.append('')
    lines += table('Saved turns (state/history.db), one turn = one model turn:', from_history(state / 'history.db', starts, now), 'turns')
    if providers:
        key_dir = key_dir or state
        for name, read in (('Anthropic', provider_anthropic), ('OpenAI', provider_openai)):
            lines.append('')
            totals, note = read(key_dir, starts, now)
            if totals is None:
                lines.append(f'{name} usage report: {note}')
                continue
            lines.append(f'{name} usage report (whole account, all keys):')
            for w in WINDOWS:
                b = totals[w]
                calls = f'{n(b["calls"]):>6} calls '
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
