"""The advisor: only the operator starts it, the other engine answers, the note reaches the working model once."""
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

import anthropic

import advisor
import cli
import harness as h
import senses
from storage import FEEDBACK_STREAM_LIMIT, advisor_note, history_messages
from test_harness import FakeClient, document, response
from test_tools_block import AnthropicFake

ADVICE = ('- Root cause: the folder does not exist.\n'
          '- Next command: mkdir -p ~/reports\n'
          '- Then run the listing again.')


def usage(**numbers):
    return SimpleNamespace(model_dump=lambda **_: dict(numbers))


def openai_reply(text=ADVICE, *, refusal=False, status='completed'):
    content = [SimpleNamespace(type='refusal', refusal='no')] if refusal else []
    return SimpleNamespace(id='advice-openai', model=h.DEFAULT_MODEL, status=status, output_text=text,
                           usage=usage(input_tokens=900, output_tokens=60, total_tokens=960, input_tokens_details={'cached_tokens': 0}),
                           output=[SimpleNamespace(type='message', content=content)])


def claude_reply(text=ADVICE, *, stop='end_turn'):
    return SimpleNamespace(id='advice-claude', model=h.ANTHROPIC_MODEL, stop_reason=stop,
                           usage=usage(input_tokens=700, output_tokens=50),
                           content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)])


class FakeAdvisor:
    """Stands in for either provider's client. It records every request and plays back queued replies."""
    def __init__(self, *replies):
        self.queue = list(replies)
        self.calls = []
        self.responses = self
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs)))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(**changes):
    return h.validate_reply(document(**changes))


def command(text='ls ~/reports', answer='This lists the reports folder.'):
    return h.validate_reply(document(intent='action_request', direct_answer=answer, execution_payload=text))


def result(stdout='', stderr='', code=0, **extra):
    return dict(approved=True, stdout=stdout, stderr=stderr, exit_code=code, **extra)


class AdvisorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        for started in (patch.object(h, 'STATE', self.state), patch.dict(os.environ, {'DEFAULT_ENGINE': 'openai'}, clear=False)):
            started.start()
            self.addCleanup(started.stop)

    def work(self, args, answers=None, results=(), stdin=''):
        """One run of the working lane with a patched model call and command runner."""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=answers or [reply()]) as api, \
                patch.object(cli, 'native', side_effect=list(results)) as native:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(cli.sys, 'stdin', io.StringIO(stdin)):
                code = h.main(args)
        return code, out.getvalue(), err.getvalue(), api, native

    def advise(self, args, client):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(advisor, 'make_client', return_value=client) as made, patch.object(h, 'request_reply') as working:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(args)
        working.assert_not_called()
        return code, out.getvalue(), err.getvalue(), made

    def session(self, name='s'):
        return json.loads((self.state / 'sessions' / (name + '.json')).read_text())

    def rows(self):
        db = sqlite3.connect(self.state / 'history.db')
        db.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in db.execute('SELECT * FROM history ORDER BY id')]
        finally:
            db.close()

    @staticmethod
    def packet(call):
        message, = call.get('input') or call.get('messages')
        return json.loads(message['content'])


