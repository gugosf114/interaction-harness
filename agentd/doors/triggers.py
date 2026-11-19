"""The event door: state/triggers.json runs a task template when something arrives on the phone.

[
  {"name": "boss mail", "when": "mail", "mailbox": "berkeley", "match": "invoice", "lane": "g2",
   "task": "A new Berkeley mail arrived. Read it and tell me what it asks:\n{text}"},
  {"name": "whatsapp", "when": "notification", "app": "com.whatsapp", "task": "Summarize this message: {text}"},
  {"name": "yana", "when": "sms", "from": "+14155550100", "task": "Yana texted: {text}. Draft a reply."}
]
"when": mail (mailbox berkeley or gmail), notification (app = package name or app name), or sms (from = a number).
"match" (optional) is a word or phrase the event text must hold, any case.
The template can use {text}, {from}, {title}, {app}, {subject} and {mailbox}.
Only events that arrive after the service first looks count.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from ..config import DEBIAN_ROOTFS, ROOT, TERMUX_BIN, number_allowed
from . import Door

KINDS = ('mail', 'notification', 'sms')
MAILBOXES = ('berkeley', 'gmail')
SEEN_LIMIT = 500
OWN_TITLE = re.compile(r'^\S+ job \d+ \w+$|^\d+ lane jobs? running$')  # the service's own notifications


class TriggerError(ValueError):
    pass


def parse_triggers(text: str) -> list:
    data = json.loads(text) if text.strip() else []
    if isinstance(data, dict):
        data = data.get('triggers', [])
    if not isinstance(data, list):
        raise TriggerError('triggers.json must be a list of rules.')
    rules = []
    for number, rule in enumerate(data, 1):
        if not isinstance(rule, dict):
            raise TriggerError(f'rule {number} is not an object.')
        when = rule.get('when')
        if when not in KINDS:
            raise TriggerError(f'rule {number}: "when" must be mail, notification or sms.')
        if not isinstance(rule.get('task'), str) or not rule['task'].strip():
            raise TriggerError(f'rule {number} needs a task template.')
        if when == 'mail' and rule.get('mailbox') not in MAILBOXES:
            raise TriggerError(f'rule {number}: "mailbox" must be berkeley or gmail.')
        if when == 'notification' and not (isinstance(rule.get('app'), str) and rule['app'].strip()):
            raise TriggerError(f'rule {number}: "app" must name an app.')
        if when == 'sms' and not (isinstance(rule.get('from'), str) and rule['from'].strip()):
            raise TriggerError(f'rule {number}: "from" must name a sender.')
        rules.append({**rule, 'name': rule.get('name') or f'rule {number}'})
    return rules


def fill(template: str, event: dict) -> str:
    """The template with the event's fields put in. Unknown {words} stay as written."""
    out = template
    for key in ('text', 'from', 'title', 'app', 'subject', 'mailbox'):
        out = out.replace('{' + key + '}', str(event.get(key) or ''))
    return out


def matches(rule: dict, event: dict) -> bool:
    if rule['when'] != event['kind']:
        return False
    if event['kind'] == 'mail' and rule['mailbox'] != event.get('mailbox'):
        return False
    if event['kind'] == 'notification':
        wanted = rule['app'].strip().lower()
        if wanted not in ((event.get('package') or '').lower(), (event.get('app') or '').lower()):
            return False
    if event['kind'] == 'sms':
        sender = rule['from'].strip()
        if not (number_allowed(event.get('from'), [sender]) or sender.lower() == str(event.get('from') or '').lower()):
            return False
    phrase = rule.get('match')
    if isinstance(phrase, str) and phrase.strip():
        haystack = ' '.join(str(event.get(key) or '') for key in ('text', 'title', 'subject', 'from')).lower()
        if phrase.strip().lower() not in haystack:
            return False
    return True


def notification_event(item: dict) -> dict:
    title = item.get('title') or ''
    body = item.get('big_text') or item.get('text') or ''
    return {'kind': 'notification', 'id': f"{item.get('notification_id')}:{item.get('timestamp')}",
            'package': item.get('package_name') or '', 'app': item.get('app_name') or '', 'title': title,
            'from': title, 'text': (title + ': ' + body).strip(': ') if title else body}


