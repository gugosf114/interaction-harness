"""Offline tests for the agentd doors: folder, text message, Telegram, voice line, clock, events, talk and tunnel."""
import datetime
import io
import json
import os
from pathlib import Path
import time
import unittest
from unittest import mock

from agentd import config
from agentd.doors import answer_text
from agentd.doors.inbox import InboxDoor, parse_drop
from agentd.doors.schedule import ScheduleDoor, ScheduleError, due, parse_schedule
from agentd.doors.sms import SmsDoor, parse_text, reply_text
from agentd.doors.telegram import TelegramDoor, parse_message, parts
from agentd.doors.triggers import (TriggerDoor, TriggerError, fill, matches, notification_event, parse_triggers,
                                   sms_event)
from agentd.doors.voice import VoiceDoor, spoken_report, tool_calls
from agentd import talk, tunnel
from test_agentd import Base

LANES = ['g2', 'g1']


class InboxTests(Base):
    def test_parse_drop_headers(self):
        self.assertEqual(parse_drop('lane: g1\nsession: s1\n\nDo the thing.\nMore.'),
                         {'lane': 'g1', 'session': 's1', 'task': 'Do the thing.\nMore.'})
        self.assertEqual(parse_drop('Just a task'), {'lane': None, 'session': None, 'task': 'Just a task'})
        with self.assertRaises(ValueError):
            parse_drop('session: bad!name\nx')

    def test_drop_becomes_job_and_answer_lands_in_outbox(self):
        daemon = self.daemon()
        door = InboxDoor(daemon)
        drop = self.paths.inbox / 'ask.txt'
        drop.write_text('lane: g1\nWhat time is it?')
        os.utime(drop, (time.time() - 5, time.time() - 5))
        door.poll()
        job = daemon.queue.get(1)
        self.assertEqual((job['lane'], job['door'], job['task']), ('g1', 'inbox', 'What time is it?'))
        self.assertTrue((self.paths.inbox / 'taken' / '1-ask.txt').exists())
        daemon.queue.finish(1, 'done', 0, 'Noon.')
        target = door.deliver(daemon.queue.get(1))
        self.assertEqual(Path(target).read_text(), 'job 1  g1  done  exit 0\n\nNoon.\n')

    def test_fresh_and_bad_files(self):
        daemon = self.daemon()
        door = InboxDoor(daemon)
        (self.paths.inbox / 'new.txt').write_text('not settled yet')
        empty = self.paths.inbox / 'empty.txt'
        empty.write_text('lane: g1\n')
        os.utime(empty, (time.time() - 5, time.time() - 5))
        door.poll()
        self.assertEqual(daemon.queue.list(), [])
        self.assertTrue((self.paths.outbox / 'empty.txt.answer.txt').read_text().startswith('Not run:'))
        self.assertTrue((self.paths.inbox / 'new.txt').exists())


class SmsTests(Base):
    def test_parse_text(self):
        self.assertEqual(parse_text('lane g1 what is the battery', 'lane', LANES), {'lane': 'g1', 'task': 'what is the battery'})
        self.assertEqual(parse_text('Lane: check mail', 'lane', LANES), {'lane': None, 'task': 'check mail'})
        self.assertEqual(parse_text('LANE G2, read it', 'lane', LANES), {'lane': 'g2', 'task': 'read it'})
        self.assertIsNone(parse_text('lanes are closed', 'lane', LANES))
        self.assertIsNone(parse_text('hello lane g1 x', 'lane', LANES))
        self.assertIsNone(parse_text('lane', 'lane', LANES))
        self.assertIsNone(parse_text('lane g1', 'lane', LANES))
        self.assertEqual(parse_text('lane g1x go', 'lane', LANES), {'lane': None, 'task': 'g1x go'})

    def test_door_listens_only_to_listed_numbers_and_new_texts(self):
        daemon = self.daemon()
        door = SmsDoor(daemon)
        daemon.phone.inbox = [{'_id': 5, 'number': '+14155550123', 'body': 'lane g1 old text'}]
        door.poll()  # first look: everything there is old
        self.assertEqual(daemon.queue.list(), [])
        daemon.phone.inbox += [{'_id': 6, 'number': '+14155550999', 'body': 'lane g1 stranger'},
                               {'_id': 7, 'number': '14155550123', 'body': 'not for the door'},
                               {'_id': 8, 'number': '(415) 555-0123', 'body': 'lane g1 battery please'}]
        door.poll()
        jobs = daemon.queue.list()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]['lane'], jobs[0]['task'], jobs[0]['door']), ('g1', 'battery please', 'sms'))
        self.assertEqual(daemon.phone.texts, [('(415) 555-0123', 'g1 job 1 started.')])
        door.poll()
        self.assertEqual(len(daemon.queue.list()), 1)
        daemon.queue.finish(1, 'done', 0, '81 percent.')
        self.assertEqual(door.deliver(daemon.queue.get(1)), 'texted (415) 555-0123')
        self.assertEqual(daemon.phone.texts[-1], ('(415) 555-0123', 'g1 job 1 done: 81 percent.'))

    def test_star_means_anyone(self):
        self.paths.doors.write_text(json.dumps({'web': {'password': 'x'}, 'sms': {'keyword': 'go', 'numbers': ['*']}, 'voice': {'key': 'k'}}))
        daemon = self.daemon()
        door = SmsDoor(daemon)
        door.poll()
        daemon.phone.inbox = [{'_id': 1, 'number': '+19995550000', 'body': 'go tell me a joke'}]
        door.poll()
        self.assertEqual(daemon.queue.get(1)['task'], 'tell me a joke')

    def test_reply_text(self):
        self.assertEqual(reply_text({'lane': 'g1', 'id': 3, 'state': 'failed', 'answer': None, 'error': 'boom'}), 'g1 job 3 failed: boom')
        self.assertEqual(answer_text({'state': 'stopped', 'answer': None}), 'Stopped.')


