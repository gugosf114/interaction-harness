"""One speaker across lane chats, daemon jobs, talk and isolated proof states."""
from contextlib import contextmanager
import fcntl
from pathlib import Path

LOCK=Path('/data/data/com.termux/files/home/.local/state/interaction-harness/speech.lock')


@contextmanager
def acquire():
    LOCK.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with LOCK.open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield
