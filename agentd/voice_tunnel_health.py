"""Renew a revoked quick tunnel even while its old process keeps retrying."""
from contextlib import contextmanager
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import time
import urllib.error
import urllib.request
from . import config


def revoked(text):
    last_error=text.rfind('Unauthorized: Tunnel not found')
    return last_error>=0 and last_error>text.rfind('Registered tunnel connection')


def address(path):
    """Read the URL issued at creation, not a later request URL printed in a log."""
    created=False
    try:
        with Path(path).open(errors='replace') as stream:
            for line in stream:
                if 'Your quick Tunnel has been created!' in line:created=True
                if created:
                    match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                    if match:return match.group(0)
    except OSError:pass
    return None


@contextmanager
def locked(paths):
    paths.home.mkdir(parents=True,exist_ok=True)
    with (paths.home/'voice-tunnel.flock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def process(pid):
    try:
        root=Path('/proc')/str(pid)
        if b'cloudflared' not in (root/'cmdline').read_bytes():return None
        text=(root/'stat').read_text();fields=text[text.rfind(')')+2:].split()
        return {'pid':pid,'start_ticks':int(fields[19])}
    except (OSError,ValueError,IndexError):return None


def pending(paths):
    try:return json.loads((paths.home/'voice-tunnel-retiring.json').read_text())
    except (OSError,ValueError):return []


def remember(paths,pid):
    item=process(pid)
    if item:
        rows=pending(paths)
        if item not in rows:rows.append(item)
        config.write_private_json(paths.home/'voice-tunnel-retiring.json',rows)


def retire(paths):
    left=[]
    for item in pending(paths):
        if process(item['pid'])!=item:continue
        try:
            if os.getpgid(item['pid'])==item['pid']:
                os.killpg(item['pid'],signal.SIGTERM)
            else:
                os.kill(item['pid'],signal.SIGTERM)
        except ProcessLookupError:continue
        except OSError:pass
        if process(item['pid'])==item:left.append(item)
    config.write_private_json(paths.home/'voice-tunnel-retiring.json',left)


def wait_route(paths,url):
    """An authenticated empty tool request proves the phone route and creates no job."""
    key=config.load_doors(paths)['voice']['key']
    data=json.dumps({'message':{'type':'tool-calls','toolCallList':[]}}).encode()
    deadline=time.monotonic()+60;last='no response'
    while time.monotonic()<deadline:
        try:
            req=urllib.request.Request(url.rstrip('/')+'/vapi/tools',data=data,
                headers={'Content-Type':'application/json','X-Line-Key':key,'User-Agent':'interaction-harness-voice/1'})
            with urllib.request.urlopen(req,timeout=10) as response:
                body=json.load(response)
                if response.status==200 and body=={'results':[]}:return
                last=f'HTTP {response.status}: unexpected tool response'
        except (OSError,ValueError,urllib.error.URLError) as exc:last=str(exc)
        time.sleep(.5)
    raise RuntimeError('Voice route is not ready: '+last)
