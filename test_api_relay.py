"""MCP relay transport, role separation, and a real local JS protocol round trip."""
import base64
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from api_mcp_relay import PhoneRelay


class Reply(io.BytesIO):
    status=200
    headers={'Content-Type':'application/json'}


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        token=self.root/'token';token.write_text('test-bridge-token')
        self.relay=PhoneRelay('https://relay.example.test',token)

    def job(self,method,params=None):
        value={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}
        return {'id':'job1','method':'POST','headers':{},'body':base64.b64encode(json.dumps(value).encode()).decode()}

    def test_remote_listing_uses_actual_phone_tools_and_filters_the_allowlist(self):
        body={'jsonrpc':'2.0','id':1,'result':{'tools':[{'name':'android_notification_list'},{'name':'android_tap'}]}}
        with patch('api_mcp_relay.urllib.request.urlopen',return_value=Reply(json.dumps(body).encode())) as request:
            result=self.relay.forward(self.job('tools/list'))
        tools=json.loads(base64.b64decode(result['body']))['result']['tools']
        self.assertEqual(tools,[{'name':'android_notification_list'}])
        self.assertEqual(request.call_args.args[0].full_url,'http://127.0.0.1:8080/mcp')

    def test_disallowed_remote_action_never_reaches_phone(self):
        with patch('api_mcp_relay.urllib.request.urlopen',side_effect=AssertionError('must not reach phone')):
            result=self.relay.forward(self.job('tools/call',{'name':'android_tap','arguments':{'x':1,'y':2}}))
        self.assertIn('allowlist',json.loads(base64.b64decode(result['body']))['error']['message'])

    def test_gzip_request_is_read_before_forwarding(self):
        import gzip
        job=self.job('tools/list');job['body']=base64.b64encode(gzip.compress(base64.b64decode(job['body']))).decode()
        job['headers']['content-encoding']='gzip'
        with patch('api_mcp_relay.urllib.request.urlopen',return_value=Reply(b'{"result":{"tools":[]}}')) as request:
            self.relay.forward(job)
        self.assertEqual(json.loads(request.call_args.args[0].data)['method'],'tools/list')

    def test_worker_round_trip_and_cancel_without_cloud_access(self):
        worker=Path(__file__).with_name('api_mcp_relay.js').read_text()
        worker=worker.replace("import { DurableObject } from 'cloudflare:workers';",
            'class DurableObject { constructor(ctx,env) { this.ctx=ctx; this.env=env; } }')
        encoded=base64.b64encode(worker.encode()).decode()
        script="""
import {webcrypto} from 'node:crypto';
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
const {McpBridge}=await import('data:text/javascript;base64,ENCODED');
const b=new McpBridge({}, {CLIENT_TOKEN:'client',BRIDGE_TOKEN:'phone'});
const req=(path,token,body)=>new Request('https://test'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token},body:body?JSON.stringify(body):undefined});
if((await b.fetch(req('/bridge/poll?client=bad','client'))).status!==401) throw Error('roles mixed');
const pending=b.fetch(req('/mcp','client',{jsonrpc:'2.0',id:1,method:'tools/list'}));
const job=await (await b.fetch(req('/bridge/poll?client=phone','phone'))).json();
if(JSON.parse(atob(job.body)).method!=='tools/list') throw Error('request changed');
await b.fetch(req('/bridge/result','phone',{id:job.id,status:200,body:btoa('{"ok":true}'),headers:{'Content-Type':'application/json'}}));
if(!(await (await pending).json()).ok) throw Error('response changed');
const waiting=b.fetch(req('/bridge/poll?client=close','phone'));
await b.fetch(req('/bridge/cancel?client=close','phone',{}));
if((await waiting).status!==204 || b.pending.size || b.polls.size) throw Error('pending job leaked');
console.log('relay round trip passed');
""".replace('ENCODED',encoded)
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('round trip passed',result.stdout)


if __name__=='__main__':unittest.main()
