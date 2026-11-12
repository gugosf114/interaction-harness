"""The text-message door: a text that starts with the keyword becomes a job; the answer goes back by text.

Settings in state/doors.json, part "sms": "keyword" (default "lane") and "numbers", the senders it listens to.
"*" in the list means anyone. A text may name the lane right after the keyword: "lane g1 what is on my calendar".
"""
from __future__ import annotations

import re

from ..config import number_allowed
from . import Door, answer_text

PUNCT = ' \t\r\n:,.;-'


def parse_text(body: str, keyword: str, lanes) -> dict | None:
    """{'lane': NAME or None, 'task': TEXT} when the text starts with the keyword and holds a task, else None."""
    keyword = (keyword or '').strip()
    if not keyword:
        return None
    match = re.match(r'\s*' + re.escape(keyword) + r'(?![A-Za-z0-9])(.*)\Z', body or '', re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    rest = match.group(1).lstrip(PUNCT)
    lane = None
    first = re.match(r'([A-Za-z0-9][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])(.*)\Z', rest, re.DOTALL)
    if first:
        names = {name.lower(): name for name in lanes}
        if first.group(1).lower() in names:
            lane, rest = names[first.group(1).lower()], first.group(2).lstrip(PUNCT)
    task = rest.strip()
    return {'lane': lane, 'task': task} if task else None


def reply_text(job) -> str:
    return f"{job['lane']} job {job['id']} {job['state']}: {answer_text(job)}"


class SmsDoor(Door):
    name = 'sms'
    interval = 10

    def poll(self):
        conf = self.daemon.door_conf('sms')
        keyword = str(conf.get('keyword') or 'lane')
        numbers = conf.get('numbers') if isinstance(conf.get('numbers'), list) else []
        messages = self.daemon.phone.sms_inbox(60)
        if messages is None:
            self.note = 'the phone did not answer termux-sms-list'
            return
        newest = max((int(m.get('_id') or 0) for m in messages), default=0)
        seen = self.daemon.queue.kv_get('sms_seen')
        if seen is None:
            # First look: everything already in the inbox is old. Only texts that arrive from now on count.
            self.daemon.queue.kv_set('sms_seen', newest)
            self.note = f'listening for "{keyword} ..." from {", ".join(numbers) or "nobody"}'
            return
        for message in sorted(messages, key=lambda m: int(m.get('_id') or 0)):
            ident = int(message.get('_id') or 0)
            if ident <= seen:
                continue
            seen = ident
            self.daemon.queue.kv_set('sms_seen', seen)
            sender = message.get('number') or message.get('address') or ''
            parsed = parse_text(message.get('body') or '', keyword, self.daemon.lanes())
            if parsed is None or not number_allowed(sender, numbers):
                continue
            try:
                job = self.daemon.add_job(parsed['task'], lane=parsed['lane'], door='sms',
                                          reply_to={'number': sender, 'sms_id': ident})
            except Exception as exc:
                self.daemon.phone.sms_send(sender, f'Not run: {exc}')
                continue
            self.daemon.phone.sms_send(sender, f"{job['lane']} job {job['id']} started.")
        self.note = f'listening for "{keyword} ..." from {", ".join(numbers) or "nobody"}; last text id {seen}'

    def deliver(self, job):
        from ..daemon import DeliveryError
        number = (job.get('reply_to') or {}).get('number')
        if not number:
            return 'no number'
        if not self.daemon.phone.sms_send(number, reply_text(job)):
            raise DeliveryError('termux-sms-send failed')
        return f'texted {number}'
