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
