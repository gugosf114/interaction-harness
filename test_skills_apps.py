"""The skill and app commands: argument handling, parsing, and the two cards."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

import harness as h

BIN = h.ROOT / 'toolbox' / 'bin'
CARDS = h.ROOT / 'toolbox' / 'cards'


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip('\n'), encoding='utf-8')


class SkillCommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        mine, plugins, grok = root / 'mine', root / 'plugins', root / 'grok'
        write(mine / 'xlsx' / 'SKILL.md', '''
            ---
            name: xlsx
            description: "Use this skill any time a spreadsheet file is the primary input. More words follow."
            ---
            Use `openpyxl`. Run `python scripts/recalc.py out.xlsx`. Read the picture. Use the Agent tool in parallel.
            ''')
        write(mine / 'xlsx' / 'scripts' / 'recalc.py', 'print(1)\n')
        write(mine / 'xlsx' / 'scripts' / 'office' / '__init__.py', '')
        write(mine / 'xlsx' / 'scripts' / 'office' / 'helper.py', 'x = 1\n')
        write(mine / 'long' / 'SKILL.md', '---\nname: long\ndescription: >\n  A folded\n  description.\n---\n' + 'word ' * 4000)
        write(plugins / 'legal' / '.claude-plugin' / 'plugin.json', '{"name": "legal"}')
        write(plugins / 'legal' / 'skills' / 'brief' / 'SKILL.md', '---\nname: brief\ndescription: Legal brief. Uses ~~CRM.\n---\nBody\n')
        write(plugins / 'legal' / 'commands' / 'triage.md', '---\ndescription: Triage a contract.\n---\nSteps\n')
        write(plugins / 'data' / 'skills' / 'brief' / 'SKILL.md', '---\nname: brief\ndescription: Data brief.\n---\nmcp__claude_ai_Gmail\n')
        write(grok / 'xlsx' / 'SKILL.md', '---\nname: xlsx\ndescription: Grok sheets.\n---\nBody\n')
        self.env = {**os.environ, 'SKILL_ROOTFS': '',
                    'SKILL_ROOTS': f'claude|{mine};claude-plugin|{plugins};grok|{grok}|grok:;claude|{root / "absent"}'}

    def skill(self, *args):
        return subprocess.run([sys.executable, str(BIN / 'skill'), *args], capture_output=True, text=True, timeout=60, env=self.env)

    def test_list_names_every_skill_with_its_purpose(self):
        done = self.skill('list')
        self.assertEqual(done.returncode, 0, done.stderr)
        names = [line.split()[0] for line in done.stdout.splitlines()[1:]]
        self.assertEqual(sorted(names), sorted(['xlsx', 'long', 'legal:brief', 'legal:triage', 'data:brief', 'grok:xlsx']))
        self.assertIn('Use this skill any time a spreadsheet file is the primary input.', done.stdout)
        self.assertNotIn('More words follow', done.stdout)
        self.assertIn('A folded description.', done.stdout)
        self.assertTrue(done.stdout.startswith('6 skills.'))

    def test_list_by_group_and_unknown_group(self):
        self.assertEqual([l.split()[0] for l in self.skill('list', 'grok').stdout.splitlines()[1:]], ['grok:xlsx'])
        bad = self.skill('list', 'nope')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('No group named nope', bad.stderr)

    def test_show_puts_lane_notes_first_then_the_text(self):
        done = self.skill('show', 'xlsx')
        self.assertEqual(done.returncode, 0, done.stderr)
        notes, _, body = done.stdout.partition('THE SKILL')
        self.assertIn('LANE NOTES', notes)
        self.assertIn('/scripts/x.py', notes)
        self.assertIn('put deb in front', notes)
        self.assertIn('look PATH', notes)
        self.assertIn('Subagents: the lanes have none', notes)
        self.assertIn('openpyxl', notes)
        self.assertIn('Use `openpyxl`.', body)

    def test_show_names_missing_connectors(self):
        self.assertIn('~~CRM', self.skill('show', 'legal:brief').stdout)
        self.assertIn('card mail', self.skill('show', 'data:brief').stdout)

    def test_show_splits_a_long_skill_into_parts(self):
        first = self.skill('show', 'long')
        self.assertTrue(first.stdout.startswith('[part 1 of 3; next: skill show long 2]'))
        self.assertIn('[continues: skill show long 2]', first.stdout)
        last = self.skill('show', 'long', '3')
        self.assertEqual(last.returncode, 0)
        self.assertNotIn('continues', last.stdout)
        self.assertEqual(self.skill('show', 'long', '4').returncode, 1)
        self.assertEqual(self.skill('show', 'long', 'two').returncode, 2)

    def test_show_all_keeps_whole_long_skill_in_one_result(self):
        result=self.skill('show','long','--all')
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout.count('word '),4000)
        self.assertNotIn('[part ',result.stdout)

    def test_short_names_resolve_only_when_unique(self):
        self.assertIn('SKILL legal:triage', self.skill('show', 'triage').stdout)
        both = self.skill('show', 'brief')
        self.assertEqual(both.returncode, 1)
        self.assertIn('legal:brief', both.stderr)
        self.assertIn('data:brief', both.stderr)
        self.assertEqual(self.skill('show', 'nothing').returncode, 1)

    def test_the_first_root_wins_a_name(self):
        self.assertIn('Use this skill any time', self.skill('show', 'xlsx').stdout)
        self.assertIn('Grok sheets', self.skill('show', 'grok:xlsx').stdout)

    def test_files_lists_scripts_with_full_paths_and_folds_libraries(self):
        done = self.skill('files', 'xlsx')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('run  scripts/recalc.py', done.stdout)
        self.assertIn('lib  scripts/office/', done.stdout)
        self.assertIn('deb python3 ', done.stdout)
        self.assertIn('only SKILL.md', self.skill('files', 'grok:xlsx').stdout)
        self.assertIn('single command file', self.skill('files', 'legal:triage').stdout)

    def test_find_ranks_the_matching_skill_first(self):
        done = self.skill('find', 'spreadsheets')
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.split()[0], 'xlsx')
        self.assertEqual(self.skill('find', 'excel').stdout.split()[0], 'xlsx')
        self.assertEqual(self.skill('find', 'zzzqqq').returncode, 1)

    def test_wrong_use_exits_two(self):
        for args in ((), ('nope',), ('show',), ('files',), ('find',), ('list', 'a', 'b'), ('groups', 'x')):
            with self.subTest(args=args):
                self.assertEqual(self.skill(*args).returncode, 2)

    def test_groups_names_each_folder(self):
        done = self.skill('groups')
        self.assertEqual(done.returncode, 0)
        self.assertIn('6 skills in all.', done.stdout)
        self.assertIn('(missing)', done.stdout)

    def test_frontmatter_reader(self):
        skill = load('skill')
        self.assertEqual(skill.frontmatter('---\nname: a\ndescription: "say \\"hi\\""\n---\n'), {'name': 'a', 'description': 'say "hi"'})
        self.assertEqual(skill.frontmatter('---\ndescription: |\n  one\n  two\nname: b\n---\n')['description'], 'one two')
        self.assertEqual(skill.frontmatter('no front matter'), {})


class AppArgumentTests(unittest.TestCase):
    """Wrong arguments exit 2 before the phone is touched: the adb path below does not exist."""

    def app(self, *args):
        env = {**os.environ, 'APP_ADB_TARGET': 'nowhere:1', 'APP_RISH': '/nonexistent/rish'}
        return subprocess.run([sys.executable, str(BIN / 'app'), *args], capture_output=True, text=True, timeout=60, env=env)

    def test_wrong_use_exits_two(self):
        cases = [(), ('nope',), ('info',), ('info', 'a', 'b'), ('info', 'not a package'), ('info', 'nodots'),
                 ('perms', '../x'), ('grant', 'com.a.b'), ('grant', 'com.a.b', 'BAD PERM'), ('revoke', 'com.a.b', 'x;y'),
                 ('install',), ('install', 'a', 'b'), ('update',), ('uninstall', 'x'), ('disable', 'com.a.b', 'c'),
                 ('enable', '-x'), ('stop',), ('clear', 'rm -rf'), ('open', 'com.a.b', '--display'),
                 ('open', 'com.a.b', '--screen', '3'), ('default',), ('default', 'not a kind!'), ('default', 'browser', 'x'),
                 ('default', 'browser', 'com.a.b', 'off'), ('default', 'example.com', 'com.a.b', 'maybe'), ('front', 'x'),
                 ('list', '--via'), ('front', '--via', 'usb')]
        for args in cases:
            with self.subTest(args=args):
                done = self.app(*args)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertEqual(done.stdout, '')

    def test_install_of_a_missing_file_exits_two(self):
        self.assertEqual(self.app('install', '/nonexistent/x.apk').returncode, 2)


class AppParsingTests(unittest.TestCase):
    def setUp(self):
        self.app = load('app')

    def test_dump_blocks_and_fields(self):
        text = ('Packages:\n  Package [com.a.one] (1):\n    versionCode=7 minSdk=24 targetSdk=36\n    versionName=1.2\n'
                '    installerPackageName=null\n  Package [com.b.two] (2):\n    versionCode=9\n    versionName=3.0-beta\n'
                '\nHidden system packages:\n  Package [com.a.one] (3):\n    versionName=0.1\n')
        blocks = self.app.dump_blocks(text)
        self.assertEqual(sorted(blocks), ['com.a.one', 'com.b.two'])
        self.assertEqual(self.app.field(blocks['com.a.one'], 'versionName'), '1.2')
        self.assertEqual(self.app.field(blocks['com.a.one'], 'versionCode'), '7')
        self.assertEqual(self.app.field(blocks['com.b.two'], 'versionName'), '3.0-beta')

    def test_permissions_are_read_from_each_section(self):
        out = textwrap.dedent('''
            Packages:
              Package [com.a.one] (1):
                requested permissions:
                  android.permission.CAMERA
                  android.permission.INTERNET
                  android.permission.READ_SMS: restricted=true
                install permissions:
                  android.permission.INTERNET: granted=true
                User 0: installed=true
                  firstInstallTime=2026-11-11 10:00:00
                  runtime permissions:
                    android.permission.CAMERA: granted=false, flags=[ USER_SENSITIVE_WHEN_GRANTED]
                    android.permission.READ_SMS: granted=true, flags=[ USER_SET]
            ''')
        requested, states = self.app.parse_permissions(out)
        self.assertEqual(requested, ['android.permission.CAMERA', 'android.permission.INTERNET', 'android.permission.READ_SMS'])
        self.assertEqual(states, {'android.permission.INTERNET': ('install', True), 'android.permission.CAMERA': ('runtime', False),
                                  'android.permission.READ_SMS': ('runtime', True)})

    def test_short_permission_names_get_the_android_prefix(self):
        self.assertEqual(self.app.full_permission('CAMERA'), 'android.permission.CAMERA')
        self.assertEqual(self.app.full_permission('com.x.PERM'), 'com.x.PERM')

    def test_package_names(self):
        for good in ('com.termux.api', 'de.markusfisch.android.binaryeye', 'a.b'):
            self.assertEqual(self.app.need_package(good), good)
        for bad in ('termux', 'com..x', 'com.x;rm', '-com.x', 'com x.y'):
            with self.subTest(bad=bad), self.assertRaises(self.app.Fail):
                self.app.need_package(bad)


class CardTests(unittest.TestCase):
    def test_cards_name_every_verb(self):
        skills = (CARDS / 'skills.md').read_text(encoding='utf-8')
        for verb in ('skill find', 'skill show', 'skill files', 'skill list'):
            self.assertIn(verb, skills)
        apps = (CARDS / 'apps.md').read_text(encoding='utf-8')
        for verb in ('app list', 'app info', 'app install', 'app update', 'app uninstall', 'app disable', 'app enable',
                     'app stop', 'app clear', 'app open', 'app perms', 'app grant', 'app revoke', 'app default', 'app front',
                     '--via adb', '--via shizuku'):
            self.assertIn(verb, apps)

    def test_index_tells_the_model_to_print_and_follow_a_matching_skill(self):
        index = (h.ROOT / 'tools_block.txt').read_text(encoding='utf-8')
        line = next(l for l in index.splitlines() if l.startswith('- skills: '))
        self.assertIn('skill show NAME and follow it', line)
        self.assertTrue(any(l.startswith('- apps: ') for l in index.splitlines()))


if __name__ == '__main__':
    unittest.main()

class AddedCoverageTests(unittest.TestCase):
    def test_current_google_maps_and_exact_unknown_tool(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            skill = load('skill')
            notes = skill.lane_notes({'text':'Google Drive Google Calendar mcp__unknown__read', 'allowed':'',
                'real_folder':Path(folder), 'kind':'skill','plugin_dir':None,'folder':folder,'name':'sample','group':'claude'})
            result=' '.join(notes)
            self.assertIn('card drive',result)
            self.assertIn('card calendar',result)
            self.assertIn('mcp__unknown__read',result)
            self.assertNotIn('no Drive connector',result)

    def test_domain_with_path_only_link_is_included(self):
        import contextlib,io
        app=load('app')
        class Phone:
            via='adb'
            def sh(self,command,check=True,**kwargs):
                if command.startswith('pm list packages'):return 'package:de.test.app\n'
                if command.startswith('cmd package query'):return ''
                if command.startswith('pm set-app'):return ''
                if command.startswith('pm get-app-links'):return ('  de.test.app:\n    Domain verification state:\n      example.com: verified\n'
                    '    User 0:\n      Selection state:\n        Enabled:\n          example.com\n')
                raise AssertionError(command)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.cmd_default(Phone(),['example.com','de.test.app']),0)
        self.assertIn('de.test.app',out.getvalue())
