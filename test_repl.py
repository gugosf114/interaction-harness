"""Chat-loop and model-setting regression checks; no live API calls."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import harness as h
from test_harness import FakeClient, response, document


class TerminalInput(io.StringIO):
    def isatty(self): return True


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.patch=patch.object(h,'STATE',self.root);self.patch.start()

    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()

    def call(self,args,text,tty=False,side_effect=None):
        out,err=io.StringIO(),io.StringIO()
        input_stream=(TerminalInput if tty else io.StringIO)(text)
        with patch.object(h.sys,'stdin',input_stream),patch.object(h,'request_reply',return_value=h.validate_reply(document()),side_effect=side_effect) as api:
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): code=h.main(args)
        return code,out.getvalue(),err.getvalue(),api

    def rows(self):
        db=sqlite3.connect(self.root/'history.db');db.row_factory=sqlite3.Row
        try:return [dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
        finally:db.close()

    def test_explicit_chat_reuses_one_session(self):
        code,out,err,api=self.call(['--chat'],'first\nsecond\nexit\n')
        self.assertEqual(code,0);self.assertEqual(api.call_count,2)
        self.assertEqual(len(api.call_args_list[1].kwargs['history']),2)
        self.assertEqual(len({r['session_id'] for r in self.rows()}),1)
        self.assertNotIn('> ',out);self.assertIn('> ',err)

    def test_no_arguments_on_terminal_starts_chat(self):
        code,_,_,api=self.call([],'first\nquit\n',tty=True)
        self.assertEqual(code,0);self.assertEqual(api.call_count,1)

    def test_argument_on_terminal_remains_one_shot(self):
        code,_,err,api=self.call(['my quick question'],'must not be read\n',tty=True)
        self.assertEqual(code,0);self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0],'my quick question');self.assertEqual(err,'')

    def test_piped_input_without_chat_remains_one_turn(self):
        _,_,_,api=self.call([],'line one\nline two\n')
        self.assertEqual(api.call_count,1);self.assertEqual(api.call_args.args[0],'line one\nline two\n')

    def test_quit_and_exit_do_not_call_api(self):
        for word in ['exit','quit',' EXIT ','Quit']:
            with self.subTest(word=word):
                code,out,_,api=self.call(['--chat'],word+'\n')
                self.assertEqual(code,0);self.assertEqual(out,'');api.assert_not_called()

    def test_blank_lines_and_eof_exit_cleanly(self):
        code,out,_,api=self.call(['--chat'],'\n   \n')
        self.assertEqual(code,0);self.assertEqual(out,'');api.assert_not_called()

    def test_named_session_is_preserved(self):
        self.call(['--chat','--session','fixed'],'one\ntwo\nquit\n')
        self.assertEqual({r['session_id'] for r in self.rows()},{'fixed'})

    def test_continue_reopens_previous_session(self):
        self.call(['--session','old','first'],'')
        _,_,_,api=self.call(['--chat','-c'],'second\nquit\n')
        self.assertEqual(len(api.call_args.kwargs['history']),2)
        self.assertEqual({r['session_id'] for r in self.rows()},{'old'})

    def test_api_error_keeps_chat_open(self):
        code,out,err,api=self.call(['--chat'],'bad\ngood\nquit\n',side_effect=[h.HarnessError('Test API error.'),h.validate_reply(document())])
        self.assertEqual(code,0);self.assertEqual(api.call_count,2)
        self.assertIn('Test API error.',err);self.assertIn('The owner',out)
        self.assertEqual([r['status'] for r in self.rows()],['error','accepted'])

    def test_oversized_line_is_drained_before_next_turn(self):
        code,_,err,api=self.call(['--chat'],'x'*(h.MAX_INPUT_CHARS+100)+'\ngood\nquit\n')
        self.assertEqual(code,0);self.assertIn('Input exceeds',err)
        self.assertEqual(api.call_count,1);self.assertEqual(api.call_args.args[0],'good')

    def test_initial_chat_argument_and_next_line_share_session(self):
        _,_,_,api=self.call(['--chat','first'],'second\nquit\n')
        self.assertEqual(api.call_count,2);self.assertEqual(len(api.call_args.kwargs['history']),2)

    def test_literal_option_text_cannot_change_engine(self):
        _,_,_,api=self.call(['--chat','--engine','openai'],'--engine anthropic\nquit\n')
        self.assertEqual(api.call_args.kwargs['engine'],'openai')
        self.assertEqual(api.call_args.args[0],'--engine anthropic')

    def test_chat_pins_selected_model_and_high_effort(self):
        _,_,_,api=self.call(['--chat','--engine','anthropic'],'one\ntwo\nquit\n')
        for call in api.call_args_list:
            self.assertEqual(call.kwargs['model'],'claude-opus-5-5')
            self.assertEqual(call.kwargs['effort'],'high')

    def test_sol_request_sends_high_reasoning(self):
        client=FakeClient([response()])
        h.request_reply('Explain the mode.',client=client,log_path=self.root/'usage')
        self.assertEqual(client.calls[0]['model'],'gpt-6.1-sol')
        self.assertEqual(client.calls[0]['reasoning'],{'effort':'high'})
        self.assertEqual(client.calls[0]['max_output_tokens'],8192)


if __name__=='__main__':unittest.main()
