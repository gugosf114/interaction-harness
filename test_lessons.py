"""The lessons page: dated fact lines in state/lessons.md, carried as the last page on every call."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import harness as h
import lessons
import lessons_cli
import pages
from storage import Store
from test_harness import FakeClient, document, response
from test_tools_block import AnthropicFake

FACT = 'The harness repo is gugosf114/interaction-harness.'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config'
        self.config.mkdir()
        self.state = Path(self.tmp.name) / 'lane'
        patcher = patch.object(h, 'STATE', self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = Store(self.state)
        self.row = store.begin('which repo', 'which repo', 'openai', 'gpt-test', 'session-a')
        store.finish(self.row, h.validate_reply(document()), [])
        store.close()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = lessons_cli.main(list(argv), config=self.config, history=self.state / 'history.db', out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def page_list(self):
        return json.loads((self.config / 'pages.json').read_text())


class LessonFileTests(Base):
    def test_add_appends_one_dated_line_that_names_its_row(self):
        entry = lessons.add(self.config, FACT, self.row, '2026-11-11')
        text = (self.config / 'lessons.md').read_text()
        self.assertTrue(text.startswith('# Lessons\n'))
        self.assertTrue(text.endswith(f'- 2026-11-11 (row {self.row}): {FACT}\n'))
        self.assertEqual((entry['number'], entry['row'], entry['text']), (1, self.row, FACT))
        lessons.add(self.config, 'Yana answers the bakery mailbox.', self.row, '2026-11-12')
        self.assertEqual([item['text'] for item in lessons.entries(self.config)], [FACT, 'Yana answers the bakery mailbox.'])
        self.assertEqual(text, (self.config / 'lessons.md').read_text()[:len(text)])

    def test_the_page_goes_last_on_the_list_and_other_entries_are_untouched(self):
        rules = self.config / 'rules.md'
        rules.write_text('## Core\nAnswer first.\n')
        (self.config / 'pages.json').write_text(json.dumps([{'label': 'rules', 'path': str(rules), 'sections': ['## Core']}]))
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        listed = self.page_list()
        self.assertEqual(listed[0], {'label': 'rules', 'path': str(rules), 'sections': ['## Core']})
        self.assertEqual(listed[1], {'label': 'lessons', 'path': str((self.config / 'lessons.md').resolve())})
        # A page someone lists later does not stay behind the lessons page.
        listed.append({'label': 'profile', 'path': str(rules)})
        (self.config / 'pages.json').write_text(json.dumps(listed))
        lessons.add(self.config, 'Yana answers the bakery mailbox.', self.row, '2026-11-11')
        self.assertEqual([entry['label'] for entry in self.page_list()], ['rules', 'profile', 'lessons'])
        self.assertEqual([page.label for page in pages.read_pages(self.config / 'pages.json')], ['rules', 'profile', 'lessons'])

    def test_drop_removes_one_line_and_the_page_leaves_the_list_with_the_last_lesson(self):
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        lessons.add(self.config, 'Yana answers the bakery mailbox.', self.row, '2026-11-11')
        gone = lessons.drop(self.config, 1)
        self.assertEqual(gone['text'], FACT)
        self.assertEqual([item['text'] for item in lessons.entries(self.config)], ['Yana answers the bakery mailbox.'])
        self.assertEqual([entry['label'] for entry in self.page_list()], ['lessons'])
        lessons.drop(self.config, 1)
        self.assertEqual(self.page_list(), [])
        self.assertEqual(pages.read_pages(self.config / 'pages.json'), [])
        with self.assertRaisesRegex(lessons.LessonError, 'No lesson 1'):
            lessons.drop(self.config, 1)

    def test_bad_lessons_are_refused(self):
        for text, row, message in (('   ', self.row, 'empty'), ('bell \x07 here', self.row, 'control characters'),
                                   (FACT, 0, 'history row')):
            with self.subTest(text=text), self.assertRaisesRegex(lessons.LessonError, message):
                lessons.add(self.config, text, row, '2026-11-11')
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        with self.assertRaisesRegex(lessons.LessonError, 'already on the page'):
            lessons.add(self.config, FACT.upper(), self.row, '2026-11-12')
        self.assertEqual(len(lessons.entries(self.config)), 1)

    def test_line_breaks_in_a_lesson_become_one_line(self):
        entry = lessons.add(self.config, 'The repo is\n  gugosf114/interaction-harness.', self.row, '2026-11-11')
        self.assertEqual(entry['text'], 'The repo is gugosf114/interaction-harness.')

    def test_a_lesson_that_would_break_the_page_limit_is_refused_and_nothing_changes(self):
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        before, before_list = (self.config / 'lessons.md').read_text(), (self.config / 'pages.json').read_text()
        with self.assertRaisesRegex(lessons.LessonError, 'exceeds 20000 characters'):
            lessons.add(self.config, 'x' * 20000, self.row, '2026-11-11')
        self.assertEqual((self.config / 'lessons.md').read_text(), before)
        self.assertEqual((self.config / 'pages.json').read_text(), before_list)

    def test_the_first_lesson_is_refused_whole_when_another_listed_page_is_broken(self):
        (self.config / 'pages.json').write_text(json.dumps([{'label': 'rules', 'path': str(self.config / 'missing.md')}]))
        before = (self.config / 'pages.json').read_text()
        with self.assertRaisesRegex(lessons.LessonError, 'missing or unreadable'):
            lessons.add(self.config, FACT, self.row, '2026-11-11')
        self.assertFalse((self.config / 'lessons.md').exists())
        self.assertEqual((self.config / 'pages.json').read_text(), before)


class NextRequestTests(Base):
    """A fact lesson reaches the next request as the last page, on both engines."""

    def test_openai_gets_the_lessons_page_last(self):
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        client = FakeClient([response()])
        with patch.object(h, 'PAGES_FILE', self.config / 'pages.json'):
            h.request_reply('Which repo holds the harness?', client=client, log_path=self.state / 'usage.jsonl')
        system = [message['content'] for message in client.calls[0]['input'] if message['role'] == 'system']
        self.assertIn(f'(row {self.row}): {FACT}', system[-1])
        self.assertTrue(system[-1].startswith('# Lessons'))
        event = json.loads((self.state / 'usage.jsonl').read_text().splitlines()[-1])
        self.assertEqual(event['pages'][-1]['label'], 'lessons')

    def test_claude_gets_the_lessons_page_last_with_the_cache_marker(self):
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        client = AnthropicFake()
        with patch.object(h, 'PAGES_FILE', self.config / 'pages.json'):
            h.request_reply('Which repo holds the harness?', client=client, engine='anthropic', log_path=self.state / 'usage.jsonl')
        system = client.calls[0]['system']
        self.assertIn(FACT, system[-1]['text'])
        self.assertEqual(system[-1]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(sum('cache_control' in block for block in system), 2)

    def test_the_pages_before_it_are_byte_identical_after_a_new_lesson(self):
        lessons.add(self.config, FACT, self.row, '2026-11-11')
        client = FakeClient([response(), response()])
        with patch.object(h, 'PAGES_FILE', self.config / 'pages.json'):
            h.request_reply('first', client=client, log_path=self.state / 'usage.jsonl')
            lessons.add(self.config, 'Yana answers the bakery mailbox.', self.row, '2026-11-11')
            h.request_reply('second', client=client, log_path=self.state / 'usage.jsonl')
        first = [m['content'] for m in client.calls[0]['input'] if m['role'] == 'system']
        second = [m['content'] for m in client.calls[1]['input'] if m['role'] == 'system']
        self.assertEqual(first[:-1], second[:-1])
        self.assertTrue(second[-1].startswith(first[-1]))


class CommandTests(Base):
    def test_add_list_drop(self):
        code, out, err = self.run_cli('add', '--row', str(self.row), FACT)
        self.assertEqual((code, err), (0, ''))
        self.assertIn(f'(row {self.row}): {FACT}', out)
        code, out, _ = self.run_cli('add', 'Yana answers the bakery mailbox.', '--row', str(self.row))
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli('list')
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 2)
        self.assertTrue(out.splitlines()[0].startswith('1. '))
        self.assertIn(FACT, out)
        code, out, _ = self.run_cli('drop', '1')
        self.assertEqual((code, out), (0, f'Dropped lesson 1: {FACT}\n'))
        self.run_cli('drop', '1')
        self.assertEqual(self.run_cli('list')[1], 'No lessons.\n')

    def test_nothing_is_added_without_a_real_history_row(self):
        code, out, err = self.run_cli('add', '--row', '999', FACT)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('No history row 999', err)
        self.assertFalse((self.config / 'lessons.md').exists())
        for argv in (['add', FACT], ['add', '--row', 'x', FACT], ['add', '--row', str(self.row)], [], ['drop'], ['drop', 'x'], ['what']):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv)[0], 2)
        self.assertFalse((self.config / 'lessons.md').exists())

    def test_a_refusal_is_exit_1(self):
        self.run_cli('add', '--row', str(self.row), FACT)
        code, _, err = self.run_cli('add', '--row', str(self.row), FACT)
        self.assertEqual(code, 1)
        self.assertIn('already on the page', err)
        self.assertEqual(self.run_cli('drop', '7')[0], 1)

    def test_the_command_file_runs_the_same_code(self):
        done = subprocess.run(['sh', str(h.ROOT / 'toolbox' / 'bin' / 'lesson')], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn('lesson add --row N', done.stderr)


if __name__ == '__main__':
    unittest.main()
