#!/usr/bin/env python3
"""Deploy the optional private MCP relay with existing Cloudflare credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.request

from api_tools_config import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',required=True)
    parser.add_argument('--worker',default='interaction-harness-mcp-api-tools')
    parser.add_argument('--token-file',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args();state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    headers={'Authorization':'Bearer '+args.token_file.read_text().strip(),'User-Agent':'InteractionHarness/1.0'}
    base='https://api.cloudflare.com/client/v4/accounts/'+args.account+'/workers'
    def call(path,method='GET',body=None,content_type='application/json'):
        request=urllib.request.Request(base+path,data=body,headers={**headers,'Content-Type':content_type},method=method)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request,timeout=30) as response:return json.loads(response.read())
            except urllib.error.HTTPError:raise
            except (urllib.error.URLError,TimeoutError):
                if attempt==2:raise
                time.sleep(attempt+1)
    subdomain=call('/subdomain')['result']['subdomain']
    existed=False
    try:
        call('/scripts/'+args.worker+'/settings');existed=True
    except urllib.error.HTTPError as exc:
        if exc.code!=404:raise
    record=state/'deployment.json'
    pending=state/'deployment-pending.json'
    owned=record if record.exists() else pending
    if existed and (not owned.exists() or json.loads(owned.read_text()).get('worker')!=args.worker):
        raise SystemExit('An existing Worker has this name; it was not overwritten.')
    for name in ('client-token','bridge-token'):
        path=state/name
        if not path.exists():path.write_text(secrets.token_urlsafe(48));path.chmod(0o600)
    metadata={'main_module':'relay.js','compatibility_date':'2025-01-01','bindings':[
        {'type':'durable_object_namespace','name':'BRIDGE','class_name':'McpBridge'},
        {'type':'secret_text','name':'CLIENT_TOKEN','text':(state/'client-token').read_text()},
        {'type':'secret_text','name':'BRIDGE_TOKEN','text':(state/'bridge-token').read_text()}]}
    if not existed:metadata['migrations']={'new_tag':'v1','new_sqlite_classes':['McpBridge']}
    code=Path(__file__).with_name('api_mcp_relay.js').read_bytes()
    write_json(pending,{'worker':args.worker,'account':args.account,'sha256':hashlib.sha256(code).hexdigest()})
    boundary='harness-'+secrets.token_hex(12);parts=[]
    for name,filename,mime,data in [('metadata',None,'application/json',json.dumps(metadata).encode()),
                                    ('relay.js','relay.js','application/javascript+module',code)]:
        disposition='form-data; name="'+name+'"'+('; filename="'+filename+'"' if filename else '')
        parts.append(('--'+boundary+'\r\nContent-Disposition: '+disposition+'\r\nContent-Type: '+mime+'\r\n\r\n').encode()+data+b'\r\n')
    body=b''.join(parts)+('--'+boundary+'--\r\n').encode()
    result=call('/scripts/'+args.worker,'PUT',body,'multipart/form-data; boundary='+boundary)
    if not result.get('success'):raise SystemExit('Worker upload failed: '+json.dumps(result.get('errors')))
    result=call('/scripts/'+args.worker+'/subdomain','POST',json.dumps({'enabled':True,'previews_enabled':False}).encode())
    if not result.get('success'):raise SystemExit('Worker address activation failed: '+json.dumps(result.get('errors')))
    url='https://'+args.worker+'.'+subdomain+'.workers.dev'
    write_json(record,{'account':args.account,'worker':args.worker,'url':url,'sha256':hashlib.sha256(code).hexdigest(),'deployed_utc':datetime.now(timezone.utc).isoformat()})
    write_json(state/'options.json',{'mcp_url':url+'/mcp','mcp_token_file':str(state/'client-token'),
        'mcp_bridge_url':url,'mcp_bridge_token_file':str(state/'bridge-token'),
        'mcp_allowed_tools':['android_notification_list']})
    print('Private MCP relay deployed: '+url)


if __name__=='__main__':raise SystemExit(main())
