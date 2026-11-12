import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from agentd.config import Paths,write_private_json
from agentd import integrations
from agentd import voice_tunnel_health as health


class VoiceTunnel(unittest.TestCase):
    def test_address_comes_from_creation_banner_even_after_long_later_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'tunnel.log'
            log.write_text('Your quick Tunnel has been created!\nhttps://owned.trycloudflare.com\n'+
                           'x'*200000+'\nrequest failed: https://other.trycloudflare.com\n')
            self.assertEqual(health.address(log),'https://owned.trycloudflare.com')
    def test_only_terminal_error_after_latest_registration_requires_renewal(self):
        self.assertTrue(health.revoked('Registered tunnel connection\nUnauthorized: Tunnel not found'))
        self.assertFalse(health.revoked('Unauthorized: Tunnel not found\nRegistered tunnel connection'))
        self.assertFalse(health.revoked('Retrying connection: network unavailable'))

    def test_expired_live_pid_gets_replaced_and_retired_only_after_verified_wire(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=Paths(folder).make();order=[]
            (paths.home/'voice-tunnel.pid').write_text('123')
            (paths.home/'voice-tunnel.log').write_text('https://old.trycloudflare.com\nUnauthorized: Tunnel not found')
            def spawn(*a,**k):
                order.append('start');k['stdout'].write(b'Your quick Tunnel has been created!\nhttps://fresh.trycloudflare.com\nRegistered tunnel connection\n');k['stdout'].flush()
                return SimpleNamespace(pid=456)
            with patch('agentd.jobs.pid_alive',return_value=True),patch.object(Path,'read_bytes',return_value=b'cloudflared'), \
                 patch.object(health,'remember') as remember,patch.object(integrations.subprocess,'Popen',side_effect=spawn), \
                 patch.object(health,'wait_route',side_effect=lambda *a:order.append('probe')), \
                 patch.object(integrations,'point_voice',side_effect=lambda *a:order.append('wire') or {'server_url':'https://fresh.trycloudflare.com/vapi/tools'}), \
                 patch.object(health,'retire',side_effect=lambda *a:order.append('retire')):
                result=integrations.ensure_voice(paths)
            remember.assert_called_once_with(paths,123)
            self.assertEqual(order,['start','probe','wire','retire'])
            self.assertEqual((paths.home/'voice-tunnel.pid').read_text(),'456')
            self.assertIn('fresh',result['server_url'])
            self.assertTrue(list(paths.home.glob('voice-tunnel-*.log')))

    def test_failed_route_does_not_retire_old_process_or_wire_an_unready_url(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=Paths(folder).make();(paths.home/'voice-tunnel.pid').write_text('456')
            (paths.home/'voice-tunnel.log').write_text('Your quick Tunnel has been created!\nhttps://fresh.trycloudflare.com\nRegistered tunnel connection')
            with patch('agentd.jobs.pid_alive',return_value=True),patch.object(Path,'read_bytes',return_value=b'cloudflared'), \
                 patch.object(health,'wait_route',side_effect=RuntimeError('not ready')), \
                 patch.object(integrations,'point_voice') as wire,patch.object(health,'retire') as retire:
                with self.assertRaises(RuntimeError):integrations.ensure_voice(paths)
            wire.assert_not_called();retire.assert_not_called()

    def test_retirement_checks_process_birth_time_before_signalling(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=Paths(folder).make();write_private_json(paths.home/'voice-tunnel-retiring.json',[{'pid':123,'start_ticks':1},{'pid':456,'start_ticks':2}])
            with patch.object(health,'process',side_effect=lambda p:{'pid':p,'start_ticks':1 if p==123 else 99}), \
                    patch.object(health.os,'getpgid',return_value=123),patch.object(health.os,'killpg') as kill:
                health.retire(paths)
            kill.assert_called_once_with(123,health.signal.SIGTERM)
            self.assertEqual(health.pending(paths),[{'pid':123,'start_ticks':1}])


if __name__=='__main__':unittest.main()