class TelegramTests(Base):
    def test_parse_message(self):
        self.assertEqual(parse_message('/lane g1 check the battery', LANES), {'lane': 'g1', 'task': 'check the battery'})
        self.assertEqual(parse_message('/g1 hi there', LANES), {'lane': 'g1', 'task': 'hi there'})
        self.assertEqual(parse_message('/g2@Abridge114_bot read mail', LANES), {'lane': 'g2', 'task': 'read mail'})
        self.assertEqual(parse_message('plain words', LANES), {'lane': None, 'task': 'plain words'})
        self.assertEqual(parse_message('/lane do it', LANES), {'lane': None, 'task': 'do it'})
        self.assertIsNone(parse_message('/start', LANES))
        self.assertIsNone(parse_message('/status', LANES))
        self.assertIsNone(parse_message('/g1', LANES))
        self.assertEqual(parts('a' * 9000), ['a' * 4000, 'a' * 4000, 'a' * 1000])

    def test_direct_bot_polls_and_replies(self):
        conf = json.loads(self.paths.doors.read_text())
        conf['telegram'] = {'token': 'T', 'chat_ids': [42]}
        self.paths.doors.write_text(json.dumps(conf))
        daemon = self.daemon()
        sent = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=0):
            body = json.loads(request.data)
            if request.full_url.endswith('/getUpdates'):
                return Response(json.dumps({'ok': True, 'result': [
                    {'update_id': 10, 'message': {'chat': {'id': 42}, 'text': '/g1 battery'}},
                    {'update_id': 11, 'message': {'chat': {'id': 7}, 'text': 'hi'}}]}).encode())
            sent.append((body['chat_id'], body['text']))
            return Response(b'{"ok": true}')

        door = TelegramDoor(daemon, opener=opener)
        door.poll()
        self.assertEqual(daemon.queue.get(1)['task'], 'battery')
        self.assertEqual(daemon.queue.kv_get('telegram_offset'), 11)
        self.assertEqual(sent[0], ('42', 'g1 job 1 started.'))
        self.assertTrue(sent[1][1].startswith('This chat is not on the list'))
        daemon.queue.finish(1, 'done', 0, 'Full.')
        self.assertEqual(door.deliver(daemon.queue.get(1)), 'sent to chat 42')
        self.assertEqual(sent[-1], ('42', 'g1 job 1 done:\nFull.'))

    def test_without_token_the_box_bridge_carries_it(self):
        daemon = self.daemon()
        door = TelegramDoor(daemon, opener=lambda *a, **k: self.fail('no call without a token'))
        door.poll()
        self.assertIn('box bridge', door.status())
        job = daemon.add_job('x', lane='g1', door='telegram')
        daemon.queue.finish(job['id'], 'done', 0, 'y')
        self.assertEqual(door.deliver(daemon.queue.get(job['id'])), 'the box bridge collects it')


