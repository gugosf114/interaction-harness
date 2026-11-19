"""Offline tests for agentd: the queue, the runner, the service loop, the web page and the CLI."""
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock
import urllib.request

from agentd import config
from agentd.cli import cmd_job, job_report, jobs_table
from agentd.daemon import Daemon, job_line
from agentd.jobs import Queue, JobError, final_answer, first_line, turns
from agentd import web

FAKE_HARNESS = textwrap.dedent('''
    import os, sqlite3, sys, time
    task = sys.stdin.read()
    session = sys.argv[sys.argv.index('--session') + 1]
    state = os.environ['HARNESS_STATE_DIR']
    if 'sleep' in task:
        time.sleep(30)
    db = sqlite3.connect(os.path.join(state, 'history.db'), timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, timestamp TEXT, engine TEXT, model TEXT, session_id TEXT, "
               "raw_input TEXT, direct_answer TEXT, execution_payload TEXT, execution_result TEXT, status TEXT, error TEXT, tokens_used INTEGER)")
    db.execute("INSERT INTO history(timestamp,engine,session_id,raw_input,direct_answer,execution_payload,execution_result,status,tokens_used) "
               "VALUES('t','fake',?,?,?,?,?,'ok',1)", (session, task, 'Working.', 'echo hi', '{"approved": true, "exit_code": 0, "stdout": "hi\\\\n"}'))
    db.execute("INSERT INTO history(timestamp,engine,session_id,raw_input,direct_answer,status,tokens_used) VALUES('t','fake',?,?,?,'ok',1)",
               (session, 'continue', 'Answer to: ' + task.strip() + '\\nsecond line'))
    db.commit()
    print('flags', ' '.join(sys.argv[1:]))
    sys.exit(3 if 'fail' in task else 0)
''')


class FakePhone:
    def __init__(self):
        self.notes, self.removed, self.said, self.texts = [], [], [], []
        self.inbox, self.shade, self.voice = [], [], 'off'

    def notify(self, ident, title, content, **kw):
        self.notes.append((ident, title, content, kw))
        return True

    def remove_notification(self, ident):
        self.removed.append(ident)
        return True

    def voice_state(self):
        return self.voice

    def say(self, text):
        self.said.append(text)
        return True

    def sms_inbox(self, limit=40):
        return list(self.inbox)

    def sms_send(self, number, text):
        self.texts.append((number, text))
        return True

    def notifications(self):
        return list(self.shade)

    def wake_lock(self):
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'state'
        self.paths = config.Paths(self.state).make()
        fake = Path(self.tmp.name) / 'fake_harness.py'
        fake.write_text(FAKE_HARNESS)
        bashrc = Path(self.tmp.name) / 'bashrc'
        bashrc.write_text('')
        self.env = mock.patch.dict(os.environ, {'HARNESS_STATE_DIR': str(self.state), 'AGENTD_BASHRC': str(bashrc),
                                                'AGENTD_NO_KEEPER': '1', 'AGENTD_NO_PHONE': '1'})
        self.env.start()
        self.paths.settings.write_text(json.dumps({'harness': [sys.executable, '-B', str(fake)], 'port': 0}))
        self.paths.doors.write_text(json.dumps({'web': {'password': 'pw1'}, 'sms': {'keyword': 'lane', 'numbers': ['+14155550123']},
                                                'telegram': {'chat_ids': []}, 'voice': {'key': 'vk'}}))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def daemon(self, doors=()):
        return Daemon(self.paths, phone=FakePhone(), doors=list(doors), serve_web=False)

    def run_until(self, daemon, predicate, seconds=40):
        deadline = time.time() + seconds
        while time.time() < deadline:
            daemon.step()
            if predicate():
                return True
            time.sleep(0.2)
        return False


