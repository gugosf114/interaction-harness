"""Agent-loop behavior, approval boundaries, observation fidelity and persistence."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import cli
import harness as h
import native_tools
from storage import Store, execution_observation, history_messages, FEEDBACK_STREAM_LIMIT
from test_harness import document, FakeClient, response


def command(text='printf test',answer='This runs the next step.'):
    return h.validate_reply(document(intent='action_request',direct_answer=answer,execution_payload=text))


def final(answer='The file contains the expected value.'):
    return h.validate_reply(document(direct_answer=answer),execution_confirmed=True)


def result(stdout='',stderr='',code=0,approved=True,**extra):
    return dict(approved=approved,stdout=stdout,stderr=stderr,exit_code=code,**extra)


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.state=patch.object(h,'STATE',self.root);self.state.start()

    def tearDown(self):self.state.stop();self.tmp.cleanup()

    def rows(self):
        db=sqlite3.connect(self.root/'history.db');db.row_factory=sqlite3.Row
        try:return [dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
        finally:db.close()

    def call(self,args,answers,results=(),stdin=None):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(h,'request_reply',side_effect=answers) as api,patch.object(cli,'native',side_effect=results) as native:
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err),patch.object(cli.sys,'stdin',io.StringIO(stdin or '')):
                code=h.main(args)
        return code,out.getvalue(),err.getvalue(),api,native

    def test_two_commands_then_final_with_result_feedback(self):
        code,out,err,api,native=self.call(['--loop','Create and read the test file.'],
            [command('printf alpha > test.txt'),command('cat test.txt'),final()],
            [result(),result('alpha\n')])
        self.assertEqual(code,0);self.assertEqual(err,'');self.assertEqual(api.call_count,3)
        self.assertEqual(native.call_count,2)
        self.assertTrue(all('auto_confirm' not in c.args[0] for c in native.call_args_list))
        self.assertIn('alpha\n',out)
        feedback=[json.loads(m['content']) for m in api.call_args_list[2].kwargs['history'] if '"type": "execution_observation"' in m['content']]
        self.assertEqual(feedback[-1]['result']['stdout'],'alpha\n')
        self.assertEqual(feedback[-1]['result']['stderr'],'')
        self.assertEqual(feedback[-1]['result']['exit_code'],0)
        self.assertTrue(api.call_args_list[2].kwargs['execution_confirmed'])
        rows=self.rows();self.assertEqual(len(rows),3)
        self.assertEqual(len({r['session_id'] for r in rows}),1)
        self.assertEqual(json.loads(rows[1]['execution_result'])['stdout'],'alpha\n')
        self.assertIsNone(rows[2]['execution_payload'])

    def test_observation_ends_loop_without_prompt(self):
        code,_,_,api,native=self.call(['--loop','Explain.'],[final()])
        self.assertEqual(code,0);self.assertEqual(api.call_count,1);native.assert_not_called()

    def test_decline_stops_without_another_model_call(self):
        code,_,err,api,native=self.call(['--loop','Do the task.'],[command()],[result(approved=False)])
        self.assertEqual(code,0);self.assertEqual(api.call_count,1);self.assertEqual(native.call_count,1)
        self.assertIn('declined',err);self.assertFalse(json.loads(self.rows()[0]['execution_result'])['approved'])

    def test_default_ceiling_stops_after_five_turns(self):
        code,_,err,api,native=self.call(['--loop','Repeat.'],[command() for _ in range(5)],[result() for _ in range(5)])
        self.assertEqual(code,3);self.assertEqual(api.call_count,5);self.assertEqual(native.call_count,5)
        self.assertIn('5-turn limit',err);self.assertEqual(self.rows()[-1]['status'],'loop_limit')

    def test_custom_ceiling_and_final_on_last_turn(self):
        code,_,err,api,native=self.call(['--loop','--max-turns','2','Task.'],[command(),final()],[result()])
        self.assertEqual(code,0);self.assertEqual(err,'');self.assertEqual(api.call_count,2);self.assertEqual(native.call_count,1)

    def test_failure_is_observed_and_can_be_repaired(self):
        code,_,_,api,_=self.call(['--loop','Repair the check.'],[command(),command(),final()],
            [result(stderr='missing parameter',code=7),result('fixed')])
        self.assertEqual(code,0)
        self.assertIn('missing parameter',json.dumps(api.call_args_list[1].kwargs['history']))
        self.assertIn('"exit_code": 7',str(api.call_args_list[1].kwargs['history']))

    def test_unresolved_failure_exit_status_survives_final(self):
        code,_,_,_,_=self.call(['--loop','Check.'],[command(),final('The check failed.')],[result(code=7)])
        self.assertEqual(code,7)

    def test_timeout_is_visible_in_next_turn(self):
        code,_,err,api,_=self.call(['--loop','Check.'],[command(),final('The command timed out.')],
            [result(code=124,timed_out=True)])
        self.assertEqual(code,124);self.assertIn('Command timed out',err)
        self.assertIn('"timed_out": true',str(api.call_args_list[1].kwargs['history']))

    def test_model_error_preserves_previous_execution_record(self):
        code,_,_,_,_=self.call(['--loop','Task.'],[command(),h.HarnessError('API unavailable.')],[result('completed')])
        self.assertEqual(code,2);rows=self.rows()
        self.assertEqual(rows[0]['status'],'accepted');self.assertEqual(rows[1]['status'],'error')
        self.assertEqual(json.loads(rows[0]['execution_result'])['stdout'],'completed')

    def test_explicit_yes_is_forwarded_for_every_step(self):
        _,_,_,_,native=self.call(['--loop','-y','Task.'],[command(),command(),final()],[result(),result()])
        self.assertTrue(all(c.args[0]['auto_confirm'] is True for c in native.call_args_list))

    def test_yes_requires_execution_mode(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
            h.main(['-y','Task.'])
        self.assertEqual(exc.exception.code,2)

    def test_invalid_ceiling_is_rejected(self):
        for value in ('0','51'):
            with self.subTest(value=value),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                h.main(['--loop','--max-turns',value,'Task.'])

    def test_print_only_and_exec_single_turn_stay_single_turn(self):
        _,_,_,api,native=self.call(['Task.'],[command()]);self.assertEqual(api.call_count,1);native.assert_not_called()
        _,_,_,api,native=self.call(['-x','Task.'],[command()],[result()]);self.assertEqual(api.call_count,1);self.assertEqual(native.call_count,1)

    def test_goal_and_latest_feedback_survive_zero_history_budget(self):
        _,_,_,api,_=self.call(['--loop','--turns','1','--history-chars','0','Keep the original goal.'],
            [command(),command(),final()],[result('first'),result('NC AIPG redmi term units')])
        past=api.call_args_list[2].kwargs['history']
        self.assertIn('Keep the original goal.',past[0]['content'])
        self.assertIn('NC AIPG redmi term units',past[-1]['content'])
        self.assertTrue(api.call_args_list[2].kwargs['execution_confirmed'])

    def test_chat_propagates_loop_and_explicit_approval_flags(self):
        code,_,_,api,native=self.call(['--chat','--loop','-y','--max-turns','2'],
            [command(),final()],[result()],stdin='Task.\nquit\n')
        self.assertEqual(code,0);self.assertEqual(api.call_count,2);self.assertTrue(native.call_args.args[0]['auto_confirm'])

    def test_recall_accepts_execution_claim_only_with_saved_evidence(self):
        self.call(['--loop','--session','proof','Check the file.'],[command(),final('Done. I checked your file.')],[result('present')])
        code,out,_,api,native=self.call(['--recall','Done'],[])
        self.assertEqual(code,0);self.assertIn('Done. I checked your file.',out);api.assert_not_called();native.assert_not_called()

    def test_history_keeps_four_field_assistant_and_labels_truncation(self):
        exchange={'normalized_input':'Task.','reply':command().model_dump(),
                  'execution_result':result('x'*(FEEDBACK_STREAM_LIMIT+100),'error')}
        history=history_messages([exchange],50000)
        self.assertEqual(set(json.loads(history[1]['content'])),set(command().model_dump()))
        observation=json.loads(history[2]['content'])
        self.assertEqual(len(observation['result']['stdout']),FEEDBACK_STREAM_LIMIT)
        self.assertEqual(observation['result']['feedback_truncated_fields'],['stdout'])
        self.assertEqual(len(exchange['execution_result']['stdout']),FEEDBACK_STREAM_LIMIT+100)

    def test_generated_completion_and_filler_use_same_gate(self):
        raw=document(direct_answer='Sure, Done. I checked your file.')
        with self.assertRaises(h.GateError):h.validate_reply(raw)
        client=FakeClient([response(raw)])
        reply=h.request_reply('Continue.',client=client,log_path=self.root/'usage',execution_confirmed=True)
        self.assertEqual(reply.direct_answer,'Done. I checked your file.')
        with self.assertRaises(h.GateError):h.validate_reply(document(direct_answer='Done. I hope this helps.'),execution_confirmed=True)

    def test_native_auto_confirm_requires_literal_true(self):
        with patch.object(native_tools,'confirm',return_value=False) as ask,patch.object(native_tools,'run_bounded') as run:
            native_tools.handle({'op':'exec','command':'true','auto_confirm':'yes'})
            ask.assert_called_once();run.assert_not_called()
        with patch.object(native_tools,'confirm') as ask,patch.object(native_tools,'run_bounded',return_value={'exit_code':0}) as run:
            native_tools.handle({'op':'exec','command':'true','auto_confirm':True})
            ask.assert_not_called();run.assert_called_once()

    def test_native_confirmation_occurs_for_each_loop_command(self):
        with patch.object(native_tools,'confirm',return_value=True) as ask,patch.object(native_tools,'run_bounded',return_value={'exit_code':0,'stdout':'','stderr':''}):
            self.call(['--loop','Task.'],[command(),command(),final()],native_tools.handle)
            self.assertEqual(ask.call_count,2)


if __name__=='__main__':unittest.main()
