"""Provider tool loops. Final text still returns through harness.py's four-field gate."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile
import time
import urllib.request
import uuid

from attachments import materialize, check_request_size
from execution_images import prepare_execution
from api_tools_config import provider_tools, canonical, cache_history, write_json

ROOT=Path(__file__).resolve().parent
LOCAL_MCP='http://127.0.0.1:8080/mcp'


def mcp_catalog(state):
    path=Path(state)/'mcp-catalog.json'
    if path.exists():return json.loads(path.read_text())
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',
             'Authorization':'Bearer '+os.environ.get('AGENTBRIDGE_TOKEN','agentbridge-mcp')}
    def call(method,params=None):
        req=urllib.request.Request(LOCAL_MCP,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),headers)
        with urllib.request.urlopen(req,timeout=20) as response:
            if response.headers.get('mcp-session-id'):headers['mcp-session-id']=response.headers['mcp-session-id']
            text=response.read().decode()
            if text.startswith(('event:','data:')):text='\n'.join(line[6:] for line in text.splitlines() if line.startswith('data: '))
            return json.loads(text)
    call('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'interaction-harness','version':'1'}})
    result=call('tools/list')
    catalog=result.get('result',{}).get('tools')
    if not isinstance(catalog,list):raise ValueError('The phone MCP server returned no tool list.')
    write_json(path,catalog);return catalog


def block_data(value):
    if hasattr(value,'model_dump'):return value.model_dump(exclude_none=True,by_alias=True,warnings=False)
    from senses import dump
    return dump(value)


class Runtime:
    def __init__(self,settings,executor=None,*,execute=False,auto_confirm=False,exec_timeout=120,session_id=None):
        self.settings=settings;self.engine=settings.engine;self.state=settings.state
        self.executor=executor;self.execute=execute;self.auto_confirm=auto_confirm;self.exec_timeout=exec_timeout
        self.session_id=session_id;self.workdir=os.environ.get('HARNESS_CALLER_CWD',os.getcwd())
        self.receipts=[];self.seen=set();self.compacted=None;self.prepared=False;self.transcript=[]
        self.catalog=mcp_catalog(self.state) if settings.on('mcp_local') else []
        self.options=settings.options;self.tools=None;self.container=None
        self.max_steps=int(self.options['max_tool_steps'])
        self.bridge=None
        self.downloaded=set();self.announced=set()
        if not 1<=self.max_steps<=200:raise ValueError('max_tool_steps must be 1–200.')

    def record(self,tool,ident,status='success',**fields):
        key=(tool,str(ident),status)
        if key not in self.seen:
            self.seen.add(key);self.receipts.append({'tool':tool,'id':str(ident),'status':status,**fields})
            if status=='success' and getattr(self,'model',None):self.settings.available(tool,self.model)

    def metadata(self):
        result={'api_tool_uses':copy.deepcopy(self.receipts),
                'api_tools_sha256':hashlib.sha256(canonical(self.tools or []).encode()).hexdigest()}
        if self.compacted:result['api_context']=copy.deepcopy(self.compacted)
        return result

    def api_error(self,exc):
        error=json.dumps(getattr(exc,'body',None),ensure_ascii=False) if getattr(exc,'body',None) else str(exc)
        candidates=[n for n,on in self.settings.enabled.items() if on and n not in ('web_search','web_fetch','history_cache')]
        import re
        refusal=r'(?:model.{0,100}(?:does not support|cannot use|not support).{0,80}tool|tool.{0,80}(?:unavailable|not supported).{0,80}model|(?:account|organization).{0,80}(?:not enabled|not permitted|do not have access|not available))'
        if len(candidates)==1 and re.search(refusal,error,re.I):
            self.settings.unavailable(candidates[0],self.model,error)
        self.record('api_error',str(len(self.receipts)),'failed',error=error)

    def close(self):
        if self.bridge:self.bridge.close();self.bridge=None

    def artifact_notice(self):
        files=[r['artifact'] for r in self.receipts if r.get('artifact') and r['artifact'] not in self.announced]
        if not files:return None
        self.announced.update(files)
        return ('The client saved these completed tool outputs on the phone: '+json.dumps(files)+
                '. Return the final four-field reply and include the saved paths in direct_answer. Do not rerun completed tools.')

    def repair(self,response,reason):
        text='The local gate rejected the final reply: '+reason+' Return a corrected four-field reply using the recorded results.'
        if self.engine=='openai':return [*self.replay,*block_data(response).get('output',[]),{'role':'user','content':text}]
        content=block_data(response.content)
        emits=[b for b in content if b.get('type')=='tool_use' and b.get('name')=='emit_reply']
        if emits:
            return [*self.replay,{'role':'assistant','content':content},
                    {'role':'user','content':[{'type':'tool_result','tool_use_id':emits[0]['id'],'is_error':True,'content':text}]}]
        return [*self.replay,{'role':'assistant','content':content},{'role':'user','content':text}]

    @property
    def work_receipts(self):
        return [r for r in self.receipts if r['status'] in ('success','failed') and r['tool']!='mcp_approval' and
                ('execution' in r or r['tool'] in ('code_execution','hosted_shell','image_generation','files','mcp_remote'))]

    @property
    def has_work(self):return bool(self.work_receipts)

    @property
    def successful_work(self):
        records=self.work_receipts
        if not records:return False
        last=records[-1];execution=last.get('execution')
        return last['status']=='success' and (execution is None or execution.get('approved') is True and
            execution.get('exit_code')==0 and not execution.get('timed_out'))

    def run_command(self,tool,ident,command,inputs=None):
        if not self.execute or self.executor is None:
            result={'approved':False,'exit_code':1,'stdout':'','stderr':'Client API tools require --loop or --exec.'}
        else:
            request={'op':'exec','command':command,'timeout':self.exec_timeout}
            if self.auto_confirm:request['auto_confirm']=True
            result=self.executor(request)
            result=prepare_execution(result,self.engine,self.state)
        status='success' if result.get('approved') and result.get('exit_code')==0 and not result.get('attachment_errors') else 'failed'
        self.record(tool,ident,status,command=command,input=inputs or {},execution=result)
        return result

    def job(self,tool,ident,kind,args=None,**fields):
        folder=self.state/'tool-jobs';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd,name=tempfile.mkstemp(suffix='.json',dir=folder)
        data={'kind':kind,'state':str(self.state),'workdir':self.workdir,'args':args or {},**fields}
        with os.fdopen(fd,'w') as stream:json.dump(data,stream)
        command=shlex.join(['/data/data/com.termux/files/usr/bin/python',str(ROOT/'api_tools_native.py'),name])
        try:return self.run_command(tool,ident,command,data)
        finally:Path(name).unlink(missing_ok=True)

    def result_blocks(self,result,engine=None):
        engine=engine or self.engine
        text=json.dumps({k:v for k,v in result.items() if k!='attachments'},ensure_ascii=False)
        message={'role':'user','content':text,'attachments':result.get('attachments',[])}
        prepared=materialize([message],engine)[0]['content']
        if isinstance(prepared,str):prepared=[{'type':'input_text' if engine=='openai' else 'text','text':prepared}]
        return prepared

    def dispatch(self,name,args,ident,toolset=None):
        if toolset and not self.settings.on(toolset):raise ValueError('The requested toolset is switched off.')
        if toolset=='computer':
            return self.job('computer',ident,'computer',target=self.options['computer_target'],actions=[{'name':name,'input':args}])
        if toolset=='browser':
            return self.job('browser',ident,'browser',args,name=name,endpoint=self.options['browser_endpoint'])
        if name.startswith('phone__'):
            if not self.settings.on('mcp_local'):raise ValueError('Local MCP is switched off.')
            raw=name[len('phone__'):]
            if raw not in {t['name'] for t in self.catalog}:raise ValueError('MCP tool was not in the pinned catalog.')
            command=shlex.join([str(Path('/data/data/com.termux/files/home/.local/bin/agentbridge-call')),raw,json.dumps(args,ensure_ascii=False)])
            return self.run_command('mcp_local',ident,command,args)
        if name in ('harness_command','local_command','bash'):
            tool={'harness_command':'functions','local_command':'custom_tools','bash':'shell'}[name]
            if not self.settings.on(tool):raise ValueError(tool+' is switched off.')
            if args.get('restart'):return {'approved':True,'exit_code':0,'stdout':'Each shell command starts a fresh shell.','stderr':''}
            return self.run_command(tool,ident,args['command'],args)
        if name=='memory' and self.settings.on('memory'):return self.job('memory',ident,'memory',args)
        if name=='str_replace_based_edit_tool' and self.settings.on('text_editor'):return self.job('text_editor',ident,'text_editor',args)
        raise ValueError('No client handler for '+str(name)+'.')

    def observe(self,response):
        data=block_data(response);uid=data.get('id','response')
        if self.engine=='openai':
            mapping={'code_interpreter_call':'code_execution','file_search_call':'file_search','image_generation_call':'image_generation',
                     'tool_search_call':'tool_search','program_output':'programmatic','mcp_call':'mcp_remote','mcp_list_tools':'mcp_discovery'}
            for index,block in enumerate(data.get('output',[])):
                kind=block.get('type');ident=block.get('id') or block.get('call_id') or uid+':'+str(index)
                if kind in mapping:
                    error=block.get('error');status='failed' if error or block.get('status') in ('failed','incomplete') else 'success'
                    fields={k:v for k,v in block.items() if k not in ('result','encrypted_content','content','output')}
                    if kind=='mcp_call' and 'output' in block:fields['output']=block['output']
                    self.record(mapping[kind],ident,status,response_id=uid,provider=fields)
                    if kind=='image_generation_call' and block.get('result'):
                        folder=self.state/'generated';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                        mime=block.get('output_format','png');path=folder/(re_safe(ident)+'.'+mime)
                        path.write_bytes(base64.b64decode(block['result']))
                        self.receipts[-1]['artifact']=str(path)
                elif kind=='shell_call' and self.settings.on('hosted_shell'):
                    self.record('hosted_shell',block.get('call_id',ident),'requested',response_id=uid,provider=block)
                elif kind=='shell_call_output' and self.settings.on('hosted_shell'):
                    code_ok=all(x.get('outcome',{}).get('type')=='exit' and x['outcome'].get('exit_code')==0 for x in block.get('output',[]))
                    call_id=block.get('call_id',ident)
                    self.record('hosted_shell',call_id,'success' if code_ok else 'failed',response_id=uid,provider=block)
                    if code_ok and self.settings.on('skills') and any(r['id']==call_id and 'SKILL.md' in json.dumps(r.get('provider',{})) for r in self.receipts):
                        self.record('skills',call_id,'success',response_id=uid)
                elif kind=='compaction':self.record('compaction',ident,response_id=uid)
        else:
            mapping={'code_execution':'code_execution','bash_code_execution':'code_execution','text_editor_code_execution':'code_execution',
                     'tool_search_tool_regex':'tool_search','tool_search_tool_bm25':'tool_search','advisor':'advisor'}
            for block in data.get('content',[]):
                kind=block.get('type');ident=block.get('id') or block.get('tool_use_id') or uid
                if kind=='server_tool_use' and block.get('name') in mapping:
                    self.record(mapping[block['name']],ident,'requested',response_id=uid,input=block.get('input',{}))
                elif kind and kind.endswith('_tool_result') and kind not in ('web_search_tool_result','web_fetch_tool_result'):
                    tool=next((r['tool'] for r in self.receipts if r['id']==ident),None)
                    if kind=='mcp_tool_result':tool='mcp_remote'
                    content=block.get('content',{})
                    error=block.get('is_error') or isinstance(content,dict) and ('error' in str(content.get('type','')) or content.get('error_code') or content.get('return_code',0)!=0)
                    if tool:self.record(tool,ident,'failed' if error else 'success',response_id=uid,provider=block)
                    if not error and self.settings.on('skills') and any(r['id']==ident and 'SKILL.md' in json.dumps(r.get('input',{})) for r in self.receipts):
                        self.record('skills',ident,'success',response_id=uid)
                elif kind=='mcp_tool_use':self.record('mcp_remote',ident,'requested',response_id=uid,input=block.get('input',{}))
                caller=block.get('caller',{})
                if caller.get('type','').startswith('code_execution_'):self.record('programmatic',ident,'success',response_id=uid,caller=caller)
            if data.get('container'):self.container=data['container'].get('id')
            if data.get('context_management'):self.record('context_editing',uid,provider=data['context_management'])

    def prepare(self,client,messages,system_pages):
        from api_tools_resources import prepare_files, compact_messages
        prepared=prepare_files(self,client,messages) if self.settings.on('files') else materialize(messages,self.engine)
        if self.settings.on('compaction'):
            prepared=compact_messages(self,client,prepared,system_pages)
        if self.settings.on('memory') and not self.prepared:
            result=self.job('memory','memory-at-start','memory',{'command':'view','path':'/memories'})
            prepared.append({'role':'user','content':'Client memory folder check: '+json.dumps(result,ensure_ascii=False)})
        self.prepared=True
        return prepared

    def send(self,senses,client,*,model,effort,max_output_tokens,messages,system_pages,schema,prefix_hash,system_blocks=None,knobs=None):
        from senses import CONTRACT, SensesError
        knobs=knobs or {}
        if self.settings.on('mcp_remote') and self.options['mcp_bridge_url'] and not self.bridge:
            from api_mcp_relay import PhoneRelay
            self.bridge=PhoneRelay(self.options['mcp_bridge_url'],self.options['mcp_bridge_token_file'],
                self.options['mcp_allowed_tools'],self.state/'mcp-relay.jsonl').start()
        self.model=model;self.tools=provider_tools(self.settings,senses.tools,self.catalog)
        prepared=self.prepare(client,messages,system_pages)
        senses.last_usage={};senses.last_responses=[];senses.paused_content=[]
        if self.engine=='openai':
            params=dict(model=model,input=prepared,reasoning={'effort':effort},max_output_tokens=max_output_tokens,
                text={'format':{'type':'json_schema','name':'interaction_reply','strict':True,'schema':schema}},
                prompt_cache_key='interaction-harness-'+prefix_hash[:24],store=self.settings.on('background'),
                instructions=CONTRACT,tools=copy.deepcopy(self.tools),include=['reasoning.encrypted_content'])
            if senses.web:params['include'].append('web_search_call.action.sources')
            if self.settings.on('background'):params['background']=True
            if self.settings.on('file_search'):params['include'].append('file_search_call.results')
            if self.settings.on('mcp_remote') and self.options['mcp_token_file']:
                token=Path(self.options['mcp_token_file']).read_text().strip()
                for tool in params['tools']:
                    if tool['type']=='mcp':tool['headers']={'Authorization':'Bearer '+token}
        else:
            params=dict(model=model,max_tokens=max_output_tokens,thinking={'type':'adaptive'},output_config={'effort':effort},
                system=copy.deepcopy(system_blocks),messages=prepared[len(system_pages):],tools=copy.deepcopy(self.tools),
                tool_choice={'type':'auto','disable_parallel_tool_use':True})
            if self.settings.on('programmatic'):params['tool_choice']={'type':'auto'}
            cache_history(params,self.settings.on('history_cache'))
            from stamp import cache_before_stamp;cache_before_stamp(params)  # the marker goes before the rules stamp
            betas=[]
            if self.compacted:betas.append('compact-2026-09-04')
            if self.settings.on('context_editing'):
                betas.append('context-management-2025-06-27')
                params['context_management']={'edits':[{'type':'clear_tool_uses_20250919','trigger':{'type':'input_tokens','value':int(self.options['compaction_threshold'])},'keep':{'type':'tool_uses','value':1}}]}
            if self.settings.on('advisor'):betas.append('advisor-tool-2026-03-01')
            if self.settings.on('mcp_remote'):
                betas.append('mcp-client-2025-11-20')
                server={'type':'url','name':'phone','url':self.options['mcp_url']}
                if self.options['mcp_token_file']:server['authorization_token']=Path(self.options['mcp_token_file']).read_text().strip()
                params['mcp_servers']=[server]
            if betas:params['betas']=betas
            if self.settings.on('skills'):
                if not self.options['anthropic_skills']:raise ValueError('Configure versioned anthropic_skills in tools.json options.')
                params['container']={'skills':copy.deepcopy(self.options['anthropic_skills'])}
        if knobs:params.update(knobs)
        for step in range(self.max_steps):
            check_request_size(params,self.engine)
            if self.engine=='openai':
                from openai_transport import complete_response
                response=complete_response(client.responses,**params)
                if self.settings.on('background'):
                    initial=response.status;deadline=time.monotonic()+1800
                    try:
                        while response.status in ('queued','in_progress'):
                            if time.monotonic()>deadline:raise SensesError('Background response timed out.')
                            time.sleep(0.5);response=client.responses.retrieve(response.id)
                    except BaseException:
                        client.responses.cancel(response.id);raise
                    self.record('background',response.id,'success' if response.status=='completed' else 'failed',initial_status=initial,final_status=response.status)
            else:
                endpoint=client.beta.messages if 'betas' in params else client.messages
                from anthropic_transport import complete_message
                response=complete_message(endpoint,**params)
            senses.observe(response);self.observe(response)
            from api_tools_resources import fetch_output_files
            fetch_output_files(self,client,response)
            if senses.errors:raise SensesError(senses.errors[0])
            if self.engine=='openai':
                output=block_data(response).get('output',[]);feedback=[]
                for block in output:
                    kind=block.get('type');ident=block.get('call_id') or block.get('id')
                    if kind=='function_call':
                        args=json.loads(block['arguments']);result=self.dispatch(block['name'],args,ident)
                        if block.get('namespace'):
                            self.record('namespaces',ident,'success' if result.get('approved') and result.get('exit_code')==0 else 'failed',namespace=block['namespace'],execution=result)
                        item={'type':'function_call_output','call_id':ident,'output':json.dumps(result,ensure_ascii=False)}
                        if block.get('caller'):item['caller']=block['caller']
                        feedback.append(item)
                    elif kind=='custom_tool_call':
                        result=self.dispatch(block['name'],{'command':block['input']},ident)
                        item={'type':'custom_tool_call_output','call_id':ident,'output':json.dumps(result,ensure_ascii=False)}
                        if block.get('caller'):item['caller']=block['caller']
                        feedback.append(item)
                    elif kind in ('shell_call','local_shell_call') and not self.settings.on('hosted_shell'):
                        outputs=[]
                        for index,command in enumerate(block['action']['commands']):
                            result=self.run_command('shell',str(ident)+':'+str(index),command,block['action'])
                            outcome={'type':'timeout'} if result.get('timed_out') else {'type':'exit','exit_code':result.get('exit_code',1)}
                            outputs.append({'stdout':result.get('stdout',''),'stderr':result.get('stderr',''),'outcome':outcome})
                        item={'type':'shell_call_output','call_id':ident,'output':outputs}
                        if block.get('caller'):item['caller']=block['caller']
                        feedback.append(item)
                    elif kind=='apply_patch_call':
                        result=self.job('apply_patch',ident,'apply_patch',block['operation'])
                        item={'type':'apply_patch_call_output','call_id':ident,'status':'completed' if result.get('exit_code')==0 else 'failed','output':json.dumps(result)}
                        if block.get('caller'):item['caller']=block['caller']
                        feedback.append(item)
                    elif kind=='computer_call':
                        result=self.job('computer',ident,'computer',target=self.options['computer_target'],actions=block['actions'],final_screenshot=True)
                        images=[b for b in self.result_blocks(result) if b['type']=='input_image']
                        if not images:raise SensesError('Computer action returned no screenshot: '+result.get('stderr',''))
                        feedback.append({'type':'computer_call_output','call_id':ident,'output':{'type':'computer_screenshot','image_url':images[-1]['image_url'],'detail':'original'}})
                        if result.get('exit_code')!=0:
                            feedback.append({'role':'user','content':'Computer action failed; the screenshot shows the resulting state. '+result.get('stdout','')+' '+result.get('stderr','')})
                    elif kind=='mcp_approval_request':
                        command='printf %s '+shlex.quote('Remote MCP request: '+block.get('name','')+' '+block.get('arguments',''))
                        result=self.run_command('mcp_approval',ident,command)
                        feedback.append({'type':'mcp_approval_response','approval_request_id':block['id'],'approve':result.get('approved') is True})
                if not feedback:
                    notice=self.artifact_notice()
                    if notice:
                        params['input'] += [{'role':'assistant','content':response.output_text or 'The tool outputs are recorded.'},{'role':'user','content':notice}]
                        continue
                    self.replay=params['input'];return response
                params['input']=[*params['input'],*output,*feedback]
            else:
                content=block_data(response.content);feedback=[]
                for block in content:
                    if block.get('type')!='tool_use' or block.get('name')=='emit_reply':continue
                    name=block['name'];ident=block['id'];toolset=block.get('toolset_name')
                    result=self.dispatch(name,block.get('input',{}),ident,toolset)
                    output=self.result_blocks(result)
                    if toolset=='browser' and result.get('exit_code')==0:
                        try:
                            browser_state=json.loads(result['stdout']).get('browser_state')
                            if browser_state:
                                if name in ('list_tabs','new_tab','switch_tab','close_tab'):output=[browser_state]
                                else:output.append(browser_state)
                        except ValueError:pass
                    item={'type':'tool_result','tool_use_id':ident,'content':output,'is_error':result.get('exit_code',1)!=0 or not result.get('approved')}
                    if toolset:item['toolset_name']=toolset
                    feedback.append(item)
                if feedback:
                    for block in content:
                        if block.get('type')=='tool_use' and block.get('name')=='emit_reply':
                            feedback.append({'type':'tool_result','tool_use_id':block['id'],'is_error':True,
                                             'content':'Wait for the other tool results, then return the final four-field reply.'})
                if not feedback and response.stop_reason!='pause_turn':
                    pending=set(senses.call_kinds)-senses.result_ids
                    if pending:raise SensesError('Claude returned a lookup without its result.')
                    notice=self.artifact_notice()
                    if notice:
                        emits=[b for b in content if b.get('type')=='tool_use' and b.get('name')=='emit_reply']
                        follow=[{'type':'tool_result','tool_use_id':b['id'],'is_error':True,'content':notice} for b in emits]
                        params['messages'] += [{'role':'assistant','content':content},{'role':'user','content':follow or notice}]
                        continue
                    self.replay=[*({'role':'system','content':p} for p in system_pages),*params['messages']]
                    return response
                assistant={'role':'assistant','content':content};params['messages'].append(assistant);senses.paused_content.append(assistant)
                if feedback:
                    message={'role':'user','content':feedback};params['messages'].append(message);senses.paused_content.append(message)
                if self.container and not self.settings.on('skills'):params['container']=self.container
        raise SensesError('API tool loop reached its configured step limit.')


def re_safe(value):
    import re
    return re.sub(r'[^a-zA-Z0-9_-]','_',str(value))[:120]
