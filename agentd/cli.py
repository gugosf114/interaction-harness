"""The commands George types: job, jobs, agentd, talk."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import config
from .jobs import FINAL, LIVE, JobError, Queue, first_line, turns

LIST_ROWS = 30


def clock(seconds) -> str:
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def job_time(job, now=None) -> str:
    """How long the job has run, or ran. A queued job shows how long it has waited."""
    now = now or time.time()
    if job['finished'] and job['started']:
        return clock(job['finished'] - job['started'])
    if job['started']:
        return clock(now - job['started'])
    return clock((job['finished'] or now) - job['created'])


def jobs_table(jobs, now=None) -> str:
    rows = [('ID', 'STATE', 'LANE', 'DOOR', 'TIME', 'TASK')]
    for job in jobs:
        rows.append((str(job['id']), job['state'], job['lane'], job['door'], job_time(job, now), first_line(job['task'])[:70]))
    widths = [max(len(row[col]) for row in rows) for col in range(5)]
    return '\n'.join('  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row[:5])) + '  ' + row[5] for row in rows)


def job_report(paths, job, full=False) -> str:
    """`job show`: the full answer and every command the job ran."""
    rows = turns(paths, job)
    head = f"job {job['id']}  {job['lane']}  {job['state']}"
    if job['exit_code'] is not None:
        head += f"  exit {job['exit_code']}"
    out = [head + f"  door {job['door']}  session {job['session']}"]
    if job['started']:
        out.append('started ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job['started'])) + ', ran ' + job_time(job))
    out += ['', 'Task:', job['task'], '']
    answer = job.get('answer') or next((row['direct_answer'] for row in reversed(rows) if row.get('direct_answer')), None)
    out += ['Answer:', answer if answer else '(none yet)' if job['state'] in LIVE else '(none)']
    if job.get('error') and job['state'] != 'done':
        out += ['', 'Error:', job['error']]
    commands = [row for row in rows if row.get('execution_payload')]
    out += ['', f'Commands ({len(commands)}):']
    for number, row in enumerate(commands, 1):
        result = row.get('execution_result') or {}
        if not result:
            status = 'not run'
        elif result.get('approved') is False:
            status = 'declined'
        elif result.get('timed_out'):
            status = 'timed out'
        else:
            status = f"exit {result.get('exit_code')}"
        out.append(f'{number}. [{status}] {row["execution_payload"]}')
        if full:
            if row.get('direct_answer'):
                out.append('   said: ' + row['direct_answer'].replace('\n', '\n   '))
            for stream in ('stdout', 'stderr'):
                text = (result.get(stream) or '').rstrip('\n')
                if text:
                    out.append(f'   --- {stream}')
                    out.extend('   ' + line for line in text.split('\n'))
    api_runs = [use for row in rows for use in row.get('api_tool_uses', [])]
    if api_runs:
        out += ['', 'API tool runs:', json.dumps(api_runs, ensure_ascii=False, indent=2)]
    return '\n'.join(out) + '\n'


def keeper(action='tick', paths=None) -> int:
    """Start (or stop) the watch loop that keeps the service running. AGENTD_NO_KEEPER=1 skips it (tests)."""
    if os.environ.get('AGENTD_NO_KEEPER') == '1':
        return 0
    env = dict(os.environ)
    if paths is not None and paths.state != config.state_dir():
        env['HARNESS_STATE_DIR'] = str(paths.state)
    try:
        return subprocess.run([config.TERMUX_BIN + '/sh', str(config.ROOT / 'agentd' / 'keeper.sh'), action], env=env,
                              stdin=subprocess.DEVNULL, timeout=60).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def service_pid(paths):
    """The service's process id when it is running, else None."""
    try:
        pid = int(paths.pid.read_text().strip())
        with open(f'/proc/{pid}/cmdline', 'rb') as stream:
            return pid if b'agentd\x00_daemon' in stream.read() else None
    except (OSError, ValueError):
        return None


