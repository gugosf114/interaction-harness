"""self-clone and self-update: test, push, pull. The suite is a stand-in here; git is real, on local repositories."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import harness as h
import self_update

IDENTITY = ['-c', 'user.name=test', '-c', 'user.email=test@localhost']


def git(folder, *arguments):
    done = subprocess.run(['git', '-C', str(folder), *IDENTITY, *arguments], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr)
    return done.stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin, self.live, self.work, self.other = root / 'origin.git', root / 'live', root / 'work', root / 'other'
        subprocess.run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', str(self.origin)], check=True, timeout=120)
        seed = root / 'seed'
        subprocess.run(['git', 'init', '--quiet', '--initial-branch=main', str(seed)], check=True, timeout=120)
        (seed / 'habit_checks.py').write_text('CUT_SENTENCES = [\n]\n')
        (seed / 'test_habit_checks.py').write_text('# tests\n')
        (seed / '.gitignore').write_text('.venv\n')
        git(seed, 'add', '-A')
        git(seed, 'commit', '--quiet', '-m', 'seed')
        git(seed, 'remote', 'add', 'origin', str(self.origin))
        git(seed, 'push', '--quiet', 'origin', 'main')
        for folder in (self.live, self.other):
            subprocess.run(['git', 'clone', '--quiet', str(self.origin), str(folder)], check=True, timeout=120)
        (self.live / '.venv').mkdir()
        self.suite_calls = []
        self.suite_result = {}

    def suite(self, folder):
        self.suite_calls.append(Path(folder).name)
        code = self.suite_result.get(Path(folder).name, 0)
        return code, ('FAILED (failures=1)\n' if code else 'Ran 12 tests in 0.5s\n\nOK\n')

    def clone(self):
        out = io.StringIO()
        code = self_update.clone(self.work, self.live, out=out)
        return code, out.getvalue()

    def update(self, message='feat: cut one more sign-off'):
        out, err = io.StringIO(), io.StringIO()
        code = self_update.update(message, self.work, self.live, suite=self.suite, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def change(self, text="CUT_SENTENCES = [\n    'Good luck!',\n]\n"):
        (self.work / 'habit_checks.py').write_text(text)
        (self.work / 'test_new_habit.py').write_text('# a new test\n')

    def tip(self, folder):
        return git(folder, 'rev-parse', 'HEAD')

    def origin_tip(self):
        return git(self.origin, 'rev-parse', 'main')

    def push_from_other(self, name='other.txt'):
        git(self.other, 'pull', '--quiet', 'origin', 'main')
        (self.other / name).write_text('landed by another worker\n')
        git(self.other, 'add', '-A')
        git(self.other, 'commit', '--quiet', '-m', 'other work')
        git(self.other, 'push', '--quiet', 'origin', 'main')


class CloneTests(Base):
    def test_clone_makes_a_working_copy_at_the_tip_with_the_python_environment_linked(self):
        code, out = self.clone()
        self.assertEqual(code, 0)
        self.assertIn(f'Working copy ready: {self.work}', out)
        self.assertEqual(self.tip(self.work), self.origin_tip())
        self.assertTrue((self.work / '.venv').is_symlink())
        self.assertEqual(os.readlink(self.work / '.venv'), str(self.live / '.venv'))
        self.assertEqual(git(self.work, 'status', '--porcelain'), '')

    def test_clone_again_refreshes_a_clean_copy_and_leaves_unlanded_work_alone(self):
        self.clone()
        self.push_from_other()
        code, out = self.clone()
        self.assertEqual(code, 0)
        self.assertEqual(self.tip(self.work), self.origin_tip())
        self.change()
        code, out = self.clone()
        self.assertEqual(code, 0)
        self.assertIn('work that is not on main', out)
        self.assertIn('habit_checks.py', out)
        self.assertIn("'Good luck!'", (self.work / 'habit_checks.py').read_text())

    def test_the_live_folder_is_never_a_working_copy(self):
        self.assertEqual(self_update.clone(self.live, self.live, out=io.StringIO(), err=io.StringIO()), 2)


class UpdateTests(Base):
    def test_a_change_with_passing_tests_lands_on_main_and_in_the_live_folder(self):
        self.clone()
        self.change()
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.suite_calls, ['work'])  # the live folder ends at the tested commit: one suite run
        self.assertEqual(self.origin_tip(), self.tip(self.work))
        self.assertEqual(self.tip(self.live), self.origin_tip())
        self.assertIn("'Good luck!'", (self.live / 'habit_checks.py').read_text())
        self.assertTrue((self.live / 'test_new_habit.py').exists())
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%s', 'main'), 'feat: cut one more sign-off')
        self.assertRegex(out, r'Landed [0-9a-f]{7,} on main: feat: cut one more sign-off')
        self.assertIn('The live folder is at', out)
        self.assertIn('Ran 12 tests', out)
        self.assertIn('Tell George: type exit, then reopen the chat with -c.', out)

    def test_a_failing_test_refuses_and_nothing_is_pushed_or_pulled(self):
        self.clone()
        before = self.origin_tip()
        self.change()
        self.suite_result['work'] = 1
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn('Tests failed in the working copy (exit 1). Nothing was pushed.', err)
        self.assertIn('FAILED (failures=1)', err)
        self.assertEqual(self.origin_tip(), before)
        self.assertEqual(self.tip(self.live), before)
        self.assertEqual(self.suite_calls, ['work'])
        # The change is still in the working copy, committed, ready for a fix and another run.
        self.suite_result['work'] = 0
        code, _, _ = self.update('feat: second try')
        self.assertEqual(code, 0)
        self.assertEqual(self.tip(self.live), self.origin_tip())

    def test_work_that_landed_meanwhile_is_rebased_under_the_change_and_tested_together(self):
        self.clone()
        self.change()
        self.push_from_other()
        code, out, _ = self.update()
        self.assertEqual(code, 0)
        self.assertTrue((self.live / 'other.txt').exists())
        self.assertIn("'Good luck!'", (self.live / 'habit_checks.py').read_text())
        self.assertEqual(git(self.origin, 'log', '--format=%s', 'main').splitlines()[:2], ['feat: cut one more sign-off', 'other work'])

    def test_a_push_that_loses_a_race_is_rebased_tested_again_and_pushed(self):
        self.clone()
        self.change()
        calls = []

        def racing_suite(folder):
            calls.append(Path(folder).name)
            if calls == ['work']:
                self.push_from_other('race.txt')   # another worker lands while the tests run
            return 0, 'Ran 12 tests in 0.5s\n\nOK\n'

        out, err = io.StringIO(), io.StringIO()
        code = self_update.update('feat: raced', self.work, self.live, suite=racing_suite, out=out, err=err)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(calls, ['work', 'work'])
        self.assertTrue((self.live / 'race.txt').exists())
        self.assertEqual(self.tip(self.live), self.origin_tip())

    def test_when_more_lands_between_the_push_and_the_pull_the_suite_runs_in_the_live_folder_too(self):
        self.clone()
        self.change()
        real_git = self_update.git

        def git_with_a_late_push(folder, *arguments, **options):
            done = real_git(folder, *arguments, **options)
            if arguments[:1] == ('push',) and done.returncode == 0:
                self.push_from_other('late.txt')   # another worker lands right after our push
            return done

        self_update.git = git_with_a_late_push
        self.addCleanup(setattr, self_update, 'git', real_git)
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.suite_calls, ['work', 'live'])
        self.assertTrue((self.live / 'late.txt').exists())
        self.assertIn('Landed', out)

    def test_a_conflict_with_main_stops_before_any_push(self):
        self.clone()
        self.change()
        git(self.other, 'pull', '--quiet', 'origin', 'main')
        (self.other / 'habit_checks.py').write_text("CUT_SENTENCES = [\n    'Take care!',\n]\n")
        git(self.other, 'commit', '--quiet', '-am', 'other habit')
        git(self.other, 'push', '--quiet', 'origin', 'main')
        before = self.origin_tip()
        code, out, err = self.update()
        self.assertEqual(code, 3)
        self.assertIn('conflicts with main in: habit_checks.py', err)
        self.assertEqual(self.origin_tip(), before)
        self.assertEqual(self.suite_calls, [])
        self.assertEqual(git(self.work, 'status', '--porcelain'), '')
        self.assertIn("'Good luck!'", (self.work / 'habit_checks.py').read_text())

    def test_nothing_to_land_still_brings_the_live_folder_to_the_tip(self):
        self.clone()
        self.push_from_other()
        code, out, _ = self.update()
        self.assertEqual(code, 0)
        self.assertIn('Nothing to land', out)
        self.assertEqual(self.tip(self.live), self.origin_tip())
        self.assertEqual(self.suite_calls, ['live'])

    def test_a_failing_suite_in_the_live_folder_is_reported_as_its_own_exit_code(self):
        self.clone()
        self.push_from_other()   # nothing of ours to land: the live folder is brought to the tip and tested there
        self.suite_result['live'] = 1
        code, _, err = self.update()
        self.assertEqual(code, 5)
        self.assertIn('the suite fails in the live folder', err)
        self.assertEqual(self.tip(self.live), self.origin_tip())

    def test_row_names_the_correction_in_the_commit_and_writes_the_commit_on_the_row(self):
        import json
        import sqlite3
        import gate_admin
        history = Path(self.tmp.name) / 'history.db'
        db = sqlite3.connect(history)
        db.execute('CREATE TABLE history (id INTEGER PRIMARY KEY, status TEXT, session_id TEXT, raw_input TEXT, '
                   'normalized_input TEXT, cleaned_input TEXT, direct_answer TEXT, gate_json TEXT)')
        db.execute("INSERT INTO history (id, status, gate_json) VALUES (1, 'accepted', NULL)")
        db.execute("INSERT INTO history (id, status, gate_json) VALUES (2, ?, ?)", (gate_admin.CORRECTION, json.dumps({'corrects_row': 1, 'outcomes': []})))
        db.commit()
        db.close()
        self.clone()
        self.change()
        out, err = io.StringIO(), io.StringIO()
        code = self_update.update('fix: cut one more sign-off', self.work, self.live, suite=self.suite, out=out, err=err, row=2, history=history)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%B', 'main').split('\n'),
                         ['fix: cut one more sign-off', '', 'Correction: history row 2'])
        landed = git(self.origin, 'rev-parse', '--short', 'main')
        self.assertIn(f'Written on history row 2: commit {landed}.', out.getvalue())
        db = sqlite3.connect(history)
        outcomes = json.loads(db.execute('SELECT gate_json FROM history WHERE id=2').fetchone()[0])['outcomes']
        untouched = db.execute('SELECT gate_json FROM history WHERE id=1').fetchone()[0]
        db.close()
        self.assertEqual([(o['bin'], o['commit'], o['message']) for o in outcomes], [('code', landed, 'fix: cut one more sign-off')])
        self.assertIsNone(untouched)

    def test_a_row_that_is_not_a_correction_case_lands_the_change_and_says_so(self):
        self.clone()
        self.change()
        out, err = io.StringIO(), io.StringIO()
        code = self_update.update('fix: x', self.work, self.live, suite=self.suite, out=out, err=err, row=7,
                                  history=Path(self.tmp.name) / 'missing.db')
        self.assertEqual(code, 0)
        self.assertIn('History row 7 is not a correction case', out.getvalue())
        self.assertEqual(self.tip(self.live), self.origin_tip())

    def test_the_command_line_takes_dir_and_row_in_any_order(self):
        seen = []
        real = self_update.update
        self_update.update = lambda message, work=None, **options: seen.append((message, work, options.get('row'))) or 0
        self.addCleanup(setattr, self_update, 'update', real)
        self.assertEqual(self_update.main_update(['--row', '12', '--dir', '/x', 'fix: y']), 0)
        self.assertEqual(self_update.main_update(['--dir', '/x', '--row', '12', 'fix: y']), 0)
        self.assertEqual(self_update.main_update(['fix: y']), 0)
        self.assertEqual(seen, [('fix: y', '/x', 12), ('fix: y', '/x', 12), ('fix: y', None, None)])
        for bad in (['--row', 'abc', 'fix: y'], ['--row', '0', 'fix: y'], ['--row', '3'], ['fix: y', 'extra'], []):
            self.assertEqual(self_update.main_update(bad), 2, bad)

    def test_wrong_use(self):
        self.assertEqual(self.update()[0], 2)                      # no working copy yet
        self.clone()
        self.assertEqual(self.update('  ')[0], 2)
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(self_update.update('x', self.live, self.live, suite=self.suite, out=out, err=err), 2)
        self.assertIn('live installation', err.getvalue())
        self.assertEqual(self.suite_calls, [])


class CommandFileTests(unittest.TestCase):
    def test_the_command_files_show_usage(self):
        for name, words in (('self-update', []), ('self-update', ['a', 'b']), ('self-clone', ['a', 'b'])):
            with self.subTest(name=name, words=words):
                done = subprocess.run([sys.executable, str(h.ROOT / 'toolbox' / 'bin' / name), *words],
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 2)
                self.assertIn('usage: ' + name, done.stderr)

    def test_the_suite_list_is_every_test_module_but_the_native_one(self):
        modules = self_update.test_modules(h.ROOT)
        self.assertIn('test_self_update', modules)
        self.assertIn('test_harness', modules)
        self.assertNotIn('test_native_terminal', modules)

    def test_the_self_card_names_the_real_commands_and_files(self):
        card = (h.ROOT / 'toolbox' / 'cards' / 'self.md').read_text(encoding='utf-8')
        for word in ('self-clone', 'self-update', 'habit_checks.py', 'test_habit_checks.py', 'edit-exact', 'CUT_SENTENCES', 'CHECKS'):
            self.assertIn(word, card)
        for name in ('habit_checks.py', 'test_habit_checks.py', 'toolbox/bin/self-clone', 'toolbox/bin/self-update', 'toolbox/bin/edit-exact'):
            self.assertTrue((h.ROOT / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
