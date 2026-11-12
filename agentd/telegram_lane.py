"""Adapter loaded by the existing Telegram bridge. It keeps that bridge's bot and chat checks."""
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request


def install(namespace, config_file=None):
    config_file = Path(config_file or os.environ.get('AGENTD_BRIDGE_CONFIG') or
                       Path.home() / '.agent-bridge/agentd.json')
    original = namespace['handle_text']

    def request(method, route, payload=None):
        conf = json.loads(config_file.read_text())
        req = urllib.request.Request(conf['url'].rstrip('/') + route,
                                     data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={'Content-Type': 'application/json',
                                              'X-Agentd-Password': conf['password']}, method=method)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def result(job):
        ident = job['id']
        while job['state'] in ('queued', 'starting', 'running'):
            time.sleep(2)
            try:
                job = request('GET', f'/api/jobs/{ident}')
            except (OSError, ValueError) as exc:
                namespace['log']('lane result lookup failed:', str(exc))
                continue
        text = f"{job['lane']} job {ident} {job['state']}:\n" + (job.get('answer') or job.get('error') or 'No answer.')
        for start in range(0, len(text), 4000):
            namespace['send'](text[start:start + 4000])

    def handle(text):
        words = text.strip().split(None, 1)
        command = words[0].split('@', 1)[0].lower() if words else ''
        if command not in ('/lane', '/g1', '/george'):
            return original(text)
        rest = words[1].strip() if len(words) > 1 else ''
        lane = command[1:] if command != '/lane' else None
        if command == '/lane':
            pair = rest.split(None, 1)
            if len(pair) != 2:
                return namespace['send']('Use /lane NAME TASK, /g1 TASK, or /george TASK.')
            lane, rest = pair
        if not rest:
            return namespace['send']('A lane job needs a task.')
        try:
            job = request('POST', '/api/jobs', {'task': rest, 'lane': lane, 'door': 'telegram',
                                               'reply_to': {'chat_id': namespace['CHAT_ID'], 'bridge': True}})
        except (OSError, ValueError) as exc:
            return namespace['send']('The lane job was not queued: ' + str(exc))
        namespace['send'](f"{job['lane']} job {job['id']} started.")
        conf = json.loads(config_file.read_text())
        if conf.get('delivery') != 'daemon':
            threading.Thread(target=result, args=(job,), daemon=True).start()

    namespace['handle_text'] = handle

