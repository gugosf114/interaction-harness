"""Chat input, status, command routing, color and persisted history; no live calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import harness as h
import chat_screen as screen
from chat_input import ChatInput, InputTooLong
from test_harness import document


class TTY(io.StringIO):
    def isatty(self): return True


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.state=patch.object(h,'STATE',self.root);self.state.start()
    def tearDown(self): self.state.stop();self.tmp.cleanup()
    def chat(self, text, args=(), side_effect=None):
        out,err=io.StringIO(),io.StringIO()
        with patch('sys.stdin',io.StringIO(text)),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            with patch.object(h,'request_reply',return_value=h.validate_reply(document()),side_effect=side_effect) as request:
                code=h.main(['--chat',*args])
        return code,out.getvalue(),err.getvalue(),request
    def test_status_uses_normalized_usage_and_last_context(self):
        args=SimpleNamespace(engine='anthropic',model='claude-opus-5-5',effort='max')
        events=[{'usage':{'input_tokens':100,'cache_read_input_tokens':400,'cache_creation_input_tokens':200,'output_tokens':20}},
                {'usage':{'input_tokens':200,'cache_read_input_tokens':500,'output_tokens':30}}]
        text=screen.status_text(args,'work',2,events,3.25,['judge'])
        for part in ('anthropic/claude-opus-5-5','max','work #2','in 1,400 out 50 cache 900','ctx 0.07%','3.2s','off: judge'): self.assertIn(part,text)
    def test_context_prefers_last_provider_call_not_aggregate(self):
        event={'usage':{'input_tokens':500000},'lookup_counts':{'provider_reports':[{'usage':{'input_tokens':100}},{'usage':{'input_tokens':120}}]}}
        self.assertEqual(screen.context_tokens([event]),120)
    def test_openai_window_uses_documented_capacity(self):
        args=SimpleNamespace(engine='openai',model='gpt-6.1-sol',effort='max')
        self.assertIn('ctx 10.00%',screen.status_text(args,'s',1,[{'usage':{'input_tokens':105000,'output_tokens':3}}],1,[]))
    def test_registry_help_matches_all_registered_commands(self):
        text=screen.help_text()
        self.assertEqual(len(text.splitlines()),len(screen.COMMANDS))
        for command in ('advisor','on','off','fork','rewind','wrong','voice','autopilot','both','image','file','model','paste','cost'):
            self.assertIn('/'+command,text)
    def test_unknown_command_lists_help_without_api_or_stdout(self):
        code,out,err,request=self.chat('/bogus\nquit\n')
        self.assertEqual(code,0);self.assertEqual(out,'');request.assert_not_called()
        self.assertIn('Unknown command: /bogus',err);self.assertIn('/help',err)
    def test_lane_switch_and_effort_keep_same_session(self):
        _,_,_,request=self.chat('one\n/model claude-opus-5-5\n/effort high\ntwo\nquit\n')
        self.assertEqual(request.call_args_list[0].kwargs['engine'],'openai')
        self.assertEqual(request.call_args_list[1].kwargs['engine'],'anthropic')
        self.assertEqual(request.call_args_list[1].kwargs['effort'],'high')
        self.assertEqual(len(request.call_args_list[1].kwargs['history']),2)
    def test_new_session_and_continue(self):
        _,_,_,request=self.chat('one\n/new\ntwo\n/continue\nthree\nquit\n')
        self.assertEqual(len(request.call_args_list[1].kwargs['history']),0)
        self.assertEqual(len(request.call_args_list[2].kwargs['history']),2)
    def test_interrupt_returns_to_prompt(self):
        code,out,err,request=self.chat('first\nsecond\nquit\n',side_effect=[KeyboardInterrupt(),h.validate_reply(document())])
        self.assertEqual(code,0);self.assertEqual(request.call_count,2);self.assertIn('Stopped.',err)
    def test_paste_and_continuation_are_whole_messages(self):
        _,_,_,request=self.chat('/paste\none\ntwo\n.\nthree\\\nfour\nquit\n')
        self.assertEqual([c.args[0] for c in request.call_args_list],['one\ntwo','three\nfour'])
    def test_paste_commands_and_quit_are_literal_messages(self):
        _,_,_,request=self.chat('/paste\nquit\n.\n/paste\n/off stamp\n.\n/retry\nquit\n')
        self.assertEqual([c.args[0] for c in request.call_args_list],['quit','/off stamp','/off stamp'])
        self.assertFalse((self.root/'switches.json').exists())
    def test_multiline_paste_keeps_its_trailing_backslash(self):
        editor=ChatInput(self.root,lambda _,text,**kw:text,100)
        with patch.object(editor,'line',side_effect=['first\nlast \\', 'NEXT']) as line:
            self.assertEqual(editor.read(),'first\nlast \\')
            self.assertEqual(line.call_count,1)
    def test_parallel_history_writers_keep_both_messages(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def append(value):
            editor=ChatInput(self.root,lambda _,text,**kw:text,100)
            barrier.wait();editor.remember(value)
        with ThreadPoolExecutor(2) as pool:list(pool.map(append,['FIRST','SECOND']))
        self.assertEqual(set(json.loads((self.root/'chat-input.json').read_text())),{'FIRST','SECOND'})
    def test_recall_status_reads_the_real_recall_switch(self):
        _,_,err,_=self.chat('/off recall\n/status\nquit\n')
        self.assertIn('recall: off',err)
    def test_history_preserves_multiline_across_launches(self):
        self.chat('/paste\none\ntwo\n.\nquit\n')
        self.chat('three\nquit\n')
        editor=ChatInput(self.root,lambda _,text,**kw:text,100)
        self.assertEqual(editor.history,['one\ntwo','three'])
        self.assertEqual((self.root/'chat-input.json').stat().st_mode & 0o777,0o600)
    def test_retry_reuses_message(self):
        _,_,_,request=self.chat('one\n/retry\nquit\n')
        self.assertEqual([c.args[0] for c in request.call_args_list],['one','one'])
    def test_clear_leaves_history_and_copy_save_uses_last_answer(self):
        path=self.root/'answer.txt'
        with patch('cli.native',return_value={'exit_code':0,'stdout':h.validate_reply(document()).direct_answer}) as native:
            _,out,err,request=self.chat(f'one\n/clear\n/copy\n/save {path}\nquit\n')
        self.assertEqual(request.call_count,1)
        self.assertEqual(path.read_text(),out)
        self.assertIn('termux-clipboard-set',native.call_args.args[0]['command'])
    def test_copy_requires_the_phone_to_return_the_same_text(self):
        with patch('cli.native',return_value={'exit_code':0,'stdout':''}):
            code,_,err,_=self.chat('one\n/copy\nquit\n')
        self.assertEqual(code,2)
        self.assertIn('The phone clipboard did not keep the answer.',err)
        self.assertNotIn('Copied the last answer.',err)
    def test_colors_turned_off_for_pipe_plain_or_no_color(self):
        for plain,no_color,tty in ((False,False,True),(True,False,True),(False,True,True),(False,False,False)):
            with patch('sys.stdout',TTY() if tty else io.StringIO()),patch('sys.stderr',TTY()),patch.dict(os.environ,{'NO_COLOR':''} if no_color else {},clear=True):
                ui=screen.Screen(SimpleNamespace(plain=plain),self.root)
                result=ui.color('answer','Text')
                self.assertEqual('\033[' in result,tty and not plain and not no_color)
    def test_source_command_and_answer_colors_still_have_exact_text(self):
        reply=h.validate_reply(document(intent='action_request',execution_payload='printf hi'))
        sources=[{'title':'Example','url':'https://example.com'}]
        with patch('sys.stdout',TTY()),patch('sys.stderr',TTY()),patch.dict(os.environ,{},clear=True):
            ui=screen.Screen(SimpleNamespace(plain=False),self.root)
            with patch.object(screen,'ACTIVE',ui): colored=screen.display_reply(reply,sources)
        import re
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m','',colored),h.display_text(reply,sources))
    def test_public_phase_events_never_show_thinking_or_partial_text(self):
        import chat_progress
        seen=[]
        with patch.object(chat_progress,'listener',lambda *x:seen.append(x)):
            for kind in ('response.reasoning_text.delta','response.output_text.delta','thinking','text'):
                chat_progress.public_event(SimpleNamespace(type=kind,delta='private text'))
            chat_progress.public_event(SimpleNamespace(type='response.web_search_call.searching'))
        self.assertEqual(seen,[('Searching the web','')])
    def test_oversized_paste_is_one_error_no_tail_request(self):
        with patch.object(h,'MAX_INPUT_CHARS',5):
            _,_,err,request=self.chat('/paste\nabc\ndef\n.\nok\nquit\n')
        self.assertEqual(request.call_count,1);self.assertEqual(request.call_args.args[0],'ok')
        self.assertIn('Input exceeds',err)

if __name__=='__main__':unittest.main()
