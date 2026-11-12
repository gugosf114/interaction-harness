#!/data/data/com.termux/files/usr/bin/python
"""Authenticated temporary MCP tunnel. The proof exposes notifications only."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from api_tools_config import write_json


def decode(data):
    text=data.decode()
    if text.startswith(('event:','data:')):text='\n'.join(line[6:] for line in text.splitlines() if line.startswith('data: '))
    return json.loads(text) if text.strip() else None


def read_body(stream,headers,limit=1_000_000):
    if headers.get('Transfer-Encoding','').lower()=='chunked':
        result=bytearray()
        while True:
            size=int(stream.readline(100).split(b';',1)[0],16)
            if not size:
                while stream.readline(8192) not in (b'\r\n',b'\n',b''):pass
                return bytes(result)
            if len(result)+size>limit:raise ValueError('Request too large.')
            result.extend(stream.read(size))
            if stream.read(2)!=b'\r\n':raise ValueError('Invalid chunk terminator.')
    size=int(headers.get('Content-Length','0'))
    if size>limit:raise ValueError('Request too large.')
    return stream.read(size)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--allow',action='append',default=[])
    parser.add_argument('--named-config',type=Path,help='Existing cloudflared YAML profile; add a protected MCP path without editing the profile.')
    args=parser.parse_args();state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    allowed=set(args.allow or ['android_notification_list'])
    token=secrets.token_urlsafe(48);token_file=state/'bearer';token_file.write_text(token);token_file.chmod(0o600)
    stop=threading.Event();records=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def reply(self,status,value,session=None):
            raw=json.dumps(value).encode() if value is not None else b''
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            if session:self.send_header('mcp-session-id',session)
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.reply(405,{'error':'Use MCP POST.'})
        def do_DELETE(self):self.reply(200,None)
        def do_POST(self):
            authorized=secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
            records.append({'method':'http_post','path':self.path,'authorized':authorized,'user_agent':self.headers.get('User-Agent',''),
                            'content_length':self.headers.get('Content-Length'),'transfer_encoding':self.headers.get('Transfer-Encoding'),'time':time.time()})
            write_json(state/'requests.json',records)
            if not authorized:
                self.reply(401,{'error':'Bearer token required.'});return
            try:
                data=json.loads(read_body(self.rfile,self.headers));method=data.get('method');params=data.get('params',{})
                records.append({'method':'rpc_received','rpc_method':method,'time':time.time()});write_json(state/'requests.json',records)
                if method=='tools/call' and params.get('name') not in allowed:
                    self.reply(200,{'jsonrpc':'2.0','id':data.get('id'),'error':{'code':-32602,'message':'Tool is outside this tunnel allowlist.'}});return
                headers={'Authorization':'Bearer '+os.environ.get('AGENTBRIDGE_TOKEN','agentbridge-mcp'),
                         'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
                for name in ('mcp-session-id','mcp-protocol-version'):
                    if self.headers.get(name):headers[name]=self.headers[name]
                request=urllib.request.Request('http://127.0.0.1:8080/mcp',json.dumps(data).encode(),headers)
                with urllib.request.urlopen(request,timeout=35) as result:
                    response=decode(result.read());session=result.headers.get('mcp-session-id')
                if method=='tools/list' and response and 'result' in response:
                    response['result']['tools']=[t for t in response['result'].get('tools',[]) if t['name'] in allowed]
                records.append({'method':method,'tool':params.get('name'),'time':time.time()})
                write_json(state/'requests.json',records)
                self.reply(200 if response else 202,response,session)
            except Exception as exc:
                error=type(exc).__name__+': '+str(exc)
                records.append({'method':'proxy_error','error':error,'time':time.time()});write_json(state/'requests.json',records)
                self.reply(502,{'error':error})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    logfile=(state/'cloudflared.log').open('w');proc=None
    try:
        url=None
        if args.named_config:
            source=args.named_config.read_text()
            def field(name):
                match=re.search(r'^\s*(?:-\s*)?'+re.escape(name)+r':\s*(\S+)\s*$',source,re.M)
                if not match:raise ValueError('Named profile has no '+name+'.')
                return match.group(1)
            ident=field('tunnel');host=field('hostname');credentials=field('credentials-file');original=field('service')
            path='/interaction-harness-mcp'
            profile={'tunnel':ident,'credentials-file':credentials,'ingress':[
                {'hostname':host,'path':'^'+path+'$','service':f'http://127.0.0.1:{server.server_port}'},
                {'hostname':host,'service':original},{'service':'http_status:404'}]}
            config=state/'named-config.json';write_json(config,profile)
            command=['deb','cloudflared','tunnel','--config',str(config),'--no-autoupdate','--protocol','http2','run',ident]
            url='https://'+host+path
        else:command=['deb','cloudflared','tunnel','--no-autoupdate','--protocol','http2','--url',f'http://127.0.0.1:{server.server_port}']
        proc=subprocess.Popen(command,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            text=(state/'cloudflared.log').read_text()
            if args.named_config and 'Registered tunnel connection' in text and proc.poll() is None:break
            match=re.search(r'https://(?!api\.)[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com',text)
            if match and proc.poll() is None:url=match.group(0)+'/mcp';break
            if proc.poll() is not None:break
            time.sleep(0.5)
        if not url or proc.poll() is not None:raise RuntimeError('cloudflared did not publish a live tunnel; see its local log.')
        write_json(state/'options.json',{'mcp_url':url,'mcp_token_file':str(token_file),'mcp_allowed_tools':sorted(allowed)})
        write_json(state/'status.json',{'pid':os.getpid(),'url':url,'allowed_tools':sorted(allowed),'running':True})
        print('MCP tunnel ready; options saved in '+str(state/'options.json'),flush=True)
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
        while not stop.wait(1):
            if proc.poll() is not None:raise RuntimeError('cloudflared exited.')
        return 0
    finally:
        server.shutdown();server.server_close()
        if proc and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        logfile.close()
        if (state/'status.json').exists():
            status=json.loads((state/'status.json').read_text());status['running']=False;write_json(state/'status.json',status)


if __name__=='__main__':raise SystemExit(main())
