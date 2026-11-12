"""Screen card, index, install and live-proof scope."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import harness as h
from verify_screen import allowed


class ScreenCardTests(unittest.TestCase):
    def test_screen_index_and_card_contract(self):
        index=(h.ROOT/'tools_block.txt').read_text()
        card=(h.ROOT/'toolbox/cards/screen.md').read_text()
        self.assertEqual(index.count('Print: card screen'),1)
        self.assertTrue(card.startswith('# screen —'))
        for text in ('screen snap','screen tap','screen swipe','screen text','screen key','screen size',
                     'look PATH','full size','private file receipt','listed, not run','Known failure'):
            self.assertIn(text,card)
        self.assertLess(len(card),4000)

    def test_installer_covers_screen_and_look(self):
        text=(h.ROOT/'toolbox/install.sh').read_text()
        self.assertIn('"$here"/bin/*',text)
        for command in ('screen','look'):
            path=h.ROOT/'toolbox/bin'/command
            self.assertTrue(path.stat().st_mode & 0o100)

    def test_existing_system_look_is_kept_and_harness_look_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'bin';folder.mkdir()
            system_look=folder/'look';system_look.write_text('system word lookup')
            result=subprocess.run(['sh',str(h.ROOT/'toolbox/install.sh')],capture_output=True,text=True,
                                  env={**os.environ,'PREFIX':tmp})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('harness-local look',result.stdout)
            self.assertEqual(system_look.read_text(),'system word lookup')
            self.assertTrue((folder/'screen').is_symlink())

    def test_live_proof_cannot_drive_visible_or_other_screens(self):
        for command in ('screen tap 1 2','screen text words --target phone','screen snap --target yana',
                        'screen tap 1 2 --target laptop','screen tap 1 2 --target hidden:web',
                        'screen snap; adb shell input tap 1 2','screen snap --out /etc/hosts',
                        'screen snap | bash','screen text "$(touch x)" --target hidden:proof'):
            self.assertFalse(allowed(command,'proof'),command)
        self.assertFalse(allowed('card phone\nadb shell input tap 1 2','proof'))
        for command in ('card screen','card phone\ncard screen\n','screen snap --target phone','screen snap --target hidden:proof',
                        'screen tap 1 2 --target hidden:proof && screen text wifi --target hidden:proof',
                        'screen snap --target hidden:proof; sleep 1; screen size --target hidden:proof'):
            self.assertTrue(allowed(command,'proof'),command)


if __name__=='__main__':unittest.main()