class QueueTests(Base):
    def test_add_gives_an_id_and_a_fresh_session(self):
        queue = Queue(self.paths)
        one, two = queue.add('g1', 'first task'), queue.add('g2', 'second', session='mine')
        self.assertEqual((one['id'], one['state'], one['door']), (1, 'queued', 'cli'))
        self.assertTrue(one['session'].startswith('job-1-'))
        self.assertEqual(two['session'], 'mine')
        self.assertEqual([job['id'] for job in queue.list()], [2, 1])

    def test_rejects_empty_task_and_bad_session(self):
        queue = Queue(self.paths)
        with self.assertRaises(JobError):
            queue.add('g1', '   ')
        with self.assertRaises(JobError):
            queue.add('g1', 'x', session='bad name')

    def test_claim_finish_and_stop(self):
        queue = Queue(self.paths)
        queue.add('g1', 'a')
        queue.add('g1', 'b')
        self.assertEqual(queue.claim()['state'], 'starting')
        stopped = queue.request_stop(2)
        self.assertEqual(stopped['state'], 'stopped')
        self.assertIsNone(queue.claim())
        queue.finish(1, 'done', 0, 'ok')
        queue.finish(1, 'failed', 1)  # a final state is never overwritten
        self.assertEqual(queue.get(1)['state'], 'done')

    def test_recover_marks_lost_runs_interrupted(self):
        queue = Queue(self.paths)
        queue.add('g1', 'a')
        queue.claim()
        queue.set_pid(1, 999999)
        self.assertEqual(queue.recover(alive=lambda pid: False), [1])
        self.assertEqual(queue.get(1)['state'], 'interrupted')

    def test_kv_and_reply_to_round_trip(self):
        queue = Queue(self.paths)
        job = queue.add('g1', 'a', door='sms', reply_to={'number': '+1'})
        self.assertEqual(queue.get(job['id'])['reply_to'], {'number': '+1'})
        queue.kv_set('x', {'a': [1]})
        self.assertEqual(queue.kv_get('x'), {'a': [1]})
        self.assertEqual(queue.kv_get('missing', 5), 5)

    def test_first_line_and_final_answer(self):
        self.assertEqual(first_line('\n  hello \nthere'), 'hello')
        self.assertEqual(final_answer([{'direct_answer': 'a'}, {'direct_answer': None}, {'direct_answer': 'b'}]), 'b')
        self.assertEqual(job_line({'answer': None, 'error': 'broke\nmore'}), 'broke')


class ConfigTests(Base):
    def test_alias_block_lanes_and_job_flags(self):
        text = ("# BEGIN interaction-harness shortcuts\nalias g2='~/interaction-harness/harness --engine anthropic --effort max'\n"
                "alias other='ls'\n# END interaction-harness shortcuts\n")
        self.assertEqual(config.alias_lanes(text), {'g2': ['--engine', 'anthropic', '--effort', 'max']})
        self.assertEqual(config.job_flags(['--chat', '--engine', 'openai']), ['--engine', 'openai', '--loop', '-y'])

    def test_lanes_always_loop_and_approve(self):
        table = config.lanes({'lanes': {'fast': ['--effort', 'low']}})
        for flags in table.values():
            self.assertIn('--loop', flags)
            self.assertIn('-y', flags)
        self.assertIn('fast', table)
        self.assertEqual(config.default_lane({}, table), 'g2')

    def test_doors_file_is_filled_once(self):
        self.paths.doors.unlink()
        first = config.load_doors(self.paths, numbers=['+14155550123'])
        self.assertTrue(first['web']['password'])
        self.assertEqual(first['sms'], {'keyword': 'lane', 'numbers': ['+14155550123']})
        self.assertEqual(oct(self.paths.doors.stat().st_mode & 0o777), '0o600')
        self.assertEqual(config.load_doors(self.paths), first)

    def test_empty_password_stays_empty(self):
        self.paths.doors.write_text(json.dumps({'web': {'password': ''}}))
        self.assertEqual(config.load_doors(self.paths, numbers=[])['web']['password'], '')

    def test_own_numbers_from_profile(self):
        profile = Path(self.tmp.name) / 'profile.json'
        profile.write_text(json.dumps({'identity': {'phone': '+14155550123'}}))
        self.assertEqual(config.own_numbers([Path('/nope'), profile]), ['+14155550123'])
        self.assertEqual(config.own_numbers([Path('/nope')]), [])

    def test_number_allowed(self):
        self.assertTrue(config.number_allowed('14155550123', ['+1 (415) 555-0123']))
        self.assertFalse(config.number_allowed('+14155550999', ['+14155550123']))
        self.assertTrue(config.number_allowed('anything', ['*']))
        self.assertFalse(config.number_allowed('', ['+14155550123']))