def sms_event(message: dict) -> dict:
    return {'kind': 'sms', 'id': int(message.get('_id') or 0), 'from': message.get('number') or message.get('address') or '',
            'text': message.get('body') or ''}


def mail_events(mailbox: str, runner=None) -> list | None:
    """The newest inbox mail of one mailbox, from the Debian side. None when the reader fails."""
    command = [TERMUX_BIN + '/proot-distro', 'login', 'debian', '--', '/usr/bin/python3', str(ROOT / 'agentd' / 'mail_new.py'), mailbox, '15']
    if not os.path.isdir(DEBIAN_ROOTFS):  # already inside Debian
        command = ['/usr/bin/python3', str(ROOT / 'agentd' / 'mail_new.py'), mailbox, '15']
    try:
        done = (runner or subprocess.run)(command, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        items = json.loads(done.stdout)
    except ValueError:
        return None
    return [{'kind': 'mail', 'mailbox': mailbox, 'id': item.get('id'), 'from': item.get('from'), 'subject': item.get('subject'),
             'title': item.get('subject'), 'text': f"From: {item.get('from')}\nSubject: {item.get('subject')}\n{item.get('snippet') or ''}"}
            for item in items if isinstance(item, dict)]


class TriggerDoor(Door):
    name = 'triggers'
    interval = 15
    mail_every = 4  # mail is read on every fourth look: once a minute

    def __init__(self, daemon):
        super().__init__(daemon)
        self.looks = 0

    def sources(self, rules) -> dict:
        """Event lists by source, only for the kinds some rule asks for. A source that failed is left out."""
        found = {}
        kinds = {rule['when'] for rule in rules}
        phone = self.daemon.phone
        if 'notification' in kinds:
            items = phone.notifications()
            if items is not None:
                found['notification'] = [notification_event(item) for item in items
                                         if not OWN_TITLE.match(item.get('title') or '')]
        if 'sms' in kinds:
            items = phone.sms_inbox(60)
            if items is not None:
                found['sms'] = [sms_event(item) for item in items]
        if 'mail' in kinds and self.looks % self.mail_every == 0:
            for box in sorted({rule['mailbox'] for rule in rules if rule['when'] == 'mail'}):
                items = mail_events(box)
                if items is not None:
                    found['mail:' + box] = items
        return found

    def poll(self):
        path = self.daemon.paths.triggers
        try:
            rules = parse_triggers(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            self.note = f'no {path.name}'
            return
        except (OSError, ValueError) as exc:
            self.note = f'{path.name}: {exc}'
            return
        events = self.sources(rules)
        self.looks += 1
        self.handle(rules, events)
        self.note = f"{len(rules)} rules; watching {', '.join(sorted(events)) or 'nothing yet'}"

    def handle(self, rules, events):
        """Run each new event through the rules. The first look at a source only records what is already there."""
        queue = self.daemon.queue
        seen = queue.kv_get('trigger_seen', {}) or {}
        fired = []
        for source, items in events.items():
            known = seen.get(source)
            ids = [str(item['id']) for item in items]
            if known is None:
                seen[source] = ids[-SEEN_LIMIT:]
                continue
            known_set = set(known)
            for item in items:
                if str(item['id']) in known_set:
                    continue
                known.append(str(item['id']))
                for rule in rules:
                    if matches(rule, item):
                        try:
                            job = self.daemon.add_job(fill(rule['task'], item), lane=rule.get('lane'), session=rule.get('session'),
                                                      door='triggers', reply_to={'rule': rule['name'], 'event': item['kind']})
                            fired.append(job['id'])
                            self.daemon.log(f"trigger {rule['name']}: {item['kind']} {item['id']} -> job {job['id']}")
                        except Exception as exc:
                            self.daemon.log(f"trigger {rule['name']} not run: {exc}")
            seen[source] = known[-SEEN_LIMIT:]
        queue.kv_set('trigger_seen', seen)
        return fired
