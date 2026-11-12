"""Outbound phone half of the authenticated MCP relay; no inbound phone port."""
import base64
import gzip
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import uuid

from api_mcp_tunnel import decode


class PhoneRelay:
    def __init__(self,url,token_file,allowed_tools=None,log=None):
        self.url=url.rstrip('/');self.token=Path(token_file).read_text().strip()
        self.allowed=set(allowed_tools or ['android_notification_list'])
        self.log=Path(log) if log else None;self.client=uuid.uuid4().hex
        self.stop=threading.Event();self.thread=None;self.last_error=None

    def request(self,path,data=None):
        headers={'Authorization':'Bearer '+self.token,'User-Agent':'InteractionHarness/1.0'}
        if data is not None:headers['Content-Type']='application/json'
        req=urllib.request.Request(self.url+path,json.dumps(data).encode() if data is not None else None,headers)
        with urllib.request.urlopen(req,timeout=30) as response:
            raw=response.read();return json.loads(raw) if raw else None

    def forward(self,job):
        raw=base64.b64decode(job.get('body',''))
        if job.get('headers',{}).get('content-encoding')=='gzip':raw=gzip.decompress(raw)
        data=json.loads(raw) if raw else None
        method=data.get('method') if isinstance(data,dict) else None
        params=data.get('params',{}) if isinstance(data,dict) else {}
        if method=='tools/call' and params.get('name') not in self.allowed:
            body=json.dumps({'jsonrpc':'2.0','id':data.get('id'),'error':{'code':-32602,'message':'Tool is outside the phone relay allowlist.'}}).encode()
            return {'id':job['id'],'status':200,'body':base64.b64encode(body).decode(),'headers':{'Content-Type':'application/json'}}
        headers={'Authorization':'Bearer '+os.environ.get('AGENTBRIDGE_TOKEN','agentbridge-mcp'),
                 'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        for name in ('mcp-session-id','mcp-protocol-version'):
            if job.get('headers',{}).get(name):headers[name]=job['headers'][name]
        req=urllib.request.Request('http://127.0.0.1:8080/mcp',raw if raw else None,headers,method=job['method'])
        try:
            response=urllib.request.urlopen(req,timeout=35)
        except urllib.error.HTTPError as exc:response=exc
        with response:
            body=response.read();status=response.status
            response_headers={'Content-Type':response.headers.get('Content-Type','application/json')}
            if response.headers.get('mcp-session-id'):response_headers['mcp-session-id']=response.headers['mcp-session-id']
        if method=='tools/list' and status==200:
            parsed=decode(body)
            if parsed and 'result' in parsed:
                parsed['result']['tools']=[t for t in parsed['result'].get('tools',[]) if t['name'] in self.allowed]
                body=json.dumps(parsed).encode();response_headers['Content-Type']='application/json'
        if self.log:
            with self.log.open('a') as stream:stream.write(json.dumps({'method':method,'tool':params.get('name'),'status':status,'time':time.time()})+'\n')
        return {'id':job['id'],'status':status,'body':base64.b64encode(body).decode(),'headers':response_headers}

    def serve(self):
        while not self.stop.is_set():
            try:
                job=self.request('/bridge/poll?client='+self.client)
                if not job:continue
                if self.stop.is_set():
                    result={'id':job['id'],'status':503,'body':base64.b64encode(b'Phone bridge is stopping.').decode()}
                else:
                    try:result=self.forward(job)
                    except Exception as exc:
                        result={'id':job['id'],'status':502,'body':base64.b64encode(str(exc).encode()).decode()}
                self.request('/bridge/result',result)
            except Exception as exc:
                self.last_error=type(exc).__name__+': '+str(exc)
                self.stop.wait(1)

    def start(self):
        self.thread=threading.Thread(target=self.serve,daemon=True);self.thread.start();return self

    def close(self):
        self.stop.set()
        try:self.request('/bridge/cancel?client='+self.client,{})
        except Exception:pass
        if self.thread:self.thread.join(timeout=3)
