import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import mod_switches
import native_tools
import speech_lock
import voice_playback as voice


class VoicePlayback(unittest.TestCase):
    def test_native_enqueue_returns_before_audio_and_owns_separate_proot(self):
        child=SimpleNamespace(pid=123,stdin=Mock())
        with patch.object(voice.subprocess,'Popen',return_value=child) as start:
            result=native_tools.handle({'op':'speak','text':'The shelf is blue.','state':'/tmp/voice-test'})
        self.assertTrue(result['queued'])
        argv=start.call_args.args[0]
        self.assertIn('proot-distro',argv[0]);self.assertIn(str(voice.ROOT/'voice_playback.py'),argv)
        self.assertNotIn('The shelf is blue.',argv)
        self.assertTrue(start.call_args.kwargs['start_new_session'])
        child.stdin.write.assert_called_once_with(b'The shelf is blue.')
        child.stdin.close.assert_called_once()

    def test_off_then_on_still_skips_old_queued_speech_after_lock_is_released(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(speech_lock,'LOCK',Path(folder)/'speaker.lock'):
            state=Path(folder)/'state';entered=threading.Event()
            def call():entered.set();return voice.play('Queued text.',state,'queued')
            with patch.object(voice.subprocess,'run') as run,patch.object(voice.subprocess,'Popen') as popen:
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    with speech_lock.acquire():
                        future=pool.submit(call);self.assertTrue(entered.wait(2))
                        mod_switches.set_value('voice',False,state)
                        mod_switches.set_value('voice',True,state)
                    result=future.result(timeout=5)
            self.assertEqual(result['status'],'stopped');run.assert_not_called();popen.assert_not_called()

    def test_off_stops_active_speech_and_records_actual_exit(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(speech_lock,'LOCK',Path(folder)/'speaker.lock'):
            root=Path(folder);state=root/'state';marker=root/'started';say=root/'say'
            say.write_text('#!'+sys.executable+'\nimport pathlib,sys,time\n'
                           'if sys.argv[1]=="-s":raise SystemExit(0)\n'
                           'pathlib.Path('+repr(str(marker))+').write_text("started")\ntime.sleep(30)\n')
            say.chmod(0o755)
            with patch.object(voice,'SAY',str(say)),concurrent.futures.ThreadPoolExecutor(1) as pool:
                future=pool.submit(voice.play,'A long spoken answer.',state,'active')
                deadline=time.monotonic()+10
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(marker.exists())
                mod_switches.set_value('voice',False,state)
                result=future.result(timeout=10)
            self.assertEqual(result['status'],'stopped');self.assertNotEqual(result['exit_code'],0)
            self.assertEqual(json.loads((state/'usage.jsonl').read_text().splitlines()[-1])['voice_id'],'active')

    def test_completed_playback_keeps_exit_receipt(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(speech_lock,'LOCK',Path(folder)/'speaker.lock'):
            child=Mock(returncode=0);child.communicate.return_value=('','')
            with patch.object(voice.subprocess,'run'),patch.object(voice.subprocess,'Popen',return_value=child):
                result=voice.play('The shelf is blue.',Path(folder)/'state','done')
            self.assertEqual((result['status'],result['exit_code']),('played',0))


if __name__=='__main__':unittest.main()
