"""/wrong WORDS: a correction case in history, then a loop run that turns it into a lesson or a gate rule."""
import contextlib
import io
import json
from pathlib import Path
import shlex
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import cli
import corrections
import gate_rules
import gate_rules_cli
import harness as h
import lessons
import lessons_cli
from test_harness import FakeClient, document, response

SIGN_OFF = 'Stay hydrated out there.'


def reply(answer, payload=None):
    return response(document(intent='action_request' if payload else 'observation', direct_answer=answer, execution_payload=payload))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'lane'
        self.config = Path(self.tmp.name) / 'config'
        self.config.mkdir()
        for target, name, value in ((h, 'STATE', self.state), (h, 'PAGES_FILE', self.config / 'pages.json'),
                                    (gate_rules, 'RULES_FILE', self.config / 'gate_rules.json')):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        gate_rules.drain()
        self.commands = []

    def native(self, request):
        """Stands in for the Termux runner: runs `lesson` and `rule` through the same code the commands use."""
        self.commands.append(request['command'])
        words = shlex.split(request['command'])
        out, err = io.StringIO(), io.StringIO()
        if words[0] == 'lesson':
            code = lessons_cli.main(words[1:], config=self.config, history=self.state / 'history.db', out=out, err=err)
        elif words[0] == 'rule':
            code = gate_rules_cli.main(words[1:], rules_file=self.config / 'gate_rules.json',
                                       history=self.state / 'history.db', out=out, err=err)
        else:
            code = 0
            out.write('card text\n')
        return {'approved': True, 'exit_code': code, 'stdout': out.getvalue(), 'stderr': err.getvalue(), 'timed_out': False}

    def run_client(self, argv, client, stdin=''):
        real = h.request_reply

        def working_model(current, **kwargs):
            return real(current, client=client, **kwargs)

        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=working_model), patch.object(cli, 'native', side_effect=self.native), \
                patch.object(cli.sys, 'stdin', io.StringIO(stdin)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(argv)
        return code, out.getvalue(), err.getvalue()

    def rows(self):
        db = sqlite3.connect(self.state / 'history.db')
        db.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in db.execute('SELECT * FROM history ORDER BY id')]
        finally:
            db.close()


class FactTests(Base):
    def test_a_fact_becomes_a_lesson_and_a_new_session_gets_it_as_a_page(self):
        client = FakeClient([
            reply('Nothing I can see names the code word.'),
            reply('This adds the fact to the lessons page.', "lesson add --row 2 'The code word for the build is marzipan-42.'"),
            reply('The lessons page now holds the code word.'),
            reply('marzipan-42.'),
        ])
        code, out, err = self.run_client(['--chat', '--session', 'first'], client,
                                         'What is the code word for the build?\n/wrong the code word for the build is marzipan-42\nexit\n')
        self.assertEqual(code, 0)
        self.assertIn('Correction saved as history row 2.', err)
        rows = self.rows()
        case = rows[1]
        self.assertEqual((case['status'], case['raw_input'], case['normalized_input']),
                         ('correction', '/wrong the code word for the build is marzipan-42', 'the code word for the build is marzipan-42'))
        self.assertEqual(case['cleaned_input'], 'What is the code word for the build?')
        self.assertEqual(case['direct_answer'], 'Nothing I can see names the code word.')
        gate = json.loads(case['gate_json'])
        self.assertEqual(gate['corrects_row'], 1)
        self.assertEqual(gate['outcomes'][0]['bin'], 'fact')
        self.assertIn('(row 2): The code word for the build is marzipan-42.', gate['outcomes'][0]['lesson'])
        # The lane got the case as its loop task: the row, the request, the answer and George's words.
        task = client.calls[1]['input'][-1]['content']
        for part in ('history row 2', 'What is the code word for the build?', 'Nothing I can see names the code word.',
                     'the code word for the build is marzipan-42', 'lesson add --row 2', 'rule add NAME --row 2', 'card self'):
            self.assertIn(part, task)
        self.assertEqual(self.commands, ["lesson add --row 2 'The code word for the build is marzipan-42.'"])
        self.assertEqual([entry['row'] for entry in lessons.entries(self.config)], [2])
        # A new session: the fact rides in as the last page.
        code, out, _ = self.run_client(['--new', 'What is the code word for the build?'], client)
        self.assertEqual((code, out), (0, 'marzipan-42.\n'))
        system = [message['content'] for message in client.calls[3]['input'] if message['role'] == 'system']
        self.assertIn('(row 2): The code word for the build is marzipan-42.', system[-1])
        earlier = [message['content'] for message in client.calls[0]['input'] if message['role'] == 'system']
        self.assertEqual(system[:-1], earlier)

    def test_the_correction_run_is_a_loop_even_when_the_chat_is_not(self):
        client = FakeClient([reply('Paris.'), reply('This adds the fact.', "lesson add --row 2 'The capital asked about is Lyon.'"),
                             reply('The lessons page now holds it.')])
        self.run_client(['--chat', '--session', 'plain'], client, 'Which city?\n/wrong it is Lyon\nexit\n')
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(self.commands), 1)
        session = json.loads((self.state / 'sessions' / 'plain.json').read_text())
        self.assertEqual([turn.get('loop_step') for turn in session['turns']], [None, 1, 2])


