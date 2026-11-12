"""The folder door: a text file dropped in state/inbox/ becomes a job. The answer lands in state/outbox/."""
from __future__ import annotations

import os
import re
import time

from ..config import SESSION_NAME
from . import Door, answer_text

HEADER = re.compile(r'^(lane|session)\s*:\s*(\S+)\s*$', re.IGNORECASE)
SETTLE_SECONDS = 1.0  # a file must be this old, so a half-written file is not taken


def parse_drop(text: str) -> dict:
    """Optional first lines `lane: NAME` and `session: NAME`, then the task. Returns lane, session, task."""
    lines = text.replace('\r\n', '\n').split('\n')
    found = {'lane': None, 'session': None}
    index = 0
    while index < len(lines):
        match = HEADER.match(lines[index])
        if not match:
            break
        found[match.group(1).lower()] = match.group(2)
        index += 1
    task = '\n'.join(lines[index:]).strip()
    if found['session'] and not SESSION_NAME.fullmatch(found['session']):
        raise ValueError('Session names use 1-64 letters, digits, underscores, or hyphens.')
    return {'lane': found['lane'], 'session': found['session'], 'task': task}


class InboxDoor(Door):
    name = 'inbox'
    interval = 2

    def poll(self):
        paths = self.daemon.paths
        taken = paths.inbox / 'taken'
        self.note = f'drop a text file in {paths.inbox}'
        for path in sorted(paths.inbox.iterdir()):
            if not path.is_file() or path.name.startswith('.') or path.suffix in ('.part', '.tmp'):
                continue
            if time.time() - path.stat().st_mtime < SETTLE_SECONDS:
                continue
            taken.mkdir(exist_ok=True, mode=0o700)
            try:
                drop = parse_drop(path.read_text(encoding='utf-8'))
                job = self.daemon.add_job(drop['task'], lane=drop['lane'], session=drop['session'],
                                          door='inbox', reply_to={'file': path.name})
                os.replace(path, taken / f"{job['id']}-{path.name}")
            except Exception as exc:
                # A file that cannot become a job is answered at once, so it never sits there silently.
                paths.outbox.mkdir(exist_ok=True, mode=0o700)
                (paths.outbox / (path.name + '.answer.txt')).write_text(f'Not run: {exc}\n', encoding='utf-8')
                os.replace(path, taken / f'rejected-{path.name}')
                self.daemon.log(f'inbox: {path.name} was not run: {exc}')

    def deliver(self, job):
        paths = self.daemon.paths
        paths.outbox.mkdir(exist_ok=True, mode=0o700)
        name = (job.get('reply_to') or {}).get('file') or f"job-{job['id']}"
        target = paths.outbox / (name + '.answer.txt')
        head = f"job {job['id']}  {job['lane']}  {job['state']}"
        if job['exit_code'] is not None:
            head += f"  exit {job['exit_code']}"
        temporary = target.with_name('.' + target.name + '.part')
        temporary.write_text(head + '\n\n' + answer_text(job) + '\n', encoding='utf-8')
        os.replace(temporary, target)
        return str(target)
