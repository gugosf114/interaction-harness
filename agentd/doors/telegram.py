"""The Telegram door: a Telegram message becomes a job; the answer goes back to the same chat.

Two roads, one door name.
1. The box bridge. George's bot (t.me/Abridge114_bot) is long-polled by /root/agent-bridge/scripts/telegram_bridge.py on
   the always-on box, and Telegram lets only one program poll a bot. The bridge's /lane, /g1 and /george commands post
   the task here over Tailscale (POST /api/jobs with "door": "telegram") and send the answer back to George's chat.
2. Direct. With "token" (a bot token) and "chat_ids" in the "telegram" part of state/doors.json, this door polls that
   bot itself: every text from a listed chat becomes a job. "/lane NAME TASK" picks a lane.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import Door, answer_text

LIMIT = 4000  # Telegram's message cap is 4096 characters; long answers go out in parts


def parse_message(text: str, lanes) -> dict | None:
    """{'lane', 'task'} from a Telegram text. "/lane g1 TASK", "/g1 TASK", or plain text for the default lane."""
    text = (text or '').strip()
    if not text or text in ('/start', '/help'):
        return None
    names = {name.lower(): name for name in lanes}
    match = re.match(r'/([A-Za-z0-9_-]+)(?:@\w+)?\s*(.*)\Z', text, re.DOTALL)
    if match:
        command, rest = match.group(1).lower(), match.group(2).strip()
        if command == 'lane':
            first = re.match(r'(\S+)\s+(.*)\Z', rest, re.DOTALL)
            if first and first.group(1).lower() in names:
                return {'lane': names[first.group(1).lower()], 'task': first.group(2).strip()} if first.group(2).strip() else None
            return {'lane': None, 'task': rest} if rest else None
        if command in names:
            return {'lane': names[command], 'task': rest} if rest else None
        return None
    return {'lane': None, 'task': text}


def parts(text: str, size=LIMIT) -> list:
    return [text[i:i + size] for i in range(0, len(text), size)] or ['']


class TelegramDoor(Door):
    name = 'telegram'
    interval = 1

    def __init__(self, daemon, opener=None):
        super().__init__(daemon)
        self.open = opener or urllib.request.urlopen

    def api(self, token, method, payload, timeout=40):
        request = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        with self.open(request, timeout=timeout) as response:
            return json.loads(response.read())

    def poll(self):
        conf = self.daemon.door_conf('telegram')
        token = str(conf.get('token') or '')
        chats = [str(chat) for chat in conf.get('chat_ids') or []]
        if conf.get('mode') == 'bridge':
            self.interval = 30
            self.note = 'the existing Telegram bridge takes tasks; this service returns the answers'
            return
        if not token:
            self.interval = 30
            self.note = 'through the box bridge (/lane, /g1, /george); no direct bot token in doors.json'
            return
        self.interval = 1
        offset = int(self.daemon.queue.kv_get('telegram_offset', 0) or 0)
        try:
            reply = self.api(token, 'getUpdates', {'timeout': 25, 'offset': offset + 1, 'allowed_updates': ['message']})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.note = f'getUpdates failed: {exc}'
            self.interval = 10
            return
        for update in reply.get('result') or []:
            offset = max(offset, int(update.get('update_id') or 0))
            self.daemon.queue.kv_set('telegram_offset', offset)
            message = update.get('message') or {}
            chat = str((message.get('chat') or {}).get('id') or '')
            text = message.get('text') or ''
            if not chat or not text:
                continue
            if chat not in chats:
                self.send(token, chat, f'This chat is not on the list. Its id: {chat}')
                continue
            parsed = parse_message(text, self.daemon.lanes())
            if parsed is None:
                self.send(token, chat, 'Send a task. /lane NAME TASK picks a lane; lanes: ' + ', '.join(sorted(self.daemon.lanes())))
                continue
            try:
                job = self.daemon.add_job(parsed['task'], lane=parsed['lane'], door='telegram', reply_to={'chat_id': chat})
                self.send(token, chat, f"{job['lane']} job {job['id']} started.")
            except Exception as exc:
                self.send(token, chat, f'Not run: {exc}')
        self.note = f'polling the bot directly for chats {", ".join(chats) or "none"}'

    def send(self, token, chat, text):
        ok = True
        for piece in parts(text):
            try:
                ok = bool(self.api(token, 'sendMessage', {'chat_id': chat, 'text': piece}, timeout=20).get('ok')) and ok
            except (urllib.error.URLError, OSError, ValueError):
                ok = False
        return ok

    def deliver(self, job):
        from ..daemon import DeliveryError
        chat = (job.get('reply_to') or {}).get('chat_id')
        token = str(self.daemon.door_conf('telegram').get('token') or '')
        if not chat or not token:
            return 'the box bridge collects it'
        if not self.send(token, chat, f"{job['lane']} job {job['id']} {job['state']}:\n{answer_text(job)}"):
            raise DeliveryError('sendMessage failed')
        return f'sent to chat {chat}'
