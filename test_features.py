"""Behavior checks for both engines, sessions, storage, STT, lint and native hooks."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import harness as h
import cli
import native_tools
from phonetics import normalize
from storage import Store, history_messages
from test_harness import FakeClient, response, document


def reply(**kw): return h.validate_reply(document(**kw))


class Features(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.state=self.root/'state'
        self.state_patch=patch.object(h,'STATE',self.state); self.state_patch.start()
        self.env_patch=patch.dict(os.environ,{'DEFAULT_ENGINE':'openai'},clear=False); self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop(); self.state_patch.stop(); self.tmp.cleanup()

    def call(self,args,answer=None,error=None):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(h,'request_reply',return_value=answer or reply(),side_effect=error) as api:
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): code=h.main(args)
        return code,out.getvalue(),err.getvalue(),api

    def rows(self):
        db=sqlite3.connect(self.state/'history.db')
        try:
            db.row_factory=sqlite3.Row; return [dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
        finally: db.close()

    def test_four_phonetic_mappings(self):
        self.assertEqual(normalize('NC about AIPG; read the redmi in term units.'),'antsy about AIGP; read the README in Termux.')

    def test_phonetic_boundaries(self):
        self.assertEqual(normalize('DANCE nc connection redmiology'),'DANCE nc connection redmiology')

    def test_literal_paths_quotes_code_not_changed(self):
        text='"NC" `AIPG` /home/redmi https://example.com/redmi \'term units\''
        self.assertEqual(normalize(text),text)

    def test_normalized_input_sent_and_raw_input_saved(self):
        _,_,_,api=self.call(['Read the redmi in term units.'])
        self.assertEqual(api.call_args.args[0],'Read the README in Termux.')
        self.assertEqual(self.rows()[0]['raw_input'],'Read the redmi in term units.')

    def test_no_normalize_preserves_exact_input(self):
        _,_,_,api=self.call(['--no-normalize','redmi NC'])
        self.assertEqual(api.call_args.args[0],'redmi NC')

    def test_default_new_does_not_send_previous_turn(self):
        self.call(['first'])
        _,_,_,api=self.call(['second'])
        self.assertEqual(api.call_args.kwargs['history'],[])
        self.assertNotEqual(self.rows()[0]['session_id'],self.rows()[1]['session_id'])

    def test_continue_sends_previous_exchange(self):
        self.call(['first'])
        _,_,_,api=self.call(['-c','second'])
        self.assertEqual(len(api.call_args.kwargs['history']),2)
        self.assertEqual(self.rows()[0]['session_id'],self.rows()[1]['session_id'])

    def test_named_sessions_are_separate(self):
        self.call(['--session','alpha','first'])
        self.call(['--session','beta','different'])
        _,_,_,api=self.call(['--session','alpha','second'])
        self.assertEqual(api.call_args.kwargs['history'][0]['content'],'first')

    def test_session_keeps_six_exchanges_database_keeps_all(self):
        for i in range(8): self.call(['--session','rolling','--turns','6',f'turn {i}'])
        data=json.loads((self.state/'sessions/rolling.json').read_text())
        self.assertEqual(len(data['turns']),6)
        self.assertEqual(data['turns'][0]['raw_input'],'turn 2')
        self.assertEqual(len(self.rows()),8)

    def test_custom_turn_limit(self):
        for i in range(4): self.call(['--session','small','--turns','2',str(i)])
        self.assertEqual(len(json.loads((self.state/'sessions/small.json').read_text())['turns']),2)

    def test_history_budget_keeps_whole_exchanges(self):
        exchanges=[{'normalized_input':'x'*20,'reply':reply().model_dump()} for _ in range(6)]
        self.assertEqual(history_messages(exchanges,10),[])
        result=history_messages(exchanges,600)
        self.assertEqual(len(result)%2,0)
        self.assertLessEqual(sum(len(m['content']) for m in result),600)

    def test_session_path_traversal_is_rejected(self):
        code,out,err,_=self.call(['--session','../../escape','hello'])
        self.assertEqual(code,2); self.assertEqual(out,''); self.assertIn('Session names',err)

    def test_continue_without_session_is_clear(self):
        code,out,err,_=self.call(['-c','hello'])
        self.assertEqual(code,2); self.assertEqual(out,''); self.assertIn('No previous session',err)

    def test_api_failure_logged_without_assistant_turn(self):
        code,out,err,_=self.call(['--session','fail','hello'],error=h.HarnessError('API test failure.'))
        self.assertEqual(code,2); self.assertEqual(out,'')
        self.assertEqual(self.rows()[0]['status'],'error')
        self.assertFalse((self.state/'sessions/fail.json').exists())

    def test_recall_uses_no_api_and_only_displays_answer(self):
        self.call(['--session','saved','remember unicorn solution'])
        code,out,err,api=self.call(['--recall','unicorn'])
        self.assertEqual(code,0); self.assertEqual(out,reply().direct_answer+'\n'); api.assert_not_called()

    def test_recall_quotes_cannot_execute_sql(self):
        self.call(['hello'])
        code,_,_,_=self.call(['--recall','"; DROP TABLE history; --'])
        self.assertEqual(code,0); self.assertEqual(len(self.rows()),1)

    def test_database_permissions(self):
        self.call(['hello'])
        self.assertEqual((self.state/'history.db').stat().st_mode&0o777,0o600)
        self.assertEqual(self.state.stat().st_mode&0o777,0o700)

    def test_token_counts_include_retries_and_anthropic_cache(self):
        store=Store(self.state); idx=store.begin('raw','clean','anthropic','test')
        events=[{'usage':{'input_tokens':10,'output_tokens':20,'cache_read_input_tokens':30,'cache_creation_input_tokens':40}},
                {'usage':{'input_tokens':100,'output_tokens':5,'total_tokens':105,'input_tokens_details':{'cached_tokens':80}}}]
        store.finish(idx,reply(),events); store.close()
        self.assertEqual(self.rows()[0]['tokens_used'],205)
        self.assertEqual(self.rows()[0]['cache_read_tokens'],110)

    def test_engine_flag_and_environment(self):
        with patch.dict(os.environ,{'DEFAULT_ENGINE':'anthropic'}):
            _,_,_,api=self.call(['hello'])
            self.assertEqual(api.call_args.kwargs['engine'],'anthropic')
            _,_,_,api=self.call(['--engine','openai','hello'])
            self.assertEqual(api.call_args.kwargs['engine'],'openai')

    def test_anthropic_strict_tool_and_cache_prefix(self):
        client=FakeClient([]); client.messages=client
        obj=SimpleNamespace(id='fake-anthropic',model=h.ANTHROPIC_MODEL,stop_reason='tool_use',
            usage=SimpleNamespace(model_dump=lambda **kw:{'input_tokens':4,'output_tokens':8,'cache_read_input_tokens':1500}),
            content=[SimpleNamespace(type='tool_use',name='emit_reply',input=json.loads(document()))])
        client.queue=[obj,obj]
        h.request_reply('first',engine='anthropic',client=client,log_path=self.root/'log')
        h.request_reply('second',engine='anthropic',client=client,log_path=self.root/'log')
        self.assertEqual(client.calls[0]['system'],client.calls[1]['system'])
        self.assertEqual(client.calls[0]['system'][0]['cache_control'],{'type':'ephemeral'})
        self.assertTrue(client.calls[0]['tools'][0]['strict'])
        self.assertEqual(client.calls[0]['tools'][0]['input_schema'],h.api_schema())
        self.assertEqual(client.calls[0]['tool_choice'],{'type':'auto','disable_parallel_tool_use':True})
        self.assertEqual(client.calls[0]['model'],'claude-opus-5-5')
        self.assertEqual(client.calls[0]['thinking'],{'type':'adaptive'})
        self.assertEqual(client.calls[0]['output_config'],{'effort':h.DEFAULT_EFFORT})
        self.assertEqual(client.calls[0]['max_tokens'],h.MAX_OUTPUT_TOKENS)

    def test_anthropic_auto_choice_plain_text_is_regated(self):
        client=FakeClient([]); client.messages=client
        base={'id':'fake','model':h.ANTHROPIC_MODEL,'usage':None}
        plain=SimpleNamespace(**base,stop_reason='end_turn',content=[SimpleNamespace(type='text',text=document())])
        tool=SimpleNamespace(**base,stop_reason='tool_use',content=[SimpleNamespace(type='tool_use',name='emit_reply',input=json.loads(document()))])
        client.queue=[plain,tool]
        answer=h.request_reply('Explain the mode.',engine='anthropic',client=client,log_path=self.root/'log')
        self.assertEqual(answer.intent,'observation')
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[0]['system'],client.calls[1]['system'])

    def test_anthropic_refusal_not_retried(self):
        client=FakeClient([]); client.messages=client
        client.queue=[SimpleNamespace(id='r',model=h.ANTHROPIC_MODEL,usage=None,stop_reason='refusal',content=[])]
        with self.assertRaisesRegex(h.HarnessError,'refused'):
            h.request_reply('hello',engine='anthropic',client=client,log_path=self.root/'log')
        self.assertEqual(len(client.calls),1)

    def test_expanded_filler_gate(self):
        for text in ["You're right, my mistake.","I'd be happy to help.",
                     'For your safety,','Here is your answer:',
                     'This is not legal advice.','**Certainly!**','I’d be happy to help.']:
            with self.subTest(text=text),self.assertRaises(h.GateError): reply(direct_answer=text)

    def test_wire_schema_uses_supported_shared_subset(self):
        schema=json.dumps(h.api_schema())
        self.assertNotIn('minLength',schema); self.assertNotIn('maxLength',schema)
        with self.assertRaises(h.GateError): h.validate_reply(document(direct_answer='x'*16001))

    def test_live_observation_reassurance_is_rejected_with_specific_feedback(self):
        with self.assertRaisesRegex(h.GateError, 'Nothing has been changed'):
            reply(direct_answer='Key presence has not been checked. Nothing has been changed.')

    def test_print_only_does_not_invoke_native(self):
        with patch.object(cli,'native') as native:
            self.call(['give command'],answer=reply(intent='action_request',execution_payload='printf test'))
            native.assert_not_called()

    def test_exec_observation_never_prompts(self):
        with patch.object(cli,'native') as native:
            self.call(['-x','observation']); native.assert_not_called()

    def test_exec_decline_is_recorded_without_output(self):
        result={'approved':False,'exit_code':0,'stdout':'','stderr':''}
        with patch.object(cli,'native',return_value=result):
            code,out,err,_=self.call(['-x','command'],answer=reply(intent='action_request',execution_payload='printf test'))
        self.assertEqual(code,0); self.assertEqual(err,'')
        self.assertFalse(json.loads(self.rows()[0]['execution_result'])['approved'])

    def test_exec_output_and_exit_status_are_preserved(self):
        result={'approved':True,'exit_code':7,'stdout':'OUT\n','stderr':'ERR\n'}
        with patch.object(cli,'native',return_value=result):
            code,out,err,_=self.call(['-x','command'],answer=reply(intent='action_request',execution_payload='printf test'))
        self.assertEqual(code,7); self.assertTrue(out.endswith('OUT\n')); self.assertEqual(err,'ERR\n')

    def test_listen_passes_transcript_through_normalizer(self):
        with patch.object(cli,'native',return_value={'text':'Read the redmi in term units.'}):
            _,_,_,api=self.call(['--listen'])
        self.assertEqual(api.call_args.args[0],'Read the README in Termux.')

    def test_listen_failure_does_not_call_api(self):
        with patch.object(cli,'native',side_effect=h.HarnessError('Dictation timed out.')):
            code,out,err,api=self.call(['--listen'])
        self.assertEqual(code,2); self.assertEqual(out,''); api.assert_not_called()

    def test_native_decline_does_not_launch_shell(self):
        with patch.object(native_tools,'confirm',return_value=False),patch.object(native_tools,'run_bounded') as run:
            result=native_tools.handle({'op':'exec','command':'printf test'})
        self.assertFalse(result['approved']); run.assert_not_called()

    def test_native_accept_runs_termux_bash(self):
        with patch.object(native_tools,'confirm',return_value=True),patch.object(native_tools,'run_bounded',return_value={'exit_code':0}) as run:
            result=native_tools.handle({'op':'exec','command':'printf test'})
        self.assertTrue(result['approved'])
        self.assertEqual(run.call_args.args[0][0],'/data/data/com.termux/files/usr/bin/bash')

    def test_native_without_tty_does_not_launch(self):
        with patch.object(native_tools,'confirm',return_value=None),patch.object(native_tools,'run_bounded') as run:
            result=native_tools.handle({'op':'exec','command':'printf test'})
        self.assertIn('interactive',result['error']); run.assert_not_called()

    def test_native_speech_missing_and_empty_errors(self):
        with patch.object(native_tools.shutil,'which',return_value=None):
            self.assertIn('Install',native_tools.handle({'op':'listen'})['error'])
        with patch.object(native_tools.shutil,'which',return_value='/fake'),patch.object(native_tools,'run_bounded',return_value={'exit_code':0,'stdout':'','timed_out':False}):
            self.assertIn('no dictation',native_tools.handle({'op':'listen'})['error'])

    def test_native_command_timeout(self):
        # Uses Debian's sh in this offline check; the native live check verifies Termux routing.
        result=native_tools.run_bounded(['/bin/sh','-c','sleep 3'],timeout=0.1)
        self.assertEqual(result['exit_code'],124); self.assertTrue(result['timed_out'])


if __name__=='__main__': unittest.main()
