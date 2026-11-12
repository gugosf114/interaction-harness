import io
import json
import signal
import unittest
from chat_bridge import exchange


class Wire:
    def __init__(self): self.written=[];self.reads=0
    def write(self,data):self.written.append(json.loads(data))
    def flush(self):pass
    def readline(self,_):
        self.reads+=1
        if self.reads==1:
            signal.raise_signal(signal.SIGINT)
            return b'{"interrupted":true,"exit_code":130}\n'
        return b'{"exit_code":0,"stdout":"next"}\n'


class BridgeTests(unittest.TestCase):
    def test_interrupt_drains_reply_then_restores_handler(self):
        wire=Wire();before=signal.getsignal(signal.SIGINT)
        with self.assertRaises(KeyboardInterrupt):exchange(wire,{'command':'sleep'})
        self.assertEqual(signal.getsignal(signal.SIGINT),before)
        self.assertEqual(exchange(wire,{'command':'next'})['stdout'],'next')
        self.assertEqual(wire.reads,2)
    def test_daemon_signal_is_forwarded_but_terminal_signal_is_not_duplicated(self):
        from unittest.mock import Mock,patch,call
        from launch import bridge_interrupt
        child=Mock(pid=10);stop=bridge_interrupt(child)
        with patch('launch.worker_pids',return_value=[30]),patch('launch.os.kill') as kill:
            with patch('launch.foreground_tty',return_value=False):stop(signal.SIGINT,None)
            self.assertEqual(kill.call_args_list,[call(30,signal.SIGINT)])
            kill.reset_mock()
            with patch('launch.foreground_tty',return_value=True):stop(signal.SIGINT,None)
            kill.assert_not_called()
    def test_worker_selection_excludes_the_proot_command_string(self):
        from unittest.mock import patch
        import launch
        path=str(launch.ROOT/'bootstrap.py').encode()
        data=[b'python\0-B\0'+path+b'\0',b'proot\0python -B '+path+b' 3 6 harness.py\0']
        with patch('launch.child_tree',return_value=[30,20]),patch('pathlib.Path.read_bytes',side_effect=data):
            self.assertEqual(launch.worker_pids(10),[30])
