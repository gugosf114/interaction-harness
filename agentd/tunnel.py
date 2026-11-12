"""`agentd tunnel [cloudflared|ngrok]`: put the service's page on a public address.

Both programs live on the Debian side. cloudflared (the default) makes a quick tunnel with a new
https://NAME.trycloudflare.com address each time. ngrok uses George's ngrok account; its one free fixed address
belongs to the voice line, so `agentd tunnel ngrok` asks ngrok for another endpoint.
The command stays in the front and prints the address; Ctrl-C closes the tunnel. The page still asks for its password.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys

from . import config

URL = {'cloudflared': re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com'),
       'ngrok': re.compile(r'https://[A-Za-z0-9.-]+\.ngrok(?:-free)?\.(?:app|dev|io)')}


def command(kind, number) -> list:
    inner = {'cloudflared': ['cloudflared', 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{number}'],
             'ngrok': ['ngrok', 'http', str(number), '--log', 'stdout', '--log-format', 'json']}[kind]
    if config.DEBIAN_ROOTFS.is_dir():
        return [config.TERMUX_BIN + '/proot-distro', 'login', 'debian', '--', *inner]
    return inner


def find_url(kind, line) -> str | None:
    if kind == 'ngrok' and line.lstrip().startswith('{'):
        try:
            data = json.loads(line)
        except ValueError:
            data = {}
        if isinstance(data.get('url'), str) and data['url'].startswith('https://'):
            return data['url']
    match = URL[kind].search(line)
    return match.group(0) if match else None


def tunnel(argv, paths) -> int:
    kind = argv[0] if argv else 'cloudflared'
    if kind not in URL:
        print('usage: agentd tunnel [cloudflared|ngrok]', file=sys.stderr)
        return 2
    settings = config.load_settings(paths)
    number = config.port(settings)
    password = str(config.load_doors(paths).get('web', {}).get('password') or '')
    record = paths.home / 'tunnel-url'
    try:
        child = subprocess.Popen(command(kind, number), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        print(f'{kind} could not start ({type(exc).__name__}).', file=sys.stderr)
        return 2
    shown, tail = None, []
    try:
        for line in child.stdout:
            tail = (tail + [line.rstrip()])[-8:]
            url = find_url(kind, line)
            if url and not shown:
                shown = url
                record.write_text(url + '\n')
                print(url + '/', flush=True)
                print('password: ' + (password or '(none)'), flush=True)
                print(f'Ctrl-C closes the tunnel. Page: {url}/?password=PASSWORD', file=sys.stderr, flush=True)
        child.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGINT)
                child.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                os.killpg(child.pid, signal.SIGKILL)
        try:
            record.unlink()
        except OSError:
            pass
    if not shown:
        print(f'{kind} ended without an address (exit {child.returncode}):', file=sys.stderr)
        print('\n'.join(tail), file=sys.stderr)
        return 1
    return 0