class HabitTests(Base):
    def test_a_habit_becomes_a_rule_and_the_next_reply_loses_the_sentence(self):
        add = ("rule add sign-off --row 2 --action strip_sentence --pattern '\\bstay hydrated\\b' "
               "--bad 'Stay hydrated out there.'")
        client = FakeClient([
            reply('It gives the owner read and write access. ' + SIGN_OFF),
            reply('This prints the card with the exact form.', 'card lessons'),
            reply('This adds a rule that cuts the sign-off.', add),
            reply('The gate now cuts that sign-off.'),
            reply('Mode 600 is owner read and write only. ' + SIGN_OFF),
        ])
        code, out, err = self.run_client(['--chat', '--session', 'habit'], client,
                                         'What does chmod 640 mean?\n/wrong stop adding sign-off lines like that\nexit\n')
        self.assertEqual(code, 0)
        self.assertIn(SIGN_OFF, out)
        self.assertEqual(self.commands, ['card lessons', add])
        entries = json.loads((self.config / 'gate_rules.json').read_text())
        self.assertEqual([(entry['name'], entry['action'], entry['history_row'], entry['bad']) for entry in entries],
                         [('sign-off', 'strip_sentence', 2, [SIGN_OFF])])
        gate = json.loads(self.rows()[1]['gate_json'])
        self.assertEqual([(outcome['bin'], outcome['rule']) for outcome in gate['outcomes']], [('habit', 'sign-off')])
        # The next reply, in a new session: the model writes the sentence again and the gate cuts it.
        code, out, _ = self.run_client(['--new', 'What does chmod 600 mean?'], client)
        self.assertEqual((code, out), (0, 'Mode 600 is owner read and write only.\n'))
        last = self.rows()[-1]
        self.assertEqual(last['direct_answer'], 'Mode 600 is owner read and write only.')
        self.assertEqual(json.loads(last['gate_json'])['rules_fired'],
                         [{'kind': 'rule', 'name': 'sign-off', 'action': 'strip_sentence', 'text': SIGN_OFF}])

    def test_a_refused_rule_goes_back_to_the_lane_as_a_failed_command(self):
        wide = "rule add wide --row 2 --action strip_sentence --pattern 'the' --bad 'the thing'"
        good = "rule add sign-off --row 2 --action strip_sentence --pattern '\\bstay hydrated\\b' --bad 'Stay hydrated out there.'"
        client = FakeClient([reply('It is mode 640. ' + SIGN_OFF), reply('This adds the rule.', wide),
                             reply('The pattern was too wide. This one names the sign-off.', good), reply('The gate now cuts it.')])
        code, _, _ = self.run_client(['--chat', '--session', 'retry'], client, 'What mode?\n/wrong no sign-offs\nexit\n')
        self.assertEqual(code, 0)
        feedback = json.loads(client.calls[2]['input'][-2]['content'])
        self.assertEqual(feedback['result']['exit_code'], 1)
        self.assertIn('known-good sentence', feedback['result']['stderr'])
        self.assertEqual([entry['name'] for entry in json.loads((self.config / 'gate_rules.json').read_text())], ['sign-off'])


class CaseTests(Base):
    def test_wrong_needs_words_a_session_and_an_earlier_answer(self):
        client = FakeClient([])
        code, out, err = self.run_client(['--chat', '--session', 'empty'], client, '/wrong\n/wrong that was off\nexit\n')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('Say what was wrong: /wrong WORDS', err)
        self.assertIn('Nothing to correct yet', err)
        code, _, err = self.run_client(['/wrong that was off'], client)
        self.assertEqual(code, 2)
        self.assertIn('add -c or --session NAME', err)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.rows(), [])

    def test_after_a_loop_run_the_case_holds_the_original_task_and_the_final_answer(self):
        turns = [{'normalized_input': 'older', 'reply': {'direct_answer': 'old'}},
                 {'normalized_input': 'Count the files.', 'loop_step': 1, 'reply': {'direct_answer': 'This counts them.'}},
                 {'normalized_input': 'Continue the original task.', 'loop_step': 2, 'reply': {'direct_answer': 'There are 3.'}}]
        self.assertEqual(corrections.previous_exchange(turns), ('Count the files.', 'There are 3.'))
        self.assertEqual(corrections.previous_exchange(turns[:1]), ('older', 'old'))

    def test_recall_does_not_show_a_correction_case(self):
        client = FakeClient([reply('Paris holds the answer.'), reply('This adds it.', "lesson add --row 2 'It is Lyon.'"),
                             reply('The page holds it.')])
        self.run_client(['--chat', '--session', 'recall'], client, 'Which city?\n/wrong it is Lyon\nexit\n')
        code, out, _ = self.run_client(['--recall', 'Paris'], client)
        self.assertEqual(code, 0)
        self.assertEqual(out.count('Paris holds the answer.'), 1)

    def test_a_trigger_is_the_whole_first_word(self):
        for line in ('/wrong', '/wrong it is Lyon', '/wrong\tit is Lyon'):
            self.assertTrue(corrections.is_trigger(line))
        for line in ('/wrongly', 'wrong', ' /wrong x', 'that is /wrong'):
            self.assertFalse(corrections.is_trigger(line))


if __name__ == '__main__':
    unittest.main()
