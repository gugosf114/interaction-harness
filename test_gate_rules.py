"""Rules as data: state/gate_rules.json, the self-testing `rule add`, and the gate that applies them."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import gate_rules
import gate_rules_cli
import habit_checks
import harness as h
from storage import Store
import test_choice_check
from test_harness import FakeClient, document, response

SIGN_OFF = 'Stay hydrated out there.'
PATTERN = r'\bstay hydrated\b'


def reply(answer, payload=None):
    return document(intent='action_request' if payload else 'observation', direct_answer=answer, execution_payload=payload)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules = self.root / 'gate_rules.json'
        self.state = patch.object(h, 'STATE', self.root)
        self.state.start()
        self.addCleanup(self.state.stop)
        switch = patch.object(gate_rules, 'RULES_FILE', self.rules)
        switch.start()
        self.addCleanup(switch.stop)
        gate_rules.drain()
        store = Store(self.root)
        self.row = store.begin('what does chmod 640 mean', 'what does chmod 640 mean', 'openai', 'gpt-test', 'session-a')
        store.finish(self.row, h.validate_reply(document()), [])
        store.close()

    def add(self, name='sign-off', pattern=PATTERN, action='strip_sentence', bad=(SIGN_OFF,), row=None):
        return gate_rules.add_rule(self.rules, name=name, pattern=pattern, action=action, bad=list(bad),
                                   history_row=row or self.row, date='2026-11-11')

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = gate_rules_cli.main(list(argv), rules_file=self.rules, history=self.root / 'history.db', out=out, err=err)
        return code, out.getvalue(), err.getvalue()


class RuleAddTests(Base):
    def test_a_good_rule_is_stored_with_every_field(self):
        self.add()
        entries = json.loads(self.rules.read_text())
        self.assertEqual(entries, [{'name': 'sign-off', 'pattern': PATTERN, 'action': 'strip_sentence', 'bad': [SIGN_OFF],
                                    'date': '2026-11-11', 'history_row': self.row}])
        self.assertEqual(os.stat(self.rules).st_mode & 0o777, 0o600)

    def test_a_rule_that_misses_one_of_its_own_bad_sentences_is_refused(self):
        with self.assertRaisesRegex(gate_rules.RuleError, 'does not match its own bad sentence'):
            self.add(bad=[SIGN_OFF, 'Drink some water.'])
        self.assertFalse(self.rules.exists())

    def test_a_rule_that_matches_a_known_good_sentence_is_refused(self):
        for pattern in (r'the', r'.*', r'\bchmod\b', r'which'):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(gate_rules.RuleError, 'known-good sentence'):
                self.add(pattern=pattern, bad=['Which is the chmod?'])
        self.assertFalse(self.rules.exists())

    def test_malformed_rules_are_refused(self):
        cases = [(dict(pattern='(unclosed'), 'not a valid regular expression'), (dict(action='delete'), 'strip_sentence or reject'),
                 (dict(name='Bad Name'), 'lower-case'), (dict(bad=[]), 'at least one bad sentence'),
                 (dict(row=0), 'history row'), (dict(pattern='  '), 'pattern is empty')]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(gate_rules.RuleError, message):
                if 'row' in changes:
                    gate_rules.add_rule(self.rules, name='x', pattern=PATTERN, action='reject', bad=[SIGN_OFF],
                                        history_row=0, date='2026-11-11')
                else:
                    self.add(**changes)
        self.assertFalse(self.rules.exists())

    def test_a_second_rule_with_the_same_name_is_refused(self):
        self.add()
        with self.assertRaisesRegex(gate_rules.RuleError, 'exists'):
            self.add()
        self.assertEqual(len(json.loads(self.rules.read_text())), 1)

    def test_drop_removes_one_rule_and_keeps_the_rest(self):
        self.add()
        self.add(name='good-luck', pattern=r'^good luck\b', bad=['Good luck!'])
        gate_rules.drop_rule(self.rules, 'sign-off')
        self.assertEqual([entry['name'] for entry in json.loads(self.rules.read_text())], ['good-luck'])
        with self.assertRaisesRegex(gate_rules.RuleError, 'No rule named'):
            gate_rules.drop_rule(self.rules, 'sign-off')


class KnownGoodTests(unittest.TestCase):
    def test_the_shipped_file_holds_the_positive_cases_of_the_existing_tests(self):
        good = set(gate_rules.known_good())
        self.assertGreater(len(good), 150)
        for answer in test_choice_check.MISSING_FACT_QUESTIONS + ['chmod 640 gives the owner read and write access.',
                                                                    'The owner can read and write the file.']:
            for sentence in gate_rules.sentences(answer):
                if len(sentence.split()) >= 3:
                    with self.subTest(sentence=sentence):
                        self.assertIn(sentence, good)

    def test_every_known_good_sentence_passes_the_built_in_gate_untouched(self):
        for sentence in gate_rules.known_good():
            with self.subTest(sentence=sentence):
                self.assertEqual(h.validate_reply(reply(sentence), execution_confirmed=True).direct_answer, sentence)

    def test_notes_and_blank_lines_are_not_sentences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'good.txt'
            path.write_text('# a note\n\nKeep this line.\n', encoding='utf-8')
            self.assertEqual(gate_rules.known_good(path), ['Keep this line.'])


class GateTests(Base):
    def test_strip_sentence_cuts_the_sentence_and_keeps_the_rest(self):
        self.add()
        out = h.validate_reply(reply('The owner can read and write the file. ' + SIGN_OFF))
        self.assertEqual(out.direct_answer, 'The owner can read and write the file.')
        self.assertEqual(gate_rules.drain(), [{'kind': 'rule', 'name': 'sign-off', 'action': 'strip_sentence', 'text': SIGN_OFF}])
        self.assertEqual(gate_rules.drain(), [])

    def test_strip_keeps_list_marks_blank_lines_and_the_command(self):
        self.add()
        text = 'Two causes:\n1. The file is mode 644. Stay hydrated out there.\n2. There is no .env file.\n\nStay hydrated out there.'
        out = h.validate_reply(reply(text, "echo 'Stay hydrated out there.'"))
        self.assertEqual(out.direct_answer, 'Two causes:\n1. The file is mode 644.\n2. There is no .env file.')
        self.assertEqual(out.execution_payload, "echo 'Stay hydrated out there.'")

    def test_reject_raises_and_the_client_asks_for_one_corrected_reply(self):
        self.add(action='reject')
        with self.assertRaisesRegex(h.GateError, 'gate rule "sign-off"'):
            h.validate_reply(reply('It is mode 640. ' + SIGN_OFF))
        client = FakeClient([response(reply('It is mode 640. ' + SIGN_OFF)), response(reply('It is mode 640.'))])
        out = h.request_reply('what mode is it', client=client, log_path=self.root / 'usage.jsonl')
        self.assertEqual(out.direct_answer, 'It is mode 640.')
        self.assertEqual(len(client.calls), 2)
        self.assertIn('gate rule "sign-off"', client.calls[1]['input'][-1]['content'])

    def test_a_reply_that_is_only_cut_sentences_gets_the_corrective_retry(self):
        self.add()
        with self.assertRaisesRegex(h.GateError, 'Every sentence of the reply'):
            h.validate_reply(reply(SIGN_OFF))

    def test_the_rules_run_after_the_built_in_checks(self):
        self.add()
        # The built-in filler check rejects first; the rule never sees the reply.
        with self.assertRaisesRegex(h.GateError, 'blocked filler'):
            h.validate_reply(reply('The mode is 640. I hope this helps. ' + SIGN_OFF))
        self.assertEqual(gate_rules.drain(), [])

    def test_a_rule_added_while_the_chat_is_open_applies_to_the_next_reply(self):
        answer = 'The mode is 640. ' + SIGN_OFF
        self.assertEqual(h.validate_reply(reply(answer)).direct_answer, answer)
        self.add()
        self.assertEqual(h.validate_reply(reply(answer)).direct_answer, 'The mode is 640.')
        gate_rules.drop_rule(self.rules, 'sign-off')
        os.utime(self.rules, ns=(1, 1))
        self.assertEqual(h.validate_reply(reply(answer)).direct_answer, answer)

    def test_no_file_and_the_switched_off_state_leave_the_gate_as_it_was(self):
        answer = 'The mode is 640. ' + SIGN_OFF
        self.assertEqual(h.validate_reply(reply(answer)).direct_answer, answer)
        self.add()
        with patch.object(gate_rules, 'RULES_FILE', None):
            self.assertEqual(h.validate_reply(reply(answer)).direct_answer, answer)

    def test_a_broken_entry_is_skipped_and_named_and_the_others_still_run(self):
        self.add()
        entries = json.loads(self.rules.read_text())
        self.rules.write_text(json.dumps([{'name': 'broken'}, *entries, entries[0]]))
        rules, problems = gate_rules.load(self.rules)
        self.assertEqual([rule.name for rule in rules], ['sign-off'])
        self.assertEqual(len(problems), 2)
        with patch.object(gate_rules.sys, 'stderr', io.StringIO()) as err:
            out = h.validate_reply(reply('The mode is 640. ' + SIGN_OFF))
        self.assertEqual(out.direct_answer, 'The mode is 640.')
        self.assertIn('Rule entry 1', err.getvalue())
        self.rules.write_text('{not json')
        with patch.object(gate_rules.sys, 'stderr', io.StringIO()):
            self.assertEqual(h.validate_reply(reply('The mode is 640.')).direct_answer, 'The mode is 640.')


class HabitCheckTests(Base):
    def test_a_listed_sentence_is_cut_whatever_its_case_and_marks(self):
        with patch.object(habit_checks, 'CUT_SENTENCES', ['Let me know how it goes.']):
            out = h.validate_reply(reply('The mode is 640. **Let me know how it goes!**'))
            self.assertEqual(out.direct_answer, 'The mode is 640.')
            kept = h.validate_reply(reply('The log says: let me know how it goes with the build.'))
            self.assertEqual(kept.direct_answer, 'The log says: let me know how it goes with the build.')
        self.assertEqual(gate_rules.drain()[0]['name'], 'CUT_SENTENCES')

    def test_a_check_written_in_code_rejects_with_its_reason(self):
        def two_questions(answer, asked):
            return 'The reply asks more than one question. Ask one.' if answer.count('?') > 1 else None
        with patch.object(habit_checks, 'CHECKS', [two_questions]):
            with self.assertRaisesRegex(h.GateError, 'more than one question'):
                h.validate_reply(reply('Which file? Which folder?'))
            self.assertEqual(h.validate_reply(reply('Which file?')).direct_answer, 'Which file?')

    def test_the_shipped_lists_leave_known_good_sentences_alone(self):
        for sentence in gate_rules.known_good():
            answer, reason = habit_checks.apply(sentence, None, gate_rules.cut_sentences, gate_rules.note)
            self.assertEqual((answer, reason), (sentence, None))


class CommandTests(Base):
    def test_add_list_test_drop(self):
        code, out, err = self.run_cli('add', 'sign-off', '--row', str(self.row), '--action', 'strip_sentence',
                                      '--pattern', PATTERN, '--bad', SIGN_OFF)
        self.assertEqual((code, err), (0, ''))
        self.assertIn('Added rule "sign-off"', out)
        code, out, _ = self.run_cli('list')
        self.assertEqual(code, 0)
        self.assertIn(f'sign-off  strip_sentence  ', out)
        self.assertIn(f'row {self.row}', out)
        self.assertIn('bad: ' + SIGN_OFF, out)
        code, out, _ = self.run_cli('test')
        self.assertEqual((code, out), (0, 'ok sign-off\n'))
        code, out, _ = self.run_cli('test', '--text', 'The mode is 640. ' + SIGN_OFF)
        self.assertEqual(code, 0)
        self.assertIn('cut by sign-off: ' + SIGN_OFF, out)
        self.assertIn('shown: The mode is 640.', out)
        code, out, _ = self.run_cli('drop', 'sign-off')
        self.assertEqual((code, out), (0, 'Dropped rule "sign-off".\n'))
        self.assertEqual(self.run_cli('list')[1], 'No rules.\n')

    def test_add_refuses_a_bad_rule_with_exit_1_and_writes_nothing(self):
        code, out, err = self.run_cli('add', 'too-wide', '--row', str(self.row), '--action', 'strip_sentence',
                                      '--pattern', r'\bfile\b', '--bad', 'The file is here.')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('was refused', err)
        self.assertIn('known-good sentence', err)
        self.assertFalse(self.rules.exists())

    def test_add_refuses_a_rule_without_a_real_history_row(self):
        code, _, err = self.run_cli('add', 'sign-off', '--row', '999', '--action', 'strip_sentence',
                                    '--pattern', PATTERN, '--bad', SIGN_OFF)
        self.assertEqual(code, 1)
        self.assertIn('No history row 999', err)
        self.assertFalse(self.rules.exists())
        code, _, err = self.run_cli('add', 'sign-off', '--action', 'strip_sentence', '--pattern', PATTERN, '--bad', SIGN_OFF)
        self.assertEqual(code, 2)

    def test_test_fails_when_a_stored_rule_no_longer_passes(self):
        self.add()
        code, out, _ = gate_rules_cli.main(['test'], rules_file=self.rules, good=['Please stay hydrated.'],
                                           out=io.StringIO(), err=io.StringIO()), None, None
        self.assertEqual(code, 1)
        self.assertEqual(self.run_cli('test', 'nope')[0], 1)

    def test_wrong_use_is_exit_2(self):
        for argv in ([], ['add'], ['drop'], ['nonsense'], ['add', 'x', '--row', 'abc', '--action', 'reject', '--pattern', 'x', '--bad', 'x']):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv)[0], 2)

    def test_the_command_file_runs_the_same_code(self):
        done = subprocess.run(['sh', str(h.ROOT / 'toolbox' / 'bin' / 'rule')], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn('rule add NAME', done.stderr)


if __name__ == '__main__':
    unittest.main()
