"""The per-turn rules stamp: read at run time, last in every request, never saved, switched by /on and /off.

No test here reads the operator's real rules file. Every test points the stamp at a temporary file,
and a plain import leaves the stamp off.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cli
import harness as h
import stamp
from storage import history_messages
from test_harness import FakeClient, document, response
from test_tools_block import AnthropicFake

RULES_FILE = """# Operating rules

1. **A numbered line above the section is not a rule.** STAMP-OUTSIDE-MARK-12

## Core interaction contract

These four rules control any broader line below that disagrees.

1. **Clarify first.** If the meaning is unclear, ask. STAMP-BODY-MARK-41

2. **Answer fast, short, simple, and to the point. Talk like to a toddler.** The first sentence gives the answer.

3. **Use mistakes.** A mistake is useful evidence.

4. **Share ideas; the operator decides.** Give the confidence and the main catch.

Plain **bold words** inside a paragraph are not a rule.

## Another section

1. **Not in the contract.** STAMP-OTHER-MARK-77
"""
FOUR = ['Clarify first.', 'Answer fast, short, simple, and to the point. Talk like to a toddler.',
        'Use mistakes.', 'Share ideas; the operator decides.']


def plain(messages):
    """The messages with the cache marker taken off: a marked one-block text message reads as its plain text again."""
    out = []
    for message in messages:
        content = message['content']
        if isinstance(content, list):
            content = [{k: v for k, v in block.items() if k != 'cache_control'} for block in content]
            if len(content) == 1 and content[0] == {'type': 'text', 'text': content[0].get('text')}:
                content = content[0]['text']
        out.append({**message, 'content': content})
    return out


def markers(value):
    """How many cache markers a request holds, anywhere in it."""
    if isinstance(value, dict):
        return int('cache_control' in value) + sum(markers(item) for item in value.values())
    if isinstance(value, list):
        return sum(markers(item) for item in value)
    return 0


def command(text='printf test'):
    return h.validate_reply(document(intent='action_request', direct_answer='This runs the next step.', execution_payload=text))


class StampCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules = self.root / 'rules.md'
        self.rules.write_text(RULES_FILE, encoding='utf-8')
        self.state = self.root / 'state'
        self.log = self.root / 'usage.jsonl'
        patcher = patch.object(h, 'STATE', self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, engine='openai', source='rules', text='Explain compound interest.', **kwargs):
        client = FakeClient([response()]) if engine == 'openai' else AnthropicFake()
        with patch.object(h, 'STAMP_SOURCE', self.rules if source == 'rules' else source), \
                patch.object(h, 'load_tools', return_value='TOOLS PAGE'):
            h.request_reply(text, client=client, engine=engine, log_path=self.log, web=False, **kwargs)
        return client.calls[0]

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


class ReadingTests(StampCase):
    def test_headlines_are_the_bold_openers_of_the_numbered_rules_word_for_word(self):
        self.assertEqual(stamp.headlines(self.rules), FOUR)

    def test_only_the_named_section_is_read(self):
        text = stamp.record(stamp.headlines(self.rules))
        for absent in ('STAMP-OUTSIDE-MARK-12', 'STAMP-BODY-MARK-41', 'STAMP-OTHER-MARK-77', 'bold words', 'Not in the contract'):
            self.assertNotIn(absent, text)

    def test_the_record_is_typed_json_that_holds_the_rules_and_says_it_is_not_a_request(self):
        data = json.loads(stamp.record(FOUR))
        self.assertEqual(data['type'], 'operator_rules_stamp')
        self.assertEqual(data['rules'], FOUR)
        self.assertEqual(set(data), {'type', 'source', 'rules', 'standing'})
        self.assertIn('not a new request', data['standing'])
        self.assertEqual(stamp.record(FOUR), stamp.record(list(FOUR)), 'the same rules give the same bytes')

    def test_an_edit_to_the_rules_file_reaches_the_next_request(self):
        first = json.loads(self.ask()['input'][-1]['content'])['rules']
        self.rules.write_text(RULES_FILE.replace('**Use mistakes.**', '**Use every mistake.**'), encoding='utf-8')
        second = json.loads(self.ask()['input'][-1]['content'])['rules']
        self.assertEqual((first[2], second[2]), ('Use mistakes.', 'Use every mistake.'))

    def test_a_fifth_rule_in_the_file_is_stamped_too(self):
        self.rules.write_text(RULES_FILE.replace('Plain **bold', '5. **Keep the thread.** Follow it.\n\nPlain **bold'), encoding='utf-8')
        self.assertEqual(stamp.headlines(self.rules), FOUR + ['Keep the thread.'])

    def test_a_bad_source_stops_the_run_before_any_api_call(self):
        cases = {
            'missing': (self.root / 'absent.md', 'missing or unreadable'),
            'no heading': (self.root / 'no-heading.md', 'no single "## Core interaction contract" section'),
            'twice': (self.root / 'twice.md', 'no single "## Core interaction contract" section'),
            'no rules': (self.root / 'no-rules.md', 'no numbered bold rule headline'),
        }
        (self.root / 'no-heading.md').write_text('# Rules\n\n1. **Clarify first.** Ask.\n')
        (self.root / 'twice.md').write_text('## Core interaction contract\n\n1. **A.** x\n\n## Core interaction contract\n\n1. **B.** y\n')
        (self.root / 'no-rules.md').write_text('## Core interaction contract\n\nJust a paragraph.\n')
        for name, (path, pattern) in cases.items():
            with self.subTest(case=name):
                client = FakeClient([])
                with patch.object(h, 'STAMP_SOURCE', path), self.assertRaisesRegex(h.HarnessError, pattern):
                    h.request_reply('Explain.', client=client, log_path=self.log)
                self.assertEqual(client.calls, [], 'the API must not be called')

    def test_the_shipped_source_is_the_core_contract_of_the_operator_rules_file(self):
        self.assertEqual(str(stamp.SOURCE), '/root/.claude/CLAUDE.md')
        self.assertEqual(stamp.HEADING, '## Core interaction contract')


class RequestTests(StampCase):
    def test_a_plain_import_leaves_the_stamp_off(self):
        self.assertIsNone(h.STAMP_SOURCE)
        self.assertIsNone(h.load_stamp())
        sent = self.ask(source=None)['input']
        self.assertEqual(sent[-1]['content'], 'Explain compound interest.')
        self.assertIsNone(self.events()[-1]['stamp_sha256'])

    def test_openai_the_stamp_is_the_last_message_and_the_request_sits_right_before_it(self):
        sent = self.ask('openai')['input']
        self.assertEqual([m['role'] for m in sent], ['system', 'system', 'user', 'user'])
        self.assertEqual(sent[-2]['content'], 'Explain compound interest.')
        self.assertEqual(sent[-1], {'role': 'user', 'content': stamp.record(FOUR)})
        self.assertTrue(stamp.is_stamp(sent[-1]))
        self.assertFalse(stamp.is_stamp(sent[-2]))

    def test_anthropic_the_stamp_is_the_last_message_and_the_system_pages_are_untouched(self):
        with_stamp, without = self.ask('anthropic'), self.ask('anthropic', source=None)
        self.assertEqual(with_stamp['system'], without['system'])
        self.assertEqual(with_stamp['tools'], without['tools'])
        self.assertEqual(with_stamp['messages'][-1], {'role': 'user', 'content': stamp.record(FOUR)})
        self.assertEqual(plain(with_stamp['messages']), without['messages'] + [{'role': 'user', 'content': stamp.record(FOUR)}])

    def test_everything_before_the_stamp_is_byte_identical_to_a_request_without_it(self):
        history = history_messages([{'normalized_input': 'Earlier question.', 'reply': json.loads(document())}], 100000)
        for engine, key in (('openai', 'input'), ('anthropic', 'messages')):
            with self.subTest(engine=engine):
                with_stamp = self.ask(engine, history=history)
                without = self.ask(engine, source=None, history=history)
                # On Claude only the cache marker moves; every word and every other setting is the same.
                self.assertEqual(plain(with_stamp[key])[:-1], without[key])
                rest = lambda call: {k: v for k, v in call.items() if k not in (key, 'cache_control')}
                self.assertEqual(rest(with_stamp), rest(without))
                # One more marker with the stamp: the conversation marker before it, next to the automatic one.
                self.assertEqual(markers(with_stamp), markers(without) + (1 if engine == 'anthropic' else 0))
        self.assertEqual(self.ask('openai', history=history)['input'][:-1], self.ask('openai', source=None, history=history)['input'])

    def test_the_stamp_is_byte_identical_from_call_to_call(self):
        first, second = self.ask(text='First question.'), self.ask(text='A different question.')
        self.assertEqual(first['input'][-1], second['input'][-1])

    def test_a_corrective_retry_keeps_the_stamp_and_adds_the_correction_after_it(self):
        client = FakeClient([response(document(intent='invalid_intent')), response()])
        with patch.object(h, 'STAMP_SOURCE', self.rules):
            h.request_reply('Explain.', client=client, log_path=self.log, web=False)
        first, second = (call['input'] for call in client.calls)
        self.assertEqual(second[:len(first)], first)
        self.assertTrue(stamp.is_stamp(first[-1]))
        self.assertIn('Local validation rejected the reply', second[-1]['content'])

    def test_usage_record_holds_the_digest_and_no_rule_text(self):
        self.ask('openai')
        self.ask('anthropic')
        raw = self.log.read_text()
        for event in self.events():
            self.assertEqual(event['stamp_sha256'], hashlib.sha256(stamp.record(FOUR).encode('utf-8')).hexdigest())
        for secret in ('Clarify first', 'toddler', 'Use mistakes', 'Share ideas', 'STAMP-BODY-MARK-41'):
            self.assertNotIn(secret, raw)


class ExtraLaneTests(StampCase):
    """The four extra lanes (lane_base.request_reply) carry the same stamp after the request."""

    def lane(self, engine, client, source='rules', **kwargs):
        events = []
        with patch.object(h, 'STAMP_SOURCE', self.rules if source == 'rules' else source), \
                patch.object(h, 'load_tools', return_value='TOOLS PAGE'):
            h.request_reply('Explain compound interest.', engine=engine, client=client, events=events,
                            log_path=self.log, web=False, **kwargs)
        return events

    def test_gemini_gets_the_stamp_as_the_last_part_after_the_request(self):
        from test_extra_lanes import FakePost, gemini_payload
        post = FakePost([gemini_payload('Interest earns interest.')])
        events = self.lane('gemini', post)
        parts = post.calls[0]['body']['contents'][-1]['parts']
        self.assertEqual([part['text'] for part in parts], ['Explain compound interest.', stamp.record(FOUR)])
        self.assertEqual(events[-1]['stamp_sha256'], hashlib.sha256(stamp.record(FOUR).encode('utf-8')).hexdigest())

    def test_the_chat_completions_lanes_get_the_stamp_as_the_last_message(self):
        from test_extra_lanes import FakeChat, chat_resp
        for engine, text in (('openrouter', document(direct_answer='Interest earns interest.')), ('glm', 'Interest earns interest.')):
            with self.subTest(engine=engine):
                chat = FakeChat([chat_resp(text)])
                with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-test-key'}):
                    self.lane(engine, chat)
                sent = chat.calls[0]['messages']
                self.assertEqual(sent[-2], {'role': 'user', 'content': 'Explain compound interest.'})
                self.assertEqual(sent[-1], {'role': 'user', 'content': stamp.record(FOUR)})

    def test_vertex_gets_the_stamp_as_the_last_message(self):
        from test_extra_lanes import FakePost, vertex_payload
        post = FakePost([vertex_payload('Interest earns interest.')])
        self.lane('vertex', post)  # a supplied client means no gcloud token is asked for
        sent = post.calls[0]['body']['messages']
        self.assertEqual(sent[-2:], [{'role': 'user', 'content': 'Explain compound interest.'},
                                     {'role': 'user', 'content': stamp.record(FOUR)}])

    def test_an_extra_lane_with_the_stamp_off_sends_the_request_last(self):
        from test_extra_lanes import FakePost, gemini_payload
        post = FakePost([gemini_payload('Interest earns interest.')])
        events = self.lane('gemini', post, source=None)
        self.assertEqual([part['text'] for part in post.calls[0]['body']['contents'][-1]['parts']], ['Explain compound interest.'])
        self.assertIsNone(events[-1]['stamp_sha256'])

    def test_the_operator_set_opening_comes_after_the_stamp(self):
        from test_extra_lanes import FakeChat, chat_resp
        import knobs as knobs_mod
        chat = FakeChat([chat_resp(document(direct_answer='In short: interest earns interest.'))])
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-test-key'}):
            self.lane('openrouter', chat, knobs=knobs_mod.Knobs(prefill='In short:'))
        sent = chat.calls[0]['messages']
        self.assertEqual(sent[-2]['content'], stamp.record(FOUR))
        self.assertIn('"type": "answer_opening"', sent[-1]['content'])


class ClaudeCacheMarkerTests(StampCase):
    """The stamp must not take the conversation cache away: a marker sits on the block before it,
    and the automatic marker still follows what one turn adds behind the stamp."""
    STAMP = {'role': 'user', 'content': stamp.record(FOUR)}

    def test_with_the_stamp_the_marker_sits_on_the_request_before_it(self):
        sent = self.ask('anthropic')
        self.assertEqual(sent['cache_control'], {'type': 'ephemeral'}, 'the automatic marker stays')
        self.assertEqual(sent['messages'], [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Explain compound interest.', 'cache_control': {'type': 'ephemeral'}}]},
            self.STAMP])
        self.assertEqual(markers(sent), 4, 'two on the system pages, one before the stamp, the automatic one')
        self.assertLessEqual(markers(sent), stamp.MAX_MARKERS)

    def test_without_the_stamp_the_automatic_marker_is_unchanged(self):
        sent = self.ask('anthropic', source=None)
        self.assertEqual(sent['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(sent['messages'], [{'role': 'user', 'content': 'Explain compound interest.'}])
        self.assertEqual(markers(sent), 3)

    def test_the_marked_front_of_one_request_comes_back_word_for_word_in_the_next(self):
        first = self.ask('anthropic', text='First question.')
        history = history_messages([{'normalized_input': 'First question.', 'reply': json.loads(document())}], 100000)
        second = self.ask('anthropic', text='Second question.', history=history)
        self.assertEqual(plain(second['messages'])[:1], plain(first['messages'])[:-1])
        self.assertEqual(second['system'], first['system'])
        self.assertEqual(second['tools'], first['tools'])
        self.assertEqual([markers(m) for m in second['messages']], [0, 0, 1, 0], 'old turns carry no marker')
        self.assertEqual(plain(second['messages'])[2]['content'], 'Second question.')

    def test_a_request_with_a_picture_gets_the_marker_on_its_last_block(self):
        picture = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'}}
        params = {'cache_control': {'type': 'ephemeral'}, 'messages': [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'What is shown?'}, picture]}, self.STAMP]}
        untouched = json.loads(json.dumps(params['messages']))
        stamp.cache_before_stamp(params)
        self.assertEqual(params['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(params['messages'][0]['content'], [{'type': 'text', 'text': 'What is shown?'},
                                                            {**picture, 'cache_control': {'type': 'ephemeral'}}])
        self.assertEqual(params['messages'][1], self.STAMP)
        self.assertEqual(untouched[0]['content'][1], picture, 'the caller\'s own blocks are not edited in place')

    def test_a_note_placed_after_the_stamp_does_not_take_the_marker(self):
        params = {'cache_control': {'type': 'ephemeral', 'ttl': '1h'}, 'messages': [
            {'role': 'user', 'content': 'Question.'}, self.STAMP, {'role': 'user', 'content': 'Client memory folder check: {}'}]}
        stamp.cache_before_stamp(params)
        self.assertEqual(params['messages'][0]['content'], [{'type': 'text', 'text': 'Question.', 'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}])
        self.assertEqual([markers(m) for m in params['messages']], [1, 0, 0])

    def test_with_no_free_slot_the_automatic_marker_is_given_up_for_the_one_before_the_stamp(self):
        mark = {'cache_control': {'type': 'ephemeral'}}
        params = {'cache_control': {'type': 'ephemeral'},
                  'system': [{'type': 'text', 'text': 'One.', **mark}, {'type': 'text', 'text': 'Two.', **mark},
                             {'type': 'text', 'text': 'Three.', **mark}],
                  'messages': [{'role': 'user', 'content': 'Question.'}, self.STAMP]}
        self.assertEqual(stamp.marker_count(params), 4)
        stamp.cache_before_stamp(params)
        self.assertNotIn('cache_control', params)
        self.assertEqual(params['messages'][0]['content'], [{'type': 'text', 'text': 'Question.', **mark}])
        self.assertEqual(stamp.marker_count(params), stamp.MAX_MARKERS)

    def test_a_turn_that_grows_behind_the_stamp_keeps_the_automatic_marker_for_its_steps(self):
        """Provider tool steps are appended after the stamp; the top-level marker is what caches them step by step."""
        params = {'cache_control': {'type': 'ephemeral'},
                  'messages': [{'role': 'user', 'content': 'Run the tool.'}, self.STAMP]}
        stamp.cache_before_stamp(params)
        params['messages'].append({'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 't1', 'name': 'shell', 'input': {}}]})
        params['messages'].append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}]})
        self.assertEqual(params['cache_control'], {'type': 'ephemeral'})
        self.assertEqual([markers(m) for m in params['messages']], [1, 0, 0, 0])
        stamp.cache_before_stamp(params)  # a second pass changes nothing
        self.assertEqual([markers(m) for m in params['messages']], [1, 0, 0, 0])
        self.assertEqual(stamp.marker_count(params), 2)

    def test_nothing_moves_without_a_marker_or_without_a_stamp(self):
        for params in ({'messages': [{'role': 'user', 'content': 'Question.'}, self.STAMP]},
                       {'cache_control': {'type': 'ephemeral'}, 'messages': [{'role': 'user', 'content': 'Question.'}]},
                       {'cache_control': {'type': 'ephemeral'}, 'messages': [self.STAMP]},
                       {'cache_control': {'type': 'ephemeral'}}):
            before = json.loads(json.dumps(params))
            self.assertEqual(stamp.cache_before_stamp(params), before)

    def test_the_api_tool_loop_moves_the_marker_too(self):
        import api_tools_runtime
        self.assertIn('cache_before_stamp(params)', Path(api_tools_runtime.__file__).read_text())

    def test_provider_compaction_keeps_the_current_request_and_the_stamp_out_of_the_summary(self):
        from types import SimpleNamespace
        from api_tools_resources import compact_messages
        system = [{'role': 'system', 'content': 'PAGE'}]
        old = [{'role': 'user', 'content': 'Old question.'}, {'role': 'assistant', 'content': 'Old answer.'}]
        current = {'role': 'user', 'content': 'New question.'}
        seen = {}

        def compact(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(id='c1', usage=None, model_dump=lambda **_: {'output': [{'type': 'compaction', 'id': 'c1'}]})
        runtime = SimpleNamespace(prepared=False, options={'compaction_threshold': 1}, engine='openai', model='m',
                                  compacted=None, record=lambda *a, **k: None)
        client = SimpleNamespace(responses=SimpleNamespace(compact=compact))
        for tail in ([current, self.STAMP], [current]):
            with self.subTest(stamp=len(tail) == 2):
                runtime.prepared = False
                out = compact_messages(runtime, client, [*system, *old, *tail], ['PAGE'])
                self.assertEqual(seen['input'], old, 'only the older exchanges are summarized')
                self.assertEqual(out, [*system, {'type': 'compaction', 'id': 'c1'}, *tail])


class LoopAndStorageTests(StampCase):
    def run_cli(self, args, answers=None, results=(), stdin=''):
        """Real request_reply with a fake OpenAI client, so the sent messages are the real ones."""
        client = FakeClient([response(json.dumps(a.model_dump())) for a in (answers or [h.validate_reply(document())])])
        out, err = io.StringIO(), io.StringIO()
        real = h.request_reply

        def through_fake(*a, **k):
            k.pop('client', None)
            return real(*a, client=client, **k)
        with patch.object(h, 'STAMP_SOURCE', self.rules), patch.object(h, 'request_reply', side_effect=through_fake), \
                patch.object(cli, 'native', side_effect=list(results)), patch.object(cli.sys, 'stdin', io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = h.main(['--usage-log', str(self.log), '--no-web', *args])
        return code, out.getvalue(), err.getvalue(), client

    def test_each_loop_request_minus_its_stamp_is_a_byte_for_byte_prefix_of_the_next(self):
        answers = [command('printf alpha > test.txt'), command('cat test.txt'),
                   h.validate_reply(document(direct_answer='The file holds alpha.'), execution_confirmed=True)]
        results = [dict(approved=True, stdout='', stderr='', exit_code=0), dict(approved=True, stdout='alpha\n', stderr='', exit_code=0)]
        code, _, _, client = self.run_cli(['--loop', '--session', 'loop', 'Create and read the test file.'], answers, results)
        self.assertEqual(code, 0)
        sent = [call['input'] for call in client.calls]
        self.assertEqual(len(sent), 3)
        for request in sent:
            self.assertTrue(stamp.is_stamp(request[-1]))
            self.assertEqual(sum(stamp.is_stamp(m) for m in request), 1, 'one stamp per request, none carried in history')
        for earlier, later in zip(sent, sent[1:]):
            self.assertEqual(later[:len(earlier) - 1], earlier[:-1])
        self.assertTrue(sent[1][-2]['content'].endswith('This is model turn 2 of 200.'))

    def test_the_stamp_is_never_saved_with_a_turn(self):
        self.run_cli(['--session', 'keep', 'First question.'])
        code, _, _, client = self.run_cli(['--session', 'keep', 'Second question.'])
        self.assertEqual(code, 0)
        second = client.calls[0]['input']
        self.assertEqual([m['content'] for m in second if m['role'] == 'user'][:1], ['First question.'])
        self.assertEqual(sum(stamp.is_stamp(m) for m in second), 1)
        saved = (self.state / 'sessions' / 'keep.json').read_text() + (self.state / 'history.db').read_bytes().decode('latin-1')
        self.assertNotIn('operator_rules_stamp', saved)
        self.assertNotIn('Clarify first', saved)


class SwitchTests(StampCase):
    def switch(self, args, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', return_value=h.validate_reply(document())) as api, \
                patch.object(cli.sys, 'stdin', io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = h.main(args)
        return code, out.getvalue(), err.getvalue(), api

    def test_it_ships_on(self):
        self.assertTrue(stamp.is_on(self.state))
        self.assertFalse((self.state / 'switches.json').exists())

    def test_off_then_on_as_the_whole_question_makes_no_model_call(self):
        code, out, err, api = self.switch(['/off stamp'])
        self.assertEqual((code, out, err), (0, '', 'Stamp off.\n'))
        api.assert_not_called()
        self.assertFalse(stamp.is_on(self.state))
        self.assertEqual(self.ask()['input'][-1]['content'], 'Explain compound interest.')
        self.assertIsNone(self.events()[-1]['stamp_sha256'])
        code, out, err, api = self.switch(['/on', 'stamp'])
        self.assertEqual((code, out, err), (0, '', 'Stamp on.\n'))
        api.assert_not_called()
        self.assertTrue(stamp.is_on(self.state))
        self.assertTrue(stamp.is_stamp(self.ask()['input'][-1]))

    def test_typed_in_a_chat_the_switch_flips_and_the_chat_goes_on(self):
        code, out, err, api = self.switch(['--chat'], 'first question\n/off stamp\nsecond question\n/ON  Stamp\nexit\n')
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0] for c in api.call_args_list], ['first question', 'second question'])
        self.assertIn('Stamp off.\n', err)
        self.assertIn('Stamp on.\n', err)
        self.assertNotIn('Stamp', out)
        self.assertTrue(stamp.is_on(self.state))

    def test_when_off_the_source_file_is_not_read(self):
        stamp.set_switch(self.state, False)
        sent = self.ask(source=self.root / 'absent.md')['input']
        self.assertEqual(sent[-1]['content'], 'Explain compound interest.')

    def test_only_the_exact_line_is_a_switch(self):
        for line in ('/off stamp', '/on stamp', ' /OFF  STAMP ', '/On\tstamp'):
            self.assertTrue(stamp.is_switch(line), line)
        for line in ('/off', '/off stamps', '/off stamp now', 'turn /off stamp', '/off web', 'off stamp', '/offstamp'):
            self.assertFalse(stamp.is_switch(line), line)
        code, _, _, api = self.switch(['/off stamp now'])
        self.assertEqual(api.call_count, 1, 'any other wording is a question for the model')
        self.assertTrue(stamp.is_on(self.state))

    def test_the_switch_keeps_other_keys_in_the_file(self):
        self.state.mkdir(parents=True)
        (self.state / 'switches.json').write_text(json.dumps({'judge': False, 'recall': True}))
        stamp.set_switch(self.state, False)
        self.assertEqual(json.loads((self.state / 'switches.json').read_text()), {'judge': False, 'recall': True, 'stamp': False})
        stamp.set_switch(self.state, True)
        self.assertEqual(json.loads((self.state / 'switches.json').read_text()), {'judge': False, 'recall': True, 'stamp': True})

    def test_a_broken_switches_file_is_an_error_and_is_not_overwritten(self):
        self.state.mkdir(parents=True)
        for content in ('not json', '[1, 2]'):
            with self.subTest(content=content):
                (self.state / 'switches.json').write_text(content)
                code, out, err, api = self.switch(['/off stamp'])
                self.assertEqual((code, out), (2, ''))
                self.assertIn('switches file', err)
                self.assertEqual((self.state / 'switches.json').read_text(), content)
                client = FakeClient([])
                with patch.object(h, 'STAMP_SOURCE', self.rules), self.assertRaisesRegex(h.HarnessError, 'switches file'):
                    h.request_reply('Explain.', client=client, log_path=self.log)
                self.assertEqual(client.calls, [])

    def test_the_isolated_state_folder_has_its_own_switch(self):
        other = self.root / 'other-state'
        stamp.set_switch(self.state, False)
        self.assertFalse(stamp.is_on(self.state))
        self.assertTrue(stamp.is_on(other))


class EntryPointTests(unittest.TestCase):
    def test_the_command_line_entry_point_switches_the_stamp_on(self):
        """Run a copy of the client with the stamp pointed at a temporary file: a missing file stops it, so the entry point reads it."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'client'
            copy.mkdir()
            for item in h.ROOT.iterdir():
                if item.is_file() and item.suffix in {'.py', '.txt'}:
                    shutil.copy(item, copy / item.name)
            absent = Path(tmp) / 'absent-rules.md'
            program = ('import runpy, sys\nfrom pathlib import Path\nimport stamp\n'
                       f'stamp.SOURCE = Path({str(absent)!r})\n'
                       "sys.argv = ['harness.py', '--engine', 'openai', 'Explain compound interest.']\n"
                       "runpy.run_path('harness.py', run_name='__main__')\n")
            env = {**os.environ, 'OPENAI_API_KEY': 'offline-test-key', 'HARNESS_STATE_DIR': str(Path(tmp) / 'run-state')}
            env.pop('HARNESS_BRIDGE_FD', None)
            run = subprocess.run([sys.executable, '-B', '-c', program], capture_output=True, text=True, timeout=120, env=env, cwd=copy)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertEqual(run.stdout, '')
            self.assertEqual(run.stderr.strip(), f'Rules stamp: the file is missing or unreadable: {absent}')

    def test_the_help_text_names_the_switch(self):
        self.assertIn('/off stamp', (h.ROOT / 'help.txt').read_text())


if __name__ == '__main__':
    unittest.main()
