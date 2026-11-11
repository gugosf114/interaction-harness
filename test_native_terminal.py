"""Run with native Termux Python: real non-seekable PTY confirmation tests."""
import errno
import os
import pty
import select
import signal
import time
import unittest

from native_tools import confirm, run_bounded, PREFIX


def terminal_confirmation(answer):
    pid,master=pty.fork()
    if pid==0:
        result=confirm()
        os.write(1,('RESULT='+str(result)+'\n').encode())
        os._exit(0)
    output=b''; sent=False; deadline=time.monotonic()+5
    try:
        while time.monotonic()<deadline:
            if not select.select([master],[],[],0.1)[0]: continue
            try: part=os.read(master,4096)
            except OSError as exc:
                if exc.errno==errno.EIO: break
                raise
            if not part: break
            output+=part
            if b'[Run command? (y/N)]: ' in output and not sent:
                os.write(master,answer); sent=True
        else:
            os.kill(pid,signal.SIGKILL)
            raise AssertionError('Terminal confirmation did not finish.')
    finally:
        os.close(master); os.waitpid(pid,0)
    return output.decode()


class NativeTerminalTests(unittest.TestCase):
    def test_yes_approves_on_real_pty(self):
        self.assertIn('RESULT=True',terminal_confirmation(b'y\n'))

    def test_no_declines_on_real_pty(self):
        self.assertIn('RESULT=False',terminal_confirmation(b'n\n'))

    def test_enter_defaults_to_no_on_real_pty(self):
        self.assertIn('RESULT=False',terminal_confirmation(b'\n'))

    def test_native_bash_uses_termux_python(self):
        result=run_bounded([PREFIX+'/bin/bash','--noprofile','--norc','-c',"python -c 'import sys; print(sys.executable)'"],timeout=10)
        self.assertEqual(result['exit_code'],0)
        self.assertIn(PREFIX+'/bin/python',result['stdout'])


if __name__=='__main__': unittest.main()
