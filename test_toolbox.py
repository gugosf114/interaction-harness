"""The toolbox: the index page, the cards, the card printer and the exact-replace edit."""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest

import harness as h

BOX = h.ROOT / 'toolbox'
CARDS = BOX / 'cards'
INDEX = h.ROOT / 'tools_block.txt'
INDEX_LINE = re.compile(r'^- ([a-z0-9-]+): .+ Print: card ([a-z0-9-]+)$')
FAMILIES = ['files', 'documents', 'phone', 'mcp-see', 'mcp-touch', 'mcp-apps', 'phone-settings', 'phone-hardware', 'shizuku',
            'devices', 'screen', 'phone-browser', 'laptop', 'yana-phone', 'tv', 'voice', 'alerts', 'timers',
            'calls', 'models', 'sessions', 'memory', 'mail', 'money', 'bakery', 'cloud', 'github',
            'agent-scripts', 'agent-box', 'programs', 'boot', 'chats', 'lanes']
CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
KEY_SHAPES = [re.compile(pattern) for pattern in (
    r'sk-[A-Za-z0-9_-]{16,}', r'AIza[0-9A-Za-z_-]{20,}', r'gh[pousr]_[A-Za-z0-9]{20,}', r'xox[abprs]-[A-Za-z0-9-]{10,}',
    r'-----BEGIN [A-Z ]*PRIVATE KEY', r'eyJ[A-Za-z0-9_-]{20,}', r'\b[0-9a-fA-F]{32,}\b', r'\b[A-Za-z0-9+_-]{40,}\b',
    r'(?i)\b(?:password|secret|token|api[_-]?key)\s*[=:]\s*[A-Za-z0-9+/_-]{12,}')]


def shipped_text_files():
    files = [INDEX, *sorted(CARDS.glob('*.md')), BOX / 'install.sh', BOX / 'hrun.py']
    for folder in ('bin', 'debian'):
        files.extend(sorted(path for path in (BOX / folder).iterdir() if path.is_file()))
    return files


def run(*command, **options):
    return subprocess.run(list(command), capture_output=True, text=True, timeout=60, **options)


class IndexAndCardTests(unittest.TestCase):
    def index_lines(self):
        return [INDEX_LINE.match(line) for line in INDEX.read_text(encoding='utf-8').splitlines() if line.startswith('- ') and 'Print: card' in line]

    def test_index_is_under_the_tools_page_cap_and_loads(self):
        self.assertLess(len(INDEX.read_text(encoding='utf-8')), h.MAX_TOOLS_CHARS)
        self.assertEqual(h.load_tools(), INDEX.read_text(encoding='utf-8').strip())

    def test_every_index_line_names_a_card_that_exists(self):
        lines = self.index_lines()
        self.assertTrue(lines and all(lines), 'every family line must read "- NAME: purpose. Print: card NAME"')
        for match in lines:
            self.assertEqual(match.group(1), match.group(2))
            self.assertTrue((CARDS / (match.group(2) + '.md')).is_file(), match.group(2))

    def test_index_and_cards_hold_the_same_families(self):
        self.assertEqual([match.group(1) for match in self.index_lines()], FAMILIES)
        self.assertEqual(sorted(path.stem for path in CARDS.glob('*.md')), sorted(FAMILIES))

    def test_every_card_is_under_its_cap_and_starts_with_its_name(self):
        for path in CARDS.glob('*.md'):
            text = path.read_text(encoding='utf-8')
            with self.subTest(card=path.name):
                self.assertLess(len(text), 4000)
                self.assertRegex(text.splitlines()[0], r'^# ' + re.escape(path.stem) + ' — .+')
                self.assertIn('Known failure', text)

    def test_no_control_characters(self):
        for path in shipped_text_files():
            with self.subTest(file=path.name):
                self.assertIsNone(CONTROLS.search(path.read_text(encoding='utf-8')))

    def test_no_key_shaped_strings(self):
        for path in shipped_text_files():
            text = path.read_text(encoding='utf-8')
            for shape in KEY_SHAPES:
                with self.subTest(file=path.name, shape=shape.pattern):
                    self.assertIsNone(shape.search(text))

    def test_key_shape_check_catches_real_shapes(self):
        samples = ['sk-' + 'a1B2' * 6, 'AIza' + 'Sy' * 12, 'ghp_' + 'x9' * 12, '0123456789abcdef' * 2,
                   'A1b2C3d4E5' * 4, 'password = hunter2hunter2', 'eyJ' + 'hbGciOiJIUzI1NiIs' * 2]
        for sample in samples:
            with self.subTest(sample=sample[:8]):
                self.assertTrue(any(shape.search(sample) for shape in KEY_SHAPES))


