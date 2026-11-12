#!/usr/bin/env python3
"""Preserve an exported key through PRoot using a pipe, never a command argument."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from native_tools import handle

ROOT = Path(__file__).resolve().parent


def foreground_tty():
    try:
        fd = os.open('/dev/tty', os.O_RDONLY | getattr(os, 'O_NOCTTY', 0))
        try: return os.tcgetpgrp(fd) == os.getpgrp()
        finally: os.close(fd)
    except OSError:
        return False


def child_tree(pid):
    """Only this launcher's child subtree; PRoot itself does not forward SIGINT."""
    # Android omits task/PID/children. The daemon's existing /proc/stat parent
    # map works here and keeps the signal inside this child's own subtree.
    from agentd.jobrun import descendants
    return [*reversed(descendants(pid)), pid]


def worker_pids(pid):
    expected = str(ROOT/'bootstrap.py').encode()
    found = []
    for target in child_tree(pid):
        try: argv = Path(f'/proc/{target}/cmdline').read_bytes().split(b'\0')
        except OSError: continue
        if expected in argv: found.append(target)
    return found


def bridge_interrupt(child):
    def stop(signum, frame):
        # A foreground terminal already signals the complete process group.
        # A daemon sends only to this launcher PID, so forward that signal.
        if not foreground_tty():
            targets = worker_pids(child.pid)
            if not targets:
                try: child.send_signal(signal.SIGINT)
                except ProcessLookupError: pass
            for pid in targets:
                try: os.kill(pid,signal.SIGINT)
                except ProcessLookupError: pass
    return stop


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {'harness.py', 'verify_live.py'}:
        print('Unknown harness entry point.', file=sys.stderr)
        return 2
    read_fd, write_fd = os.pipe()
    values = {name: os.environ[name] for name in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','DEFAULT_ENGINE','OPENAI_MODEL','ANTHROPIC_MODEL','HARNESS_STATE_DIR','NO_COLOR','GEMINI_API_KEY','GEMINI_MODEL','OPENROUTER_API_KEY','OPENROUTER_BASE_URL','OPENROUTER_MODEL','GLM_OPENAI_URL','GLM_MODEL','VERTEX_MODEL') if os.environ.get(name)}
    values['HARNESS_CALLER_CWD']=os.getcwd()
    if 'NO_COLOR' in os.environ: values['NO_COLOR']=os.environ['NO_COLOR']
    if os.environ.get('HARNESS_SPEECH_OWNER') == 'agentd': values['HARNESS_SPEECH_OWNER']='agentd'
    parent_socket, child_socket = socket.socketpair()
    command = ['proot-distro', 'login', 'debian', '--', str(ROOT / '.venv/bin/python'),
               '-B', str(ROOT / 'bootstrap.py'), str(read_fd), str(child_socket.fileno()), *sys.argv[1:]]
    try:
        child = subprocess.Popen(command, pass_fds=(read_fd,child_socket.fileno()))
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        print('The Debian Python environment could not start.', file=sys.stderr)
        return 2
    os.close(read_fd)
    child_socket.close()
    idle_interrupt = bridge_interrupt(child)
    try:
        with os.fdopen(write_fd, 'w') as stream:
            json.dump(values, stream)
        with parent_socket, parent_socket.makefile('rwb') as stream:
            while True:
                # The terminal also delivers SIGINT to the Debian chat. Let it
                # stop its turn; keep its native bridge alive for the next turn.
                previous = signal.signal(signal.SIGINT, idle_interrupt)
                try: line=stream.readline(1048576)
                finally: signal.signal(signal.SIGINT, previous)
                if not line: break
                try: result=handle(json.loads(line))
                except KeyboardInterrupt:
                    result={'interrupted':True,'approved':True,'exit_code':130,'stdout':'','stderr':''}
                except (OSError,ValueError,TypeError): result={'error':'The native Termux operation failed.'}
                previous = signal.signal(signal.SIGINT, idle_interrupt)
                try: stream.write(json.dumps(result).encode()+b'\n'); stream.flush()
                finally: signal.signal(signal.SIGINT, previous)
        return child.wait()
    except KeyboardInterrupt:
        child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 130
    except (BrokenPipeError, OSError):
        child.wait()
        print('The key handoff to Python failed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
