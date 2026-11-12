"""Run one job: start the harness for it, wait, and write the result into the queue.

Each job has its own runner process, so a job keeps going when the service is killed.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from . import config
from .jobs import Queue, final_answer, history_floor, turns

STOP_GRACE_SECONDS = 8


def descendants(pid) -> list:
    """Every process below pid, deepest last. Commands the harness runs sit in their own sessions, so walk parents."""
    parents = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            parents.setdefault(int(fields[1]), []).append(int(entry.name))
        except (OSError, IndexError, ValueError):
            continue
    found, frontier = [], [pid]
    while frontier:
        children = [child for parent in frontier for child in parents.get(parent, [])]
        found.extend(children)
        frontier = children
    return found


def kill_tree(pid, sig=signal.SIGKILL):
    for target in [*reversed(descendants(pid)), pid]:
        try:
            os.kill(target, sig)
        except (ProcessLookupError, PermissionError):
            pass


def stop_child(child):
    """Ctrl-C first, so the harness records the turn as stopped. Then kill what is left."""
    tree = descendants(child.pid)
    try:
        child.send_signal(signal.SIGINT)
        child.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        pass
    for target in [*reversed(tree), child.pid]:
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def tail(path, lines=3) -> str:
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return ''
    return '\n'.join(text.splitlines()[-lines:])


def run(job_id, paths=None) -> int:
    paths = paths or config.Paths()
    queue = Queue(paths)
    job = queue.get(job_id)
    if job is None or job['state'] not in ('queued', 'starting'):
        return 1
    settings = config.load_settings(paths)
    table = config.lanes(settings)
    folder = paths.jobs / str(job_id)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if job['lane'] not in table:
        queue.finish(job_id, 'failed', error=f"No lane named {job['lane']}.")
        return 1
    if queue.stop_requested(job_id):
        queue.finish(job_id, 'stopped', error='Stopped before it started.')
        return 0
    command = [*config.harness_command(settings), *table[job['lane']], '--session', job['session']]
    env = dict(os.environ)
    env['HARNESS_SPEECH_OWNER'] = 'agentd'
    env['PATH'] = config.TERMUX_BIN + os.pathsep + env.get('PATH', '')
    if paths.state != config.state_dir():
        env['HARNESS_STATE_DIR'] = str(paths.state)  # an explicit state folder; otherwise the harness resolves it as usual
    stopping = {'now': False}
    signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__('now', True))
    queue.running(job_id, os.getpid(), history_floor(paths))
    try:
        with open(folder / 'stdout.txt', 'wb') as out, open(folder / 'stderr.txt', 'wb') as err:
            # The task goes in on stdin: no length limit of a command line, and it never shows in the process list.
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err, env=env,
                                     cwd=str(config.TERMUX_HOME) if config.TERMUX_HOME.is_dir() else None)
            try:
                child.stdin.write(job['task'].encode('utf-8'))
                child.stdin.close()
            except OSError:
                pass
            stopped = False
            while child.poll() is None:
                if stopping['now'] or queue.stop_requested(job_id):
                    stopped = True
                    stop_child(child)
                    break
                time.sleep(0.5)
            code = child.returncode
    except OSError as exc:
        queue.finish(job_id, 'failed', error=f'The harness could not start ({type(exc).__name__}).')
        return 1
    job = queue.get(job_id)
    ceiling = history_floor(paths)
    answer = final_answer(turns(paths, {**job, 'history_ceiling': ceiling}))
    if stopped:
        queue.finish(job_id, 'stopped', code, answer, 'Stopped.', ceiling)
    elif code == 0:
        queue.finish(job_id, 'done', code, answer, None, ceiling)
    else:
        queue.finish(job_id, 'failed', code, answer, tail(folder / 'stderr.txt') or f'The harness exited {code}.', ceiling)
    return 0


if __name__ == '__main__':
    raise SystemExit(run(int(sys.argv[1])))
