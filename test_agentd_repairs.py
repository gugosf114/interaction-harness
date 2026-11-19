"""Regressions found while proving the always-on service on the phone."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from agentd.config import Paths
from agentd.jobs import Queue
from agentd.daemon import Daemon
from agentd.phone import Phone
from agentd.integrations import patch_once, telegram
from agentd.telegram_lane import install as install_telegram


class Repairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = Paths(Path(self.temp.name) / 'state').make()

    def tearDown(self):
        self.temp.cleanup()

    def test_retry_webhook_creates_only_one_job_even_after_reopen(self):
        q = Queue(self.paths)
        first = q.add('g1', 'Read it', door='voice', source_id='call:tool')
        q.close()
        q = Queue(self.paths)
        try:
            second = q.add('g1', 'Read it', door='voice', source_id='call:tool')
            self.assertEqual(first['id'], second['id'])
            self.assertEqual(len(q.list()), 1)
        finally:
            q.close()

    def test_same_session_jobs_wait_but_other_sessions_run(self):
        q = Queue(self.paths)
        try:
            a = q.add('g1', 'a', session='same')
            b = q.add('g1', 'b', session='same')
            c = q.add('g2', 'c', session='other')
            self.assertEqual(q.claim()['id'], a['id'])
            self.assertEqual(q.claim()['id'], c['id'])
            self.assertIsNone(q.claim())
            q.finish(a['id'], 'done', 0)
            self.assertEqual(q.claim()['id'], b['id'])
        finally:
            q.close()

    def test_notification_failure_is_not_marked_notified_and_retries(self):
        phone = Mock()
        phone.notify.side_effect = [False, True]
        phone.last_error = 'Android refused this notification'
        d = Daemon(self.paths, phone=phone, doors=[], serve_web=False)
        try:
            job = d.queue.add('g1', 'task')
            d.queue.finish(job['id'], 'done', 0, 'Answer.')
            d.finish_jobs()
            self.assertEqual(d.queue.get(job['id'])['notified'], 0)
            self.assertIn(phone.last_error, self.paths.log.read_text())
            d.notification_wait.clear()
            d.finish_jobs()
            self.assertEqual(d.queue.get(job['id'])['notified'], 1)
            self.assertEqual(d.speech.qsize(), 1)
        finally:
            d.queue.close()

    def test_android_json_error_is_kept(self):
        run = Mock(return_value=(0, '{"error":"Invalid subscription"}', ''))
        phone = Phone(run)
        self.assertFalse(phone.sms_send('+14155550100', 'test'))
        self.assertEqual(phone.last_error, 'Invalid subscription')
        self.assertEqual(run.call_args.kwargs['input_text'], 'test')

    def test_daemon_owns_speech_without_switching_any_gate(self):
        import lane_mods
        with patch.dict(os.environ, {'HARNESS_SPEECH_OWNER':'agentd'}), patch.object(lane_mods, '_h') as harness:
            lane_mods.speak('Answer.')
        harness.assert_not_called()

    def test_job_transport_tracks_public_id_and_ignores_deltas(self):
        import chat_progress
        from types import SimpleNamespace
        from agentd.runtime import activate
        with patch.object(chat_progress, 'listener'), patch.object(chat_progress, 'response_listener'), \
             patch.dict(os.environ, {'HARNESS_STATE_DIR':str(self.paths.state)}):
            activate()
            chat_progress.public_event(SimpleNamespace(type='response.output_text.delta', delta='private'))
            self.assertFalse((self.paths.home/'requests').exists())
            chat_progress.public_event(SimpleNamespace(type='response.created', response=SimpleNamespace(id='resp-test')))
            data=json.loads(next((self.paths.home/'requests').iterdir()).read_text())
            self.assertEqual(data['response_id'], 'resp-test')
            self.assertNotIn('private', json.dumps(data))

    def test_talk_reports_playback_failure(self):
        from agentd import talk
        with patch.object(talk, 'transcribe', return_value='Two plus two'), \
             patch.object(talk, 'ask_lane', return_value={'answer':'4','state':'done','exit_code':0}), \
             patch.object(talk, 'speak', return_value=False), \
             patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO) as err:
            code = talk.main(['--lane','g1','--clip','fake.mp3'], self.paths)
        self.assertEqual(code, 2)
        self.assertIn('say failed', err.getvalue())

    def test_talk_interrupt_requests_job_stop(self):
        from agentd import talk
        with patch('agentd.cli.keeper'), patch.object(talk.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                talk.ask_lane(self.paths, 'g1', 'voice-proof', 'task')
        q = Queue(self.paths)
        try:
            self.assertEqual(q.list()[0]['state'], 'stopped')
        finally:
            q.close()

    def test_bridge_patch_is_idempotent_and_preserves_other_code(self):
        target = Path(self.temp.name) / 'bridge.py'
        target.write_text('before\nHERE\nafter\n')
        self.assertTrue(patch_once(target, 'HERE', 'ADDED\nHERE'))
        self.assertFalse(patch_once(target, 'HERE', 'ADDED\nHERE'))
        self.assertEqual(target.read_text(), 'before\nADDED\nHERE\nafter\n')
        self.assertEqual(len(list(target.parent.glob('bridge.py.before-agentd-*'))), 1)

    def test_voice_tool_keeps_existing_brain_routes(self):
        from agentd.integrations import point_voice
        legacy = {'type':'function','function':{'name':'brain_job'},
                  'server':{'url':'https://old.example/tools','headers':{'X-Line-Key':'old-key'}}}
        assistant = {'model':{'provider':'anthropic','model':'voice-model','tools':[legacy]}}
        def api(method, route, payload=None):
            if method == 'PATCH': assistant.update(payload)
            return assistant
        with patch('agentd.integrations.api', side_effect=api):
            result = point_voice(self.paths, 'https://new.trycloudflare.com')
        self.assertEqual(assistant['model']['tools'][0], legacy)
        lane = assistant['model']['tools'][1]
        self.assertEqual(lane['server']['url'], 'https://new.trycloudflare.com/vapi/tools')
        self.assertNotEqual(lane['server']['headers']['X-Line-Key'], 'old-key')
        self.assertEqual(result['server_url'], lane['server']['url'])

    def test_voice_tunnel_reuses_its_live_process_and_saved_address(self):
        from agentd.integrations import ensure_voice
        from agentd.config import write_private_json
        (self.paths.home/'voice-tunnel.pid').write_text('12345')
        (self.paths.home/'voice-tunnel.log').write_text('Your quick Tunnel has been created!\nhttps://test.trycloudflare.com')
        write_private_json(self.paths.home/'voice-address.json', {'server_url':'https://test.trycloudflare.com/vapi/tools'})
        with patch('agentd.jobs.pid_alive', return_value=True), patch.object(Path,'read_bytes',return_value=b'cloudflared'), \
             patch('agentd.integrations.subprocess.Popen') as spawn, patch('agentd.integrations.api') as api:
            result = ensure_voice(self.paths)
        spawn.assert_not_called()
        api.assert_not_called()
        self.assertEqual(result['server_url'], 'https://test.trycloudflare.com/vapi/tools')

    def test_telegram_installer_preserves_existing_routes(self):
        folder = Path(self.temp.name) / 'agent-bridge/scripts'
        folder.mkdir(parents=True)
        script = folder / 'telegram_bridge.py'
        script.write_text('def handle_text(t): pass\nif __name__ == "__main__":\n    main()\n')
        a = telegram(script, 'http://phone:8377', 'private')
        b = telegram(script, 'http://phone:8377', 'private')
        self.assertEqual(a, b)
        self.assertEqual(script.read_text().count('install_lane_door(globals())'), 1)
        self.assertEqual(Path(a['config']).stat().st_mode & 0o777, 0o600)
        namespace = {'handle_text':Mock(), 'CHAT_ID':'123', 'send':Mock(), 'log':Mock()}
        old = namespace['handle_text']
        install_telegram(namespace, a['config'])
        namespace['handle_text']('/status')
        old.assert_called_once_with('/status')

    def test_telegram_queues_lane_then_returns_full_answer(self):
        cfg = Path(self.temp.name) / 'telegram.json'
        cfg.write_text(json.dumps({'url':'http://phone:8377','password':'private'}))
        namespace = {'handle_text':Mock(), 'CHAT_ID':'123', 'send':Mock(), 'log':Mock()}
        install_telegram(namespace, cfg)
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps({'id':7,'lane':'g1','state':'done','answer':'A' * 5000})))
        response.__exit__ = Mock(return_value=False)
        def start(*args, **kw):
            kw['target'](*kw['args'])
            return Mock()
        with patch('urllib.request.urlopen', return_value=response) as opener, \
             patch('agentd.telegram_lane.threading.Thread', side_effect=start):
            namespace['handle_text']('/g1 Read the battery.')
        req = opener.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body['task'], 'Read the battery.')
        self.assertEqual(body['lane'], 'g1')
        messages = [call.args[0] for call in namespace['send'].call_args_list]
        self.assertEqual(messages[0], 'g1 job 7 started.')
        self.assertEqual(''.join(messages[1:]), 'g1 job 7 done:\n' + 'A' * 5000)


if __name__ == '__main__':
    unittest.main()
