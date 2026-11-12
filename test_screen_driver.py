"""Screen routing without touching a device; real PNG decoder checks use Debian."""
import base64
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import screen_driver as s
from senses_fixtures import png


def decode_powershell(command):
    loader = base64.b64decode(command[-1].split()[-1]).decode('utf-16le')
    compressed = re.search(r"FromBase64String\('([^']+)'\)", loader).group(1)
    outer = gzip.decompress(base64.b64decode(compressed)).decode()
    inner = base64.b64decode(re.search(r'-EncodedCommand ([A-Za-z0-9+/=]+)"', outer).group(1)).decode('utf-16le')
    return outer, inner


class ScreenDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(s, 'PHONE_HOME', self.root); self.patch.start(); self.addCleanup(self.patch.stop)
        self.image = self.root/'fixture.png'; png(self.image, '123456')

    def test_each_verb_on_each_target(self):
        values = {'snap': [], 'size': [], 'tap': [10, 20], 'swipe': [10, 20, 30, 40, 300], 'text': ['hello world'], 'key': ['KEYCODE_ENTER']}
        for target in ('phone', 'hidden:proof', 'laptop', 'yana'):
            for verb, args in values.items():
                with self.subTest(target=target, verb=verb):
                    calls = []
                    def run(cmd):
                        calls.append(cmd)
                        if 'status' in cmd: return b'UP'
                        if 'id' in cmd: return b'148\n'
                        if cmd[-1] == 'cmd display get-displays --type VIRTUAL':
                            return b'Display id 148: type VIRTUAL, uniqueId "proof-unique", isValid=true\n'
                        if cmd[-1] == 'dumpsys SurfaceFlinger --display-id':
                            return b'Display 999 (Virtual display): displayName="same-name" uniqueId="proof-unique"'
                        if 'screen-inspect.py' in cmd[-2]: return b'{"width":440,"height":110,"black":false}'
                        if 'shot' in cmd:
                            Path(cmd[-1]).write_bytes(self.image.read_bytes()); return b''
                        if 'exec-out' in cmd: return self.image.read_bytes()
                        if 'wimlaptop' in cmd: return base64.b64encode(self.image.read_bytes()) if verb in ('snap','size') else b'OK'
                        return b''
                    with patch.object(s, 'announce') as announce:
                        result = s.drive(verb, target, args, self.root/'out.png' if verb == 'snap' else None, run)
                    if verb == 'snap': announce.assert_called_once(); self.assertTrue(Path(result).exists())
                    else: announce.assert_not_called()
                    if verb == 'size': self.assertEqual(result, '440 110')
                    act = [c for c in calls if 'status' not in c and 'id' not in c and 'screen-inspect.py' not in c[-2]
                           and c[-1] not in ('cmd display get-displays --type VIRTUAL','dumpsys SurfaceFlinger --display-id')][0]
                    if target == 'laptop':
                        self.assertIn('wimlaptop', act); outer, body = decode_powershell(act)
                        self.assertIn('-LogonType Interactive', outer)
                        self.assertIn('-WindowStyle Hidden', outer)
                        self.assertIn("-Execute 'wscript.exe'",outer)
                        self.assertIn('Unregister-ScheduledTask', outer)
                        self.assertLess(len(act[-1]), 8191)
                        expected = {'snap': 'CopyFromScreen', 'size': 'CopyFromScreen', 'tap': 'SetCursorPos(10,20)',
                                    'swipe': 'Start-Sleep -Milliseconds 15', 'text': "SendWait('hello world')", 'key': "SendWait('{ENTER}')"}
                        self.assertIn(expected[verb], body)
                    elif verb in ('snap', 'size'):
                        if target == 'phone': self.assertEqual(act[:2], ['deb', 'shot'])
                        elif target == 'yana': self.assertEqual(act, ['deb','adb','-s',s.YANA,'exec-out','screencap','-p'])
                        else: self.assertEqual(act, ['adb','-s',s.PHONE,'exec-out','screencap','-p','-d','999'])
                    else:
                        self.assertEqual(act, s.android_command(target, verb, args, '148' if target.startswith('hidden:') else None))
                        if target.startswith('hidden:'): self.assertIn('input -d 148 ', act[-1])
                        elif target == 'yana': self.assertEqual(act[:4], ['deb','adb','-s',s.YANA])
                        else: self.assertEqual(act[:3], ['adb','-s',s.PHONE])

    def test_missing_hidden_never_falls_back_to_phone(self):
        for value in (b'', b'0', b'148; input tap 1 1'):
            calls = []
            def run(cmd): calls.append(cmd); return value
            with self.assertRaisesRegex(s.ScreenError, 'target is missing'):
                s.drive('tap', 'hidden:gone', [1,2], run=run)
            self.assertEqual(len(calls), 2)

    def test_unknown_target(self):
        with self.assertRaisesRegex(s.ScreenError, 'unknown target'): s.drive('snap', 'hidden:../../phone')

    def test_capture_id_requires_exact_virtual_unique_id(self):
        displays=b'Display id 148: type VIRTUAL, uniqueId "wanted", isValid=true\nDisplay id 1480: type VIRTUAL, uniqueId "wrong", isValid=true'
        for surfaces in (b'Display 10 (HWC display 0): uniqueId="wanted"',
                         b'Display 10 (Virtual display): uniqueId="wrong"',
                         b'Display 10 (Virtual display): uniqueId="wanted"\nDisplay 11 (Virtual display): uniqueId="wanted"'):
            with self.assertRaisesRegex(s.ScreenError,'no capture id'):
                s.hidden_surface_id('148',lambda cmd:displays if cmd[-1].startswith('cmd ') else surfaces)

    def test_static_hidden_screen_uses_fresh_screencap_every_time(self):
        commands=[]
        def run(cmd):
            commands.append(cmd)
            if 'status' in cmd:return b'UP'
            if 'id' in cmd:return b'148'
            if cmd[-1].startswith('cmd display'):return b'Display id 148: type VIRTUAL, uniqueId "unique", isValid=true'
            if cmd[-1].startswith('dumpsys'):return b'Display 999 (Virtual display): uniqueId="unique"'
            if 'exec-out' in cmd:return self.image.read_bytes()
            return b'{"width":440,"height":110,"black":false}'
        with patch.object(s,'announce'):
            for _ in range(3):s.drive('snap','hidden:proof',run=run)
        self.assertEqual(sum('exec-out' in c for c in commands),3)
        self.assertFalse(any('shot' in c for c in commands))

    def test_timeout_has_its_own_message(self):
        with patch.object(s.subprocess, 'run', side_effect=subprocess.TimeoutExpired('adb', 1)):
            with self.assertRaisesRegex(s.ScreenError, '^timeout$'): s.run_command(['adb'])

    def test_black_capture_is_rejected_and_old_out_survives(self):
        out = self.root/'old.png'; out.write_bytes(b'old')
        def run(cmd):
            if 'shot' in cmd: Path(cmd[-1]).write_bytes(self.image.read_bytes()); return b''
            return b'{"width":10,"height":10,"black":true}'
        with patch.object(s, 'announce') as announce:
            with self.assertRaisesRegex(s.ScreenError, 'screen is off or capture is all black'):
                s.drive('snap','phone',out=out,run=run)
        announce.assert_not_called(); self.assertEqual(out.read_bytes(), b'old')

    def test_real_png_decoder_handles_color_black_and_transparency(self):
        # System Python has Pillow; no API or device calls.
        script = str(s.ROOT/'toolbox/debian/screen-inspect.py')
        make = "from PIL import Image; import sys; Image.new('RGBA',(3,2),tuple(map(int,sys.argv[2:]))).save(sys.argv[1])"
        for color, expected in [((0,0,0,255),True), ((255,255,255,0),True), ((0,2,0,255),False)]:
            subprocess.run(['/usr/bin/python3','-c',make,str(self.image),*map(str,color)],check=True)
            r=subprocess.run(['/usr/bin/python3',script,str(self.image)],capture_output=True,check=True)
            self.assertEqual(json.loads(r.stdout),{'width':3,'height':2,'black':expected})

    def test_text_is_one_remote_argument(self):
        import shlex
        text = "George's $(echo nope); words"
        cmd=s.android_command('hidden:proof','text',[text],'148')
        self.assertEqual(shlex.split(cmd[-1]),['input','-d','148','text',text.replace(' ','%s')])
        for text in ('a\nb','literal%s','café'):
            with self.assertRaises(s.ScreenError): s.android_command('phone','text',[text])

    def test_laptop_text_escapes_sendkeys(self):
        _,body=decode_powershell(s.laptop_command('text',["a+b%'s"]))
        self.assertIn("a{+}b{%}''s",body)

    def test_bad_arguments_print_one_line(self):
        for args in ([],['tap','1'],['tap','x','2'],['key',';'],['size','--out','a'],['snap','--target','bad']):
            out,err=io.StringIO(),io.StringIO()
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): code=s.main(args)
            self.assertEqual(code,1);self.assertEqual(out.getvalue(),'');self.assertEqual(len(err.getvalue().splitlines()),1)


if __name__ == '__main__': unittest.main()