def cmd_job(argv, paths=None) -> int:
    parser = argparse.ArgumentParser(prog='job', description='Hand a task to a lane. It runs in the background.')
    sub = parser.add_subparsers(dest='verb', required=True)
    add = sub.add_parser('add', help='Queue a task. Prints the job id at once.')
    add.add_argument('--lane', help='george, g1, or any lane in the ~/.bashrc shortcut block.')
    add.add_argument('--session', metavar='NAME', help='Continue this harness session. Default: a new session for the job.')
    add.add_argument('task', nargs='+', help='The task in words.')
    listing = sub.add_parser('list', help='Every job with its state. The same as: jobs')
    listing.add_argument('--all', action='store_true', help=f'Every job, not only the newest {LIST_ROWS}.')
    show = sub.add_parser('show', help='The full answer and every command the job ran.')
    show.add_argument('id', type=int)
    show.add_argument('--full', action='store_true', help='Also each step\'s words and each command\'s output.')
    stop = sub.add_parser('stop', help='Stop a job.')
    stop.add_argument('id', type=int)
    wait = sub.add_parser('wait', help='Wait for a job to end, then print its answer.')
    wait.add_argument('id', type=int)
    wait.add_argument('--timeout', type=float, default=None, metavar='SECONDS')
    args = parser.parse_args(argv)
    paths = paths or config.Paths()
    queue = Queue(paths)
    try:
        if args.verb == 'add':
            settings = config.load_settings(paths)
            table = config.lanes(settings)
            lane = args.lane or config.default_lane(settings, table)
            if lane not in table:
                print(f'No lane named {lane}. Lanes: {", ".join(sorted(table))}.', file=sys.stderr)
                return 2
            job = queue.add(lane, ' '.join(args.task), session=args.session)
            print(f"job {job['id']} queued on {lane} (session {job['session']})")
            keeper('start', paths)
            return 0
        if args.verb == 'list':
            jobs = queue.list(limit=1000000 if args.all else LIST_ROWS)
            if not jobs:
                print('No jobs yet.')
                return 0
            print(jobs_table(jobs))
            total = queue.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            if total > len(jobs):
                print(f'{total - len(jobs)} older jobs: jobs --all')
            return 0
        job = queue.get(args.id)
        if job is None:
            print(f'No job {args.id}.', file=sys.stderr)
            return 1
        if args.verb == 'show':
            sys.stdout.write(job_report(paths, job, args.full))
            return 0
        if args.verb == 'stop':
            if job['state'] in FINAL:
                print(f"job {job['id']} already ended: {job['state']}")
                return 0
            queue.request_stop(args.id)
            deadline = time.time() + 30
            while time.time() < deadline:
                job = queue.get(args.id)
                if job['state'] in FINAL:
                    break
                queue.recover()
                time.sleep(0.5)
            print(f"job {job['id']} {job['state']}")
            return 0 if job['state'] in FINAL else 1
        if args.verb == 'wait':
            deadline = time.time() + args.timeout if args.timeout else None
            while job['state'] not in FINAL:
                if deadline and time.time() > deadline:
                    print(f"job {job['id']} is still {job['state']}.", file=sys.stderr)
                    return 124
                time.sleep(1)
                job = queue.get(args.id)
            print(job.get('answer') or job.get('error') or '(no answer)')
            return 0 if job['state'] == 'done' else (job['exit_code'] or 1)
    except (JobError, config.ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        queue.close()
    return 2


def cmd_agentd(argv, paths=None) -> int:
    paths = paths or config.Paths()
    verb = argv[0] if argv else 'status'
    rest = argv[1:]
    if verb == '_daemon':
        from .daemon import Daemon
        return Daemon(paths).run()
    if verb == '_jobrun':
        from .jobrun import run
        return run(int(rest[0]), paths)
    if verb in ('start', 'restart'):
        if verb == 'restart':
            keeper('stop', paths)
            time.sleep(1.5)
        keeper('start', paths)
        for _ in range(40):
            if service_pid(paths):
                break
            time.sleep(0.25)
        return cmd_agentd(['status'], paths)
    if verb == 'stop':
        keeper('stop', paths)
        for _ in range(40):
            if not service_pid(paths):
                break
            time.sleep(0.25)
        print('The service is stopped. Running jobs keep going. Start it again: agentd start')
        return 0
    if verb == 'status':
        from .status import report
        sys.stdout.write(report(paths))
        return 0
    if verb == 'log':
        count = int(rest[0]) if rest and rest[0].isdigit() else 40
        try:
            lines = paths.log.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            lines = []
        print('\n'.join(lines[-count:]))
        return 0
    if verb == 'install':
        from .install import install
        return install(paths)
    if verb == 'tunnel':
        from .tunnel import tunnel
        return tunnel(rest, paths)
    if verb == 'wire-voice':
        from .integrations import voice
        try:
            result = voice(paths, rest[0] if rest else None)
            print('Personal voice line: lane_job installed and read back from Vapi.')
            print(result['server_url'])
            return 0
        except Exception as exc:
            import urllib.error
            detail = exc.read().decode('utf-8', 'replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
            print('Voice door setup failed: ' + detail, file=sys.stderr)
            return 1
    if verb == 'wire-telegram':
        from .integrations import telegram
        if len(rest) not in (1, 2):
            print('usage: agentd wire-telegram SCRIPT [PHONE_URL]', file=sys.stderr)
            return 2
        try:
            result = telegram(rest[0], rest[1] if len(rest) > 1 else f'http://127.0.0.1:{config.port(config.load_settings(paths))}',
                              config.load_doors(paths)['web']['password'])
            print('Telegram lane adapter installed: ' + result['script'])
            return 0
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if verb == 'password':
        from .status import password
        value = password(paths)
        print(value or '(none: the page is open to anyone with the link)')
        return 0
    if verb == 'url':
        from .status import urls
        print('\n'.join(urls(paths)))
        return 0
    print('usage: agentd status | start | stop | restart | log [N] | url | password | tunnel [cloudflared|ngrok] | install | wire-voice [PUBLIC_URL] | wire-telegram SCRIPT [PHONE_URL]',
          file=sys.stderr)
    return 2


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    program = argv.pop(0) if argv else ''
    if program == 'job':
        return cmd_job(argv)
    if program == 'jobs':
        return cmd_job(['list', *argv])
    if program == 'agentd':
        return cmd_agentd(argv)
    if program == 'talk':
        from .talk import main as talk
        return talk(argv)
    print('usage: job | jobs | agentd | talk', file=sys.stderr)
    return 2