class TriggerTests(AdvisorCase):
    def test_only_the_exact_word_is_a_trigger(self):
        for line in ('/advisor', '/advisor why did it fail?', '/advisor\twhy'):
            self.assertTrue(advisor.is_trigger(line), line)
        for line in ('/advisors', '/advisory board', ' /advisor', 'ask the /advisor', '/ADVISOR', '/image x.png /advisor'):
            self.assertFalse(advisor.is_trigger(line), line)

    def test_chat_line_with_and_without_a_question(self):
        client = FakeAdvisor(claude_reply(), claude_reply())
        out, err = io.StringIO(), io.StringIO()
        typed = 'first request\n/advisor\n/advisor why did it fail?\nexit\n'
        with patch.object(h, 'request_reply', return_value=reply()) as working, patch.object(advisor, 'make_client', return_value=client):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(cli.sys, 'stdin', io.StringIO(typed)):
                code = h.main(['--chat', '--session', 's'])
        self.assertEqual(code, 0)
        self.assertEqual(working.call_count, 1, '/advisor must not make the working model speak')
        self.assertEqual(working.call_args.args[0], 'first request')
        self.assertEqual(len(client.calls), 2)
        self.assertIsNone(self.packet(client.calls[0])['operator_question'])
        self.assertEqual(self.packet(client.calls[1])['operator_question'], 'why did it fail?')
        self.assertEqual(out.getvalue(), reply().direct_answer + '\n' + ('Advisor (claude-opus-5-5):\n' + ADVICE + '\n') * 2)

    def test_chat_passes_a_question_that_starts_with_a_dash(self):
        client = FakeAdvisor(claude_reply())
        with patch.object(h, 'request_reply', return_value=reply()), patch.object(advisor, 'make_client', return_value=client):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(cli.sys, 'stdin', io.StringIO('first\n/advisor -x did nothing, why?\nexit\n')):
                h.main(['--chat', '--session', 's', '--engine', 'openai'])
        self.assertEqual(self.packet(client.calls[0])['operator_question'], '-x did nothing, why?')

    def test_command_line_form_needs_a_saved_session(self):
        self.work(['--session', 's', 'first request'])
        code, out, _, _ = self.advise(['--session', 's', '--advisor', 'is the path right?'], FakeAdvisor(claude_reply()))
        self.assertEqual((code, out.splitlines()[0]), (0, 'Advisor (claude-opus-5-5):'))
        code, out, _, _ = self.advise(['-c', '--advisor'], FakeAdvisor(claude_reply()))
        self.assertEqual(code, 0)
        for bad in (['--advisor', 'question'], ['--session', 's', '--advisor', 'q', 'extra text'], ['--session', 's', '--advisor', '--chat'],
                    ['--session', 's', '--advisor', 'q', '--recall', 'x'], ['--session', 's', '--advisor', '--advisor-turns', '0'],
                    ['--session', 's', '--advisor', '--advisor-turns', '51']):
            with self.subTest(arguments=bad), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                h.main(bad)
            self.assertEqual(stopped.exception.code, 2)

    def test_empty_session_is_one_short_error_and_no_api_call(self):
        code, out, err, made = self.advise(['--session', 'fresh', '--advisor'], FakeAdvisor())
        self.assertEqual((code, out), (2, ''))
        self.assertEqual(err, 'Nothing to review yet: this session has no exchange.\n')
        made.assert_not_called()
        self.assertEqual(self.rows(), [])


