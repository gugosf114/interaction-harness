"""The judge: the other engine reads each reply; a fail gets one corrective retry; a judge failure passes through."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import anthropic

import advisor
import cli
import gate_rules
import harness as h
import reply_judge
from test_advisor import FakeAdvisor, claude_reply, openai_reply
from test_harness import FakeClient, document, response

QUESTION = 'What is the capital of France?'
WRONG = 'chmod 640 gives the owner read and write access.'
RIGHT = 'Paris.'
REASON = 'The reply explains a file mode, and the request asks for the capital of France; answer that question.'


def reply(answer, payload=None):
    return document(intent='action_request' if payload else 'observation', direct_answer=answer, execution_payload=payload)


def verdict(value='pass', reason='ok', **extra):
    return {'engine': 'anthropic', 'model': h.ANTHROPIC_MODEL, 'verdict': value, 'reason': reason, 'status': 'ok', **extra}


class FakeJudge:
    """Stands in for reply_judge.ask: records each packet and plays back queued verdicts."""
    def __init__(self, *verdicts):
        self.queue = list(verdicts)
        self.packets = []
        self.calls = []

    def __call__(self, packet, **kwargs):
        self.packets.append(json.loads(packet))
        self.calls.append(kwargs)
        return dict(self.queue.pop(0))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'usage.jsonl'
        for target, name, value in ((h, 'STATE', self.root), (reply_judge, 'LIVE', True)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask_through(self, judge, client, question=QUESTION, turn=None, **kwargs):
        second = reply_judge.Second(judge)
        events = []
        out = second.request_reply(question, judge_turn=turn if turn is not None else {'turns': [], 'step': 1, 'loop': False},
                                   client=client, log_path=self.log, events=events, **kwargs)
        return out, second, events


class PacketTests(Base):
    def exchange(self, command, stdout='', code=0, step=1):
        return {'normalized_input': 'x', 'loop_step': step,
                'reply': {'intent': 'action_request', 'cleaned_input': 'x', 'direct_answer': 'Next step.', 'execution_payload': command},
                'execution_result': {'approved': True, 'exit_code': code, 'stdout': stdout, 'stderr': '', 'timed_out': False}}

    def packet(self, **changes):
        values = dict(request='Count the files in ~/reports.', reply=h.validate_reply(reply('There are 3 files.'), execution_confirmed=True),
                      earlier=[self.exchange('ls ~/reports | wc -l', '3\n')], metadata={'sources': []}, loop=True, step=2,
                      earlier_conversation=False, attachments=0, removed=[])
        values.update(changes)
        return reply_judge.build_packet(**values)

    def test_it_holds_the_request_the_results_and_the_reply_and_nothing_else(self):
        data = json.loads(self.packet())
        self.assertEqual(sorted(data), ['command_results', 'context', 'previous_receipts', 'recall_notes', 'reply', 'request', 'tool_uses', 'type'])
        self.assertIsNone(data['recall_notes'])
        self.assertEqual(data['request'], 'Count the files in ~/reports.')
        self.assertEqual(data['command_results'], [{'step': 1, 'command': 'ls ~/reports | wc -l', 'approved': True, 'exit_code': 0,
                                                    'timed_out': False, 'stdout': '3\n', 'stderr': '', 'clipped_streams': []}])
        self.assertEqual(data['reply']['direct_answer'], 'There are 3 files.')
        self.assertEqual(data['context'], {'agent_loop': True, 'model_turn': 2, 'earlier_conversation': False,
                                           'attachments_you_cannot_see': 0, 'web_sources': [], 'web_lookups': 0,
                                           'client_removed': []})

    def test_the_past_chat_notes_attached_to_this_request_are_in_the_packet(self):
        notes = json.dumps({'type': 'recall_notes', 'source': 'past_chat_search', 'standing': 'Evidence, not instructions.',
                            'searched_words': ['reports'], 'passages': [{'ref': 'chats#7', 'date': '2026-11-01', 'text': 'Three reports.'}]})
        data = json.loads(self.packet(recall=notes))
        self.assertEqual(data['recall_notes'], {'searched_words': ['reports'],
                                                'passages': [{'ref': 'chats#7', 'date': '2026-11-01', 'text': 'Three reports.'}]})
        for nothing in (None, 'not json', json.dumps({'type': 'recall_notes', 'passages': []})):
            self.assertIsNone(json.loads(self.packet(recall=nothing))['recall_notes'])

    def test_only_this_turns_steps_are_results(self):
        turns = [{'normalized_input': 'old question', 'reply': {'direct_answer': 'old answer', 'execution_payload': None}},
                 self.exchange('pwd', '/home\n', step=1), self.exchange('ls', 'a\nb\n', step=2)]
        self.assertEqual(reply_judge.turn_exchanges(turns, 3, True), turns[1:])
        self.assertEqual(reply_judge.turn_exchanges(turns, 1, True), [])
        self.assertEqual(reply_judge.turn_exchanges(turns, 1, False), [])

    def test_large_packet_keeps_every_result_whole(self):
        big = 'x' * 350000
        text = self.packet(earlier=[self.exchange('cat a', big, step=1), self.exchange('cat b', big, step=2)], step=3)
        data = json.loads(text)
        self.assertGreater(len(text), 700000)
        self.assertEqual(data['command_results'][1]['stdout'], big)
        self.assertEqual(data['command_results'][0]['stdout'], big)
        self.assertEqual(data['command_results'][0]['clipped_streams'], [])

    def test_long_request_is_kept_for_provider_to_accept_or_refuse(self):
        request='y' * 700000
        self.assertEqual(json.loads(self.packet(request=request))['request'],request)


class AskTests(Base):
    def ask(self, client, engine='openai'):
        return reply_judge.ask('{"type":"judge_packet"}', engine=engine, model='judge-model', effort='max', timeout=30,
                               client=client, log_path=self.log)

    def test_openai_gets_the_prompt_and_the_packet_with_no_tools_and_no_history(self):
        client = FakeAdvisor(openai_reply(json.dumps({'verdict': 'fail', 'reason': REASON})))
        record = self.ask(client)
        self.assertEqual((record['verdict'], record['reason'], record['status']), ('fail', REASON, 'ok'))
        call = client.calls[0]
        self.assertEqual(call['instructions'], reply_judge.SYSTEM_PROMPT)
        self.assertEqual(call['input'], [{'role': 'user', 'content': '{"type":"judge_packet"}'}])
        self.assertEqual(call['text'], {'format': {'type': 'json_schema', 'name': 'judge_verdict', 'strict': True,
                                                   'schema': reply_judge.SCHEMA}})
        self.assertNotIn('tools', call)
        self.assertIs(call['store'], False)
        self.assertEqual(call['reasoning'], {'effort': 'max'})

    def test_claude_gets_the_prompt_and_the_packet_with_no_tools_and_no_history(self):
        client = FakeAdvisor(claude_reply(json.dumps({'verdict': 'pass', 'reason': 'ok'})))
        record = self.ask(client, engine='anthropic')
        self.assertEqual((record['verdict'], record['status']), ('pass', 'ok'))
        call = client.calls[0]
        self.assertEqual(call['system'], reply_judge.SYSTEM_PROMPT)
        self.assertEqual(call['messages'], [{'role': 'user', 'content': '{"type":"judge_packet"}'}])
        self.assertEqual(call['output_config'], {'effort': 'max', 'format': {'type': 'json_schema', 'schema': reply_judge.SCHEMA}})
        self.assertNotIn('tools', call)
        self.assertNotIn('temperature', call)

    def test_anything_but_the_strict_json_is_no_verdict(self):
        for text in ('pass', '{"verdict": "maybe", "reason": "x"}', '{"verdict": "pass"}', '[1]',
                     '{"verdict": "fail", "reason": ""}', '{"verdict": "pass", "reason": "ok", "extra": 1}',
                     'Here is my verdict: {"verdict": "pass", "reason": "ok"}'):
            with self.subTest(text=text):
                record = self.ask(FakeAdvisor(openai_reply(text)))
                self.assertEqual((record['verdict'], record['status']), (None, 'not_strict_json'))

    def test_a_timeout_an_api_error_a_refusal_and_a_missing_key_give_no_verdict(self):
        request = SimpleNamespace(method='POST', url='https://api.anthropic.com/v1/messages')
        broken = SimpleNamespace(status_code=529, headers={}, request=request)
        cases = [(anthropic.APITimeoutError(request=request), 'timeout'),
                 (anthropic.APIStatusError('overloaded', response=broken, body=None), 'error'),
                 (claude_reply('', stop='refusal'), 'refusal'), (claude_reply('', stop='max_tokens'), 'incomplete'),
                 (OSError('network down'), 'error')]
        for item, status in cases:
            with self.subTest(status=status, item=type(item).__name__):
                record = self.ask(FakeAdvisor(item), engine='anthropic')
                self.assertEqual((record['verdict'], record['status']), (None, status))
        with patch.object(advisor, 'make_client', side_effect=h.HarnessError('Export OPENAI_API_KEY.')):
            record = reply_judge.ask('{}', engine='openai', model='m', effort='max', timeout=30, log_path=self.log)
        self.assertEqual((record['verdict'], record['status'], record['error']), (None, 'error', 'Export OPENAI_API_KEY.'))

    def test_the_judge_log_sits_next_to_the_usage_log_and_holds_no_text(self):
        self.ask(FakeAdvisor(openai_reply(json.dumps({'verdict': 'fail', 'reason': REASON}))))
        self.assertFalse(self.log.exists())
        lines = (self.root / 'judge.jsonl').read_text().splitlines()
        event = json.loads(lines[0])
        self.assertEqual((event['kind'], event['status'], event['verdict'], event['engine']), ('judge', 'ok', 'fail', 'openai'))
        self.assertNotIn(REASON, lines[0])
        self.assertNotIn('judge_packet', lines[0])
        self.assertEqual(event['usage']['input_tokens'], 900)


class FlowTests(Base):
    def test_a_wrong_question_reply_is_failed_by_the_judge_and_retried_once(self):
        judge = FakeJudge(verdict('fail', REASON), verdict())
        client = FakeClient([response(reply(WRONG)), response(reply(RIGHT))])
        out, second, events = self.ask_through(judge, client)
        self.assertEqual(out.direct_answer, RIGHT)
        self.assertEqual(len(client.calls), 2)
        tail = client.calls[1]['input'][-3:]
        self.assertEqual(tail[0], {'role': 'user', 'content': QUESTION})
        self.assertEqual(json.loads(tail[1]['content'])['direct_answer'], WRONG)
        self.assertEqual(tail[1]['role'], 'assistant')
        self.assertIn(REASON, tail[2]['content'])
        self.assertIn('A second reviewer', tail[2]['content'])
        # Everything before the tail is what the first call sent: the cached front is unchanged.
        self.assertEqual(client.calls[1]['input'][:-3], client.calls[0]['input'][:-1])
        self.assertEqual([(r['reply'], r['verdict']) for r in second.records], [(1, 'fail'), (2, 'pass')])
        self.assertEqual(judge.packets[0]['request'], QUESTION)
        self.assertEqual(judge.packets[0]['reply']['direct_answer'], WRONG)
        self.assertEqual(judge.packets[1]['reply']['direct_answer'], RIGHT)
        self.assertEqual([event['status'] for event in events], ['accepted', 'accepted'])

    def test_the_judge_is_the_other_engine_at_the_lanes_effort(self):
        judge = FakeJudge(verdict())
        self.ask_through(judge, FakeClient([response(reply(RIGHT))]), engine='openai', effort='xhigh', timeout=77)
        self.assertEqual(judge.calls[0]['engine'], 'anthropic')
        self.assertEqual(judge.calls[0]['model'], h.ANTHROPIC_MODEL)
        self.assertEqual((judge.calls[0]['effort'], judge.calls[0]['timeout']), ('xhigh', 77))

    def test_the_judge_uses_the_lane_timeout(self):
        judge = FakeJudge(verdict())
        self.ask_through(judge, FakeClient([response(reply(RIGHT))]), engine='openai', effort='max', timeout=1800)
        self.assertEqual(judge.calls[0]['timeout'], 1800)

    def test_a_second_fail_is_shown_anyway(self):
        judge = FakeJudge(verdict('fail', REASON), verdict('fail', 'Still the wrong question; name the capital.'))
        client = FakeClient([response(reply(WRONG)), response(reply('The file mode is 640.'))])
        out, second, _ = self.ask_through(judge, client)
        self.assertEqual(out.direct_answer, 'The file mode is 640.')
        self.assertEqual(len(client.calls), 2)
        self.assertEqual([r['verdict'] for r in second.records], ['fail', 'fail'])

    def test_a_judge_timeout_passes_the_reply_through(self):
        request = SimpleNamespace(method='POST', url='https://api.anthropic.com/v1/messages')
        judge_client = FakeAdvisor(anthropic.APITimeoutError(request=request))
        client = FakeClient([response(reply(WRONG))])
        with patch.object(advisor, 'make_client', return_value=judge_client):
            out, second, _ = self.ask_through(None, client)
        self.assertEqual(out.direct_answer, WRONG)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(judge_client.calls), 1)
        self.assertEqual([(r['status'], r['verdict']) for r in second.records], [('timeout', None)])

    def test_a_judge_error_passes_the_reply_through(self):
        for record in (verdict(None, '', status='error'), verdict(None, '', status='not_strict_json'),
                       verdict(None, '', status='refusal')):
            with self.subTest(status=record['status']):
                client = FakeClient([response(reply(WRONG))])
                out, second, _ = self.ask_through(FakeJudge(record), client)
                self.assertEqual(out.direct_answer, WRONG)
                self.assertEqual(len(client.calls), 1)

    def test_a_pass_makes_no_second_call(self):
        client = FakeClient([response(reply(RIGHT))])
        out, second, _ = self.ask_through(FakeJudge(verdict()), client)
        self.assertEqual((out.direct_answer, len(client.calls)), (RIGHT, 1))
        self.assertEqual(len(second.records), 1)

    def test_when_the_corrected_reply_fails_the_local_gate_the_first_reply_stands(self):
        judge = FakeJudge(verdict('fail', REASON))
        client = FakeClient([response(reply(WRONG)), response(reply('Sure, I hope this helps.')), response(reply('I hope this helps.'))])
        out, second, events = self.ask_through(judge, client)
        self.assertEqual(out.direct_answer, WRONG)
        self.assertEqual(len(judge.packets), 1)
        self.assertIn('Both replies failed', second.records[0]['retry_error'])
        # The shown reply's own event stays last, so its sources and counts are the ones saved with the turn.
        self.assertEqual([event['status'] for event in events], ['gate_rejected', 'gate_rejected', 'accepted'])

    def test_the_judge_is_told_what_the_gate_rules_cut(self):
        rules = self.root / 'gate_rules.json'
        with patch.object(gate_rules, 'RULES_FILE', rules):
            gate_rules.write_entries(rules, [{'name': 'sign-off', 'pattern': r'\bstay hydrated\b', 'action': 'strip_sentence',
                                              'bad': ['Stay hydrated.'], 'date': '2026-11-11', 'history_row': 1}])
            judge = FakeJudge(verdict())
            out, second, _ = self.ask_through(judge, FakeClient([response(reply('Paris. Stay hydrated.'))]))
        self.assertEqual(out.direct_answer, 'Paris.')
        self.assertEqual(judge.packets[0]['context']['client_removed'], ['Stay hydrated.'])
        self.assertEqual(second.fired[0]['name'], 'sign-off')

    def test_off_and_on(self):
        self.assertTrue(reply_judge.is_on(self.root))
        (self.root / 'switches.json').write_text('{"stamp": false}')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(reply_judge.chat_switch('/off judge', self.root), 0)
        self.assertEqual(err.getvalue(), 'judge off.\n')
        self.assertEqual(json.loads((self.root / 'switches.json').read_text()), {'stamp': False, 'judge': False})
        judge = FakeJudge()
        out, second, _ = self.ask_through(judge, FakeClient([response(reply(WRONG))]))
        self.assertEqual((out.direct_answer, judge.packets, second.records), (WRONG, [], []))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reply_judge.chat_switch('/on judge', self.root), 0)
        self.assertTrue(reply_judge.is_on(self.root))
        for line in ('/on web_search', '/off', '/on judge now', 'judge off', '/wrong judge'):
            self.assertIsNone(reply_judge.chat_switch(line, self.root))

    def test_without_the_command_line_entry_point_no_judge_is_called(self):
        judge = FakeJudge()
        with patch.object(reply_judge, 'LIVE', False):
            out, _, _ = self.ask_through(judge, FakeClient([response(reply(WRONG))]))
        self.assertEqual((out.direct_answer, judge.packets), (WRONG, []))


class ClientTests(Base):
    """The judge inside the real command-line flow, with the working model and the judge both faked."""

    def run_client(self, argv, answers, results=(), judge=None, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=answers) as api, patch.object(cli, 'native', side_effect=results), \
                patch.object(reply_judge, 'ask', judge or FakeJudge()), patch.object(cli.sys, 'stdin', io.StringIO(stdin)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(argv)
        return code, out.getvalue(), err.getvalue(), api

    def rows(self):
        db = sqlite3.connect(self.root / 'history.db')
        db.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in db.execute('SELECT * FROM history ORDER BY id')]
        finally:
            db.close()

    def test_each_loop_step_is_judged_with_this_turns_results_and_the_verdict_is_saved(self):
        step_one = h.validate_reply(reply('This counts the files.', 'ls ~/reports | wc -l'))
        wrong = h.validate_reply(reply('There are 9 files.'), execution_confirmed=True)
        right = h.validate_reply(reply('There are 3 files.'), execution_confirmed=True)
        judge = FakeJudge(verdict(), verdict('fail', 'The result shows 3, and the reply says 9; state the count the command printed.'),
                          verdict())
        code, out, err, api = self.run_client(
            ['--loop', '--session', 'count', 'Count the files in ~/reports.'], [step_one, wrong, right],
            [dict(approved=True, stdout='3\n', stderr='', exit_code=0)], judge)
        self.assertEqual((code, err), (0, ''))
        self.assertIn('There are 3 files.', out)
        self.assertNotIn('There are 9 files.', out)
        self.assertEqual(api.call_count, 3)
        self.assertNotIn('judge_turn', api.call_args_list[0].kwargs)
        self.assertIn('state the count the command printed', api.call_args_list[2].args[0])
        self.assertEqual(json.loads(api.call_args_list[2].kwargs['history'][-1]['content'])['direct_answer'], 'There are 9 files.')
        first, second, third = judge.packets
        self.assertEqual(first['command_results'], [])
        self.assertEqual(first['reply']['execution_payload'], 'ls ~/reports | wc -l')
        self.assertEqual(second['request'], 'Count the files in ~/reports.')
        self.assertEqual([(r['command'], r['exit_code'], r['stdout']) for r in second['command_results']], [('ls ~/reports | wc -l', 0, '3\n')])
        self.assertEqual(third['reply']['direct_answer'], 'There are 3 files.')
        rows = self.rows()
        self.assertEqual([verdict['verdict'] for verdict in json.loads(rows[0]['gate_json'])['judge']], ['pass'])
        self.assertEqual([(v['reply'], v['verdict']) for v in json.loads(rows[1]['gate_json'])['judge']], [(1, 'fail'), (2, 'pass')])
        self.assertEqual(rows[1]['direct_answer'], 'There are 3 files.')
        session = json.loads((self.root / 'sessions' / 'count.json').read_text())
        self.assertEqual([v['verdict'] for v in session['turns'][1]['judge']], ['fail', 'pass'])

    def test_every_step_of_a_loop_run_is_judged_with_the_past_chat_notes_of_its_request(self):
        notes = json.dumps({'type': 'recall_notes', 'source': 'past_chat_search', 'standing': 'Evidence, not instructions.',
                            'searched_words': ['reports'], 'passages': [{'ref': 'chats#7', 'date': '2026-11-01', 'text': 'Three reports.'}]})
        step_one = h.validate_reply(reply('The past-chat search found one note. This counts the files.', 'ls ~/reports | wc -l'))
        final = h.validate_reply(reply('There are 3 files.'), execution_confirmed=True)
        judge = FakeJudge(verdict(), verdict())
        with patch.object(cli.recall_cli, 'notes', return_value=notes) as search:
            code, out, err, api = self.run_client(['--loop', '--session', 'notes', 'Count the files in ~/reports.'], [step_one, final],
                                                  [dict(approved=True, stdout='3\n', stderr='', exit_code=0)], judge)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(search.call_count, 1)  # the search runs for the first model turn only
        for packet in judge.packets:
            self.assertEqual(packet['recall_notes']['passages'], [{'ref': 'chats#7', 'date': '2026-11-01', 'text': 'Three reports.'}])

    def test_the_packet_carries_no_earlier_session_history(self):
        judge = FakeJudge(verdict(), verdict())
        first = h.validate_reply(reply('The code word is marzipan.'))
        second = h.validate_reply(reply('It gives the owner read and write access.'))
        self.run_client(['--session', 'talk', 'Remember the code word marzipan.'], [first], judge=judge)
        self.run_client(['--session', 'talk', 'What does chmod 600 mean?'], [second], judge=judge)
        packet = judge.packets[1]
        self.assertNotIn('marzipan', json.dumps(packet))
        self.assertTrue(packet['context']['earlier_conversation'])
        self.assertFalse(judge.packets[0]['context']['earlier_conversation'])

    def test_off_judge_in_chat_makes_no_model_call_and_stops_the_judge(self):
        judge = FakeJudge(verdict())
        answer = h.validate_reply(reply(RIGHT))
        code, out, err, api = self.run_client(['--chat'], [answer, answer], judge=judge,
                                              stdin='/off judge\nfirst question\n/on judge\nsecond question\nexit\n')
        self.assertEqual(code, 0)
        self.assertEqual(api.call_count, 2)
        self.assertIn('judge off.', err)
        self.assertIn('judge on.', err)
        self.assertEqual(len(judge.packets), 1)
        self.assertEqual(judge.packets[0]['request'], 'second question')
        self.assertEqual(out.count(RIGHT), 2)

    def test_off_judge_typed_as_the_whole_question(self):
        code, out, err, api = self.run_client(['/off judge'], [])
        self.assertEqual((code, out, err, api.call_count), (0, '', 'judge off.\n', 0))
        self.assertFalse(reply_judge.is_on(self.root))


if __name__ == '__main__':
    unittest.main()