class VoiceTests(Base):
    def test_tool_calls_accepts_both_shapes(self):
        body = {'message': {'toolCallList': [{'id': 'a', 'function': {'name': 'lane_job', 'arguments': '{"task": "x"}'}},
                                             {'id': 'b', 'name': 'other', 'arguments': {'q': 1}}]}}
        self.assertEqual(tool_calls(body), [('a', 'lane_job', {'task': 'x'}), ('b', 'other', {'q': 1})])
        self.assertEqual(tool_calls({}), [])

    def test_delivery_into_the_live_call(self):
        calls = []

        def http(argv, payload=None, timeout=20, secret_header=None):
            calls.append((argv, payload, secret_header))
            if payload is None:
                return 200, json.dumps({'id': 'c1', 'status': 'in-progress', 'monitor': {'controlUrl': 'https://phone.vapi.ai/x/control'}})
            return 200, ''

        daemon = self.daemon()
        door = VoiceDoor(daemon, http=http)
        job = daemon.add_job('t', lane='g1', door='voice', reply_to={'call_id': 'c1', 'control_url': None})
        daemon.queue.finish(job['id'], 'done', 0, 'It is 80 percent.')
        with mock.patch('agentd.doors.voice.vapi_key', return_value='K'):
            self.assertEqual(door.deliver(daemon.queue.get(job['id'])), 'accepted by Vapi')
        self.assertEqual(calls[0][0], ['https://api.vapi.ai/call/c1'])
        self.assertEqual(calls[0][2], 'Authorization: Bearer K')
        self.assertNotIn('K', ' '.join(calls[0][0]))
        self.assertEqual(calls[1][0], ['https://phone.vapi.ai/x/control'])
        self.assertEqual(calls[1][1]['type'], 'add-message')
        self.assertFalse(calls[1][1]['triggerResponseEnabled'])
        self.assertIn('It is 80 percent.', calls[1][1]['message']['content'])
        self.assertEqual(calls[2][1]['type'], 'say')
        self.assertEqual(calls[2][1]['content'], 'It is 80 percent.')

    def test_ended_call_and_no_call(self):
        daemon = self.daemon()
        door = VoiceDoor(daemon, http=lambda argv, payload=None, **k: (200, json.dumps({'id': 'c1', 'status': 'ended'})))
        job = daemon.add_job('t', lane='g1', door='voice', reply_to={'call_id': 'c1'})
        daemon.queue.finish(job['id'], 'done', 0, 'a')
        with mock.patch('agentd.doors.voice.vapi_key', return_value='K'):
            self.assertEqual(door.deliver(daemon.queue.get(job['id'])), 'call ended; answer kept in the job')
        self.assertEqual(door.deliver({**daemon.queue.get(job['id']), 'reply_to': {}}), 'no live call')
        self.assertIn('"answer": "a"', spoken_report(daemon.queue.get(job['id'])))


class ScheduleTests(Base):
    def test_parse_schedule(self):
        entries = parse_schedule(json.dumps([{'name': 'm', 'at': '8:05', 'task': 'x', 'days': ['Monday']},
                                             {'every_minutes': 30, 'task': 'y', 'lane': 'g1'}]))
        self.assertEqual(entries[0]['at'], (8, 5))
        self.assertEqual(entries[0]['days'], {'mon'})
        self.assertEqual(entries[1]['every'], 30)
        self.assertTrue(entries[1]['key'].startswith('sha:'))
        for bad in ([{'task': 'x'}], [{'at': '25:00', 'task': 'x'}], [{'at': '08:00', 'every_minutes': 5, 'task': 'x'}],
                    [{'every_minutes': 0, 'task': 'x'}], [{'at': '08:00'}], {'jobs': 5}, [{'at': '08:00', 'task': 'x', 'days': ['funday']}]):
            with self.assertRaises((ScheduleError, ValueError)):
                parse_schedule(json.dumps(bad))
        self.assertEqual(parse_schedule(''), [])

    def test_due(self):
        entry = parse_schedule(json.dumps([{'at': '08:00', 'task': 'x'}]))[0]
        at = datetime.datetime(2026, 11, 11, 8, 0, 30)
        self.assertTrue(due(entry, at, None))
        self.assertFalse(due(entry, at, at.timestamp()))
        self.assertFalse(due(entry, datetime.datetime(2026, 11, 11, 7, 59), None))
        self.assertFalse(due(entry, datetime.datetime(2026, 11, 11, 10, 0), None))  # past the catch-up hour
        every = parse_schedule(json.dumps([{'every_minutes': 2, 'task': 'x'}]))[0]
        self.assertTrue(due(every, at, at.timestamp() - 121))
        self.assertFalse(due(every, at, at.timestamp() - 60))
        weekday = parse_schedule(json.dumps([{'at': '08:00', 'task': 'x', 'days': ['tue']}]))[0]
        self.assertFalse(due(weekday, at, None))  # Nov 11, 2026 is a Wednesday

    def test_door_runs_entries_once_when_due(self):
        self.paths.schedule.write_text(json.dumps([{'name': 'soon', 'at': '08:02', 'lane': 'g1', 'task': 'scheduled task'},
                                                   {'name': 'often', 'every_minutes': 1, 'task': 'tick'}]))
        daemon = self.daemon()
        door = ScheduleDoor(daemon)
        door.poll(datetime.datetime(2026, 11, 11, 8, 0))
        self.assertEqual(daemon.queue.list(), [])
        door.poll(datetime.datetime(2026, 11, 11, 8, 2, 10))
        jobs = daemon.queue.list()
        self.assertEqual([(j['task'], j['door'], j['lane']) for j in jobs], [('tick', 'schedule', 'g2'), ('scheduled task', 'schedule', 'g1')])
        door.poll(datetime.datetime(2026, 11, 11, 8, 2, 40))
        self.assertEqual(len(daemon.queue.list()), 2)

    def test_new_time_entry_never_fires_for_the_past(self):
        self.paths.schedule.write_text(json.dumps([{'name': 'late', 'at': '08:00', 'task': 'x'}]))
        daemon = self.daemon()
        door = ScheduleDoor(daemon)
        door.poll(datetime.datetime(2026, 11, 11, 8, 10))
        door.poll(datetime.datetime(2026, 11, 11, 8, 11))
        self.assertEqual(daemon.queue.list(), [])
        door.poll(datetime.datetime(2026, 11, 12, 8, 0, 5))
        self.assertEqual(len(daemon.queue.list()), 1)

    def test_bad_file_is_a_note(self):
        self.paths.schedule.write_text('{broken')
        door = ScheduleDoor(self.daemon())
        door.poll()
        self.assertIn('schedule.json', door.status())