class CommandTests(unittest.TestCase):
    def test_card_prints_a_card_and_fails_on_an_unknown_name(self):
        good = run('sh', str(BOX / 'bin' / 'card'), 'files')
        self.assertEqual(good.returncode, 0)
        self.assertEqual(good.stdout, (CARDS / 'files.md').read_text(encoding='utf-8'))
        for name in ('nope', '../cards/files', 'Files', ''):
            with self.subTest(name=name):
                bad = run('sh', str(BOX / 'bin' / 'card'), name)
                self.assertNotEqual(bad.returncode, 0)
                self.assertEqual(bad.stdout, '')
                self.assertIn('No card named', bad.stderr)
        self.assertEqual(run('sh', str(BOX / 'bin' / 'card')).returncode, 2)

    def test_cards_lists_every_family_with_its_purpose(self):
        listing = run('sh', str(BOX / 'bin' / 'cards'))
        self.assertEqual(listing.returncode, 0)
        lines = listing.stdout.splitlines()
        self.assertEqual(sorted(line.split()[0] for line in lines), sorted(FAMILIES))
        self.assertTrue(all(len(line.split(None, 1)) == 2 for line in lines))

    def test_bridge_and_wrappers_show_usage_without_arguments(self):
        self.assertEqual(run('sh', str(BOX / 'bin' / 'deb')).returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'text-pdf')).returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'text-pdf'), 'out.txt', 'words').returncode, 2)
        for script in ('paypal-get.sh', 'page-text.sh', 'cloud-check.sh'):
            with self.subTest(script=script):
                self.assertEqual(run('bash', str(BOX / 'debian' / script)).returncode, 2)
        self.assertEqual(run('bash', str(BOX / 'debian' / 'paypal-get.sh'), 'https://elsewhere.example/v2/x').returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'debian' / 'mail-unread.py'), 'nobody').returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'mcp')).returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'mcp'), 'android_tap', '{not json').returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'mcp'), 'android_tap', '[1, 2]').returncode, 2)
        self.assertEqual(run('sh', str(BOX / 'bin' / 'rish')).returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'media-volume'), 'loud').returncode, 2)
        self.assertEqual(run(sys.executable, str(BOX / 'bin' / 'media-volume'), '10', '20').returncode, 2)

    def test_the_three_mcp_cards_name_all_fifty_five_tools_once(self):
        names = []
        for card in ('mcp-see', 'mcp-touch', 'mcp-apps'):
            text = (CARDS / (card + '.md')).read_text(encoding='utf-8')
            names.extend(sorted(set(re.findall(r'mcp (android_[a-z_]+)', text))))
        self.assertEqual(len(set(names)), 55)

    def rish_with_fake_launcher(self, launcher_text, command):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder, 'launcher'); launcher.write_text(launcher_text, encoding='utf-8')
            box = Path(folder, 'box')
            env = {**os.environ, 'RISH_LAUNCHER': str(launcher), 'RISH_BOX': str(box), 'COUNT': str(Path(folder, 'count'))}
            done = subprocess.run(['sh', str(BOX / 'bin' / 'rish'), '-c', command], capture_output=True, text=True, env=env, timeout=60)
            return done, Path(folder, 'count').read_text().strip(), sorted(path.name for path in box.iterdir())

    def test_rish_prints_the_answer_in_order_with_the_real_exit_code_after_a_first_refusal(self):
        # The launcher refuses once, then runs the text it was given and exits 0 whatever happened.
        launcher = ('count=$(cat "$COUNT" 2>/dev/null || echo 0); count=$((count + 1)); echo $count > "$COUNT"\n'
                    '[ "$count" -lt 2 ] && { echo "Server is not running"; exit 1; }\n'
                    'eval "$2"\nexit 0\n')
        done, calls, left = self.rish_with_fake_launcher(launcher, "echo \"it's out\"; echo err >&2; exit 7")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (7, "it's out\nerr\n", ''))
        self.assertEqual((calls, left), ('2', []))

    def test_rish_gives_up_after_three_refusals_and_says_what_the_launcher_said(self):
        launcher = ('count=$(cat "$COUNT" 2>/dev/null || echo 0); echo $((count + 1)) > "$COUNT"\n'
                    'echo "Server is not running"; exit 1\n')
        done, calls, left = self.rish_with_fake_launcher(launcher, 'echo never')
        self.assertEqual((done.returncode, done.stdout, done.stderr), (1, '', 'Server is not running\n'))
        self.assertEqual((calls, left), ('3', []))

    def test_no_key_value_is_stored_for_the_mcp_server(self):
        text = (BOX / 'bin' / 'mcp').read_text(encoding='utf-8')
        self.assertNotIn('Bearer agent', text)
        self.assertIn('agentbridge-call', text)

    def test_every_command_file_is_runnable(self):
        for folder in ('bin', 'debian'):
            for path in (BOX / folder).iterdir():
                with self.subTest(file=path.name):
                    self.assertTrue(path.stat().st_mode & stat.S_IXUSR)
                    self.assertTrue(path.read_text(encoding='utf-8').startswith('#!'))

    def test_install_is_safe_to_run_twice_and_never_replaces_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'bin').mkdir()
            env = {**os.environ, 'PREFIX': tmp}
            for _ in range(2):
                done = run('sh', str(BOX / 'install.sh'), env=env)
                self.assertEqual(done.returncode, 0, done.stderr)
            names = sorted(path.name for path in (BOX / 'bin').iterdir())
            self.assertEqual(sorted(path.name for path in (Path(tmp) / 'bin').iterdir()), names)
            self.assertTrue(all((Path(tmp) / 'bin' / name).is_symlink() for name in names))
            (Path(tmp) / 'bin' / 'deb').unlink()
            (Path(tmp) / 'bin' / 'deb').write_text('someone else\n')
            blocked = run('sh', str(BOX / 'install.sh'), env=env)
            self.assertEqual(blocked.returncode, 1)
            self.assertIn('SKIPPED deb', blocked.stderr)
            self.assertEqual((Path(tmp) / 'bin' / 'deb').read_text(), 'someone else\n')


class EditExactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'a.txt'

    def edit(self, *arguments):
        return run(sys.executable, str(BOX / 'bin' / 'edit-exact'), *arguments)

    def test_replaces_text_that_appears_once(self):
        self.file.write_text('one apple\ntwo plums\n')
        done = self.edit(str(self.file), 'apple', 'pear')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.file.read_text(), 'one pear\ntwo plums\n')
        self.assertIn('Replaced 1 occurrence', done.stdout)
        self.assertIn('at line 1', done.stdout)

    def test_refuses_when_the_text_is_missing(self):
        self.file.write_text('one apple\n')
        done = self.edit(str(self.file), 'grape', 'pear')
        self.assertEqual(done.returncode, 1)
        self.assertIn('was not found', done.stderr)
        self.assertEqual(self.file.read_text(), 'one apple\n')

    def test_refuses_when_the_text_appears_more_than_once(self):
        self.file.write_text('apple apple\napple\n')
        done = self.edit(str(self.file), 'apple', 'pear')
        self.assertEqual(done.returncode, 1)
        self.assertIn('appears 3 times', done.stderr)
        self.assertEqual(self.file.read_text(), 'apple apple\napple\n')

    def test_works_across_lines_and_reports_the_line(self):
        self.file.write_text('a\nb\nc\nd\n')
        done = self.edit(str(self.file), 'b\nc', 'B\nC\nC2')
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.file.read_text(), 'a\nB\nC\nC2\nd\n')
        self.assertIn('at line 2', done.stdout)

    def test_keeps_line_endings_other_text_and_permissions(self):
        self.file.write_bytes('first\r\nsecond — ünïcode\r\nthird'.encode('utf-8'))
        self.file.chmod(0o640)
        self.assertEqual(self.edit(str(self.file), 'second', '2nd').returncode, 0)
        self.assertEqual(self.file.read_bytes(), 'first\r\n2nd — ünïcode\r\nthird'.encode('utf-8'))
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)
        self.assertEqual([path.name for path in Path(self.tmp.name).iterdir()], ['a.txt'])

    def test_can_delete_text_and_treats_special_characters_as_plain_text(self):
        self.file.write_text('price: $5.00 (was $7.00)\n')
        self.assertEqual(self.edit(str(self.file), ' (was $7.00)', '').returncode, 0)
        self.assertEqual(self.file.read_text(), 'price: $5.00\n')
        self.assertEqual(self.edit(str(self.file), '$5.00', r'\1 .* [x]').returncode, 0)
        self.assertEqual(self.file.read_text(), 'price: \\1 .* [x]\n')

    def test_wrong_use_and_unreadable_files_exit_two_and_write_nothing(self):
        self.file.write_text('one apple\n')
        cases = [(), (str(self.file),), (str(self.file), 'apple'), (str(self.file), '', 'x'), (str(self.file), 'apple', 'apple'),
                 (str(Path(self.tmp.name) / 'absent.txt'), 'a', 'b'), (self.tmp.name, 'a', 'b')]
        for arguments in cases:
            with self.subTest(arguments=arguments[1:]):
                self.assertEqual(self.edit(*arguments).returncode, 2)
        binary = Path(self.tmp.name) / 'b.bin'
        binary.write_bytes(b'\xff\xfe\x00apple')
        self.assertEqual(self.edit(str(binary), 'apple', 'pear').returncode, 2)
        self.assertEqual(binary.read_bytes(), b'\xff\xfe\x00apple')
        self.assertEqual(self.file.read_text(), 'one apple\n')


if __name__ == '__main__':
    unittest.main()
