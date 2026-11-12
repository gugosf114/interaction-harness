"""Offline tests for the extra lanes, the knobs, and the `both` fan-out.

Every provider call is a fake client, so nothing here reaches the network."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import harness as h
import extra_lanes
import knobs as knobs_mod
import both
from test_harness import document


def chat_usage(cached=4):
    return NS(model_dump=lambda **_: {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                                      'prompt_tokens_details': {'cached_tokens': cached}})


def chat_resp(content, usage=None, rid='r1'):
    return NS(choices=[NS(message=NS(content=content))], usage=usage or chat_usage(), id=rid)


class FakeChat:
    """Stands in for an OpenAI-compatible client: client.chat.completions.create."""
    def __init__(self, items):
        self.items = list(items)
        self.calls = []
        self.chat = NS(completions=self)

    def create(self, **kw):
        self.calls.append(kw)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeMessages:
    """Stands in for AnthropicVertex: client.messages.create."""
    def __init__(self, items):
        self.items = list(items)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def vertex_reply(answer='The owner can read and write the file.'):
    block = NS(type='tool_use', name='emit_reply', input=json.loads(document(direct_answer=answer)))
    usage = NS(model_dump=lambda **_: {'input_tokens': 30, 'output_tokens': 12})
    return NS(content=[block], usage=usage, id='vtx1', stop_reason='tool_use')


class LaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / 'usage.jsonl'
        self.state = patch.object(h, 'STATE', self.root / 'state')
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.tmp.cleanup()

    def ask(self, engine, client, query='Explain chmod 640.', **kw):
        events = []
        reply = h.request_reply(query, engine=engine, client=client, events=events, log_path=self.log, **kw)
        return reply, events

    # ---- registry ----
    def test_registry_shortcuts_unique(self):
        shortcuts = [lane.shortcut for lane in extra_lanes.LANES.values()]
        self.assertEqual(sorted(shortcuts), ['g2', 'g3', 'g4', 'gv'])
        for name in ('gemini', 'openrouter', 'glm', 'vertex'):
            self.assertIn(name, extra_lanes.LANES)

    # ---- gemini / openrouter json lanes ----
    def test_gemini_json_lane(self):
        client = FakeChat([chat_resp(document(direct_answer='chmod 640 lets the owner read and write.'))])
        reply, events = self.ask('gemini', client)
        self.assertEqual(reply.intent, 'observation')
        self.assertIn('owner', reply.direct_answer)
        self.assertEqual(events[-1]['status'], 'accepted')
        self.assertEqual(events[-1]['engine'], 'gemini')
        # response_format strict schema is requested.
        self.assertEqual(client.calls[0]['response_format']['json_schema']['strict'], True)
        # reasoning effort is mapped to a value gemini accepts.
        self.assertIn(client.calls[0]['reasoning_effort'], ('low', 'medium', 'high'))
        self.assertEqual(events[-1]['usage']['cache_read_input_tokens'], 4)

    def test_openrouter_json_lane(self):
        client = FakeChat([chat_resp(document(direct_answer='The group can only read.'))])
        reply, _ = self.ask('openrouter', client)
        self.assertIn('group', reply.direct_answer)
        self.assertNotIn('reasoning_effort', client.calls[0])  # openrouter lane does not force it

    # ---- glm wrap lane ----
    def test_glm_wrap_lane(self):
        client = FakeChat([chat_resp('Owner reads and writes; group reads; others get nothing.')])
        reply, _ = self.ask('glm', client)
        self.assertEqual(reply.intent, 'observation')
        self.assertIsNone(reply.execution_payload)
        self.assertIn('group reads', reply.direct_answer)
        self.assertNotIn('response_format', client.calls[0])  # wrap lane sends no schema

    def test_glm_empty_answer_is_error(self):
        client = FakeChat([chat_resp('   ')])
        with self.assertRaises(h.HarnessError):
            self.ask('glm', client)

    # ---- vertex lane ----
    def test_vertex_lane(self):
        client = FakeMessages([vertex_reply()])
        reply, events = self.ask('vertex', client)
        self.assertEqual(reply.intent, 'observation')
        self.assertEqual(events[-1]['engine'], 'vertex')
        # the emit_reply tool is offered, no web tools.
        self.assertEqual(client.calls[0]['tools'][0]['name'], 'emit_reply')

    # ---- knobs: applied, skipped, and drop-retry ----
    def test_knob_temperature_applied_on_gemini(self):
        client = FakeChat([chat_resp(document())])
        self.ask('gemini', client, knobs=knobs_mod.Knobs(temperature=0.4))
        self.assertEqual(client.calls[0]['temperature'], 0.4)

    def test_knob_seed_skipped_on_gemini_with_note(self):
        client = FakeChat([chat_resp(document())])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.ask('gemini', client, knobs=knobs_mod.Knobs(seed=7))
        self.assertNotIn('seed', client.calls[0])
        self.assertIn('--seed not supported', err.getvalue())

    def test_knob_stop_applied_on_gemini(self):
        client = FakeChat([chat_resp(document())])
        self.ask('gemini', client, knobs=knobs_mod.Knobs(stop=['STOP']))
        self.assertEqual(client.calls[0]['stop'], ['STOP'])

    def test_prefill_forces_opening(self):
        client = FakeChat([chat_resp(document(direct_answer='read and write for the owner.'))])
        reply, _ = self.ask('gemini', client, knobs=knobs_mod.Knobs(prefill='Short answer:'))
        self.assertTrue(reply.direct_answer.startswith('Short answer:'))

    def test_knob_drop_retry_on_live_rejection(self):
        from openai import BadRequestError
        resp = NS(status_code=400, headers={}, request=None)
        err = BadRequestError('Unknown name "seed": Cannot find field.', response=resp,
                              body={'error': {'message': 'Unknown name "seed"'}})
        # openrouter lane marks seed supported, so it sends it; the fake provider rejects once.
        client = FakeChat([err, chat_resp(document())])
        msg = io.StringIO()
        with contextlib.redirect_stderr(msg):
            reply, _ = self.ask('openrouter', client, knobs=knobs_mod.Knobs(seed=5))
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn('seed', client.calls[1])
        self.assertIn('knob --seed refused', msg.getvalue())

    def test_vertex_maps_stop_to_stop_sequences(self):
        client = FakeMessages([vertex_reply()])
        self.ask('vertex', client, knobs=knobs_mod.Knobs(stop=['END']))
        self.assertEqual(client.calls[0]['stop_sequences'], ['END'])

    # ---- builtin knob resolution ----
    def test_resolve_builtin_openai(self):
        wire, notes = knobs_mod.resolve_builtin('openai', knobs_mod.Knobs(temperature=0.3, service_tier='priority'))
        self.assertEqual(wire, {'service_tier': 'priority'})
        self.assertTrue(any('temperature refused' in n for n in notes))

    def test_resolve_builtin_anthropic(self):
        wire, notes = knobs_mod.resolve_builtin('anthropic', knobs_mod.Knobs(stop=['X'], service_tier='standard_only'))
        self.assertEqual(wire, {'stop_sequences': ['X'], 'service_tier': 'standard_only'})
        self.assertEqual(notes, [])

    def test_attachments_rejected_on_lane(self):
        client = FakeChat([chat_resp(document())])
        with self.assertRaises(h.HarnessError):
            self.ask('gemini', client, attachments=[{'kind': 'image', 'path': '/x', 'sha256': '0', 'size_bytes': 1,
                                                     'media_type': 'image/png'}])


class BothTests(unittest.TestCase):
    def test_select_lanes_explicit_order(self):
        self.assertEqual(both.select_lanes('glm,gemini'), ['gemini', 'glm'])

    def test_select_lanes_unknown(self):
        with self.assertRaises(h.HarnessError):
            both.select_lanes('nope')

    def test_both_fan_out(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        self.addCleanup(tmp.cleanup)
        args = NS(lanes='gemini,glm', session=None, no_normalize=True, effort='max', timeout=90,
                  usage_log=root / 'usage.jsonl', turns=100, no_web=True, web_max=5, model=None,
                  temperature=None, seed=None, stop=None, prefill=None, service_tier=None)

        def fake_reply(current, *, engine, **kw):
            events = kw.get('events')
            if events is not None:
                events.append({'lookup_counts': {'total': 0, 'search': 0, 'fetch': 0, 'find': 0},
                               'sources': [], 'usage': {'input_tokens': 1, 'output_tokens': 1}})
            return h.HarnessReply(intent='observation', cleaned_input=current,
                                  direct_answer=f'Answer from {engine}.', execution_payload=None)

        out = io.StringIO()
        with patch.object(h, 'STATE', root / 'state'), patch.object(h, 'request_reply', fake_reply), \
                contextlib.redirect_stdout(out):
            code = both.run(args, 'Explain chmod 640.')
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn('gemini', text)
        self.assertIn('glm', text)
        self.assertIn('Answer from gemini.', text)
        self.assertIn('Answer from glm.', text)
        # Each lane kept its own session file.
        sessions = {p.name for p in (root / 'state' / 'sessions').glob('*.json')}
        self.assertIn('both-gemini.json', sessions)
        self.assertIn('both-glm.json', sessions)


if __name__ == '__main__':
    unittest.main()
