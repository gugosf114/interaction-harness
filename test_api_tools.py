"""API switches, real request shapes with fake clients, claims and history caching."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import harness as h
import cli
import api_tools_cli as wiring
from api_tools_config import TOOLS, Settings, provider_tools, canonical, cache_history
from api_tools_runtime import Runtime
from api_tool_gate import violation
from api_tools_native import file_operation, bounded_path, patch_operation
from senses import tool_list
from test_harness import FakeClient, response, document
from test_senses import ac


def settings(root,engine,**flags):
    if engine=='openai' and ('web_search' in flags or 'web_fetch' in flags):
        value=flags.get('web_search',flags.get('web_fetch'));flags.update(web_search=value,web_fetch=value)
    return Settings(root,engine,{**{n:False for n in TOOLS},**flags},
        {'mcp_url':'https://mcp.example.test/mcp','vector_store_ids':['vs_test'],
         'openai_skills':[{'type':'skill_reference','skill_id':'skill_test','version':'1'}],
         'anthropic_skills':[{'type':'anthropic','skill_id':'pdf','version':'1'}]})


def execution(stdout='test\n',code=0,approved=True):
    return {'approved':approved,'exit_code':code,'stdout':stdout,'stderr':'','timed_out':False}


class ApiToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        self.state=patch.object(h,'STATE',self.root);self.state.start();self.addCleanup(self.state.stop)
        self.catalog=[{'name':'android_notification_list','description':'List notifications','inputSchema':{'type':'object','properties':{'limit':{'type':'integer'}}}}]

    def test_every_switch_on_off_and_stable_tool_bytes(self):
        for engine in ('openai','anthropic'):
            for name,(lanes,_,_,_) in TOOLS.items():
                with self.subTest(engine=engine,tool=name):
                    on=settings(self.root,engine,**{name:True})
                    self.assertEqual(on.on(name),engine in lanes)
                    before=canonical(provider_tools(on,tool_list(engine,h.api_schema(),False),self.catalog))
                    self.assertEqual(before,canonical(provider_tools(on,tool_list(engine,h.api_schema(),False),self.catalog)))
                    off=settings(self.root,engine,**{name:False});self.assertFalse(off.on(name))

    def test_unavailable_error_persists_and_lists_exact_text(self):
        config=settings(self.root,'openai',computer=True)
        error='This model does not support the computer tool.'
        config.unavailable('computer',h.DEFAULT_MODEL,error)
        self.assertIn('unavailable: '+error,Settings(self.root,'openai').listing(h.DEFAULT_MODEL))

    def test_named_claim_requires_current_successful_receipt(self):
        text='I used the memory tool to read the note.'
        self.assertIsNotNone(violation(text,[]))
        self.assertIsNone(violation(text,[{'tool':'memory','status':'success'}]))
        self.assertIsNotNone(violation(text,[{'tool':'memory','status':'failed'}]))
        self.assertIsNone(violation('I did not use the memory tool.',[]))
        self.assertIsNone(violation('The log says "I used the memory tool".',[]))

    def test_existing_local_tool_use_is_not_rejected_as_an_unrecorded_api_call(self):
        evidence={'tool':'native_command','command':'/home/user/agentbridge-call android_notification_list {}',
                  'execution':{'approved':True,'exit_code':0},'status':'success'}
        self.assertIsNone(violation('I used agentbridge-call to read the list.',[evidence]))
        evidence['command']='printf agentbridge-call'
        self.assertIsNotNone(violation('I used agentbridge-call to read the list.',[evidence]))

    def test_history_cache_uses_one_of_four_slots(self):
        params={'system':[{'type':'text','text':'a','cache_control':{'type':'ephemeral'}},
                          {'type':'text','text':'b','cache_control':{'type':'ephemeral'}}],
                'messages':[{'role':'user','content':'old'},{'role':'assistant','content':'answer'},{'role':'user','content':'new'}]}
        old=copy.deepcopy(params['messages']);cache_history(params)
        self.assertEqual(params['cache_control'],{'type':'ephemeral'});self.assertEqual(params['messages'],old)
        with self.assertRaises(ValueError):cache_history({'system':params['system']*2})
        self.assertNotIn('cache_control',cache_history({},False))

    def test_local_mcp_calls_real_wrapper_through_runner(self):
        config=settings(self.root,'openai',mcp_local=True)
        with patch('api_tools_runtime.mcp_catalog',return_value=self.catalog):runtime=Runtime(config,execute=True,executor=lambda request:execution('[]'))
        result=runtime.dispatch('phone__android_notification_list',{'limit':5},'call1')
        self.assertEqual(result['exit_code'],0)
        command=runtime.receipts[-1]['command'];self.assertIn('agentbridge-call',command);self.assertIn('android_notification_list',command)
        self.assertEqual(runtime.receipts[-1]['input'],{'limit':5})

    def test_memory_lives_in_own_state_and_rejects_escape(self):
        root=self.root/'memory'
        file_operation({'command':'create','path':'/memories/a.md','file_text':'amber note'},memory_root=root)
        self.assertIn('amber note',file_operation({'command':'view','path':'/memories/a.md'},memory_root=root))
        with self.assertRaises(ValueError):bounded_path(root,'/memories/../../outside')
        (root/'link').symlink_to(self.root)
        with self.assertRaises(ValueError):bounded_path(root,'/memories/link/outside')

    def test_memory_reads_at_start_and_writes_during_turn(self):
        config=settings(self.root,'anthropic',memory=True)
        def execute(request):
            import shlex
            job=json.loads(Path(shlex.split(request['command'])[-1]).read_text())
            return execution(json.dumps({'text':file_operation(job['args'],memory_root=self.root/'memory')}))
        runtime=Runtime(config,execute=True,executor=execute)
        first=ac();first.content=[NS(type='tool_use',id='write',name='memory',input={'command':'create','path':'/memories/proof.md','file_text':'gold marker'})]
        client=FakeClient([first,ac(answer='The note contains gold marker.')]);client.messages=client
        reply=h.request_reply('Save the note.',engine='anthropic',client=client,api_runtime=runtime,web=False,log_path=self.root/'usage')
        self.assertIn('gold marker',reply.direct_answer)
        self.assertEqual([r['input']['args']['command'] for r in runtime.receipts],['view','create'])
        self.assertEqual((self.root/'memory/proof.md').read_text(),'gold marker')

    def test_function_loop_both_engines_and_four_fields(self):
        for engine in ('openai','anthropic'):
            config=settings(self.root,engine,functions=True)
            runtime=Runtime(config,execute=True,executor=lambda req:execution('4919'))
            if engine=='openai':
                first=response('');first.output=[NS(type='function_call',call_id='call1',name='harness_command',arguments='{"command":"printf 4919"}')]
                last=response(document(direct_answer='The command returned 4919.'))
            else:
                first=ac();first.content=[NS(type='tool_use',id='call1',name='harness_command',input={'command':'printf 4919'})]
                last=ac(answer='The command returned 4919.')
            client=FakeClient([first,last]);client.messages=client
            reply=h.request_reply('Read the command output.',engine=engine,client=client,api_runtime=runtime,web=False,log_path=self.root/'usage')
            self.assertEqual(set(reply.model_dump()),{'intent','cleaned_input','direct_answer','execution_payload'})
            self.assertEqual(client.calls[0]['tools'],client.calls[1]['tools'])
            self.assertIn('4919',json.dumps(client.calls[1]))
            self.assertEqual(runtime.receipts[-1]['status'],'success')

    def test_disabled_tool_cannot_execute(self):
        runtime=Runtime(settings(self.root,'anthropic'),execute=True,executor=lambda _:self.fail('must not execute'))
        for name,args,toolset in [('memory',{'command':'view','path':'/memories'},None),('screenshot',{},'computer'),('harness_command',{'command':'echo x'},None)]:
            with self.assertRaises(ValueError):runtime.dispatch(name,args,'bad',toolset)

    def test_later_api_failure_cannot_borrow_an_earlier_success(self):
        runtime=Runtime(settings(self.root,'openai',functions=True))
        runtime.record('functions','old','success',execution=execution())
        runtime.record('functions','new','failed',execution=execution(code=1))
        self.assertFalse(runtime.successful_work)
        client=FakeClient([response(document(direct_answer='Done.')),response(document(direct_answer='The command failed.'))])
        reply=h.request_reply('Finish the job.',client=client,api_runtime=runtime,execution_confirmed=True,web=False,log_path=self.root/'usage')
        self.assertEqual(reply.direct_answer,'The command failed.')
        self.assertEqual(len(client.calls),2)

    def test_patch_exact_context_and_scope(self):
        file=self.root/'file.txt';file.write_text('red\nblue\n')
        patch_operation({'type':'update_file','path':'file.txt','diff':'@@\n red\n-blue\n+green\n'},self.root)
        self.assertEqual(file.read_text(),'red\ngreen\n')
        with self.assertRaises(ValueError):patch_operation({'type':'delete_file','path':'../no'},self.root)

    def test_chat_switch_persists_and_listing_needs_no_api(self):
        import argparse
        args=argparse.Namespace(engine='anthropic',no_web=False,computer_target=None)
        for name in TOOLS:setattr(args,'api_'+name,None)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(wiring.chat_command('/on memory',args,self.root,h.ANTHROPIC_MODEL))
            self.assertTrue(Settings(self.root,'anthropic').on('memory'))
            self.assertTrue(wiring.chat_command('/off memory',args,self.root,h.ANTHROPIC_MODEL))
            self.assertFalse(Settings(self.root,'anthropic').on('memory'))
            with patch.object(h,'request_reply',side_effect=AssertionError('No API allowed')):
                self.assertEqual(cli.main(['--tools']),0)

    def test_new_chat_questions_keep_the_previous_request_prefix(self):
        reply=h.validate_reply(document(direct_answer='Recorded.'))
        with patch.object(h,'request_reply',return_value=reply) as api,contextlib.redirect_stdout(io.StringIO()):
            for question in ('Remember apples.','Remember pears.','Name the first fruit.'):
                self.assertEqual(cli.main(['--loop','--session','cache-proof',question]),0)
        requests=[c.kwargs['history']+[{'role':'user','content':c.args[0]}] for c in api.call_args_list]
        for earlier,later in zip(requests,requests[1:]):self.assertEqual(earlier,later[:len(earlier)])

    def test_browser_tab_result_is_only_browser_state(self):
        config=settings(self.root,'anthropic',browser=True)
        runtime=Runtime(config,execute=True)
        state={'type':'browser_state','tabs':[]}
        first=ac();first.content=[NS(type='tool_use',id='tabs',name='list_tabs',toolset_name='browser',input={})]
        client=FakeClient([first,ac(answer='There are zero tabs.')]);client.messages=client
        with patch.object(runtime,'job',return_value=execution(json.dumps({'text':'OK','browser_state':state}))):
            h.request_reply('List tabs.',engine='anthropic',client=client,api_runtime=runtime,web=False,log_path=self.root/'usage')
        self.assertEqual(client.calls[1]['messages'][-1]['content'][0]['content'],[state])

    def test_programmatic_does_not_disable_parallel_calls(self):
        runtime=Runtime(settings(self.root,'anthropic',programmatic=True))
        client=FakeClient([ac(answer='The value is 4.')]);client.messages=client
        h.request_reply('Calculate.',engine='anthropic',client=client,api_runtime=runtime,web=False,log_path=self.root/'usage')
        self.assertEqual(client.calls[0]['tool_choice'],{'type':'auto'})

    def test_namespace_receipt_comes_from_actual_call(self):
        runtime=Runtime(settings(self.root,'openai',namespaces=True),execute=True,executor=lambda _:execution())
        first=response('');first.output=[NS(type='function_call',call_id='ns1',name='harness_command',namespace='local',arguments='{"command":"printf test"}')]
        client=FakeClient([first,response(document(direct_answer='The command returned test.'))])
        h.request_reply('Run it.',client=client,api_runtime=runtime,web=False,log_path=self.root/'usage')
        self.assertTrue(any(r['tool']=='namespaces' and r['namespace']=='local' for r in runtime.receipts))

    def test_chunked_mcp_request_and_size_bound(self):
        from api_mcp_tunnel import read_body
        self.assertEqual(read_body(io.BytesIO(b'4\r\ntest\r\n3\r\n123\r\n0\r\n\r\n'),{'Transfer-Encoding':'chunked'}),b'test123')
        with self.assertRaises(ValueError):read_body(io.BytesIO(b'4\r\ntest\r\n0\r\n\r\n'),{'Transfer-Encoding':'chunked'},3)
        self.assertEqual(read_body(io.BytesIO(b'hello'),{'Content-Length':'5'}),b'hello')

    def test_cli_rejects_a_tool_not_offered_on_the_lane(self):
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--engine','openai','--memory','Read a note.']),2)

    def test_computer_members_without_hardware_are_withheld(self):
        config=settings(self.root,'anthropic',computer=True)
        tools=provider_tools(config,tool_list('anthropic',h.api_schema(),False))
        computer=next(t for t in tools if t.get('type')=='computer_toolset_20260801')
        self.assertEqual(computer['configs'],{n:{'enabled':False} for n in ('right_click','middle_click','cursor_position')})

    def test_live_proof_accepts_only_the_exact_remote_notification_approval(self):
        from verify_tools import allowed
        import shlex
        for limit,expected in ((5,True),(50,False)):
            command='printf %s '+shlex.quote('Remote MCP request: android_notification_list '+json.dumps({'limit':limit}))
            self.assertEqual(allowed({'op':'exec','command':command},self.root,'marker'),expected)

    def test_mcp_discovery_and_approval_are_not_completed_work(self):
        runtime=Runtime(settings(self.root,'openai',mcp_remote=True),execute=True,executor=lambda _:execution())
        runtime.run_command('mcp_approval','approval','printf approved')
        reply=response('');reply.output=[NS(type='mcp_list_tools',id='listing',tools=[])]
        runtime.observe(reply)
        self.assertFalse(runtime.has_work)
        self.assertFalse(any(r['tool']=='mcp_remote' for r in runtime.receipts))
        reply.output=[NS(type='mcp_call',id='call',status='completed',output='[]')]
        runtime.observe(reply)
        self.assertTrue(runtime.successful_work)
        reply.output=[NS(type='mcp_call',id='failed-call',status='failed',error='offline')]
        runtime.observe(reply)
        self.assertFalse(runtime.successful_work)

    def test_extended_tools_reject_an_unfinished_web_lookup(self):
        runtime=Runtime(settings(self.root,'anthropic',web_search=True,functions=True))
        reply=ac(answer='The page says hello.')
        reply.content.insert(0,NS(type='server_tool_use',id='missing',name='web_search',input={'query':'hello'}))
        client=FakeClient([reply]);client.messages=client
        with self.assertRaisesRegex(h.HarnessError,'lookup without its result'):
            h.request_reply('Search hello.',engine='anthropic',client=client,api_runtime=runtime,web=True,log_path=self.root/'usage')

    def test_provider_output_files_are_saved_hashed_and_announced_once(self):
        from api_tools_resources import fetch_output_files
        import hashlib
        content=NS(write_to_file=lambda path:path.write_bytes(b'proof output'))
        files=NS(retrieve_metadata=lambda ident:NS(filename='../proof.txt'),download=lambda ident:content)
        client=NS(files=files,containers=NS(files=NS(content=NS(retrieve=lambda ident,container_id:content))))
        for engine in ('openai','anthropic'):
            with self.subTest(engine=engine):
                runtime=Runtime(settings(self.root/engine,engine,files=True))
                block={'type':'container_file_citation','file_id':'file_proof','container_id':'cntr_proof','filename':'../proof.txt'} if engine=='openai' else {'type':'bash_code_execution_output','file_id':'file_proof'}
                reply=NS(output=[block]) if engine=='openai' else NS(content=[block])
                fetch_output_files(runtime,client,reply)
                record=runtime.receipts[-1];path=Path(record['artifact'])
                self.assertEqual(path.read_bytes(),b'proof output')
                self.assertEqual(record['sha256'],hashlib.sha256(b'proof output').hexdigest())
                self.assertTrue(path.is_relative_to(runtime.state/'downloads'))
                self.assertIn(str(path),runtime.artifact_notice())
                self.assertIsNone(runtime.artifact_notice())
                fetch_output_files(runtime,client,reply)
                self.assertEqual(len(runtime.receipts),1)


if __name__=='__main__':unittest.main()
