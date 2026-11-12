"""The operator's tools page rides right after the frozen prefix on both engines."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import harness as h
from test_harness import FakeClient, document, response


class AnthropicFake:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs)))
        usage = SimpleNamespace(model_dump=lambda **_: {'input_tokens': 10, 'output_tokens': 5})
        block = SimpleNamespace(type='tool_use', name='emit_reply', input=json.loads(document()))
        return SimpleNamespace(id='offline', model=h.ANTHROPIC_MODEL, usage=usage, stop_reason='tool_use', content=[block])


class ToolsPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'usage.jsonl'

    def call(self, engine, client, page):
        with patch.object(h, 'load_tools', return_value=page):
            return h.request_reply('Explain chmod 640.', client=client, engine=engine, log_path=self.log)

    def test_openai_gets_prefix_then_tools_then_history_then_request(self):
        client = FakeClient([response()])
        with patch.object(h, 'load_tools', return_value='TOOLS PAGE'):
            h.request_reply('Explain chmod 640.', client=client, log_path=self.log,
                            history=[{'role': 'user', 'content': 'earlier'}, {'role': 'assistant', 'content': 'reply'}])
        sent = client.calls[0]['input']
        self.assertEqual([m['role'] for m in sent], ['system', 'system', 'user', 'assistant', 'user'])
        self.assertEqual(sent[0]['content'], h.load_prefix())
        self.assertEqual(sent[1]['content'], 'TOOLS PAGE')
        self.assertEqual(sent[-1]['content'], 'Explain chmod 640.')

    def test_anthropic_gets_two_cached_system_pages_and_no_system_role_in_messages(self):
        client = AnthropicFake()
        self.call('anthropic', client, 'TOOLS PAGE')
        sent = client.calls[0]
        self.assertEqual([b['text'] for b in sent['system']], [h.load_prefix(), 'TOOLS PAGE'])
        self.assertTrue(all(b['cache_control'] == {'type': 'ephemeral'} for b in sent['system']))
        self.assertEqual([m['role'] for m in sent['messages']], ['user'])

    def test_without_a_tools_page_the_request_is_unchanged(self):
        openai_client, claude = FakeClient([response()]), AnthropicFake()
        self.call('openai', openai_client, None)
        self.call('anthropic', claude, None)
        self.assertEqual([m['role'] for m in openai_client.calls[0]['input']], ['system', 'user'])
        self.assertEqual(len(claude.calls[0]['system']), 1)

    def test_usage_log_records_the_tools_page_digest(self):
        self.call('openai', FakeClient([response()]), 'TOOLS PAGE')
        event = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual(len(event['tools_sha256']), 64)

    def test_load_tools_rules(self):
        root = Path(self.tmp.name)
        with patch.object(h, 'ROOT', root):
            self.assertIsNone(h.load_tools())
            (root / 'tools_block.txt').write_text('  \n')
            self.assertIsNone(h.load_tools())
            (root / 'tools_block.txt').write_text('gh is installed.\n')
            self.assertEqual(h.load_tools(), 'gh is installed.')
            (root / 'tools_block.txt').write_text('x' * (h.MAX_TOOLS_CHARS + 1))
            with self.assertRaises(h.HarnessError): h.load_tools()
            (root / 'tools_block.txt').write_text('bad \x1b[31m page')
            with self.assertRaises(h.HarnessError): h.load_tools()

    def test_the_shipped_tools_page_loads(self):
        page = h.load_tools()
        self.assertIsNotNone(page)
        self.assertIn('Print: card github', page)


if __name__ == '__main__':
    unittest.main()