class ServiceTests(Base):
    def test_job_runs_in_background_lands_in_history_and_notifies(self):
        daemon = self.daemon()
        job = daemon.add_job('say hello', lane='g1')
        self.assertTrue(self.run_until(daemon, lambda: daemon.queue.get(job['id'])['state'] == 'done'))
        daemon.step()
        done = daemon.queue.get(job['id'])
        self.assertEqual(done['answer'], 'Answer to: say hello\nsecond line')
        self.assertEqual(done['exit_code'], 0)
        out = (self.paths.jobs / str(job['id']) / 'stdout.txt').read_text()
        self.assertIn('--loop -y --session ' + done['session'], out)
        rows = turns(self.paths, done)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['execution_payload'], 'echo hi')
        titles = [note[1] for note in daemon.phone.notes]
        self.assertIn(f"g1 job {job['id']} done", titles)
        content = [note[2] for note in daemon.phone.notes if note[1] == f"g1 job {job['id']} done"][0]
        self.assertEqual(content, 'Answer to: say hello')
        report = job_report(self.paths, done)
        self.assertIn('1. [exit 0] echo hi', report)
        self.assertIn('Answer to: say hello', report)
        self.assertIn('--- stdout', job_report(self.paths, done, full=True))

    def test_two_jobs_run_in_parallel(self):
        daemon = self.daemon()
        one, two = daemon.add_job('first', lane='g1'), daemon.add_job('second', lane='g2')
        daemon.step()
        states = {daemon.queue.get(one['id'])['state'], daemon.queue.get(two['id'])['state']}
        self.assertTrue(states <= {'starting', 'running', 'done'})
        self.assertEqual(len(daemon.children) + sum(1 for j in (one, two) if daemon.queue.get(j['id'])['state'] == 'done'), 2)
        self.assertTrue(self.run_until(daemon, lambda: all(daemon.queue.get(j['id'])['state'] == 'done' for j in (one, two))))
        status = [note for note in daemon.phone.notes if note[0] == 'agentd-status']
        self.assertTrue(any('2 lane jobs running' == note[1] for note in status))
        table = jobs_table(daemon.queue.list())
        self.assertEqual(len(table.splitlines()), 3)

    def test_failed_job_and_spoken_answer(self):
        daemon = self.daemon()
        daemon.phone.voice = 'first'
        job = daemon.add_job('please fail', lane='g1')
        self.assertTrue(self.run_until(daemon, lambda: daemon.queue.get(job['id'])['state'] == 'failed'))
        daemon.step()
        self.assertEqual(daemon.queue.get(job['id'])['exit_code'], 3)
        spoken = daemon.speech.get(timeout=2)
        self.assertEqual(spoken['id'], job['id'])

    def test_speaker_follows_voice_setting(self):
        daemon = self.daemon()
        daemon.phone.voice = 'first'
        daemon.speech.put({'answer': 'line one\nline two'})
        thread = threading.Thread(target=daemon.speaker)
        thread.start()
        deadline = time.time() + 5
        while not daemon.phone.said and time.time() < deadline:
            time.sleep(0.05)
        daemon.stop.set()
        thread.join()
        self.assertEqual(daemon.phone.said, ['line one'])

    def test_stop_ends_a_running_job(self):
        daemon = self.daemon()
        job = daemon.add_job('sleep please', lane='g1')
        self.assertTrue(self.run_until(daemon, lambda: daemon.queue.get(job['id'])['state'] == 'running', 20))
        daemon.queue.request_stop(job['id'])
        self.assertTrue(self.run_until(daemon, lambda: daemon.queue.get(job['id'])['state'] == 'stopped', 30))

    def test_unknown_lane_is_refused(self):
        with self.assertRaises(ValueError):
            self.daemon().add_job('x', lane='nope')

    def test_new_history_db_is_put_in_wal_mode(self):
        daemon = self.daemon()
        daemon.prepare_history()
        db = sqlite3.connect(self.paths.history)
        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        db.close()


