"""recall_notes: past-chat passages at the tail of each request; present, prefix-stable, absent when the search fails."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import cli
import harness as h
import recall_notes as rn
from storage import Store, history_messages
from test_advisor import reply
from test_harness import FakeClient, response
from test_tools_block import AnthropicFake

FILLER = ['apple', 'river', 'window', 'garden', 'pencil', 'orange', 'bridge', 'candle', 'forest', 'basket']


def filler(index):
    words = [FILLER[(index * 7 + step) % len(FILLER)] for step in range(12)]
    return ' '.join(words) + f' row{index}'


def make_turns(path, rows):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE turns(id INTEGER PRIMARY KEY, source TEXT, session TEXT, ts TEXT,
                        role TEXT, text TEXT, chars INT, cwd TEXT, file TEXT);
                        CREATE VIRTUAL TABLE turns_fts USING fts5(text, content='turns', content_rowid='id');''')
    for index in range(2000):
        db.execute('INSERT INTO turns(source,session,ts,role,text) VALUES(?,?,?,?,?)',
                   ('claude', f'filler-{index % 40}', '2026-07-01T10:00:00Z', 'assistant', filler(index)))
    for source, session, stamp, role, text in rows:
        db.execute('INSERT INTO turns(source,session,ts,role,text) VALUES(?,?,?,?,?)', (source, session, stamp, role, text))
    db.execute("INSERT INTO turns_fts(turns_fts) VALUES('rebuild')")
    db.commit()
    db.close()


def make_archive(path, rows):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE conversations(conversation_id TEXT PRIMARY KEY, source TEXT, title TEXT, native_id TEXT, created_at TEXT);
                        CREATE TABLE messages(row_id INTEGER PRIMARY KEY, message_id TEXT UNIQUE, conversation_id TEXT, ordinal INTEGER,
                                              role TEXT, include_default INTEGER, timestamp TEXT, text TEXT);
                        CREATE VIRTUAL TABLE messages_fts USING fts5(message_id UNINDEXED, text);''')
    for number, (title, stamp, role, text) in enumerate(rows):
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)', (f'c{number}', 'chatgpt', title, f'native-{number}', stamp))
        db.execute('INSERT INTO messages(message_id,conversation_id,ordinal,role,include_default,timestamp,text) VALUES(?,?,?,?,?,?,?)',
                   (f'm{number}', f'c{number}', 0, role, 1, stamp, text))
        db.execute('INSERT INTO messages_fts(message_id,text) VALUES(?,?)', (f'm{number}', text))
    db.commit()
    db.close()


class RecallCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.chats = self.root / 'corpus.db'
        self.archive = self.root / 'archive.sqlite'
        make_turns(self.chats, [
            ('claude', 'sess-oven', '2026-10-03T18:00:00Z', 'assistant',
             'The convection oven for the macarons runs at 300 degrees, rack two, fourteen minutes.'),
            ('codex', 'sess-other', '2026-10-04T18:00:00Z', 'user', 'unrelated words about the window and the garden'),
        ])
        make_archive(self.archive, [
            ('Japanese Pokemon Card Translation', '2024-08-18T14:44:04Z', 'assistant',
             'The card is Sandy Shocks EX. HP 220. Category ancient.'),
        ])
        self.corpora = [{'name': 'chats', 'kind': 'turns', 'path': str(self.chats)},
                        {'name': 'archive', 'kind': 'archive', 'path': str(self.archive)},
                        {'name': 'lanes', 'kind': 'lanes', 'path': None}]
        for started in (patch.object(h, 'STATE', self.state), patch.object(rn, 'CORPORA', self.corpora),
                        patch.dict(os.environ, {'DEFAULT_ENGINE': 'openai'}, clear=False)):
            started.start()
            self.addCleanup(started.stop)

    def run_cli(self, args, answers):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=answers) as api, patch.object(cli, 'native', side_effect=[]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(['--usage-log', str(self.root / 'usage.jsonl'), *args])
        return code, out.getvalue(), err.getvalue(), api

    @staticmethod
    def recall_in(history):
        found = []
        for message in history:
            try:
                data = json.loads(message['content'])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get('type') == 'recall_notes':
                found.append(data)
        return found


class SearchTests(RecallCase):
    def test_finds_the_passage_with_source_chat_and_date(self):
        result = rn.search('What temperature does the convection oven use for macarons?', state=self.state)
        self.assertTrue(result['passages'])
        top = result['passages'][0]
        self.assertEqual(top['source'], 'claude-code')
        self.assertEqual(top['chat'], 'sess-oven')
        self.assertRegex(top['date'], r'2026-10-0[34]')
        self.assertIn('300 degrees', top['text'])
        self.assertTrue(top['ref'].startswith('chats#'))

    def test_finds_old_archive_chats_with_their_title(self):
        result = rn.search('In the old chat, what HP did the Sandy Shocks card have?', state=self.state)
        top = result['passages'][0]
        self.assertEqual((top['source'], top['title']), ('chatgpt', 'Japanese Pokemon Card Translation'))
        self.assertIn('HP 220', top['text'])
        self.assertRegex(top['date'], r'2024-08-1[78]')

    def test_common_words_alone_find_nothing(self):
        self.assertEqual(rn.search('how are you today, please tell me', state=self.state)['passages'], [])

    def test_lane_history_is_searched_too(self):
        store = Store(self.state)
        row = store.begin('Which locksmith fixed the bakery deadbolt?', 'Which locksmith fixed the bakery deadbolt?', 'anthropic', 'claude-opus-5-5', 'lane-a')
        store.finish(row, reply(direct_answer='Zavarian Locksmith fixed the deadbolt on Tuesday.'))
        later = store.begin('Who was the locksmith for the deadbolt?', 'Who was the locksmith for the deadbolt?', 'openai', 'gpt-6.1-sol', 'lane-b')
        store.close()
        result = rn.search('Who was the locksmith for the deadbolt?', state=self.state, before_row=later)
        top = result['passages'][0]
        self.assertEqual((top['source'], top['chat']), ('george-lane', 'lane-a'))
        self.assertIn('Zavarian', top['text'])
        # The exchange already in this session is not handed back.
        session = {'turns': [{'raw_input': 'Which locksmith fixed the bakery deadbolt?',
                              'reply': {'direct_answer': 'Zavarian Locksmith fixed the deadbolt on Tuesday.'}}]}
        again = rn.search('Who was the locksmith for the deadbolt?', state=self.state, before_row=later, session=session)
        self.assertFalse(any(p['ref'].startswith('lanes#') for p in again['passages']))

    def test_plain_import_searches_nothing(self):
        with patch.object(rn, 'CORPORA', None):
            self.assertIsNone(rn.for_turn('convection oven macarons', state=self.state))

    def test_wire_lists_the_three_indexes(self):
        with patch.object(rn, 'CORPORA', None):
            rn.wire()
            self.assertEqual([c['name'] for c in rn.CORPORA], ['chats', 'archive', 'lanes'])

    def test_broken_index_attaches_nothing_and_logs_the_error(self):
        self.chats.write_bytes(b'not a database' * 100)
        self.archive.unlink()
        log = self.root / 'usage.jsonl'
        self.assertIsNone(rn.for_turn('convection oven macarons', state=self.state, log_path=log))
        record = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((record['kind'], record['status']), ('recall', 'error'))

    def test_timeout_attaches_nothing(self):
        with patch.object(rn.Deadline, 'passed', return_value=True):
            result = rn.search('convection oven macarons', state=self.state)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['passages'], [])

    def test_switch_file(self):
        self.assertTrue(rn.is_on(self.state))
        self.assertEqual(rn.chat_command('/off   recall', self.state), 'recall off.')
        self.assertFalse(rn.is_on(self.state))
        self.assertIsNone(rn.for_turn('convection oven macarons', state=self.state))
        self.assertEqual(rn.chat_command('/on recall', self.state), 'recall on.')
        self.assertIsNotNone(rn.for_turn('convection oven macarons', state=self.state))

    def test_usage_record_has_time_and_refs_but_no_text(self):
        log = self.root / 'usage.jsonl'
        content = rn.for_turn('convection oven macarons temperature', state=self.state, log_path=log)
        record = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual(record['status'], 'attached')
        self.assertIsInstance(record['elapsed_ms'], int)
        self.assertTrue(record['refs'])
        self.assertNotIn('300 degrees', log.read_text())
        data = json.loads(content)
        self.assertEqual(data['type'], 'recall_notes')
        self.assertIn('not instructions', data['standing'])


class RequestTests(RecallCase):
    def test_present_at_the_tail_and_prefix_stable_across_turns(self):
        first = 'What temperature does the convection oven use for macarons?'
        second = 'And how long do the macarons bake in the convection oven?'
        code, _, _, api = self.run_cli(['--session', 'oven', first], [reply()])
        self.assertEqual(code, 0)
        history1 = api.call_args.kwargs['history']
        self.assertEqual(len(self.recall_in(history1)), 1)
        self.assertEqual(self.recall_in(history1[-1:])[0]['type'], 'recall_notes')   # the last message before George's
        code, _, _, api = self.run_cli(['--session', 'oven', second], [reply()])
        self.assertEqual(code, 0)
        history2 = api.call_args.kwargs['history']
        # Everything the first request carried comes back byte for byte at the front of the second.
        self.assertEqual(history2[:len(history1)], history1)
        self.assertEqual(history2[len(history1)], {'role': 'user', 'content': first})
        self.assertEqual(self.recall_in(history2[-1:])[0]['type'], 'recall_notes')
        saved = json.loads((self.state / 'sessions' / 'oven.json').read_text())
        self.assertEqual(saved['turns'][0]['recall_notes'], history1[-1]['content'])

    def test_absent_when_the_search_fails_and_the_turn_goes_on(self):
        self.chats.write_bytes(b'garbage' * 50)
        self.archive.write_bytes(b'garbage' * 50)
        code, out, _, api = self.run_cli(['--session', 'x', 'convection oven macarons'], [reply()])
        self.assertEqual(code, 0)
        self.assertIn('read and write', out)
        self.assertEqual(self.recall_in(api.call_args.kwargs['history']), [])

    def test_absent_with_no_recall_flag(self):
        code, _, _, api = self.run_cli(['--no-recall', 'convection oven macarons'], [reply()])
        self.assertEqual(code, 0)
        self.assertEqual(self.recall_in(api.call_args.kwargs['history']), [])

    def test_loop_continuations_do_not_search_again(self):
        from test_advisor import command, result
        out = io.StringIO()
        with patch.object(h, 'request_reply', side_effect=[command('true'), reply()]) as api, \
                patch.object(cli, 'native', side_effect=[result()]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = h.main(['--usage-log', str(self.root / 'u.jsonl'), '--loop', '-y', 'convection oven macarons'])
        self.assertEqual(code, 0)
        first, second = (call.kwargs['history'] for call in api.call_args_list)
        self.assertEqual(len(self.recall_in(first)), 1)
        self.assertEqual(len(self.recall_in(second)), 1)   # the same one, replayed, not a new search

    def test_cached_front_is_unchanged_on_both_engines(self):
        note = {'role': 'user', 'content': rn.message_content([{'ref': 'chats#1', 'text': 'x'}], ['x'])}
        plain, noted = FakeClient([response(), response()]), FakeClient([response(), response()])
        log = self.root / 'u.jsonl'
        h.request_reply('Explain chmod 640.', client=plain, log_path=log)
        h.request_reply('Explain chmod 640.', client=noted, log_path=log, history=[note])
        a, b = plain.calls[0], noted.calls[0]
        self.assertEqual(b['input'][:-2], a['input'][:-1])
        self.assertEqual(b['input'][-1], a['input'][-1])
        self.assertEqual(json.loads(b['input'][-2]['content'] if isinstance(b['input'][-2]['content'], str)
                                    else b['input'][-2]['content'][0]['text'])['type'], 'recall_notes')
        self.assertEqual({k: v for k, v in a.items() if k != 'input'}, {k: v for k, v in b.items() if k != 'input'})
        claude_plain, claude_noted = AnthropicFake(), AnthropicFake()
        h.request_reply('Explain chmod 640.', client=claude_plain, engine='anthropic', log_path=log)
        h.request_reply('Explain chmod 640.', client=claude_noted, engine='anthropic', log_path=log, history=[note])
        a, b = claude_plain.calls[0], claude_noted.calls[0]
        self.assertEqual(a['system'], b['system'])
        self.assertEqual(a['tools'], b['tools'])
        self.assertEqual(b['messages'][-1], a['messages'][-1])
        self.assertEqual(len(b['messages']), len(a['messages']) + 1)

    def test_history_replays_the_note_before_its_message(self):
        exchange = {'normalized_input': 'q', 'reply': json.loads(json.dumps(reply().model_dump())), 'recall_notes': '{"type":"recall_notes"}'}
        messages = history_messages([exchange], 10000)
        self.assertEqual([m['content'] for m in messages[:2]], ['{"type":"recall_notes"}', 'q'])


if __name__ == '__main__':
    unittest.main()