class PacketTests(AdvisorCase):
    def loop_that_fails(self):
        long_output = 'HEAD' + 'x' * (FEEDBACK_STREAM_LIMIT * 2) + 'TAIL'
        self.work(['--loop', '--session', 's', 'List my reports folder and count the files.'],
                  [command('ls ~/reports'), reply(direct_answer='The listing failed: the folder is missing.')],
                  [result(stdout=long_output, stderr='ls: cannot access reports: No such file or directory', code=2)])

    def test_packet_holds_the_loop_task_the_exchanges_and_the_command_result(self):
        self.loop_that_fails()
        client = FakeAdvisor(claude_reply())
        self.advise(['--session', 's', '--advisor', 'why did it fail?'], client)
        packet = self.packet(client.calls[0])
        self.assertEqual(packet['type'], 'advisor_packet')
        self.assertEqual((packet['working_engine'], packet['working_model']), ('openai', 'gpt-6.1-sol'))
        self.assertEqual((packet['task'], packet['task_kind']), ('List my reports folder and count the files.', 'loop_original_task'))
        self.assertEqual(packet['operator_question'], 'why did it fail?')
        first, second = packet['exchanges']
        self.assertEqual((first['input'], first['input_kind']), ('List my reports folder and count the files.', 'operator'))
        self.assertEqual(set(first['reply']), {'intent', 'cleaned_input', 'direct_answer', 'execution_payload'})
        ran = first['command_result']
        self.assertEqual((ran['command'], ran['approved'], ran['exit_code'], ran['timed_out']), ('ls ~/reports', True, 2, False))
        self.assertIn('No such file or directory', ran['stderr'])
        self.assertEqual(len(ran['stdout']), FEEDBACK_STREAM_LIMIT)
        self.assertTrue(ran['stdout'].startswith('HEAD') and ran['stdout'].endswith('TAIL') and 'omitted' in ran['stdout'])
        self.assertEqual(ran['clipped_streams'], ['stdout'])
        self.assertEqual(second['input_kind'], 'loop_continuation')
        self.assertNotIn('command_result', second)

    def test_packet_takes_the_last_three_exchanges_and_the_first_request(self):
        for number in range(1, 6):
            self.work(['--session', 's', f'request number {number}'])
        client = FakeAdvisor(claude_reply(), claude_reply())
        self.advise(['--session', 's', '--advisor'], client)
        packet = self.packet(client.calls[0])
        self.assertEqual((packet['task'], packet['task_kind']), ('request number 1', 'session_first_request'))
        self.assertEqual([item['input'] for item in packet['exchanges']], ['request number 3', 'request number 4', 'request number 5'])
        self.advise(['--session', 's', '--advisor', '--advisor-turns', '1'], client)
        second = self.packet(client.calls[1])
        self.assertEqual([item['input'] for item in second['exchanges']], ['request number 5'])
        self.assertEqual(second['exchanges'][0]['earlier_advisor_notes'], [{'model': 'claude-opus-5-5', 'text': ADVICE}])

    def test_packet_over_the_cap_is_refused_before_any_call(self):
        self.assertEqual(advisor.PACKET_CAP_CHARS, 600000)
        big = 'x' * 250000   # The task (the first request) and two exchanges: 750,000 characters. One exchange: 500,000.
        self.work(['--session', 's', big])
        self.work(['--session', 's', big])
        before = self.session()
        code, out, err, made = self.advise(['--session', 's', '--advisor'], FakeAdvisor())
        self.assertEqual((code, out), (2, ''))
        self.assertRegex(err, r'^The advisor packet is \d+ characters; the cap is 600000\. Use a smaller --advisor-turns\.\n$')
        made.assert_not_called()
        self.assertEqual(self.session(), before)
        client = FakeAdvisor(claude_reply())
        code, _, _, _ = self.advise(['--session', 's', '--advisor', '--advisor-turns', '1'], client)
        self.assertEqual(code, 0, 'one exchange fits')
        self.assertLessEqual(len(client.calls[0]['messages'][0]['content']), advisor.PACKET_CAP_CHARS)

    def test_one_exchange_over_the_cap_says_so(self):
        self.work(['--session', 's', 'x' * (advisor.PACKET_CAP_CHARS + 10)])
        code, out, err, made = self.advise(['--session', 's', '--advisor', '--advisor-turns', '1'], FakeAdvisor())
        self.assertEqual((code, out), (2, ''))
        self.assertRegex(err, r'^The advisor packet is \d+ characters; the cap is 600000\. The latest exchange alone is over the cap\.\n$')
        made.assert_not_called()

    def test_packet_under_the_cap_is_sent_whole(self):
        self.work(['--session', 's', 'y' * 50000])
        client = FakeAdvisor(claude_reply())
        self.advise(['--session', 's', '--advisor'], client)
        self.assertEqual(self.packet(client.calls[0])['exchanges'][0]['input'], 'y' * 50000)


