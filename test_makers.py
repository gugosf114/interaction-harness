"""The maker commands: pictures, video, office files, deep research, web hands, laptop hands, publish. Offline."""
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
BOX = ROOT / 'toolbox'
DEBIAN = BOX / 'debian'
sys.path.insert(0, str(DEBIAN))

import makers_common as common  # noqa: E402


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


image = load('make_image', DEBIAN / 'make-image.py')
video = load('make_video', DEBIAN / 'make-video.py')
office = load('office', DEBIAN / 'office.py')
laptop = load('laptop_input', DEBIAN / 'laptop-input.py')
publish = load('publish', DEBIAN / 'publish.py')
research = load('deep_research', BOX / 'bin' / 'deep-research')

COMMANDS = {'pictures': ['make-image', 'make-video'],
            'office': ['make-docx', 'make-xlsx', 'make-pptx', 'make-pdf', 'read-doc'],
            'research': ['deep-research'],
            'web-hands': ['page-open', 'page-click', 'page-type', 'page-wait', 'page-eval', 'page-shot', 'page-close'],
            'laptop-hands': ['laptop-click', 'laptop-move', 'laptop-type', 'laptop-key'],
            'publish': ['publish']}
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def libraries_present():
    common.add_libraries()
    try:
        import docx, openpyxl, pptx, pypdf, markdown_it  # noqa: F401
        return True
    except ImportError:
        return False