class TriggerTests(Base):
    RULES = [{'name': 'wa', 'when': 'notification', 'app': 'com.whatsapp', 'task': 'Message: {text}', 'lane': 'g1'},
             {'name': 'yana', 'when': 'sms', 'from': '+14155550100', 'match': 'bread', 'task': 'Yana: {text}'},
             {'name': 'mail', 'when': 'mail', 'mailbox': 'berkeley', 'task': 'Mail {subject} from {from}'}]

    def test_parse_triggers(self):
        self.assertEqual(len(parse_triggers(json.dumps(self.RULES))), 3)
        for bad in ([{'when': 'call', 'task': 'x'}], [{'when': 'mail', 'mailbox': 'yahoo', 'task': 'x'}],
                    [{'when': 'notification', 'task': 'x'}], [{'when': 'sms', 'task': 'x'}], [{'when': 'sms', 'from': '1'}], 5):
            with self.assertRaises((TriggerError, ValueError)):
                parse_triggers(json.dumps(bad))

    def test_matches_and_fill(self):
        rules = parse_triggers(json.dumps(self.RULES))
        note = notification_event({'notification_id': 'a', 'timestamp': 1, 'package_name': 'com.whatsapp', 'app_name': 'WhatsApp',
                                   'title': 'Yana', 'text': 'hi', 'big_text': None})
        self.assertTrue(matches(rules[0], note))
        self.assertEqual(fill(rules[0]['task'], note), 'Message: Yana: hi')
        self.assertTrue(matches({**rules[0], 'app': 'whatsapp'}, note))
        text = sms_event({'_id': 3, 'number': '14155550100', 'body': 'Buy bread'})
        self.assertTrue(matches(rules[1], text))
        self.assertFalse(matches(rules[1], {**text, 'text': 'Buy milk'}))
        self.assertFalse(matches(rules[1], {**text, 'from': '+14155550199'}))
        mail = {'kind': 'mail', 'mailbox': 'berkeley', 'id': 'm1', 'from': 'Dean', 'subject': 'Hello', 'text': 'x'}
        self.assertTrue(matches(rules[2], mail))
        self.assertFalse(matches(rules[2], {**mail, 'mailbox': 'gmail'}))
        self.assertEqual(fill(rules[2]['task'], mail), 'Mail Hello from Dean')
        self.assertEqual(fill('keep {unknown}', mail), 'keep {unknown}')

    def test_door_fires_only_on_new_events(self):
        self.paths.triggers.write_text(json.dumps(self.RULES[:2]))
        daemon = self.daemon()
        door = TriggerDoor(daemon)
        old = {'notification_id': 'n1', 'timestamp': 1, 'package_name': 'com.whatsapp', 'app_name': 'WhatsApp', 'title': 'A', 'text': 'old'}
        daemon.phone.shade = [old]
        daemon.phone.inbox = [{'_id': 1, 'number': '+14155550100', 'body': 'bread old'}]
        door.poll()
        self.assertEqual(daemon.queue.list(), [])
        daemon.phone.shade = [old, {**old, 'notification_id': 'n2', 'timestamp': 2, 'text': 'new one'},
                              {**old, 'notification_id': 'n3', 'timestamp': 3, 'title': 'g1 job 4 done', 'text': 'own'}]
        daemon.phone.inbox.append({'_id': 2, 'number': '+14155550100', 'body': 'get bread'})
        door.poll()
        tasks = sorted(job['task'] for job in daemon.queue.list())
        self.assertEqual(tasks, ['Message: A: new one', 'Yana: get bread'])
        door.poll()
        self.assertEqual(len(daemon.queue.list()), 2)
        self.assertEqual(daemon.queue.get(1)['door'], 'triggers')