class CallTests(AdvisorCase):
    def test_from_claude_the_call_goes_to_gpt_alone(self):
        self.work(['--engine', 'anthropic', '--session', 's', 'first request'])
        pages = self.root / 'pages.json'
        private = self.root / 'private.md'
        private.write_text('OPERATOR-PAGE-MARK-31')
        pages.write_text(json.dumps([{'label': 'rules', 'path': str(private)}]))
        client = FakeAdvisor(openai_reply())
        with patch.object(h, 'PAGES_FILE', pages):
            code, out, _, made = self.advise(['--engine', 'anthropic', '--effort', 'high', '--session', 's', '--advisor', 'q'], client)
        self.assertEqual(code, 0)
        self.assertEqual(made.call_args.args[0], 'openai')
        call, = client.calls
        self.assertEqual(set(call), {'model', 'instructions', 'input', 'reasoning', 'max_output_tokens', 'store'})
        self.assertEqual((call['model'], call['instructions'], call['reasoning'], call['store']),
                         ('gpt-6.1-sol', advisor.SYSTEM_PROMPT, {'effort': 'high'}, False))
        self.assertEqual([message['role'] for message in call['input']], ['user'])
        sent = json.dumps(call)
        for absent in ('OPERATOR-PAGE-MARK-31', 'FROZEN PREFIX', 'OPERATOR TOOLS', 'web_search', 'temperature'):
            self.assertNotIn(absent, sent)
        self.assertEqual(out, 'Advisor (gpt-6.1-sol):\n' + ADVICE + '\n')

    def test_from_gpt_the_call_goes_to_claude_alone(self):
        self.work(['--engine', 'openai', '--session', 's', 'first request'])
        client = FakeAdvisor(claude_reply())
        code, out, _, made = self.advise(['--engine', 'openai', '--effort', 'max', '--session', 's', '--advisor'], client)
        self.assertEqual(code, 0)
        self.assertEqual(made.call_args.args[0], 'anthropic')
        call, = client.calls
        self.assertEqual(set(call), {'model', 'max_tokens', 'thinking', 'output_config', 'system', 'messages'})
        self.assertEqual((call['model'], call['system'], call['thinking'], call['output_config']),
                         ('claude-opus-5-5', advisor.SYSTEM_PROMPT, {'type': 'adaptive'}, {'effort': 'max'}))
        self.assertEqual([message['role'] for message in call['messages']], ['user'])
        self.assertEqual(out, 'Advisor (claude-opus-5-5):\n' + ADVICE + '\n')

    def test_the_reviewer_prompt_is_the_agreed_text(self):
        self.assertEqual(advisor.SYSTEM_PROMPT, "You are an outside reviewer of another model's work. State the root cause, then the next "
                                                "command or fix. At most three short bullets. No greeting, no praise, no reassurance.")

    def test_history_row_and_usage_record(self):
        self.work(['--session', 's', 'first request'])
        self.advise(['--session', 's', '--usage-log', str(self.root / 'usage.jsonl'), '--advisor', 'why?'], FakeAdvisor(claude_reply()))
        row = self.rows()[-1]
        self.assertEqual((row['status'], row['engine'], row['model'], row['session_id']), ('advisor', 'anthropic', 'claude-opus-5-5', 's'))
        self.assertEqual((row['raw_input'], row['normalized_input'], row['direct_answer'], row['intent']), ('/advisor why?', 'why?', ADVICE, None))
        self.assertEqual((row['input_tokens'], row['output_tokens'], row['tokens_used']), (700, 50, 750))
        raw = (self.root / 'usage.jsonl').read_text()
        event = json.loads(raw.splitlines()[-1])
        self.assertEqual((event['kind'], event['engine'], event['status'], event['usage']['output_tokens']), ('advisor', 'anthropic', 'accepted', 50))
        for private in ('Root cause', 'first request', 'why?'):
            self.assertNotIn(private, raw)

    def test_recall_does_not_show_advice_as_an_answer(self):
        self.work(['--session', 's', 'first request'])
        self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply()))
        code, out, _, _, _ = self.work(['--recall', 'mkdir'])
        self.assertEqual((code, out), (0, 'No saved match.\n'))