class CardsAndWrappers(unittest.TestCase):
    def test_native_runner_honors_long_command_timeout(self):
        import native_tools
        with mock.patch.object(native_tools, 'run_bounded', return_value={'exit_code': 0}) as run:
            native_tools.handle({'op': 'exec', 'command': 'true', 'auto_confirm': True, 'timeout': 86400})
            self.assertEqual(run.call_args.kwargs['timeout'], 86400)
            native_tools.handle({'op': 'exec', 'command': 'true', 'auto_confirm': True, 'timeout': 37})
            self.assertEqual(run.call_args.kwargs['timeout'], 37)

    def test_every_command_is_on_its_card_and_has_a_wrapper(self):
        for card, commands in COMMANDS.items():
            text = (BOX / 'cards' / (card + '.md')).read_text(encoding='utf-8')
            for name in commands:
                with self.subTest(command=name):
                    self.assertIn(name, text)
                    path = BOX / 'bin' / name
                    self.assertTrue(path.is_file() and os.access(path, os.X_OK))

    def test_wrappers_point_at_files_that_exist(self):
        for card, commands in COMMANDS.items():
            for name in commands:
                text = (BOX / 'bin' / name).read_text(encoding='utf-8')
                for target in re.findall(r'\$here/\.\./debian/([A-Za-z0-9_.-]+)', text):
                    self.assertTrue((DEBIAN / target).is_file(), target)

    def test_installer_pins_match_the_shared_list(self):
        done = subprocess.run(['bash', str(DEBIAN / 'makers-install.sh'), '--pins'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        pins = dict(line.split('==') for line in done.stdout.split())
        self.assertEqual(pins, common.PINS)

    def test_help_names_every_command(self):
        text = (ROOT / 'help.txt').read_text(encoding='utf-8')
        for commands in COMMANDS.values():
            for name in commands:
                self.assertIn(name, text)


class Pictures(unittest.TestCase):
    def test_default_uses_documented_four_k_ceiling(self):
        args = image.parse(['blue teapot', '/tmp/teapot.png'])
        self.assertEqual((args.size, args.quality), ('3840x2160', 'max'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_image(self, *argv, engines=None):
        err = io.StringIO()
        with mock.patch('sys.stderr', err), mock.patch('sys.stdout', io.StringIO()) as out:
            code = image.main(list(argv), engines=engines)
        return code, out.getvalue(), err.getvalue()

    def test_wrong_use_exits_two(self):
        out = os.path.join(self.tmp.name, 'a.png')
        for argv in ([], ['words'], ['', out], ['p', out, '--size', 'big'], ['p', out, '--model', 'x'],
                     ['p', os.path.join(self.tmp.name, 'a.gif')], ['p', '/no/such/folder/a.png'],
                     ['p', out, '--engine', 'paint'], ['p', out, '--from', os.path.join(self.tmp.name, 'none.png')]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_image(*argv)[0], 2)

    def test_falls_back_to_the_next_engine_and_writes_the_file(self):
        calls = []

        def broken(*args):
            calls.append('openai')
            raise common.MakerError('HTTP 500: down')

        def working(*args):
            calls.append('gemini')
            return PNG

        out = os.path.join(self.tmp.name, 'a.png')
        with mock.patch.object(image, 'fit_format', lambda data, form: (data, 4, 4)):
            code, said, err = self.run_image('teapot', out, engines={'openai': broken, 'gemini': working})
        self.assertEqual((code, calls), (0, ['openai', 'gemini']))
        self.assertIn('openai (gpt-image-2.6-sunburst): HTTP 500: down', err)
        self.assertIn('gemini gemini-3-pro-image', said)
        self.assertEqual(Path(out).read_bytes(), PNG)

    def test_every_engine_failing_exits_one_and_writes_nothing(self):
        def broken(*args):
            raise common.MakerError('no')
        out = os.path.join(self.tmp.name, 'a.png')
        self.assertEqual(self.run_image('t', out, engines={'openai': broken, 'gemini': broken})[0], 1)
        self.assertFalse(os.path.exists(out))

    def test_gemini_shape_picks_the_nearest_ratio_and_size_class(self):
        self.assertEqual(image.gemini_shape('1024x1024'), ('1:1', '1K'))
        self.assertEqual(image.gemini_shape('1920x1080'), ('16:9', '2K'))
        self.assertEqual(image.gemini_shape('1080x3840'), ('9:16', '4K'))

    def test_openai_request_shape(self):
        seen = {}

        def http(url, **kw):
            seen['url'], seen['body'] = url, kw.get('body')
            return 200, json.dumps({'data': [{'b64_json': 'iVBORw0KGgo='}]}).encode()

        image.openai_image('p', [], '1024x1024', 'max', 'png', 'gpt-image-2.6-sunburst', http=http, key='k')
        self.assertTrue(seen['url'].endswith('/v1/images/generations'))
        self.assertEqual(seen['body'], {'model': 'gpt-image-2.6-sunburst', 'prompt': 'p', 'quality': 'max',
                                        'output_format': 'png', 'size': '1024x1024', 'complexity': 'high'})

    def test_video_wrong_use_and_openai_error_text(self):
        out = os.path.join(self.tmp.name, 'a.mp4')
        for argv in ([], ['p', out, '--seconds', '2'], ['p', out, '--seconds', '16'], ['p', 'a.mov'],
                     ['p', out] + ['--from', 'x.png'] * 7, ['p', out, '--resolution', '8k']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(video.main(argv), 2)
        args = video.parse(['p', out])
        with self.assertRaises(common.MakerError) as said:
            video.openai_video(args, [], 'sora-2-pro', http=lambda *a, **k: (404, b''), key='k')
        self.assertIn('HTTP 404, empty body', str(said.exception))


@unittest.skipUnless(libraries_present(), 'pinned libraries not installed (makers-install.sh)')
class Office(unittest.TestCase):
    def test_single_column_csv_and_empty_sheets(self):
        self.assertEqual(office.sheets_from_text('loaf\nwhite\nrye\n','Bread'), [('Bread', [['loaf'], ['white'], ['rye']])])
        with self.assertRaises(common.MakerError):
            office.make_xlsx([], None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make(self, *argv, text=''):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch('sys.stdout', out), mock.patch('sys.stderr', err):
            code = office.main(list(argv), stdin=io.StringIO(text))
        return code, out.getvalue(), err.getvalue()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_docx_round_trip(self):
        md = '# Bread\n\n- crust\n- **crumb**\n  - holes\n1. flour\n\n| a | b |\n|---|---|\n| 1 | 2 |\n'
        code, said, _ = self.make('docx', self.path('b.docx'), text=md)
        self.assertEqual(code, 0)
        self.assertRegex(said, r'b\.docx  \d+ bytes')
        text = self.make('read', self.path('b.docx'))[1]
        for piece in ('# Bread', '- crust', '- crumb', '- holes', '- flour', 'a\tb', '1\t2'):
            self.assertIn(piece, text)

    def test_xlsx_several_sheets_from_csv_and_json(self):
        Path(self.path('prices.csv')).write_text('item,usd\nloaf,6\nroll,1.25\n')
        Path(self.path('more.json')).write_text('{"Stock":[{"item":"loaf","n":3}],"Notes":[["x"]]}')
        self.assertEqual(self.make('xlsx', self.path('b.xlsx'), self.path('prices.csv'), self.path('more.json'))[0], 0)
        import openpyxl
        book = openpyxl.load_workbook(self.path('b.xlsx'))
        self.assertEqual(book.sheetnames, ['prices', 'Stock', 'Notes'])
        self.assertEqual(book['prices']['B3'].value, 1.25)
        self.assertEqual([c.value for c in book['Stock'][1]], ['item', 'n'])
        text = self.make('read', self.path('b.xlsx'))[1]
        self.assertIn('== sheet: Stock', text)

    def test_xlsx_from_stdin_with_a_sheet_name(self):
        self.assertEqual(self.make('xlsx', self.path('c.xlsx'), '--sheet', 'Prices', text='a,b\n1,2\n')[0], 0)
        self.assertIn('== sheet: Prices', self.make('read', self.path('c.xlsx'))[1])

    def test_pptx_outline_to_slides(self):
        outline = '# Talk\nBy George\n# Why bread\n- good\n  - warm\n- cheap\n> slowly\n'
        self.assertEqual(self.make('pptx', self.path('t.pptx'), text=outline)[0], 0)
        text = self.make('read', self.path('t.pptx'))[1]
        self.assertEqual(text.count('== slide'), 2)
        self.assertIn('  warm', text)
        self.assertIn('notes: slowly', text)

    @unittest.skipUnless(shutil.which('weasyprint'), 'weasyprint not installed')
    def test_pdf_from_markdown(self):
        self.assertEqual(self.make('pdf', self.path('r.pdf'), text='# Title\n\n- one\n\n| a |\n|---|\n| 9 |\n')[0], 0)
        text = self.make('read', self.path('r.pdf'))[1]
        self.assertIn('Title', text)
        self.assertIn('9', text)

    def test_wrong_use_exits_two_and_bad_files_exit_one(self):
        cases = [('docx',), ('docx', self.path('a.txt')), ('docx', '/no/such/folder/a.docx'), ('pptx', self.path('a.pptx'), 'x', 'y'),
                 ('read',), ('xlsx', self.path('a.xlsx'), '--sheet')]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(self.make(*argv, text='words')[0], 2)
        self.assertEqual(self.make('docx', self.path('e.docx'), text='   ')[0], 2)
        Path(self.path('plain.txt')).write_text('hello')
        self.assertEqual(self.make('read', self.path('plain.txt'))[0], 1)

    def test_cell_values_keep_numbers(self):
        self.assertEqual([office.cell_value(v) for v in ('12', '-3.5', '007', '1e5', 'x')], [12, -3.5, '007', '1e5', 'x'])


class DeepResearch(unittest.TestCase):
    def test_wrong_use_exits_two(self):
        for argv in ([], [''], ['q', '--web-max', '1'], ['q', '--max-turns', '0'], ['q', '--out', '/no/such/dir/r.pdf'],
                     ['q', '--engine', 'other'], ['q', '--retries', '99']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as done:
                    research.parse(argv)
                self.assertEqual(done.exception.code, 2)

    def test_command_runs_this_harness_in_a_long_loop(self):
        args = research.parse(['q', '--out', '/tmp/r.md', '--engine', 'anthropic'])
        command = research.harness_command(args, 'PROMPT')
        self.assertEqual(command[0], str(ROOT / 'harness'))
        for flag in ('--loop', '-y', '--web-max', '--max-turns', '--effort'):
            self.assertIn(flag, command)
        self.assertEqual(command[-3:], ['--engine', 'anthropic', 'PROMPT'])

    def test_only_recorded_links_stay(self):
        sources = [{'url': 'https://a.example/x', 'title': 'A'}, {'url':'https://unused.example/', 'title':'Unused'}]
        text, dropped = research.keep_recorded_links('Fact (https://a.example/x). Other (https://made.up/y).', sources)
        self.assertEqual(dropped, ['https://made.up/y'])
        self.assertNotIn('made.up', text)
        self.assertIn('https://a.example/x', text)
        report = research.report(text, sources)
        self.assertIn('## Sources', report)
        self.assertIn('1. [A](<https://a.example/x>)', report)
        self.assertIn('([1](<https://a.example/x>))', report)
        self.assertEqual(research.urls(report), {'https://a.example/x'})
        self.assertNotIn('unused.example', report)

    def test_failed_run_never_publishes_an_earlier_accepted_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'report.md'
            caller = Path(tmp)/'caller'; caller.mkdir()
            (caller/'mods.json').write_text('{"memory-version":false,"voice":false}')
            def failed(argv, **kw):
                state = Path(kw['env']['HARNESS_STATE_DIR'])
                self.assertFalse(json.loads((state/'mods.json').read_text())['memory-version'])
                with sqlite3.connect(state/'history.db') as db:
                    db.execute('CREATE TABLE history (id INTEGER PRIMARY KEY,engine TEXT,model TEXT,status TEXT,error TEXT,direct_answer TEXT,sources_json TEXT,lookup_counts_json TEXT)')
                    db.execute('INSERT INTO history VALUES (1,?,?,?,?,?,?,?)', ('openai','m','accepted',None,'Draft (https://a.example/x)',json.dumps([{'url':'https://a.example/x','title':'A'}]),'{"total":2}'))
                    db.execute('INSERT INTO history VALUES (2,?,?,?,?,?,?,?)', ('openai','m','error','API unavailable',None,'[]','{}'))
                return subprocess.CompletedProcess(argv,2)
            with mock.patch.object(research,'HOME',tmp), mock.patch.dict(os.environ,{'HARNESS_STATE_DIR':str(caller)}), mock.patch.object(research.subprocess,'run',side_effect=failed), mock.patch('sys.stderr',io.StringIO()):
                self.assertEqual(research.main(['question','--out',str(out),'--retries','0']),2)
            self.assertFalse(out.exists())

    def test_retry_keeps_the_task_when_first_web_turn_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            out = Path(tmp)/'report.md'
            def run(argv, **kw):
                calls.append(argv[-1])
                with sqlite3.connect(Path(kw['env']['HARNESS_STATE_DIR'])/'history.db') as db:
                    db.execute('CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY,engine TEXT,model TEXT,status TEXT,error TEXT,direct_answer TEXT,sources_json TEXT,lookup_counts_json TEXT)')
                    if len(calls) == 1:
                        db.execute('INSERT INTO history VALUES (1,?,?,?,?,?,?,?)',('anthropic','m','error','Claude web lookup failed: url_not_in_prior_context',None,'[]','{}'))
                    else:
                        db.execute('INSERT INTO history VALUES (2,?,?,?,?,?,?,?)',('anthropic','m','accepted',None,'# Answer\n\nFact (https://a.example/x)',json.dumps([{'url':'https://a.example/x','title':'A'}]),'{"total":2}'))
                return subprocess.CompletedProcess(argv,2 if len(calls)==1 else 0)
            with mock.patch.object(research,'HOME',tmp), mock.patch.object(research.subprocess,'run',side_effect=run), mock.patch('sys.stdout',io.StringIO()):
                self.assertEqual(research.main(['What date was Daly City incorporated?','--out',str(out)]),0)
            self.assertEqual(len(calls),2)
            self.assertIn('What date was Daly City incorporated?',calls[1])
            self.assertIn('url_not_in_prior_context',calls[1])
            self.assertTrue(out.exists())

    def test_reads_the_runs_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'history.db')
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE history (id INTEGER PRIMARY KEY, engine TEXT, model TEXT, status TEXT, error TEXT, '
                            'direct_answer TEXT, sources_json TEXT, lookup_counts_json TEXT)')
                con.execute("INSERT INTO history VALUES (1,'anthropic','m','error','Claude web lookup failed: url_not_accessible',NULL,"
                            "'[{\"url\":\"https://a.example/x\",\"title\":\"A\"}]','{\"total\":4}')")
                con.commit()
                self.assertIn('url_not_accessible', research.last_lookup_error(db))
                con.execute("INSERT INTO history VALUES (2,'anthropic','m','accepted',NULL,'# Report','[]','{\"total\":3}')")
                con.commit()
            answer, sources, lookups, turns, model = research.read_run(db)
            self.assertEqual((answer, lookups, turns, model), ('# Report', 7, 2, 'anthropic m'))
            self.assertEqual(sources, [{'url': 'https://a.example/x', 'title': 'A'}])
            self.assertIsNone(research.last_lookup_error(db))


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class WebHands(unittest.TestCase):
    def test_wrappers_pass_private_tab_state_across_proot(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)/'proot-distro'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'); fake.chmod(0o755)
            env = {**os.environ,'PATH':tmp+os.pathsep+os.environ['PATH'],'HARNESS_STATE_DIR':'/tmp/private-run','PAGE_TAB_FILE':'/tmp/private-tab','CDP_PORT':'9335'}
            for name in COMMANDS['web-hands']:
                done = subprocess.run(['sh',str(BOX/'bin'/name),'probe'],env=env,capture_output=True,text=True)
                self.assertEqual(done.returncode,0,done.stderr)
                for value in ('HARNESS_STATE_DIR=/tmp/private-run','PAGE_TAB_FILE=/tmp/private-tab','CDP_PORT=9335'):
                    self.assertIn(value,done.stdout.splitlines(),name)

    def page(self, *argv):
        env = {**os.environ, 'CDP_PORT': '1', 'PAGE_TAB_FILE': '/nonexistent/tab'}
        return subprocess.run(['node', str(DEBIAN / 'page.cjs'), *argv], capture_output=True, text=True, timeout=30, env=env)

    def test_wrong_use_exits_two_before_any_browser_call(self):
        for argv in ([], ['fly'], ['open'], ['open', 'example.com'], ['open', 'https://a.example', 'soon'], ['click'],
                     ['type', 'only-one'], ['shot', 'a.jpg'], ['wait'], ['wait', 'x', '-5'], ['eval', ' '], ['close', 'x']):
            with self.subTest(argv=argv):
                done = self.page(*argv)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn('usage:', done.stderr)

    def test_no_open_page_is_said_plainly(self):
        done = self.page('click', 'Submit')
        self.assertEqual(done.returncode, 1)
        self.assertIn('No page is open. Run page-open URL first.', done.stderr)


class LaptopHands(unittest.TestCase):
    def test_bodies(self):
        code, said = laptop.body('click', ['10', '20', '--double'])
        self.assertIn('[HarnessInput]::Move(10,20)', code)
        self.assertIn("Click('left',2)", code)
        self.assertEqual(said, 'left click x2 at 10 20')
        self.assertIn("Click('right',1)", laptop.body('click', ['1', '2', '--right'])[0])
        self.assertNotIn('Click', laptop.body('move', ['1', '2'])[0])
        code, _ = laptop.body('type', ['Größe 漢'])
        self.assertIn('R3LDtsOfZSDmvKI=', code)  # the words travel as base64, so no quoting can break them
        self.assertIn('[uint16[]]@(17,83)', laptop.body('key', ['ctrl+s'])[0])
        self.assertIn('@($true,$false)', laptop.body('key', ['win+r'])[0])

    def test_wrong_use(self):
        for verb, args in (('click', ['1']), ('click', ['1', 'b']), ('click', ['1', '2', '--left']), ('move', ['1', '2', '--right']),
                           ('type', ['']), ('type', []), ('key', ['ctrl+zz']), ('key', ['ctrl+']), ('key', [])):
            with self.subTest(verb=verb, args=args), self.assertRaises(laptop.InputError):
                laptop.body(verb, args)
        with mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(laptop.main(['jump']), 2)

    def test_runs_as_a_desktop_task_copied_by_scp(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, 'OK cursor at 5 6 | front window: Notepad (0,0 to 9,9)', '')

        with mock.patch('sys.stdout', io.StringIO()) as out:
            self.assertEqual(laptop.main(['move', '5', '6'], run=run), 0)
        self.assertEqual(out.getvalue().strip(), 'cursor at 5 6 | front window: Notepad (0,0 to 9,9)')
        self.assertEqual(calls[0][0], 'scp')
        self.assertTrue(calls[0][-1].startswith('wimlaptop:C:/Users/georg/AppData/Local/Temp/harness-input-'))
        self.assertEqual(calls[1][:6], laptop.SSH)
        self.assertIn('-File', calls[1][-1])
        _, script = laptop.command('1')
        self.assertIn('SendInput', laptop.HELPER)
        for piece in ('-LogonType Interactive', 'Register-ScheduledTask', 'Unregister-ScheduledTask'):
            self.assertIn(piece, script)

    def test_a_desktop_error_exits_one_with_its_words(self):
        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, 'ERR no answer from the desktop in 120 s', '')
        with mock.patch('sys.stderr', io.StringIO()) as err:
            self.assertEqual(laptop.main(['key', 'enter'], run=run), 1)
        self.assertIn('laptop: no answer from the desktop', err.getvalue())


class Publish(unittest.TestCase):
    def test_names(self):
        self.assertEqual(publish.slug('My Report 2026.final'), 'my-report-2026-final')
        with self.assertRaises(publish.PublishError):
            publish.slug('***')

    def test_wrong_use(self):
        for argv in ([], ['--list', 'x'], ['--remove'], ['a', 'b', 'c'], ['--size', 'x'], ['/no/such/file.md']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(publish.main(argv), 2)
        with tempfile.NamedTemporaryFile(suffix='.txt') as handle, mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(publish.main([handle.name]), 2)

    def test_gh_404_is_none_and_other_errors_raise(self):
        not_found = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, '', 'gh: Not Found (HTTP 404)')
        self.assertIsNone(publish.gh('repos/x', run=not_found))
        refused = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, '', 'gh: Bad credentials (HTTP 401)')
        with self.assertRaises(publish.PublishError):
            publish.gh('repos/x', run=refused)

    def test_wait_for_live_and_gone(self):
        class Answer(io.BytesIO):
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        live = lambda request, timeout: Answer(b'<html>STAMP</html>')
        self.assertEqual(publish.wait_for('https://x/', b'STAMP', sleep=lambda s: None, opener=live, tries=2), 200)
        self.assertIsNone(publish.wait_for('https://x/', b'OTHER', sleep=lambda s: None, opener=live, tries=2))

    @unittest.skipUnless(libraries_present(), 'pinned libraries not installed')
    def test_markdown_becomes_a_page_with_its_title(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as handle:
            handle.write('# Bread prices\n\n| a |\n|---|\n| 1 |\n')
        self.addCleanup(os.unlink, handle.name)
        html = publish.page_html(handle.name)
        self.assertIn('<title>Bread prices</title>', html)
        self.assertIn('<table>', html)
        self.assertIn('max-width:46rem', html)


if __name__ == '__main__':
    unittest.main()
