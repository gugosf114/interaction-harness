"""Offline checks of the lane mods: answer checks, gate retry, narrator, thread tree, proof marks, voice,
switches, chat commands, autopilot and the usage meter. No network calls, no keys."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import harness as h
import answer_checks as ac
import lane_mods
import mod_switches
import narrator
import proof_marks
import thread_tree
import usage_meter
from test_harness import FakeClient, document, response

LONG = ' '.join(['The owner can read the file and the group can read it too.'] * 6)


def obs(command, stdout):
    return {'role': 'user', 'content': json.dumps({'type': 'execution_observation', 'source': 'native_termux',
                                                   'command': command, 'result': {'stdout': stdout, 'exit_code': 0}})}


class AnswerChecks(unittest.TestCase):
    def test_length_yes_no_cap(self):
        self.assertIn('answer too long', ac.length(LONG, 'Is the file readable?'))
        self.assertIn('ceiling is 40', ac.length(LONG, 'Is the file readable?'))
        self.assertIsNone(ac.length('Yes. The group can read it.', 'Is the file readable?'))

    def test_length_question_and_default_caps(self):
        self.assertIsNone(ac.length(LONG, 'What does 640 mean?'))     # 72 words, cap 120
        self.assertIn('ceiling is 120', ac.length(LONG * 2, 'What does 640 mean?'))
        self.assertIsNone(ac.length(LONG * 2, 'I was looking at the file mode'))  # cap 250
        self.assertIsNone(ac.length(LONG * 9, 'go ahead and fix it'))         # a build order has no cap

    def test_length_counts_prose_only(self):
        code = '```\n' + ' word' * 500 + '\n```\nYes.'
        self.assertIsNone(ac.length(code, 'Is it there?'))

    def test_plain_words_grade_and_jargon(self):
        hard = ('The idempotent configuration facilitates deterministic orchestration of asynchronous serialization '
                'across heterogeneous infrastructure, guaranteeing reproducible provenance for subsequent invocations.')
        reason = ac.plain_words(hard + ' ' + hard)
        self.assertIn('plain words', reason)
        self.assertIn('Jargon present', reason)
        self.assertIn('idempotent', reason)
        easy = 'The cat sat on the mat. It was a big red mat. The dog ran to the cat. They both sat there. It was fun to see.'
        self.assertIsNone(ac.plain_words(easy))

    def test_plain_words_skips_short_answers(self):
        self.assertIsNone(ac.plain_words('Idempotent orchestration.'))

    def test_receipts_needs_read_or_guess(self):
        claim = 'The WiM bubble sends the text by itself.'
        self.assertIn('receipts', ac.receipts(claim, ''))
        self.assertIsNone(ac.receipts(claim + ' GUESS', ''))
        self.assertIsNone(ac.receipts('I read the bubble code.', ''))          # self-talk
        self.assertIsNone(ac.receipts(claim, 'cat wim-android/BubbleService.kt ... fun sends() ...'))
        # A WiM read that holds no matching action word is no receipt.
        self.assertIn('receipts', ac.receipts(claim, 'cat wim-android/BubbleService.kt ... fun draw() ...'))

    def test_turn_evidence_is_this_turn_only(self):
        history = [{'role': 'user', 'content': 'old question'}, obs('cat wim-android/a', 'sends'),
                   {'role': 'assistant', 'content': '{}'}, {'role': 'user', 'content': 'new question'},
                   obs('ls', 'listing')]
        cont = ac.CONTINUATION + ' This is model turn 2 of 5.'
        evidence = ac.turn_evidence(history, cont)
        self.assertIn('listing', evidence)
        self.assertNotIn('wim-android', evidence)
        self.assertEqual(ac.turn_evidence(history, 'a fresh question'), '')

    def test_no_background(self):
        for command in ('nohup sleep 9 &', 'setsid foo', 'sleep 5 &', 'x; disown', '(sleep 3 &)'):
            with self.subTest(command=command):
                self.assertIn('no background', ac.no_background(command))
        for command in ('ls && pwd', 'cmd 2>&1', 'a | b', 'echo "&&"', None):
            with self.subTest(command=command):
                self.assertIsNone(ac.no_background(command))

    def test_undertaker(self):
        text = "The invoice went out, $650.\nDon't worry.\nTo be clear, it is done.\nJust to be clear."
        self.assertEqual(ac.undertaker(text), "The invoice went out, $650.\nTo be clear, it is done.")
        self.assertFalse(ac.is_junk("Don't worry, the invoice went out, $650"))

    def test_soft_violation_obeys_switches(self):
        with tempfile.TemporaryDirectory() as tmp:
            reply = SimpleNamespace(direct_answer=LONG, execution_payload=None)
            self.assertIn('answer too long', ac.soft_violation(reply, 'Is it readable?', [], 'Is it readable?', tmp))
            mod_switches.set_value('length', False, tmp)
            self.assertIsNone(ac.soft_violation(reply, 'Is it readable?', [], 'Is it readable?', tmp))
            with patch.object(ac, 'PLAY_MODE', tmp):   # the play-mode sign exists: style checks step aside
                mod_switches.set_value('length', True, tmp)
                self.assertIsNone(ac.soft_violation(reply, 'Is it readable?', [], 'Is it readable?', tmp))


class GateRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'events.jsonl'
        self.patches = [patch.object(h, 'STATE', Path(self.tmp.name) / 'state'), patch.object(h, 'MODS_ON', True),
                        patch.object(ac, 'PLAY_MODE', Path(self.tmp.name) / 'no-play-mode')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_long_answer_retried_then_short_answer_shown(self):
        client = FakeClient([response(document(direct_answer=LONG)), response(document(direct_answer='Yes.'))])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = h.request_reply('Is the file readable?', client=client, log_path=self.log)
        self.assertEqual(out.direct_answer, 'Yes.')
        self.assertEqual(len(client.calls), 2)
        self.assertIn('answer check: answer too long - asked again', err.getvalue())
        first, second = self.events()
        self.assertEqual(first['status'], 'gate_rejected')
        self.assertIn('answer too long', first['gate_reason'])
        self.assertEqual(second['status'], 'accepted')

    def test_second_failing_answer_is_still_shown(self):
        client = FakeClient([response(document(direct_answer=LONG)), response(document(direct_answer=LONG))])
        with contextlib.redirect_stderr(io.StringIO()):
            out = h.request_reply('Is the file readable?', client=client, log_path=self.log)
        self.assertEqual(out.direct_answer, LONG)
        self.assertEqual(self.events()[-1]['answer_check_kept'], 'answer too long')

    def test_detached_command_retried(self):
        bad = document(intent='action_request', direct_answer='Starting it.', execution_payload='nohup sleep 300 &')
        good = document(intent='action_request', direct_answer='Running it.', execution_payload='sleep 1')
        client = FakeClient([response(bad), response(good)])
        with contextlib.redirect_stderr(io.StringIO()):
            out = h.request_reply('start a sleep', client=client, log_path=self.log)
        self.assertEqual(out.execution_payload, 'sleep 1')
        self.assertIn('no background', self.events()[0]['gate_reason'])

    def test_undertaker_in_gate_and_off_switch(self):
        text = 'The mode is 640.\nTo be clear.'
        self.assertEqual(h.validate_reply(document(direct_answer=text)).direct_answer, 'The mode is 640.')
        mod_switches.set_value('undertaker', False, h.STATE)
        self.assertEqual(h.validate_reply(document(direct_answer=text)).direct_answer, text)

    def test_mods_off_on_plain_import(self):
        with patch.object(h, 'MODS_ON', False):
            client = FakeClient([response(document(direct_answer=LONG))])
            self.assertEqual(h.request_reply('Is the file readable?', client=client, log_path=self.log).direct_answer, LONG)


class Narrator(unittest.TestCase):
    def test_sentences(self):
        cases = {'card mail': 'Read the mail card', 'gh pr list -R x/y': 'Asked GitHub: pr list -R',
                 'screen snap --target phone': 'Took a picture of the screen', 'cat /a/b/notes.md': 'Read notes.md',
                 'deb cat /root/x.txt': 'On the Debian side: Read x.txt', 'grep -n foo bar.py': 'Searched for "foo"',
                 'curl -s https://example.com/a': 'Read a web page: example.com', 'FOO=1 python3 run.py': 'Ran run.py',
                 'timeout 30 ls /tmp': 'Listed tmp', 'cd /x && git status': 'Used git: status',
                 'mail-unread berkeley 3': 'Checked the berkeley inbox'}
        for command, sentence in cases.items():
            with self.subTest(command=command):
                self.assertEqual(narrator.describe(command), sentence)
        self.assertTrue(narrator.describe('weirdtool --x').startswith('Ran a command — weirdtool'))


class ThreadTree(unittest.TestCase):
    def test_push_pop_switch_new(self):
        tree = thread_tree.empty()
        thread_tree.apply(tree, 'new', 'bakery site')
        thread_tree.apply(tree, 'push', 'contact form')
        thread_tree.apply(tree, 'push', 'spam filter')
        self.assertEqual(thread_tree.labels(tree), ['bakery site', 'contact form', 'spam filter'])
        thread_tree.apply(tree, 'pop')
        self.assertTrue(tree['popped'])
        self.assertEqual(thread_tree.labels(tree), ['bakery site', 'contact form'])
        thread_tree.apply(tree, 'switch', 'photos')
        self.assertEqual(thread_tree.labels(tree), ['bakery site', 'photos'])
        thread_tree.apply(tree, 'new', 'taxes')
        self.assertEqual(thread_tree.labels(tree), ['taxes'])
        text = thread_tree.render(tree)
        self.assertIn('Where we are: taxes', text)
        self.assertIn('  └ contact form  (closed)', text)
        self.assertIn('    └ spam filter  (closed)', text)
        self.assertIn('taxes  ◀ here', text)

    def test_pop_at_top_stays(self):
        tree = thread_tree.apply(thread_tree.empty(), 'new', 'one')
        thread_tree.apply(tree, 'pop')
        self.assertEqual(thread_tree.labels(tree), ['one'])
        self.assertFalse(tree['popped'])

    def test_update_parses_and_seeds(self):
        tree, done = thread_tree.update(thread_tree.empty(), 'nonsense', 'What is the bakery tax rate?')
        self.assertEqual(thread_tree.labels(tree), ['bakery tax rate'])
        tree, done = thread_tree.update(tree, '{"action":"push","label":"sales tax","done":true}', 'and sales tax?')
        self.assertTrue(done)
        self.assertEqual(thread_tree.after_turn_line(tree, done), '↑ "sales tax" looks settled. Back to "bakery tax rate": type /up.')
        self.assertEqual(thread_tree.up(tree), 'bakery tax rate')
        self.assertIsNone(thread_tree.up(tree))

    def test_after_pop_line(self):
        tree = thread_tree.apply(thread_tree.empty(), 'new', 'a')
        thread_tree.apply(tree, 'push', 'b')
        thread_tree.apply(tree, 'pop')
        self.assertEqual(thread_tree.after_turn_line(tree, False), '↑ back to: a')

    def test_prompt_carries_trail(self):
        tree = thread_tree.apply(thread_tree.empty(), 'new', 'alpha')
        self.assertIn('1. alpha', thread_tree.move_prompt(tree, 'msg', 'ans'))


class ProofMarks(unittest.TestCase):
    def test_parse_and_render(self):
        lines = ['Battery is 80%.', 'It will last all day.', 'I pushed the fix.']
        marks = proof_marks.parse('{"1":"g","2":"y","3":"r"}', 3)
        self.assertEqual(marks, ['g', 'y', 'r'])
        self.assertEqual(proof_marks.render(lines, marks), 'proof: 1 shown · 1 guess · 1 no proof\n  ✗ I pushed the fix.')
        self.assertIsNone(proof_marks.parse('no json', 3))
        self.assertEqual(proof_marks.parse('{"1":"x"}', 2), ['y', 'y'])

    def test_evidence_keeps_observations_only(self):
        history = [{'role': 'user', 'content': 'question'}, obs('ls', 'a.txt')]
        self.assertIn('a.txt', proof_marks.evidence(history))
        self.assertNotIn('question', proof_marks.evidence(history))


class TurnEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(h, 'STATE', Path(self.tmp.name)), patch.object(h, 'MODS_ON', True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_proof_tree_voice_after_answer(self):
        answers = {'proof': '{"1":"g","2":"r"}', 'tree': '{"action":"new","label":"battery check"}'}
        reply = SimpleNamespace(direct_answer='Battery is 80%.\nI fixed the charger.')
        args = SimpleNamespace(engine='anthropic', usage_log=Path(self.tmp.name) / 'u.jsonl')
        session, saved = {}, []
        err = io.StringIO()
        import cli
        with patch.object(lane_mods.helper_model, 'complete', side_effect=lambda e, kind, *a, **k: answers[kind]), \
                patch.object(lane_mods.os.path, 'exists', return_value=True), \
                patch.object(cli,'native',return_value={'queued':True,'pid':123,'voice_id':'test'}) as native, \
                contextlib.redirect_stderr(err):
            lane_mods.turn_end(args, session, 'how is the battery', reply, [obs('termux-battery-status', '80')],
                               lambda: saved.append(1))
        self.assertIn('proof: 1 shown · 0 guess · 1 no proof', err.getvalue())
        self.assertIn('✗ I fixed the charger.', err.getvalue())
        self.assertEqual(thread_tree.labels(session['thread_tree']), ['battery check'])
        self.assertEqual(saved, [1])
        native.assert_called_once_with({'op':'speak','text':'Battery is 80%. I fixed the charger.','state':str(h.STATE),'generation':0})
        event = json.loads((h.STATE / 'usage.jsonl').read_text().splitlines()[-1])
        self.assertEqual((event['kind'], event['status'], event['pid']), ('hook:voice', 'queued', 123))

    def test_voice_short_and_off(self):
        self.assertEqual(lane_mods.spoken('**Yes.** The battery is fine.\n\n- one\n- two', False), 'Yes. The battery is fine.')
        mod_switches.set_value('voice', False, h.STATE)
        mod_switches.set_value('proof', False, h.STATE)
        mod_switches.set_value('tree', False, h.STATE)
        with patch.object(lane_mods.subprocess, 'Popen') as popen, patch.object(lane_mods.helper_model, 'complete') as call:
            lane_mods.turn_end(SimpleNamespace(engine='openai', usage_log=None), {}, 'x',
                               SimpleNamespace(direct_answer='Hi there friend.'), [], lambda: None)
        popen.assert_not_called()
        call.assert_not_called()

    def test_failing_mod_never_breaks_turn(self):
        with patch.object(lane_mods.helper_model, 'complete', side_effect=RuntimeError('boom')), \
                patch.object(lane_mods, 'speak', side_effect=OSError):
            lane_mods.turn_end(SimpleNamespace(engine='openai', usage_log=None), {}, 'x',
                               SimpleNamespace(direct_answer='Fine.'), [], lambda: None)

    def test_narrator_and_memory_version(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                patch.object(lane_mods.memory_versions, 'snapshot', return_value={'status': 'saved'}) as snapshot:
            lane_mods.before_command('card mail')
            lane_mods.after_command({'exit_code': 0})
        self.assertEqual(err.getvalue(), '» Read the mail card\n')
        snapshot.assert_called_once_with(h.STATE)


class ChatLines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.patches = [patch.object(h, 'STATE', self.state), patch.object(h, 'MODS_ON', True)]
        for p in self.patches:
            p.start()
        (self.state / 'sessions').mkdir()
        tree = thread_tree.apply(thread_tree.empty(), 'new', 'site')
        thread_tree.apply(tree, 'push', 'form')
        turns = [{'reply': {'direct_answer': f'answer {i}'}} for i in range(9)]
        (self.state / 'sessions' / 's1.json').write_text(json.dumps({'version': 1, 'id': 's1', 'turns': turns,
                                                                       'thread_tree': tree}))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def line(self, text, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            result = lane_mods.chat_line(text, 's1', kw.get('run', lambda t: 0), kw.get('native'))
        return result, out.getvalue()

    def test_on_off_and_mods(self):
        self.assertEqual(self.line('/off plain-words'), ((True, None), 'plain-words off.\n'))
        self.assertFalse(mod_switches.is_on('plain-words', self.state))
        self.line('/on plain-words')
        self.assertTrue(mod_switches.is_on('plain-words', self.state))
        (_, out) = self.line('/mods')
        self.assertIn('on   plain-words', out)
        # A name that is not a mod passes through, so another /on handler (API tools) can take it.
        self.assertEqual(self.line('/on web-search')[0], (False, None))

    def test_where_and_up_keep_every_exchange(self):
        self.assertIn('Where we are: site › form', self.line('/where')[1])
        self.assertIn('↑ back to: site', self.line('/up')[1])
        data = json.loads((self.state / 'sessions' / 's1.json').read_text())
        self.assertEqual(len(data['turns']), 9)
        self.assertEqual(thread_tree.labels(data['thread_tree']), ['site'])
        self.assertIn('Already at the top', self.line('/up')[1])

    def test_voice_commands(self):
        with patch.object(lane_mods.subprocess, 'run'):
            self.line('/voice short')
            self.assertEqual(mod_switches.setting('voice-mode', self.state), 'short')
            self.line('/voice off')
            self.assertFalse(mod_switches.is_on('voice', self.state))
            self.line('/voice full')
        self.assertTrue(mod_switches.is_on('voice', self.state))
        self.assertEqual(mod_switches.setting('voice-mode', self.state), 'full')

    def test_v_listens(self):
        native = lambda request: {'text': 'what is the battery'} if request['op'] == 'listen' else {}
        self.assertEqual(self.line('v', native=native)[0], (False, 'what is the battery'))
        self.assertEqual(self.line('в', native=lambda r: {'text': ''})[0], (True, None))

    def test_plain_text_passes(self):
        self.assertEqual(self.line('hello there')[0], (False, None))

    def test_autopilot_runs_until_complete(self):
        answers = iter(['did a step\nAUTOPILOT: CONTINUE', 'all built\nAUTOPILOT: COMPLETE'])
        prompts = []

        def run(text):
            prompts.append(text)
            data = json.loads((self.state / 'sessions' / 's1.json').read_text())
            data['turns'].append({'reply': {'direct_answer': next(answers)}})
            (self.state / 'sessions' / 's1.json').write_text(json.dumps(data))
            return 0
        self.line('/autopilot build the price page', run=run)
        self.assertEqual(len(prompts), 2)
        self.assertIn('build the price page', prompts[0])
        self.assertIn(str(self.state / 'autopilot') + '/log.md', prompts[0])
        self.assertEqual(json.loads((self.state / 'autopilot' / 'run.json').read_text())['state'], 'complete')
        self.assertIn('complete · step 2', self.line('/autopilot status')[1])

    def test_autopilot_brakes(self):
        times = iter([0, 0, 11 * 3600])
        with contextlib.redirect_stderr(io.StringIO()):
            lane_mods.autopilot('g', 's1', lambda t: 0, clock=lambda: next(times))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lane_mods.autopilot('g', 's1', lambda t: 130), 130)
        self.assertEqual(lane_mods.outcome('x\nAUTOPILOT: BLOCKED'), 'blocked')


class UsageMeter(unittest.TestCase):
    def test_windows_and_sources(self):
        now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone(timedelta(hours=-8)))   # a Wednesday
        starts = usage_meter.window_starts(now)
        self.assertEqual(starts['week'].day, 9)
        self.assertEqual(starts['month'].day, 1)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            def at(hours_ago):
                return (now - timedelta(hours=hours_ago)).astimezone(timezone.utc).isoformat()
            events = [
                {'time_utc': at(1), 'engine': 'anthropic', 'usage': {'input_tokens': 10, 'cache_read_input_tokens': 100,
                                                                     'cache_creation_input_tokens': 5, 'output_tokens': 7}},
                {'time_utc': at(30), 'engine': 'openai', 'usage': {'input_tokens': 50, 'output_tokens': 5,
                                                                   'input_tokens_details': {'cached_tokens': 40}}},
                {'time_utc': at(24 * 6), 'model_requested': 'gpt-6.1-sol', 'usage': {'input_tokens': 1, 'output_tokens': 1}},
            ]
            (state / 'usage.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\nnot json\n')
            log = usage_meter.from_log(state / 'usage.jsonl', starts)
            self.assertEqual(log['anthropic']['today'], {'calls': 1, 'input': 115, 'output': 7, 'cache_read': 100})
            self.assertEqual(log['openai']['today']['calls'], 0)
            self.assertEqual(log['openai']['week'], {'calls': 1, 'input': 50, 'output': 5, 'cache_read': 40})
            self.assertEqual(log['openai']['month']['calls'], 2)
            db = sqlite3.connect(state / 'history.db')
            db.execute('CREATE TABLE history (engine, timestamp, input_tokens, output_tokens, cache_read_tokens, tokens_used)')
            db.execute('INSERT INTO history VALUES (?,?,?,?,?,?)', ('anthropic', at(2), 115, 7, 100, 122))
            db.commit(); db.close()
            hist = usage_meter.from_history(state / 'history.db', starts)
            self.assertEqual(hist['anthropic']['today'], {'calls': 1, 'input': 115, 'output': 7, 'cache_read': 100})
            text = usage_meter.report(state, now=now, providers=False)
            self.assertIn('george', text)
            self.assertIn('g1', text)

    def test_provider_refusal_is_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'api-key').write_text('k')
            starts = usage_meter.window_starts(datetime.now().astimezone())
            with patch.object(usage_meter, '_get', return_value=(403, 'Missing scopes: api.usage.read.')):
                totals, note = usage_meter.provider_openai(Path(tmp), starts)
            self.assertIsNone(totals)
            self.assertEqual(note, 'HTTP 403 with api-key: Missing scopes: api.usage.read.')

    def test_provider_report_sums(self):
        starts = usage_meter.window_starts(datetime.now().astimezone())
        day = int(datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        page = {'data': [{'start_time': day, 'results': [{'input_tokens': 9, 'output_tokens': 2, 'input_cached_tokens': 4,
                                                          'num_model_requests': 3}]}], 'has_more': False}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'openai-admin-key').write_text('k')
            with patch.object(usage_meter, '_get', return_value=(200, page)):
                totals, note = usage_meter.provider_openai(Path(tmp), starts)
        self.assertEqual(note, 'ok')
        self.assertEqual(totals['today'], {'calls': 3, 'input': 9, 'output': 2, 'cache_read': 4})


if __name__ == '__main__':
    unittest.main()
