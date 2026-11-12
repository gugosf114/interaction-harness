"""note add / show / list: George's memory format, one pointer line, never an overwrite."""
from datetime import datetime
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import note_tool as nt


class NoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / 'MEMORY.md').write_text('# Memory index\n\n## This box\n- [Say tool](say-tool.md) — speaks\n')
        (self.dir / 'say-tool.md').write_text('---\nname: say-tool\ndescription: "speaks text"\nmetadata:\n  type: reference\n---\n\nbody\n')
        started = patch.dict(os.environ, {'NOTE_DIR': str(self.dir)})
        started.start()
        self.addCleanup(started.stop)

    def run_main(self, *argv):
        out = io.StringIO()
        with patch('sys.stderr', io.StringIO()) as err:
            code = nt.main(list(argv), out=out)
        return code, out.getvalue(), err.getvalue()

    def test_add_writes_the_note_and_one_pointer(self):
        path, line = nt.add('oven-temps', 'Macarons bake at 300 F, rack two.\nFourteen minutes.', today=datetime(2026, 11, 11, 21, 5))
        text = path.read_text()
        self.assertTrue(text.startswith('---\nname: oven-temps\ndescription: "11/11: Macarons bake at 300 F, rack two. Fourteen minutes."\n'
                                        'metadata:\n  type: reference\n'))
        self.assertIn('\n---\n\nMacarons bake at 300 F, rack two.\nFourteen minutes.\n', text)
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        self.assertEqual(line, '- [Oven temps](oven-temps.md) — 11/11: Macarons bake at 300 F, rack two. Fourteen minutes.')
        index = (self.dir / 'MEMORY.md').read_text()
        self.assertTrue(index.endswith('\n## From the lanes\n' + line + '\n'))
        nt.add('second-one', 'More.', today=datetime(2026, 11, 11))
        self.assertEqual((self.dir / 'MEMORY.md').read_text().count('## From the lanes'), 1)

    def test_never_overwrites_and_checks_names(self):
        nt.add('x1', 'first')
        with self.assertRaises(nt.NoteError):
            nt.add('x1', 'second')
        self.assertIn('first', (self.dir / 'x1.md').read_text())
        for bad in ('Bad', '../up', 'memory', '', 'a b'):
            with self.assertRaises(nt.NoteError):
                nt.add(bad, 'text')
        with self.assertRaises(nt.NoteError):
            nt.add('empty', '   ')

    def test_long_hook_is_clipped(self):
        _, line = nt.add('long', 'word ' * 100)
        self.assertLess(len(line), 140)
        self.assertTrue(line.endswith('…'))

    def test_main_add_show_list(self):
        code, out, _ = self.run_main('add', 'cli-note', 'Text', 'in', 'parts')
        self.assertEqual(code, 0)
        self.assertIn('MEMORY.md: - [Cli note](cli-note.md)', out)
        code, out, _ = self.run_main('show', 'cli-note')
        self.assertEqual(code, 0)
        self.assertIn('Text in parts', out)
        code, out, _ = self.run_main('list')
        self.assertEqual(code, 0)
        self.assertIn('say-tool  speaks text', out)
        self.assertIn('cli-note', out)
        self.assertIn('2 notes in', out)
        self.assertEqual(self.run_main('show', 'missing')[0], 1)
        self.assertEqual(self.run_main('add', 'cli-note', 'again')[0], 1)
        self.assertEqual(self.run_main('nothing')[0], 2)


if __name__ == '__main__':
    unittest.main()
