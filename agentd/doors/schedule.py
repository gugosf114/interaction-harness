"""The clock door: state/schedule.json lists jobs at a time of day or every N minutes.

[
  {"name": "morning", "at": "08:00", "lane": "george", "task": "Read my Berkeley inbox and list what needs me."},
  {"name": "battery", "every_minutes": 30, "lane": "g1", "task": "Report the battery level."}
]
"at" is the phone's local time, HH:MM. Optional "days": ["mon", "tue", ...]. Optional "session": a fixed session name.
The service checks the clock every 20 seconds. Android's timer 7742 restarts the service (agentd install hangs it).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

from ..config import SESSION_NAME
from . import Door

DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
CATCH_UP_SECONDS = 3600  # a time of day missed while the phone slept still runs within this window


class ScheduleError(ValueError):
    pass


def entry_key(entry) -> str:
    if isinstance(entry.get('name'), str) and entry['name'].strip():
        return 'name:' + entry['name'].strip()
    return 'sha:' + hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]


def parse_schedule(text: str) -> list:
    """The checked entries of schedule.json. A bad entry is an error that names it."""
    data = json.loads(text) if text.strip() else []
    if isinstance(data, dict):
        data = data.get('jobs', [])
    if not isinstance(data, list):
        raise ScheduleError('schedule.json must be a list of entries.')
    found = []
    for number, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise ScheduleError(f'entry {number} is not an object.')
        task = entry.get('task')
        if not isinstance(task, str) or not task.strip():
            raise ScheduleError(f'entry {number} needs a task.')
        at, every = entry.get('at'), entry.get('every_minutes')
        if (at is None) == (every is None):
            raise ScheduleError(f'entry {number} needs exactly one of "at" or "every_minutes".')
        if at is not None:
            match = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', str(at).strip())
            if not match:
                raise ScheduleError(f'entry {number}: "at" must be HH:MM.')
            at = (int(match.group(1)), int(match.group(2)))
        if every is not None and (not isinstance(every, (int, float)) or every <= 0):
            raise ScheduleError(f'entry {number}: "every_minutes" must be a number above 0.')
        days = entry.get('days')
        if days is not None:
            if not isinstance(days, list) or not all(isinstance(d, str) and d[:3].lower() in DAYS for d in days):
                raise ScheduleError(f'entry {number}: "days" must name days such as "mon".')
            days = {d[:3].lower() for d in days}
        session = entry.get('session')
        if session is not None and not (isinstance(session, str) and SESSION_NAME.fullmatch(session)):
            raise ScheduleError(f'entry {number}: bad session name.')
        found.append({'key': entry_key(entry), 'name': entry.get('name') or f'entry {number}', 'task': task.strip(),
                      'lane': entry.get('lane'), 'session': session, 'at': at, 'every': every, 'days': days})
    return found


def due(entry, now: datetime.datetime, last) -> bool:
    """Should this entry run now? last is the time it last ran (epoch seconds) or None."""
    stamp = now.timestamp()
    if entry['every'] is not None:
        return last is not None and stamp - last >= entry['every'] * 60
    target = now.replace(hour=entry['at'][0], minute=entry['at'][1], second=0, microsecond=0)
    if target > now:
        target -= datetime.timedelta(days=1)
    if entry['days'] and DAYS[target.weekday()] not in entry['days']:
        return False
    return stamp - target.timestamp() < CATCH_UP_SECONDS and (last is None or last < target.timestamp())


class ScheduleDoor(Door):
    name = 'schedule'
    interval = 20

    def poll(self, now=None):
        path = self.daemon.paths.schedule
        try:
            entries = parse_schedule(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            self.note = f'no {path.name}'
            return
        except (OSError, ValueError) as exc:
            self.note = f'{path.name}: {exc}'
            return
        now = now or datetime.datetime.now()
        last = self.daemon.queue.kv_get('schedule_last', {}) or {}
        changed = False
        for entry in entries:
            key = entry['key']
            if key not in last:
                # Seen for the first time. "every": the first run is one period later. "at": a time that already
                # passed today waits for its next turn, so a new entry never fires for the past.
                last[key], changed = now.timestamp(), True
                continue
            if not due(entry, now, last.get(key)):
                continue
            last[key], changed = now.timestamp(), True
            try:
                job = self.daemon.add_job(entry['task'], lane=entry['lane'], session=entry['session'], door='schedule',
                                          reply_to={'entry': entry['name']})
                self.daemon.log(f"schedule: {entry['name']} -> job {job['id']}")
            except Exception as exc:
                self.daemon.log(f"schedule: {entry['name']} not run: {exc}")
        if changed:
            self.daemon.queue.kv_set('schedule_last', last)
        self.note = f'{len(entries)} entries in {path.name}'