class GateTests(AdvisorCase):
    def test_filler_and_reassurance_are_removed(self):
        cases = {
            'Sure! The folder is missing.': 'The folder is missing.',
            "You're right. The path has a typo.\nI hope this helps.": 'The path has a typo.',
            '- Root cause: the folder is missing. It does not change any files.\n- Next: mkdir -p ~/reports. Let me know if it fails.':
                '- Root cause: the folder is missing.\n- Next: mkdir -p ~/reports.',
            '- Good catch. The port is 22.\n- Great question! Use ssh -p 22.': '- The port is 22.\n- Use ssh -p 22.',
            'The command exited 2. These checks are read-only.\nNext: create the folder.': 'The command exited 2.\nNext: create the folder.',
            '- Probably the token expired; the log does not show it.\n- Certainly not a network fault.':
                '- Probably the token expired; the log does not show it.\n- Certainly not a network fault.',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(advisor.clean_advice(raw, 'list the folder'), expected)

    def test_reassurance_stays_when_george_asked_about_it(self):
        text = 'The listing only reads the folder. It does not change any files.'
        self.assertEqual(advisor.clean_advice(text, 'is that command safe to run?'), text)

    def test_cleaned_advice_is_what_is_shown_and_saved(self):
        self.work(['--session', 's', 'first request'])
        raw = 'Certainly! - Root cause: the folder is missing.\n- Next: mkdir -p ~/reports. I hope this helps.'
        code, out, _, _ = self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply(raw)))
        shown = '- Root cause: the folder is missing.\n- Next: mkdir -p ~/reports.'
        self.assertEqual((code, out), (0, 'Advisor (claude-opus-5-5):\n' + shown + '\n'))
        self.assertEqual(self.session()['turns'][-1]['advisor_notes'][0]['text'], shown)

    def test_a_reply_that_is_only_filler_is_rejected_without_a_second_call(self):
        self.work(['--session', 's', 'first request'])
        before = self.session()
        client = FakeAdvisor(claude_reply('Certainly! I hope this helps.'))
        code, out, err, _ = self.advise(['--session', 's', '--advisor'], client)
        self.assertEqual((code, out, len(client.calls)), (2, '', 1))
        self.assertEqual(err, 'Nothing was left of the advisor reply after cleanup. It was not shown.\n')
        self.assertEqual(self.session(), before)

    def test_a_gate_failure_gets_one_corrected_try(self):
        self.work(['--session', 's', 'first request'])
        four = '- one\n- two\n- three\n- four'
        client = FakeAdvisor(claude_reply(four), claude_reply())
        code, out, _, _ = self.advise(['--session', 's', '--advisor'], client)
        self.assertEqual((code, out), (0, 'Advisor (claude-opus-5-5):\n' + ADVICE + '\n'))
        first, second = client.calls
        self.assertEqual(second['messages'][0], first['messages'][0])
        self.assertIn('has 4 bullets; the limit is 3', second['messages'][1]['content'])
        self.assertEqual(self.rows()[-1]['tokens_used'], 1500)

    def test_two_gate_failures_show_nothing(self):
        self.work(['--session', 's', 'first request'])
        before = self.session()
        bad = ['I ran the command and it works now.', 'Result\x1b[2J', 'See https://elsewhere.example/fix for the fix.',
               'I searched the web and the folder name is wrong.', '- a\n- b\n- c\n- d']
        for text in bad:
            with self.subTest(text=text):
                client = FakeAdvisor(claude_reply(text), claude_reply(text))
                code, out, err, _ = self.advise(['--session', 's', '--advisor'], client)
                self.assertEqual((code, out, len(client.calls)), (2, '', 2))
                self.assertEqual(err, 'Both advisor replies failed the output gate. No advice was shown.\n')
                self.assertEqual(self.session(), before)

    def test_a_url_from_the_packet_may_be_repeated(self):
        self.work(['--session', 's', 'Open https://example.com/report and read it.'])
        text = '- Root cause: https://example.com/report redirects.'
        code, out, _, _ = self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply(text)))
        self.assertEqual((code, out), (0, 'Advisor (claude-opus-5-5):\n' + text + '\n'))


