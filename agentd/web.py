"""The web page and its small JSON API, served by the service itself.

One listener on 0.0.0.0:PORT: this phone, George's Tailscale network, and any tunnel pointed at it.
The password is `web.password` in state/doors.json. An empty password opens the page to anyone with the link.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import socket
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from . import config
from .jobs import JobError, turns

TAILNET = ipaddress.ip_network('100.64.0.0/10')
MAX_BODY = 4 * 1024 * 1024
COOKIE = 'agentd_pw'


def password_given(password, headers, query) -> bool:
    """True when no password is set, or the request carries it: header, ?password=, or the page's cookie."""
    if not password:
        return True
    offered = [headers.get('X-Agentd-Password'), (query.get('password') or [None])[0]]
    bearer = headers.get('Authorization') or ''
    if bearer.startswith('Bearer '):
        offered.append(bearer[7:])
    for part in (headers.get('Cookie') or '').split(';'):
        name, _, value = part.strip().partition('=')
        if name == COOKIE:
            offered.append(unquote(value))
    return any(value and hmac.compare_digest(value.strip().encode(), password.encode()) for value in offered)


def tailscale_ip():
    """This phone's Tailscale address, or None when Tailscale is off. No packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('100.100.100.100', 53))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return address if ipaddress.ip_address(address) in TAILNET else None


def job_view(job) -> dict:
    return {key: job[key] for key in ('id', 'created', 'started', 'finished', 'lane', 'session', 'task', 'door', 'state',
                                      'exit_code', 'answer', 'error')}


def job_detail(paths, job) -> dict:
    view = job_view(job)
    view['turns'] = [{'answer': row.get('direct_answer'), 'command': row.get('execution_payload'),
                      'result': {key: (row.get('execution_result') or {}).get(key) for key in ('approved', 'exit_code', 'timed_out', 'stdout', 'stderr')}
                      if row.get('execution_result') else None, 'status': row.get('status'), 'error': row.get('error')}
                     for row in turns(paths, job)]
    return view


class Handler(BaseHTTPRequestHandler):
    server_version = 'agentd'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    # --- plumbing ----------------------------------------------------------------------------------------
    def send(self, status, body, content_type='application/json', extra=None):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type + ('; charset=utf-8' if 'charset' not in content_type else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def allowed(self, query) -> bool:
        return password_given(self.server.daemon.web_password(), self.headers, query)

    def read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            raise ValueError('The request is too large.')
        raw = self.rfile.read(length) if length else b''
        data = json.loads(raw.decode('utf-8')) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError('The request must be one JSON object.')
        return data

    def same_site(self) -> bool:
        """A write must come from this page or from a program: JSON body, and no foreign Origin."""
        if 'application/json' not in (self.headers.get('Content-Type') or '').lower():
            return False
        origin = self.headers.get('Origin')
        return not origin or urlsplit(origin).netloc == (self.headers.get('Host') or '')

    # --- routes ------------------------------------------------------------------------------------------
    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self.allowed(query):
            if (urlsplit(self.path).path.rstrip('/') or '/') == '/':
                return self.send(401, LOGIN, 'text/html')
            return self.send(401, {'error': 'This page needs its password.'})
        daemon = self.server.daemon
        path = url.path.rstrip('/') or '/'
        if path == '/':
            return self.send(200, PAGE, 'text/html')
        if path == '/api/state':
            table = daemon.lanes()
            return self.send(200, {'lanes': sorted(table), 'default_lane': config.default_lane(daemon.settings, table),
                                   'jobs': [job_view(job) for job in daemon.queue.list(limit=200)],
                                   'doors': {door.name: door.status() for door in daemon.doors}})
        if path.startswith('/api/jobs/'):
            try:
                job = daemon.queue.get(int(path.rsplit('/', 1)[1]))
            except ValueError:
                job = None
            if job is None:
                return self.send(404, {'error': 'No such job.'})
            return self.send(200, job_detail(daemon.paths, job))
        return self.send(404, {'error': 'Not found.'})

    do_HEAD = do_GET

    def do_POST(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        daemon = self.server.daemon
        path = url.path.rstrip('/') or '/'
        public = [door for door in daemon.doors if hasattr(door, 'public')]
        if not self.allowed(query) and not any(path == route for door in public for route in getattr(door, 'routes', ())):
            return self.send(401, {'error': 'This page needs its password.'})
        if 'application/json' not in (self.headers.get('Content-Type') or '').lower():
            return self.send(415, {'error': 'Send JSON.'})
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            return self.send(400, {'error': str(exc) or 'The request is not JSON.'})
        for door in public:
            reply = door.public('POST', path, self.headers, body)
            if reply is not None:
                return self.send(*reply)
        if not self.allowed(query):
            return self.send(401, {'error': 'This page needs its password.'})
        if not self.same_site():
            return self.send(403, {'error': 'Send JSON from this page or from a program.'})
        if path == '/api/jobs':
            door = body.get('door') if body.get('door') in ('web', 'telegram') else 'web'
            reply_to = body.get('reply_to') if isinstance(body.get('reply_to'), dict) else None
            try:
                job = daemon.add_job(str(body.get('task') or ''), lane=body.get('lane') or None,
                                     session=body.get('session') or None, door=door, reply_to=reply_to)
            except (JobError, ValueError) as exc:
                return self.send(400, {'error': str(exc)})
            return self.send(201, job_view(job))
        if path.startswith('/api/jobs/') and path.endswith('/stop'):
            try:
                job = daemon.queue.request_stop(int(path.split('/')[3]))
            except ValueError:
                job = None
            if job is None:
                return self.send(404, {'error': 'No such job.'})
            return self.send(200, job_view(job))
        return self.send(404, {'error': 'Not found.'})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, daemon):
        super().__init__(address, Handler)
        self.daemon = daemon


class Web:
    def __init__(self, servers):
        self.servers = servers

    def stop(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()


def start_web(daemon, address='0.0.0.0'):
    """Start the listener. A port that is taken is logged; the service keeps running without the page."""
    number = config.port(daemon.settings)
    try:
        server = Server((address, number), daemon)
    except OSError as exc:
        daemon.log(f'web: port {number} is not free ({exc})')
        return Web([])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    daemon.log(f'web: page on {address}:{number}')
    return Web([server])


LOGIN = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lanes</title>
<style>:root{--bg:#f6f4ef;--card:#fff;--ink:#1c1b19;--line:#dcd7cc;--go:#1f6f4a}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--line:#37342e;--go:#58b889}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,sans-serif}
form{max-width:360px;margin:15vh auto;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:10px}
input,button{font:inherit;width:100%;box-sizing:border-box;padding:9px;border-radius:8px;margin-top:8px}
input{border:1px solid var(--line);background:var(--bg);color:inherit}button{border:0;background:var(--go);color:#fff}</style></head>
<body><form id="f"><b>Lanes</b><input id="p" type="password" placeholder="Password" autofocus><button>Open</button></form>
<script>document.getElementById('f').onsubmit=e=>{e.preventDefault();
document.cookie='agentd_pw='+encodeURIComponent(document.getElementById('p').value)+'; path=/; max-age=31536000; SameSite=Strict';location.reload()}</script>
</body></html>
'''


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lanes</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1c1b19;--dim:#6b675f;--line:#dcd7cc;--go:#1f6f4a;--stop:#a3322a;--mono:ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--dim:#9a958a;--line:#37342e;--go:#58b889;--stop:#e0776d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0 12px}h2{font-size:15px;margin:18px 0 6px;color:var(--dim);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
textarea,select,input{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;width:100%}
textarea{min-height:92px;resize:vertical}
.row{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}.row>*{flex:1 1 140px}
button{font:inherit;border:0;border-radius:8px;padding:9px 16px;background:var(--go);color:#fff;cursor:pointer;flex:0 0 auto}
button.stop{background:var(--stop)}button:disabled{opacity:.5}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600}tbody tr{cursor:pointer}tbody tr.on{background:var(--bg)}
.state{font-weight:600}.running,.starting,.queued{color:var(--go)}.failed,.interrupted,.stopped{color:var(--stop)}
pre{white-space:pre-wrap;word-break:break-word;font:13px/1.45 var(--mono);margin:6px 0;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px}
.dim{color:var(--dim)}.task{max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#msg{color:var(--stop);min-height:1.2em;margin-top:6px}
.tablewrap{overflow-x:auto}
</style></head><body><main>
<h1>Lanes</h1>
<div class="card">
<textarea id="task" placeholder="Type a task"></textarea>
<div class="row"><select id="lane" aria-label="Lane"></select><input id="session" placeholder="Session name (blank: a new one)"><button id="run">Run</button></div>
<div id="msg"></div>
</div>
<h2>Jobs</h2>
<div class="card tablewrap"><table><thead><tr><th>ID</th><th>State</th><th>Lane</th><th>Door</th><th>Time</th><th>Task</th></tr></thead><tbody id="jobs"></tbody></table></div>
<div id="detail"></div>
</main><script>
const pw=new URLSearchParams(location.search).get('password');
if(pw)document.cookie='agentd_pw='+encodeURIComponent(pw)+'; path=/; max-age=31536000; SameSite=Strict';
const head={'Content-Type':'application/json'};
let chosen=Number(new URLSearchParams(location.search).get('job'))||null,lanesSet=false;
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function clock(s){s=Math.max(0,Math.floor(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')}
function ran(j){const now=Date.now()/1000;if(j.finished&&j.started)return clock(j.finished-j.started);if(j.started)return clock(now-j.started);return clock((j.finished||now)-j.created)}
async function api(path,options){const r=await fetch(path,Object.assign({headers:head},options||{}));const d=await r.json().catch(()=>({error:'No answer from the phone.'}));if(!r.ok)throw new Error(d.error||r.status);return d}
async function refresh(){
  try{const s=await api('/api/state');
    if(!lanesSet){$('lane').innerHTML=s.lanes.map(l=>'<option'+(l===s.default_lane?' selected':'')+'>'+esc(l)+'</option>').join('');lanesSet=true}
    $('jobs').innerHTML=s.jobs.map(j=>'<tr data-id="'+j.id+'"'+(j.id===chosen?' class="on"':'')+'><td>'+j.id+'</td><td class="state '+j.state+'">'+j.state+'</td><td>'+esc(j.lane)+'</td><td>'+esc(j.door)+'</td><td>'+ran(j)+'</td><td><div class="task">'+esc(j.task.split('\n')[0])+'</div></td></tr>').join('')||'<tr><td colspan="6" class="dim">No jobs yet.</td></tr>';
    if(chosen)show(chosen)
  }catch(e){$('msg').textContent=e.message}
}
async function show(id){
  try{const j=await api('/api/jobs/'+id);const live=['queued','starting','running'].includes(j.state);
    let h='<h2>Job '+j.id+' &middot; '+esc(j.lane)+' &middot; <span class="state '+j.state+'">'+j.state+'</span>'+(j.exit_code==null?'':' &middot; exit '+j.exit_code)+' &middot; '+ran(j)+'</h2><div class="card">';
    if(live)h+='<div class="row"><button class="stop" id="stop">Stop</button></div>';
    h+='<div class="dim">Task</div><pre>'+esc(j.task)+'</pre><div class="dim">Answer</div><pre>'+esc(j.answer||(live?'Working.':(j.error||'No answer.')))+'</pre>';
    const cmds=j.turns.filter(t=>t.command);h+='<div class="dim">Commands ('+cmds.length+')</div>';
    cmds.forEach((t,i)=>{const r=t.result;const st=!r?'not run':r.approved===false?'declined':r.timed_out?'timed out':'exit '+r.exit_code;
      h+='<details><summary>'+(i+1)+'. ['+st+'] <code>'+esc(t.command.split('\n')[0].slice(0,140))+'</code></summary><pre>'+esc(t.command)+'</pre>'+(t.answer?'<div class="dim">Said</div><pre>'+esc(t.answer)+'</pre>':'')+(r&&r.stdout?'<div class="dim">stdout</div><pre>'+esc(r.stdout)+'</pre>':'')+(r&&r.stderr?'<div class="dim">stderr</div><pre>'+esc(r.stderr)+'</pre>':'')+'</details>'});
    const open=[...document.querySelectorAll('#detail details')].map(d=>d.open);
    $('detail').innerHTML=h+'</div>';
    document.querySelectorAll('#detail details').forEach((d,i)=>{if(open[i])d.open=true});
    const b=$('stop');if(b)b.onclick=async()=>{b.disabled=true;try{await api('/api/jobs/'+id+'/stop',{method:'POST',body:'{}'})}catch(e){$('msg').textContent=e.message}refresh()};
  }catch(e){$('detail').innerHTML=''}
}
$('jobs').onclick=e=>{const tr=e.target.closest('tr[data-id]');if(tr){chosen=Number(tr.dataset.id);refresh()}};
$('run').onclick=async()=>{const task=$('task').value.trim();if(!task){$('msg').textContent='Type a task first.';return}
  $('run').disabled=true;$('msg').textContent='';
  try{const j=await api('/api/jobs',{method:'POST',body:JSON.stringify({task,lane:$('lane').value,session:$('session').value.trim()})});chosen=j.id;$('task').value=''}catch(e){$('msg').textContent=e.message}
  $('run').disabled=false;refresh()};
refresh();setInterval(refresh,2000);
</script></body></html>
'''
