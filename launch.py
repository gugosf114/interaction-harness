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


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {'harness.py', 'verify_live.py'}:
        print('Unknown harness entry point.', file=sys.stderr)
        return 2
    read_fd, write_fd = os.pipe()
    values = {name: os.environ[name] for name in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','DEFAULT_ENGINE','OPENAI_MODEL','ANTHROPIC_MODEL','HARNESS_STATE_DIR') if os.environ.get(name)}
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
    try:
        with os.fdopen(write_fd, 'w') as stream:
            json.dump(values, stream)
        with parent_socket, parent_socket.makefile('rwb') as stream:
            while True:
                line=stream.readline(1048576)
                if not line: break
                try: result=handle(json.loads(line))
                except (OSError,ValueError,TypeError): result={'error':'The native Termux operation failed.'}
                stream.write(json.dumps(result).encode()+b'\n'); stream.flush()
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