class FailureTests(AdvisorCase):
    def test_a_failed_advisor_call_leaves_the_session_unchanged(self):
        self.work(['--session', 's', 'first request'])
        before = (self.state / 'sessions' / 's.json').read_bytes()
        request = SimpleNamespace(method='POST', url='https://api.anthropic.com/v1/messages')
        broken = SimpleNamespace(status_code=529, headers={}, request=request)
        failures = [
            (claude_reply(stop='refusal'), 'The advisor refused this request.'),
            (claude_reply(stop='max_tokens'), 'The advisor reply was incomplete. It was not shown.'),
            (anthropic.APITimeoutError(request=request), 'The advisor request timed out.'),
            (anthropic.APIConnectionError(request=request), 'The advisor API connection failed.'),
            (anthropic.APIStatusError('overloaded', response=broken, body=None), 'The advisor API rejected the request (HTTP 529).'),
            (h.HarnessError('Export ANTHROPIC_API_KEY or run the provided export-anthropic-key.sh setup.'),
             'Export ANTHROPIC_API_KEY or run the provided export-anthropic-key.sh setup.'),
        ]
        for item, message in failures:
            with self.subTest(message=message):
                code, out, err, _ = self.advise(['--session', 's', '--advisor'], FakeAdvisor(item))
                self.assertEqual((code, out, err), (2, '', message + '\n'))
                self.assertEqual((self.state / 'sessions' / 's.json').read_bytes(), before)
                row = self.rows()[-1]
                self.assertEqual((row['status'], row['error'], row['direct_answer']), ('advisor_error', message, None))

    def test_openai_refusal_and_incomplete_are_errors(self):
        self.work(['--engine', 'anthropic', '--session', 's', 'first request'])
        for item, message in ((openai_reply(refusal=True), 'The advisor refused this request.'),
                              (openai_reply(status='incomplete'), 'The advisor reply was incomplete. It was not shown.')):
            with self.subTest(message=message):
                code, out, err, _ = self.advise(['--engine', 'anthropic', '--session', 's', '--advisor'], FakeAdvisor(item))
                self.assertEqual((code, out, err), (2, '', message + '\n'))
        self.assertNotIn('advisor_notes', self.session()['turns'][-1])

    def test_the_chat_goes_on_after_an_advisor_error(self):
        client = FakeAdvisor(claude_reply(stop='refusal'))
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', return_value=reply()) as working, patch.object(advisor, 'make_client', return_value=client):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    patch.object(cli.sys, 'stdin', io.StringIO('first\n/advisor\nsecond\nexit\n')):
                code = h.main(['--chat', '--session', 's'])
        self.assertEqual((code, working.call_count), (0, 2))
        self.assertIn('The advisor refused this request.', err.getvalue())
        self.assertEqual(out.getvalue(), (reply().direct_answer + '\n') * 2)