class PhoneTests(Base):
    def test_voice_flags_and_text(self):
        from agentd.phone import parse_notification_list, parse_voice_state, voice_flags
        folder = Path(self.tmp.name) / 'claude'
        folder.mkdir()
        self.assertEqual(voice_flags(folder), 'off')
        (folder / '.voice-full').touch()
        self.assertEqual(voice_flags(folder), 'off')
        (folder / '.voice-on').touch()
        self.assertEqual(voice_flags(folder), 'full')
        (folder / '.voice-full').unlink()
        self.assertEqual(voice_flags(folder), 'first')
        self.assertEqual(parse_voice_state('Voice is OFF\nFull: EVERY session\n'), 'off')
        self.assertEqual(parse_voice_state('Voice is ON\nFull: EVERY session\n'), 'full')
        self.assertEqual(parse_notification_list('CAUTION: data\n{"notifications":[{"title":"a"}],"count":1}'), [{'title': 'a'}])
        self.assertIsNone(parse_notification_list('nothing'))

    def test_sms_send_sees_a_refusal_and_sends_text_on_stdin(self):
        from agentd.phone import Phone
        calls = []

        def runner(argv, timeout=60, input_text=None):
            calls.append((argv, input_text))
            return 0, '{\n  "error": "Please grant the following permission to use this command: android.permission.SEND_SMS"\n}', ''

        self.assertFalse(Phone(run=runner).sms_send('+14155550123', '-n looks like a flag'))
        self.assertEqual(calls[0][0][-2:], ['-n', '+14155550123'])
        self.assertEqual(calls[0][1], '-n looks like a flag')
        self.assertTrue(Phone(run=lambda *a, **k: (0, '', '')).sms_send('+1', 'x'))


class KeeperTests(Base):
    """keeper.sh through a link, the way ~/.termux/boot/20-agentd starts it: one watch loop, and the service comes back."""

    def test_one_loop_through_a_link_and_the_service_returns(self):
        import subprocess
        root = Path(__file__).resolve().parent
        fake = Path(self.tmp.name) / 'fakepy'
        # Stands in for python: `fakepy -B .../agentd _daemon` writes its pid and sleeps, like the service.
        fake.write_text('#!/bin/sh\necho $$ > "$HARNESS_STATE_DIR/agentd/daemon.pid"\n'
                        'exec python3 -c "import time; time.sleep(300)" agentd _daemon\n')
        fake.chmod(0o755)
        link = Path(self.tmp.name) / '20-agentd'
        link.symlink_to(root / 'agentd' / 'boot' / '20-agentd')
        env = {**os.environ, 'AGD_PYTHON': str(fake), 'AGD_SEC': '1'}
        keeper = root / 'agentd' / 'keeper.sh'
        try:
            for _ in range(3):
                subprocess.run(['sh', str(link)], env=env, timeout=30)
                time.sleep(0.5)
            time.sleep(2)
            def read(path):
                try:
                    return path.read_bytes()
                except OSError:
                    return b''
            from keeper_test_processes import snapshot,independent_pids
            deadline=time.monotonic()+15
            while True:
                rows=snapshot(self.state);mine=independent_pids(rows)
                try:owner=int((self.paths.home/'keeper.lock/pid').read_text())
                except (OSError,ValueError):owner=None
                if mine==[owner] or time.monotonic()>=deadline:break
                time.sleep(.05)
            self.assertEqual(mine,[owner],{'processes':rows,'registered_owner':owner})
            first = int((self.paths.home / 'daemon.pid').read_text())
            os.kill(first, 9)
            deadline = time.time() + 15
            while time.time() < deadline:
                time.sleep(0.5)
                try:
                    now = int((self.paths.home / 'daemon.pid').read_text())
                except (OSError, ValueError):
                    continue
                if now != first:
                    break
            self.assertNotEqual(now, first)
        finally:
            subprocess.run(['sh', str(keeper), 'stop'], env=env, timeout=30)
        self.assertTrue((self.paths.home / 'STOPPED').exists())