class TalkTests(Base):
    def test_transcribe_sends_the_file_and_model(self):
        clip = Path(self.tmp.name) / 'clip.m4a'
        clip.write_bytes(b'audio-bytes')
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=0):
            seen['url'], seen['auth'], seen['type'], seen['body'] = (request.full_url, request.headers['Authorization'],
                                                                     request.headers['Content-type'], request.data)
            return Response(b'{"text": " What is the battery level? "}')

        self.assertEqual(talk.transcribe(clip, key='K', opener=opener), 'What is the battery level?')
        self.assertEqual(seen['url'], 'https://api.openai.com/v1/audio/transcriptions')
        self.assertEqual(seen['auth'], 'Bearer K')
        self.assertTrue(seen['type'].startswith('multipart/form-data; boundary='))
        self.assertIn(b'name="model"\r\n\r\ngpt-transcribe', seen['body'])
        self.assertIn(b'filename="clip.m4a"\r\nContent-Type: audio/mp4\r\n\r\naudio-bytes', seen['body'])

    def test_empty_clip_and_stop_words(self):
        clip = Path(self.tmp.name) / 'empty.wav'
        clip.write_bytes(b'')
        with self.assertRaises(talk.TalkError):
            talk.transcribe(clip, key='K')
        self.assertTrue(talk.STOP_WORDS.match('Stop.'))
        self.assertTrue(talk.STOP_WORDS.match('goodbye!'))
        self.assertFalse(talk.STOP_WORDS.match('stop the music'))

    def test_clip_conversation_uses_one_session(self):
        clips = [Path(self.tmp.name) / f'{n}.m4a' for n in (1, 2)]
        for clip in clips:
            clip.write_bytes(b'x')
        words = iter(['first question', 'second question'])
        asked = []

        def ask(paths, lane, session, text, timeout=None):
            asked.append((lane, session, text))
            return {'id': len(asked), 'state': 'done', 'answer': f'answer {len(asked)}', 'exit_code': 0}

        out = io.StringIO()
        with mock.patch.object(talk, 'transcribe', lambda path: next(words)), mock.patch.object(talk, 'ask_lane', ask), \
                mock.patch('sys.stdout', out), mock.patch('sys.stderr', io.StringIO()):
            code = talk.main(['--lane', 'g1', '--no-speak', '--clip', str(clips[0]), '--clip', str(clips[1])], self.paths)
        self.assertEqual(code, 0)
        self.assertEqual([a[2] for a in asked], ['first question', 'second question'])
        self.assertEqual(len({a[1] for a in asked}), 1)
        self.assertIn('g1: answer 2', out.getvalue())


class TunnelTests(unittest.TestCase):
    def test_find_url(self):
        line = '2026-11-11T21:00:00Z INF |  https://quiet-river-1234.trycloudflare.com                |'
        self.assertEqual(tunnel.find_url('cloudflared', line), 'https://quiet-river-1234.trycloudflare.com')
        self.assertEqual(tunnel.find_url('ngrok', '{"msg":"started tunnel","url":"https://ab12.ngrok-free.app"}'), 'https://ab12.ngrok-free.app')
        self.assertIsNone(tunnel.find_url('cloudflared', 'INF Requesting new quick Tunnel'))

    def test_command_runs_on_the_debian_side(self):
        argv = tunnel.command('cloudflared', 8377)
        self.assertEqual(argv[-4:], ['tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8377'][-4:])
        if config.DEBIAN_ROOTFS.is_dir():
            self.assertIn('proot-distro', argv[0])


if __name__ == '__main__':
    unittest.main()
