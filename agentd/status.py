"""`agentd status`: is the service up, where is the page, what are the jobs and the doors doing."""
from __future__ import annotations

from . import config
from .jobs import Queue


def urls(paths) -> list:
    from .web import tailscale_ip
    try:
        number = config.port(config.load_settings(paths))
    except config.ConfigError:
        number = config.DEFAULT_PORT
    found = [f'http://127.0.0.1:{number}/']
    address = tailscale_ip()
    if address:
        found.append(f'http://{address}:{number}/')
    return found


def password(paths) -> str:
    try:
        return str(config.load_doors(paths).get('web', {}).get('password') or '')
    except config.ConfigError:
        return ''


def keeper_pid(paths):
    try:
        pid = int((paths.home / 'keeper.lock' / 'pid').read_text().strip())
        with open(f'/proc/{pid}/cmdline', 'rb') as stream:
            return pid if b'agentd/keeper.sh\x00watch' in stream.read() else None
    except (OSError, ValueError):
        return None


def report(paths) -> str:
    from .cli import service_pid
    pid, keeper = service_pid(paths), keeper_pid(paths)
    lines = ['service: ' + (f'running (pid {pid})' if pid else 'not running'),
             'keeper:  ' + (f'running (pid {keeper})' if keeper else 'not running')
             + ('; stopped by hand (agentd start)' if (paths.home / 'STOPPED').exists() else ''),
             'page:    ' + '  '.join(urls(paths)),
             'password: ' + (password(paths) or '(none: open to anyone with the link)')]
    queue = Queue(paths)
    try:
        counts = dict(queue.db.execute('SELECT state, COUNT(*) FROM jobs GROUP BY state').fetchall())
        doors = queue.kv_get('doors', {})
    finally:
        queue.close()
    lines.append('jobs:    ' + (', '.join(f'{count} {state}' for state, count in sorted(counts.items())) or 'none yet'))
    if doors:
        lines.append('doors:')
        width = max(len(name) for name in doors)
        lines.extend(f'  {name.ljust(width)}  {note}' for name, note in doors.items())
    return '\n'.join(lines) + '\n'