class CliTests(Base):
    def test_job_add_list_show(self):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            self.assertEqual(cmd_job(['add', '--lane', 'g1', 'count', 'files'], self.paths), 0)
            self.assertEqual(cmd_job(['list'], self.paths), 0)
            self.assertEqual(cmd_job(['show', '1'], self.paths), 0)
        text = out.getvalue()
        self.assertIn('job 1 queued on g1', text)
        self.assertIn('queued', text)
        self.assertIn('count files', text)

    def test_unknown_lane_and_job(self):
        err = io.StringIO()
        with mock.patch('sys.stderr', err):
            self.assertEqual(cmd_job(['add', '--lane', 'nope', 'x'], self.paths), 2)
            self.assertEqual(cmd_job(['show', '9'], self.paths), 1)

    def test_stop_a_queued_job(self):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            cmd_job(['add', 'x'], self.paths)
            self.assertEqual(cmd_job(['stop', '1'], self.paths), 0)
        self.assertIn('job 1 stopped', out.getvalue())


class WebTests(Base):
    def setUp(self):
        super().setUp()
        self.service = self.daemon()
        from agentd.doors.voice import VoiceDoor
        self.service.doors = [VoiceDoor(self.service, http=lambda *a, **k: (200, '{}'))]
        self.server = web.Server(('127.0.0.1', 0), self.service)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method='POST' if body is not None else 'GET',
                                         headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_password_gates_page_and_api(self):
        status, text = self.call('/')
        self.assertEqual(status, 401)
        self.assertIn('type="password"', text)
        self.assertEqual(self.call('/api/state')[0], 401)
        self.assertEqual(self.call('/api/state', headers={'X-Agentd-Password': 'wrong'})[0], 401)
        status, text = self.call('/api/state?password=pw1')
        self.assertEqual(status, 200)
        self.assertIn('g1', json.loads(text)['lanes'])
        self.assertEqual(self.call('/', headers={'Cookie': 'agentd_pw=pw1'})[0], 200)

    def test_empty_password_opens_the_page(self):
        self.paths.doors.write_text(json.dumps({'web': {'password': ''}, 'sms': {'numbers': []}, 'voice': {'key': 'vk'}}))
        self.assertEqual(self.call('/api/state')[0], 200)

    def test_add_job_and_detail(self):
        head = {'X-Agentd-Password': 'pw1'}
        status, text = self.call('/api/jobs', {'task': 'hello', 'lane': 'g1'}, head)
        self.assertEqual(status, 201)
        job = json.loads(text)
        self.assertEqual((job['door'], job['state']), ('web', 'queued'))
        status, text = self.call(f"/api/jobs/{job['id']}", headers=head)
        self.assertEqual(json.loads(text)['task'], 'hello')
        self.assertEqual(self.call('/api/jobs', {'task': 'x', 'door': 'telegram'}, head)[0], 201)
        self.assertEqual(self.service.queue.get(2)['door'], 'telegram')
        self.assertEqual(self.call('/api/jobs', {'task': ''}, head)[0], 400)
        self.assertEqual(self.call('/api/jobs', {'task': 'x'}, {**head, 'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.call(f"/api/jobs/{job['id']}/stop", {}, head)[0], 200)
        self.assertEqual(self.service.queue.get(job['id'])['state'], 'stopped')

    def test_vapi_tools_use_the_line_key_not_the_password(self):
        body = {'message': {'type': 'tool-calls', 'call': {'id': 'call1', 'monitor': {'controlUrl': 'https://x.vapi.ai/c'}},
                            'toolCallList': [{'id': 't1', 'type': 'function',
                                              'function': {'name': 'lane_job', 'arguments': {'task': 'check battery', 'lane': 'g1'}}}]}}
        self.assertEqual(self.call('/vapi/tools', body)[0], 401)
        status, text = self.call('/vapi/tools', body, {'X-Line-Key': 'vk'})
        self.assertEqual(status, 200)
        result = json.loads(text)['results'][0]
        self.assertEqual(result['toolCallId'], 't1')
        self.assertIn('Job 1 is running on the g1 lane', result['result'])
        job = self.service.queue.get(1)
        self.assertEqual((job['door'], job['reply_to']['call_id']), ('voice', 'call1'))


if __name__ == '__main__':
    unittest.main()
