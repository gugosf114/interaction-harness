"""Install the adapters in George's existing personal bridges; preserve their other routes."""
from pathlib import Path
import json
import shutil
import os
import subprocess
import time
import urllib.request
from . import config
from .doors.voice import ASSISTANT, BRIDGE, debian_path, vapi_key


def patch_once(path, before, after):
    text = path.read_text()
    if after in text:
        return False
    if text.count(before) != 1:
        raise ValueError(f'{path}: expected one insertion point, found {text.count(before)}.')
    backup = path.with_name(path.name + '.before-agentd-' + str(time.time_ns()))
    shutil.copy2(path, backup)
    path.write_text(text.replace(before, after, 1))
    return True


def telegram(script, url, password, config_file=None):
    script = Path(script)
    config_file = Path(config_file or script.parent.parent.parent / '.agent-bridge/agentd.json')
    config.write_private_json(config_file, {'url': url, 'password': password})
    shutil.copy2(config.ROOT / 'agentd/telegram_lane.py', script.parent / 'telegram_lane.py')
    before = 'if __name__ == "__main__":'
    after = 'from telegram_lane import install as install_lane_door\ninstall_lane_door(globals())\n\n' + before
    patch_once(script, before, after)
    return {'script': str(script), 'config': str(config_file)}


def api(method, route, payload=None):
    key = vapi_key()
    if not key:
        raise ValueError('The Vapi key is missing: /root/.gmail/aicalls.env, VAPI_KEY.')
    req = urllib.request.Request('https://api.vapi.ai' + route,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={'Authorization':'Bearer ' + key, 'Content-Type':'application/json',
                                          'User-Agent':'curl/8.5.0'}, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def voice(paths, public_url=None):
    preserve_lane_tools()
    conf = config.load_doors(paths)
    conf['voice']['bridge_enabled'] = True
    config.write_private_json(paths.doors, conf)
    if public_url:
        return point_voice(paths, public_url)
    return ensure_voice(paths)


def preserve_lane_tools():
    """A legacy voice keeper must update only the three tools it owns."""
    path = debian_path(BRIDGE) / 'phone.sh'
    if not path.exists():
        return
    old = 'for t in tools: t["server"]={"url":turl,"timeoutSeconds":t.get("server",{}).get("timeoutSeconds",15),"headers":{"X-Line-Key":lk}}'
    new = 'for t in tools:\n    if t.get("function",{}).get("name") in ("brain_job","brain_ask","memory_lookup"): t["server"]={"url":turl,"timeoutSeconds":t.get("server",{}).get("timeoutSeconds",15),"headers":{"X-Line-Key":lk}}'
    if old in path.read_text():
        patch_once(path, old, new)


def point_voice(paths, public_url):
    """Only lane_job changes. The personal line's existing brain tools keep their current host and key."""
    conf = config.load_doors(paths)
    assistant = api('GET', '/assistant/' + ASSISTANT)
    config.write_private_json(paths.home / ('vapi-before-' + str(time.time_ns()) + '.json'), assistant)
    model = assistant['model']
    tools = model.setdefault('tools', [])
    existing = next((t for t in tools if t.get('function', {}).get('name') == 'lane_job'), None)
    descriptor = {'type': 'function', 'function': {'name': 'lane_job',
        'description': 'Give a task to George\'s g1 or g2 lane. Returns a job number at once. The full answer is sent into this same call when it finishes.',
        'parameters': {'type': 'object', 'properties': {'task': {'type':'string'},
                        'lane': {'type':'string','enum':['g1','g2']}}, 'required':['task','lane']}},
        'server': {'url':public_url.rstrip('/') + '/vapi/tools', 'timeoutSeconds':30,
                   'headers':{'X-Line-Key':conf['voice']['key']}}}
    if existing:
        tools[tools.index(existing)] = descriptor
    else:
        tools.append(descriptor)
    api('PATCH', '/assistant/' + ASSISTANT, {'model': model})
    reread = api('GET', '/assistant/' + ASSISTANT)
    saved = next((t for t in reread['model'].get('tools', []) if t.get('function', {}).get('name') == 'lane_job'), {})
    if saved.get('server', {}).get('url') != descriptor['server']['url']:
        raise ValueError('Vapi did not retain the lane_job address after PATCH.')
    result = {'assistant':ASSISTANT, 'server_url':descriptor['server']['url']}
    config.write_private_json(paths.home / 'voice-address.json', result)
    return result


def ensure_voice(paths):
    """Keep this phone's lane webhook reachable. Its dedicated tunnel never starts a brain session."""
    from .voice_tunnel_health import locked
    with locked(paths):
        return _ensure_voice(paths)


def _ensure_voice(paths):
    import re
    from . import voice_tunnel_health as health
    from .phone import DEB
    from .jobs import pid_alive
    pidfile = paths.home / 'voice-tunnel.pid'
    logfile = paths.home / 'voice-tunnel.log'
    try:
        pid = int(pidfile.read_text())
        running = pid_alive(pid) and b'cloudflared' in Path(f'/proc/{pid}/cmdline').read_bytes()
    except (OSError, ValueError):
        running = False
    if running and logfile.exists() and health.revoked(logfile.read_text(errors='replace')[-100000:]):
        health.remember(paths,pid)
        running=False
    if not running:
        # Save each prior log, so a new tunnel cannot reuse a dead address.
        if logfile.exists():
            logfile.rename(paths.home / ('voice-tunnel-' + str(time.time_ns()) + '.log'))
        env = dict(os.environ)
        env.pop('LD_LIBRARY_PATH', None)
        with open(logfile, 'ab') as out:
            child = subprocess.Popen([*DEB, 'cloudflared', 'tunnel', '--no-autoupdate', '--protocol', 'http2',
                                      '--url', f'http://127.0.0.1:{config.port(config.load_settings(paths))}'],
                                     env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
        pidfile.write_text(str(child.pid))
    deadline = time.monotonic() + 30
    url = None
    while time.monotonic() < deadline:
        text = logfile.read_text(errors='replace')[-100000:] if logfile.exists() else ''
        url=health.address(logfile)
        if url:
            break
        time.sleep(.5)
    if not url:
        raise RuntimeError('voice tunnel returned no address: ' + text[-800:])
    try:
        prior = json.loads((paths.home / 'voice-address.json').read_text())
    except (OSError, ValueError):
        prior = {}
    if prior.get('server_url') != url + '/vapi/tools':
        health.wait_route(paths,url)
        result=point_voice(paths,url)
        health.retire(paths)
        return result
    if health.pending(paths):
        health.wait_route(paths,url)
        health.retire(paths)
    return prior
