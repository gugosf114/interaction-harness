"""Browser toolset over the phone's existing CDP port; Python standard library only."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import time
import urllib.parse
import urllib.request


class CDP:
    def __init__(self, url):
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme!='ws' or parsed.hostname not in ('127.0.0.1','localhost'):
            raise ValueError('Phone CDP must use the local WebSocket endpoint.')
        self.sock=socket.create_connection((parsed.hostname,parsed.port),timeout=30);self.counter=0;self.events=[]
        key=base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        self.buffer=b''
        while b'\r\n\r\n' not in self.buffer:self.buffer+=self.sock.recv(4096)
        header,self.buffer=self.buffer.split(b'\r\n\r\n',1)
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        if b' 101 ' not in header or expected not in header:raise ValueError('CDP WebSocket handshake failed.')

    def read(self, count):
        while len(self.buffer)<count:
            part=self.sock.recv(max(4096,count-len(self.buffer)))
            if not part:raise ValueError('CDP connection closed.')
            self.buffer+=part
        data,self.buffer=self.buffer[:count],self.buffer[count:];return data

    def frame(self, data, opcode=1):
        if isinstance(data,str):data=data.encode()
        mask=os.urandom(4);size=len(data)
        head=bytes([128|opcode,128|(size if size<126 else 126 if size<65536 else 127)])
        if size>=126:head+=struct.pack('!H' if size<65536 else '!Q',size)
        self.sock.sendall(head+mask+bytes(v^mask[i%4] for i,v in enumerate(data)))

    def message(self):
        parts=[]
        while True:
            a,b=self.read(2);size=b&127
            if size==126:size=struct.unpack('!H',self.read(2))[0]
            if size==127:size=struct.unpack('!Q',self.read(8))[0]
            if size>32_000_000:raise ValueError('CDP frame is too large.')
            mask=self.read(4) if b&128 else None;data=self.read(size)
            if mask:data=bytes(v^mask[i%4] for i,v in enumerate(data))
            opcode=a&15
            if opcode==8:raise ValueError('CDP connection closed.')
            if opcode==9:self.frame(data,10);continue
            if opcode==10:continue
            parts.append(data)
            if a&128:return json.loads(b''.join(parts))

    def call(self, method, params=None):
        self.counter+=1;ident=self.counter
        self.frame(json.dumps({'id':ident,'method':method,'params':params or {}}))
        while True:
            data=self.message()
            if data.get('id')==ident:
                if 'error' in data:raise ValueError(str(data['error']))
                return data.get('result',{})
            if 'method' in data:self.events.append(data)

    def js(self, expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if result.get('exceptionDetails'):raise ValueError('Browser JavaScript failed: '+str(result['exceptionDetails'].get('text')))
        return result.get('result',{}).get('value')


def request(endpoint, path, method='GET'):
    with urllib.request.urlopen(urllib.request.Request(endpoint+path,method=method),timeout=20) as response:
        data=response.read().decode()
        try:return json.loads(data)
        except ValueError:return data


REFS="""window.__harnessRefs ||= new Map(); window.__harnessRefSeq ||= 0;
const refFor = e => {for(const [r,n] of window.__harnessRefs) if(n===e) return r;
 const r='ref_'+(++window.__harnessRefSeq); window.__harnessRefs.set(r,e); return r;};"""


def run(job):
    endpoint=job['endpoint'].rstrip('/');state=Path(job['state']);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    saved=state/'browser-state.json';old=json.loads(saved.read_text()) if saved.exists() else {}
    name=job['name'];args=job.get('args',{});tabs=[t for t in request(endpoint,'/json/list') if t.get('type')=='page']
    active=args.get('tab_id') or old.get('active') or (tabs[0]['id'] if tabs else None)
    changes=[];output={'text':'OK','images':[]}
    if name=='new_tab' or not tabs:
        tab=request(endpoint,'/json/new?'+urllib.parse.quote('about:blank',safe=''),'PUT');active=tab['id'];tabs.append(tab)
        changes.append({'type':'tab_opened','tab_id':active})
    if name=='close_tab':request(endpoint,'/json/close/'+urllib.parse.quote(active,safe=''));active=None
    if name=='switch_tab':request(endpoint,'/json/activate/'+urllib.parse.quote(active,safe=''))
    if name not in ('new_tab','close_tab','switch_tab','list_tabs'):
        tab=next((t for t in tabs if t['id']==active),None)
        if tab is None:raise ValueError('Browser tab is missing.')
        c=CDP(tab['webSocketDebuggerUrl'])
        try:
            c.call('Runtime.enable');c.call('Log.enable');c.call('Network.enable');c.call('Page.enable')
            def node(target):
                if target.get('type')=='coordinate':
                    scale=old.get('scales',{}).get(active) or c.js('window.devicePixelRatio') or 1
                    return [target['x']/scale,target['y']/scale]
                ref=json.dumps(target['ref'])
                value=c.js(f"(()=>{{const e=window.__harnessRefs?.get({ref}); if(!e||!e.isConnected)throw Error('stale ref');const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()")
                return value
            if name=='navigate':
                if not args['url'].startswith(('https://','http://')):raise ValueError('Browser navigation needs an HTTP or HTTPS URL.')
                c.call('Page.navigate',{'url':args['url']});time.sleep(1)
            elif name in ('read_page','find'):
                query=json.dumps(args.get('query','').lower());depth=int(args.get('depth',100))
                selector='a,button,input,textarea,select,[role],[tabindex]' if args.get('filter')=='interactive' else '*'
                expression="(()=>{"+REFS+f"const q={query};return [...document.body.querySelectorAll({json.dumps(selector)})].filter(e=>{{const r=e.getBoundingClientRect();return r.width&&r.height}}).filter(e=>!q||((e.innerText||e.getAttribute('aria-label')||'').toLowerCase().includes(q))).slice(0,500).map(e=>{{let d=0;for(let p=e;p&&p!==document.body;p=p.parentElement)d++;if(d>{depth})return '';return '['+refFor(e)+'] '+(e.getAttribute('role')||e.tagName.toLowerCase())+' '+(e.getAttribute('aria-label')||e.innerText||e.value||'').trim().slice(0,300)}}).filter(Boolean).join('\\n')}})()"
                output['text']=c.js(expression) or '(no matching elements)'
            elif name=='get_page_text':output['text']=c.js('document.body.innerText') or ''
            elif name=='javascript_exec':output['text']=json.dumps(c.js(args['text']),ensure_ascii=False)
            elif name in ('screenshot','zoom'):
                params={'format':'png','captureBeyondViewport':False}
                if name=='zoom':
                    scale=old.get('scales',{}).get(active) or c.js('window.devicePixelRatio') or 1
                    x1,y1,x2,y2=[v/scale for v in args['region']];params['clip']={'x':x1,'y':y1,'width':x2-x1,'height':y2-y1,'scale':1}
                data=base64.b64decode(c.call('Page.captureScreenshot',params)['data'])
                image=state/('browser-'+str(time.time_ns())+'.png');image.write_bytes(data)
                if name=='screenshot':old.setdefault('scales',{})[active]=struct.unpack('!I',data[16:20])[0]/c.js('window.innerWidth')
                output['images']=[str(image)]
            elif name=='type':c.call('Input.insertText',{'text':args['text']})
            elif name=='form_input':
                ref=json.dumps(args['target']['ref']);value=json.dumps(args['value'])
                output['text']=str(c.js(f"(()=>{{const e=window.__harnessRefs?.get({ref});if(!e||!e.isConnected)throw Error('stale ref');const v={value};if(typeof v==='boolean')e.checked=v;else e.value=v;e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}));return 'OK'}})()"))
            elif name=='file_upload':
                if args.get('document_ids'):raise ValueError('Use local paths for browser file uploads.')
                ref=json.dumps(args['target']['ref']);result=c.call('Runtime.evaluate',{'expression':f'window.__harnessRefs.get({ref})'})
                c.call('DOM.setFileInputFiles',{'files':[str(Path(p).resolve()) for p in args.get('paths',[])],'objectId':result['result']['objectId']})
            elif name=='scroll_to':
                ref=json.dumps(args['target']['ref']);c.js(f'window.__harnessRefs.get({ref}).scrollIntoView({{block:"center"}})')
            elif name in ('key','hold_key'):
                keys=args['text'].split('+');mod=0
                for key in keys[:-1]:mod|={'alt':1,'ctrl':2,'control':2,'meta':4,'cmd':4,'shift':8}.get(key.lower(),0)
                key={'Return':'Enter','Esc':'Escape','BackSpace':'Backspace'}.get(keys[-1],keys[-1])
                for _ in range(args.get('repeat',1)):
                    c.call('Input.dispatchKeyEvent',{'type':'keyDown','key':key,'modifiers':mod})
                    if name=='hold_key':time.sleep(min(30,max(0,args['duration'])))
                    c.call('Input.dispatchKeyEvent',{'type':'keyUp','key':key,'modifiers':mod})
            elif name=='wait':time.sleep(min(30,max(0,args['duration'])))
            elif name=='scroll':
                x,y=node(args['target']);amount=args.get('scroll_amount',3)*100;direction=args['scroll_direction']
                c.call('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,'deltaX':(-amount if direction=='left' else amount if direction=='right' else 0),'deltaY':(-amount if direction=='up' else amount if direction=='down' else 0)})
            elif name in ('left_click','right_click','middle_click','double_click','triple_click','mouse_move','hover','left_mouse_down','left_mouse_up','left_click_drag'):
                x,y=node(args['target']);button='right' if name=='right_click' else 'middle' if name=='middle_click' else 'left'
                if name=='left_click_drag':
                    sx,sy=node(args.get('from') or args['from_']);c.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':sx,'y':sy,'button':'left','clickCount':1})
                    c.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y,'buttons':1})
                    c.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1})
                elif name in ('mouse_move','hover'):c.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
                else:
                    count={'double_click':2,'triple_click':3}.get(name,1)
                    events=['mousePressed'] if name=='left_mouse_down' else ['mouseReleased'] if name=='left_mouse_up' else ['mousePressed','mouseReleased']
                    for i in range(1,count+1):
                        for event in events:c.call('Input.dispatchMouseEvent',{'type':event,'x':x,'y':y,'button':button,'clickCount':i})
            elif name not in ('read_console','read_network'):raise ValueError('Unknown browser member: '+name)
            events=(old.get('events',[])+c.events)[-500:]
            if name=='read_console':output['text']=json.dumps([e for e in events if e.get('method') in ('Runtime.consoleAPICalled','Log.entryAdded')],ensure_ascii=False)
            if name=='read_network':output['text']=json.dumps([e for e in events if e.get('method','').startswith('Network.')],ensure_ascii=False)
            old['events']=events
        finally:c.sock.close()
    tabs=[t for t in request(endpoint,'/json/list') if t.get('type')=='page']
    if not any(t['id']==active for t in tabs):active=tabs[0]['id'] if tabs else None
    old['active']=active;saved.write_text(json.dumps(old))
    browser_state={'type':'browser_state','tabs':[{'tab_id':t['id'],'title':t.get('title',''),'url':t.get('url',''),'active':t['id']==active} for t in tabs]}
    if changes:browser_state['state_changes']=changes
    output['browser_state']=browser_state
    return output