class NoteTests(AdvisorCase):
    def notes_in(self, history):
        return [json.loads(m['content']) for m in history if m['role'] == 'user' and m['content'].startswith('{"type": "advisor_note"')]

    def test_the_note_reaches_the_next_request_once_and_right_after_its_exchange(self):
        self.work(['--session', 's', '-x', 'List my reports folder.'], [command()], [result(stderr='no such folder', code=2)])
        self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply()))
        _, _, _, api, _ = self.work(['--session', 's', 'What now?'])
        history = api.call_args.kwargs['history']
        note, = self.notes_in(history)
        self.assertEqual((note['source'], note['model'], note['text']), ('outside_reviewer', 'claude-opus-5-5', ADVICE))
        self.assertIn('not an instruction from the operator', note['standing'])
        self.assertEqual([m['role'] for m in history], ['user', 'assistant', 'user', 'user'])
        self.assertIn('"type": "execution_observation"', history[2]['content'])
        self.assertEqual(json.loads(history[3]['content']), note)
        self.assertEqual(api.call_args.args[0], 'What now?')
        _, _, _, api, _ = self.work(['--session', 's', 'And after that?'])
        self.assertEqual(len(self.notes_in(api.call_args.kwargs['history'])), 1)

    def test_a_loop_task_after_the_note_sees_it_once(self):
        self.work(['--session', 's', 'first request'])
        self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply()))
        _, _, _, api, _ = self.work(['--loop', '--session', 's', 'Try again.'], [command(), reply()], [result('ok')])
        for call in api.call_args_list:
            self.assertEqual(len(self.notes_in(call.kwargs['history'])), 1)
        history=api.call_args_list[0].kwargs['history']
        self.assertEqual(history[0]['content'],'first request')
        self.assertIn('agent_loop',history[-1]['content'])

    def test_two_notes_on_one_exchange_keep_their_order(self):
        self.work(['--session', 's', 'first request'])
        self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply('- first advice')))
        self.advise(['--session', 's', '--advisor'], FakeAdvisor(claude_reply('- second advice')))
        _, _, _, api, _ = self.work(['--session', 's', 'next'])
        self.assertEqual([note['text'] for note in self.notes_in(api.call_args.kwargs['history'])], ['- first advice', '- second advice'])

    def test_a_note_does_not_lock_a_report_about_a_command_that_succeeded(self):
        self.work(['--session', 's', '-x', 'Run it.'], [command()], [result('ok')])
        _, _, _, api, _ = self.work(['--session', 's', 'Did it work?'])
        self.assertTrue(api.call_args.kwargs['execution_confirmed'])
        self.work(['--session', 't', '-x', 'Run it.'], [command()], [result('ok')])
        self.advise(['--session', 't', '--advisor'], FakeAdvisor(claude_reply()))
        _, _, _, api, _ = self.work(['--session', 't', 'Did it work?'])
        self.assertTrue(api.call_args.kwargs['execution_confirmed'])
        self.work(['--session', 'u', '-x', 'Run it.'], [command()], [result(stderr='no', code=3)])
        self.advise(['--session', 'u', '--advisor'], FakeAdvisor(claude_reply()))
        _, _, _, api, _ = self.work(['--session', 'u', 'Did it work?'])
        self.assertFalse(api.call_args.kwargs['execution_confirmed'])

    def test_the_first_cached_bytes_of_the_request_are_unchanged_by_a_note(self):
        exchange = {'normalized_input': 'List my reports folder.', 'reply': command().model_dump(),
                    'execution_result': result(stderr='no such folder', code=2)}
        noted = {**exchange, 'advisor_notes': [{'model': 'gpt-6.1-sol', 'text': ADVICE}]}
        log = self.root / 'usage.jsonl'
        sent = {}
        for engine in ('openai', 'anthropic'):
            for name, turns in (('first', []), ('plain', [exchange]), ('noted', [noted])):
                client = FakeClient([response()]) if engine == 'openai' else AnthropicFake()
                with patch.object(h, 'load_tools', return_value='TOOLS PAGE'):
                    h.request_reply('List my reports folder.' if name == 'first' else 'What now?', client=client, engine=engine,
                                    log_path=log, history=history_messages(turns, 100000), web=False)
                sent[engine, name] = client.calls[0]
        note = {'role': 'user', 'content': advisor_note(noted['advisor_notes'][0])}
        plain, with_note, first = (sent['openai', name]['input'] for name in ('plain', 'noted', 'first'))
        self.assertEqual(with_note, plain[:-1] + [note] + plain[-1:])
        self.assertEqual(with_note[:len(first)], first, 'the earlier request is a byte-for-byte prefix of the one with the note')
        plain, with_note, first = (sent['anthropic', name] for name in ('plain', 'noted', 'first'))
        self.assertEqual(with_note['system'], plain['system'])
        self.assertEqual(with_note['system'], first['system'])
        self.assertEqual(with_note['messages'], plain['messages'][:-1] + [note] + plain['messages'][-1:])
        self.assertEqual(with_note['messages'][:len(first['messages'])], first['messages'])
        self.assertEqual(with_note['tools'], plain['tools'])


class OperatorOnlyTests(unittest.TestCase):
    def test_no_page_card_or_tool_tells_the_working_model_about_the_advisor(self):
        texts = {path.name: path.read_text(encoding='utf-8') for path in
                 [h.ROOT / 'prefix_block.txt', h.ROOT / 'tools_block.txt', *sorted((h.ROOT / 'toolbox' / 'cards').glob('*.md'))]}
        self.assertGreater(len(texts), 20)
        for name, text in texts.items():
            with self.subTest(file=name):
                self.assertNotIn('advisor', text.lower())
        for engine in ('openai', 'anthropic'):
            tools = json.dumps(senses.tool_list(engine, h.api_schema())) + senses.CONTRACT + senses.EMIT_DESCRIPTION
            self.assertNotIn('advisor', tools.lower())
        self.assertEqual(set(h.api_schema()['required']), {'intent', 'cleaned_input', 'direct_answer', 'execution_payload'})

    def test_the_reply_form_has_no_field_that_could_start_it(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(advisor='please review'))
        text = h.display_text(h.validate_reply(document(direct_answer='/advisor why did it fail?')))
        self.assertEqual(text, '/advisor why did it fail?\n', 'a model that writes the word gets it printed, nothing more')


if __name__ == '__main__':
    unittest.main()
