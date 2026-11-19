"""Sessions: fork, /fork, /rewind, cut, splice, the golden session, the list and the export."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cli
import harness as h
import recall_notes as rn
import session_tools as st
from storage import atomic_json
from test_advisor import reply

ROOT = Path(__file__).resolve().parent


def turn(text, answer=None, step=None, engine='anthropic'):
    item = {'raw_input': text, 'normalized_input': text, 'engine': engine, 'model': 'claude-opus-5-5' if engine == 'anthropic' else 'gpt-6.1-sol',
            'reply': {'intent': 'observation', 'cleaned_input': text, 'direct_answer': answer or f'answer to {text}', 'execution_payload': None}}
    if step:
        item['loop_step'] = step
    return item


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        for started in (patch.object(h, 'STATE', self.state), patch.object(rn, 'CORPORA', None),
                        patch.dict(os.environ, {'DEFAULT_ENGINE': 'anthropic'}, clear=False)):
            started.start()
            self.addCleanup(started.stop)

    def save(self, name, turns, **extra):
        atomic_json(self.state / 'sessions' / f'{name}.json',
                    {'version': 1, 'id': name, 'created_at': '2026-11-11T10:00:00+00:00', 'updated_at': '2026-11-11T10:00:00+00:00',
                     'turns': turns, **extra})

    def load(self, name):
        return json.loads((self.state / 'sessions' / f'{name}.json').read_text())

    def run_cli(self, args, answers=None, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        answers = list(answers or [reply()])
        with patch.object(h, 'request_reply', side_effect=answers) as api, patch.object(cli, 'native', side_effect=[]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                if stdin is None:
                    code = h.main(['--usage-log', str(self.state.parent / 'u.jsonl'), *args])
                else:
                    with patch.object(cli.sys, 'stdin', io.StringIO(stdin)):
                        code = h.main(['--usage-log', str(self.state.parent / 'u.jsonl'), *args])
        return code, out.getvalue(), err.getvalue(), api

    def command(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = st.command(list(argv), state=self.state, out=out)
        return code, out.getvalue(), err.getvalue()


class ToolTests(SessionCase):
    def test_groups_keep_loop_steps_with_their_exchange(self):
        turns = [turn('a'), turn('b', step=1), turn('Continue', step=2), turn('Continue', step=3), turn('c')]
        self.assertEqual(st.groups(turns), [[0], [1, 2, 3], [4]])

    def test_fork_is_a_full_copy_and_the_source_is_untouched(self):
        self.save('base', [turn('a'), turn('b')])
        before = (self.state / 'sessions' / 'base.json').read_bytes()
        code, out, _ = self.command('fork', 'base', 'copy')
        self.assertEqual(code, 0)
        self.assertIn('copy: a copy of base with 2 exchanges', out)
        self.assertEqual((self.state / 'sessions' / 'base.json').read_bytes(), before)
        copy = self.load('copy')
        self.assertEqual(copy['turns'], self.load('base')['turns'])
        self.assertEqual(copy['forked_from']['id'], 'base')
        self.assertEqual(self.command('fork', 'base', 'copy')[0], 1)        # never overwrites
        self.assertEqual(st.fork(self.state, 'base')[0], 'base-fork')
        self.assertEqual(st.fork(self.state, 'base')[0], 'base-fork-2')

    def test_rewind_drops_whole_exchanges_and_keeps_them_aside(self):
        self.save('s', [turn('a'), turn('b', step=1), turn('Continue', step=2), turn('c')])
        code, out, _ = self.command('rewind', 's', '2')
        self.assertEqual(code, 0)
        self.assertIn('s: 1 exchange left.', out)
        self.assertIn('dropped: b', out)
        self.assertIn('dropped: c', out)
        self.assertEqual([t['raw_input'] for t in self.load('s')['turns']], ['a'])
        aside = [json.loads(line) for line in (self.state / 'sessions' / 's.removed.jsonl').read_text().splitlines()]
        self.assertEqual([item['exchange']['raw_input'] for item in aside], ['b', 'Continue', 'c'])
        self.assertEqual(len(self.load('s')['rewound']), 3)
        self.assertEqual(self.command('rewind', 's', '5')[0], 1)

    def test_cut_and_splice(self):
        self.save('s', [turn('a'), turn('b'), turn('c'), turn('d')])
        self.save('o', [turn('x'), turn('y')])
        self.assertEqual(self.command('cut', 's', '2', '3')[0], 0)
        self.assertEqual([t['raw_input'] for t in self.load('s')['turns']], ['a', 'd'])
        code, out, _ = self.command('splice', 's', 'o')
        self.assertEqual(code, 0)
        self.assertIn('2 exchanges added from o; 4 exchanges now', out)
        self.assertEqual([t['raw_input'] for t in self.load('s')['turns']], ['a', 'd', 'x', 'y'])
        self.assertEqual(self.command('splice', 's', 'o', '2', '2')[0], 0)
        self.assertEqual(self.load('s')['turns'][-1]['raw_input'], 'y')
        self.assertEqual(len(self.load('o')['turns']), 2)
        self.assertEqual(self.command('cut', 's', '3', '9')[0], 1)
        self.assertEqual(self.command('splice', 's', 's')[0], 1)

    def test_list_shows_date_lane_count_and_first_line(self):
        self.save('alpha', [turn('first question here\nsecond line'), turn('more')])
        self.save('beta', [turn('gpt question', engine='openai')])
        st.set_golden(self.state, 'alpha')
        code, out, _ = self.command('list')
        self.assertEqual(code, 0)
        self.assertRegex(out, r'\* +2026-11-1[01] \d\d:\d\d  alpha  g2 \(claude-opus-5-5\)\s+2  first question here\n')
        self.assertIn('g1 (gpt-6.1-sol)', out)
        self.assertIn('2 sessions.', out)
        self.assertIn('* golden: every new chat starts as a copy of alpha.', out)

    def test_show_and_text_export(self):
        self.save('s', [turn('hello there')])
        code, out, _ = self.command('show', 's')
        self.assertEqual(code, 0)
        self.assertIn('[1] George:\nhello there', out)
        self.assertIn('answer to hello there', out)
        target = self.state.parent / 'out.txt'
        self.assertEqual(self.command('export', 's', '--out', str(target))[0], 0)
        self.assertIn('hello there', target.read_text())

    def test_pdf_export_calls_weasyprint_and_reports_the_file(self):
        self.save('s', [turn('<b>bold</b> & more')])
        target = self.state.parent / 's.pdf'
        seen = {}

        def fake(cmd, **_):
            seen['cmd'] = cmd
            seen['html'] = Path(cmd[-2]).read_text()
            Path(cmd[-1]).write_bytes(b'%PDF-1.7 test')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        path, size = st.export_pdf(self.state, 's', str(target), run=fake)
        self.assertEqual((path, size), (str(target), 13))
        self.assertTrue(any(Path(part).name == 'weasyprint' for part in seen['cmd']))
        self.assertIn('&lt;b&gt;bold&lt;/b&gt; &amp; more', seen['html'])
        self.assertEqual(st.export_pdf.__defaults__[0], None)
        self.assertEqual(st.DOWNLOADS, '/sdcard/Download')

    def test_golden_set_clear(self):
        self.assertEqual(self.command('golden')[1], 'No golden session is set.\n')
        self.assertEqual(self.command('golden', 'nope')[0], 1)
        self.save('g', [turn('page')])
        self.assertEqual(self.command('golden', 'g')[0], 0)
        self.assertEqual(st.golden(self.state), 'g')
        self.assertEqual(self.command('golden', '--clear')[0], 0)
        self.assertIsNone(st.golden(self.state))

    def test_bad_usage_is_exit_2(self):
        self.assertEqual(self.command('frobnicate')[0], 2)
        self.assertEqual(self.command('rewind', 's', 'zero')[0], 1)


class CliTests(SessionCase):
    def test_fork_flag_copies_then_continues_apart(self):
        self.save('base', [turn('the base question')])
        code, _, err, api = self.run_cli(['--fork', 'base', 'branch', '--', 'next question'])
        self.assertEqual(code, 0)
        self.assertIn('Forked base -> branch (1 exchange). base is unchanged.', err)
        history = api.call_args.kwargs['history']
        self.assertEqual(history[0]['content'], 'the base question')
        self.assertEqual(len(self.load('base')['turns']), 1)
        self.assertEqual([t['raw_input'] for t in self.load('branch')['turns']], ['the base question', 'next question'])

    def test_fork_flag_without_new_name(self):
        self.save('base', [turn('q')])
        code, _, _, _ = self.run_cli(['--fork', 'base', '--', 'two words'])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.load('base-fork')['turns']), 2)

    def test_chat_fork_and_rewind(self):
        self.save('live', [turn('one'), turn('two'), turn('three')])
        script = '/rewind 2\nafter rewind\n/fork side\non the side\nquit\n'
        code, _, err, api = self.run_cli(['--chat', '--session', 'live'], answers=[reply(), reply()], stdin=script)
        self.assertEqual(code, 0)
        self.assertIn('Rewound live: 1 exchange left.', err)
        self.assertIn('Forked live -> side', err)
        first_history = [m['content'] for m in api.call_args_list[0].kwargs['history']]
        self.assertIn('one', first_history)
        self.assertNotIn('two', first_history)
        self.assertNotIn('three', first_history)
        self.assertEqual([t['raw_input'] for t in self.load('live')['turns']], ['one', 'after rewind'])
        self.assertEqual([t['raw_input'] for t in self.load('side')['turns']], ['one', 'after rewind', 'on the side'])

    def test_chat_recall_switch(self):
        code, _, err, _ = self.run_cli(['--chat', '--session', 'sw'], answers=[], stdin='/off recall\n/on recall\nquit\n')
        self.assertEqual(code, 0)
        self.assertIn('recall off.', err)
        self.assertIn('recall on.', err)

    def test_golden_seeds_every_new_session_and_new_skips_it(self):
        self.save('gold', [turn('the golden page')])
        st.set_golden(self.state, 'gold')
        code, _, _, api = self.run_cli(['a fresh question'])
        self.assertEqual(code, 0)
        self.assertEqual(api.call_args.kwargs['history'][0]['content'], 'the golden page')
        self.assertEqual(len(self.load('gold')['turns']), 1)
        code, _, _, api = self.run_cli(['--new', 'empty please'])
        self.assertEqual(api.call_args.kwargs['history'], [])
        code, _, _, api = self.run_cli(['--session', 'named-new', 'a named question'])
        self.assertEqual(api.call_args.kwargs['history'][0]['content'], 'the golden page')
        st.set_golden(self.state, None)
        code, _, _, api = self.run_cli(['after clear'])
        self.assertEqual(api.call_args.kwargs['history'], [])

    def test_from_flag(self):
        self.save('src', [turn('source page')])
        code, _, _, api = self.run_cli(['--from', 'src', '--session', 'dest', 'go'])
        self.assertEqual(code, 0)
        self.assertEqual(api.call_args.kwargs['history'][0]['content'], 'source page')
        code, _, err, _ = self.run_cli(['--from', 'src', '--session', 'dest', 'again'])
        self.assertEqual(code, 2)
        self.assertIn('already exists', err)

    def test_rewound_turns_stay_in_history_db(self):
        self.run_cli(['--session', 'h', 'keep me in the database'])
        st.rewind(self.state, 'h', 1)
        import sqlite3
        rows = sqlite3.connect(self.state / 'history.db').execute('SELECT raw_input FROM history').fetchall()
        self.assertIn(('keep me in the database',), rows)
        self.assertEqual(self.load('h')['turns'], [])


class CommandFileTests(unittest.TestCase):
    def test_toolbox_commands_exist(self):
        for name in ('session', 'sessions', 'note', 'past-chats'):
            path = ROOT / 'toolbox' / 'bin' / name
            self.assertTrue(os.access(path, os.X_OK), name)
        self.assertEqual(os.readlink(ROOT / 'toolbox' / 'bin' / 'sessions'), 'session')


if __name__ == '__main__':
    unittest.main()
