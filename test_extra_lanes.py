"""Offline tests for the extra lanes, the knobs, and the `both` fan-out.

Every provider call is a fake, so nothing here reaches the network. The two JSON-over-
HTTPS lanes (gemini, vertex) take a fake `post_json(url, body, headers, timeout)` as
their client; the two OpenAI-compatible lanes (openrouter, glm) take a fake chat client.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import harness as h
import extra_lanes
import lane_base
import knobs as knobs_mod
import both
from lane_base import ProviderHTTPError
from test_harness import document


# ---- fakes -----------------------------------------------------------------

class FakePost:
    """Stands in for lane_base.post_json: callable(url, body, headers, timeout)."""
    def __init__(self, items):
        self.items = list(items)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({'url': url, 'body': body, 'headers': headers})
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        payload, hdrs = item if isinstance(item, tuple) else (item, {})
        return payload, hdrs


def gemini_payload(direct_answer='The owner can read and write the file.', *, intent='observation',
                   raw=None, prompt=40, cached=0, output=12, grounding=None, finish='STOP'):
    text = raw if raw is not None else document(intent=intent, direct_answer=direct_answer)
    cand = {'content': {'parts': [{'text': text}]}, 'finishReason': finish}
    if grounding is not None:
        cand['groundingMetadata'] = grounding
    meta = {'promptTokenCount': prompt, 'cachedContentTokenCount': cached, 'candidatesTokenCount': output,
            'totalTokenCount': prompt + output, 'serviceTier': 'standard'}
    return {'candidates': [cand], 'usageMetadata': meta, 'responseId': 'gem1'}


def vertex_payload(answer='The owner can read and write the file.', *, content=None, stop='tool_use', usage=None):
    if content is None:
        content = [{'type': 'tool_use', 'name': 'emit_reply', 'input': json.loads(document(direct_answer=answer))}]
    return {'content': content, 'usage': usage or {'input_tokens': 30, 'output_tokens': 12},
            'id': 'vtx1', 'stop_reason': stop}


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


def chat_usage(cached=4):
    return NS(model_dump=lambda **_: {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                                      'prompt_tokens_details': {'cached_tokens': cached}})


def chat_resp(content, usage=None, rid='r1', annotations=None):
    message = NS(content=content, annotations=annotations)
    return NS(choices=[NS(message=message)], usage=usage or chat_usage(), id=rid)


def bad_request(message):
    from openai import BadRequestError
    resp = NS(status_code=400, headers={}, request=None)
    return BadRequestError(message, response=resp, body={'error': {'message': message}})


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
        reply = h.request_reply(query, engine=engine, client=client, events=events, log_path=self.log,
                                web=kw.pop('web', False), **kw)
        return reply, events

    # ---- registry ----
    def test_registry_shortcuts_unique(self):
        shortcuts = sorted(lane.shortcut for lane in extra_lanes.LANES.values())
        self.assertEqual(shortcuts, ['g2', 'g3', 'g4', 'gv'])
        for name in ('gemini', 'openrouter', 'glm', 'vertex'):
            self.assertIn(name, extra_lanes.LANES)
            self.assertTrue(extra_lanes.is_lane(name))
        self.assertFalse(extra_lanes.is_lane('openai'))

    # ---- gemini (native JSON over HTTPS) ----
    def test_gemini_json_lane(self):
        post = FakePost([gemini_payload('chmod 640 lets the owner read and write.', cached=7)])
        reply, events = self.ask('gemini', post)
        self.assertEqual(reply.intent, 'observation')
        self.assertIn('owner', reply.direct_answer)
        self.assertEqual(events[-1]['status'], 'accepted')
        self.assertEqual(events[-1]['engine'], 'gemini')
        body = post.calls[0]['body']
        self.assertEqual(body['generationConfig']['responseMimeType'], 'application/json')
        self.assertIn('responseJsonSchema', body['generationConfig'])
        self.assertIn(body['generationConfig']['thinkingConfig']['thinkingLevel'], ('LOW', 'MEDIUM', 'HIGH'))
        self.assertNotIn('tools', body)  # web off
        self.assertEqual(events[-1]['usage']['cache_read_input_tokens'], 7)

    def test_gemini_web_records_sources(self):
        grounding = {'webSearchQueries': ['python release'],
                     'groundingChunks': [{'web': {'uri': 'https://python.org/', 'title': 'Python'}}]}
        post = FakePost([gemini_payload(intent='action_request', direct_answer='Python 3.15 is current.',
                                        grounding=grounding)])
        reply, events = self.ask('gemini', post, query='latest python?', web=True)
        self.assertIn('Python', reply.direct_answer)
        self.assertEqual(events[-1]['lookup_counts']['search'], 1)
        self.assertEqual(events[-1]['sources'][0]['url'], 'https://python.org/')
        self.assertEqual(post.calls[0]['body']['tools'], [{'google_search': {}}, {'url_context': {}}])

    def test_gemini_bad_finish_is_error(self):
        post = FakePost([gemini_payload(finish='SAFETY')])
        with self.assertRaises(h.HarnessError):
            self.ask('gemini', post)

    # ---- openrouter ----
    def test_openrouter_json_lane(self):
        client = FakeChat([chat_resp(document(direct_answer='The group can only read.'))])
        reply, _ = self.ask('openrouter', client)
        self.assertIn('group', reply.direct_answer)
        self.assertEqual(client.calls[0]['response_format']['json_schema']['strict'], True)

    def test_openrouter_web_plugin_and_sources(self):
        ann = [NS(model_dump=lambda: {'url_citation': {'url': 'https://ex.com/', 'title': 'Ex'}})]
        client = FakeChat([chat_resp(document(intent='action_request', direct_answer='Fresh fact.'), annotations=ann)])
        reply, events = self.ask('openrouter', client, query='news?', web=True)
        self.assertEqual(client.calls[0]['extra_body']['plugins'][0]['id'], 'web')
        self.assertEqual(events[-1]['sources'][0]['url'], 'https://ex.com/')
        self.assertGreaterEqual(events[-1]['lookup_counts']['total'], 1)

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

    # ---- vertex ----
    def test_vertex_lane(self):
        post = FakePost([vertex_payload()])
        reply, events = self.ask('vertex', post)
        self.assertEqual(reply.intent, 'observation')
        self.assertEqual(events[-1]['engine'], 'vertex')
        self.assertEqual(post.calls[0]['body']['tools'][0]['name'], 'emit_reply')
        self.assertNotIn('model', post.calls[0]['body'])  # model is in the URL, not the body

    def test_vertex_quota_error_surfaces(self):
        err = ProviderHTTPError(429, json.dumps({'error': {'code': 429, 'message': 'Quota exceeded'}}))
        post = FakePost([err])
        with self.assertRaises(h.HarnessError) as ctx:
            self.ask('vertex', post)
        self.assertIn('429', str(ctx.exception))
        self.assertIn('Quota exceeded', str(ctx.exception))

    # ---- knobs: applied, skipped, drop-retry ----
    def test_knob_temperature_applied_on_gemini(self):
        post = FakePost([gemini_payload()])
        self.ask('gemini', post, knobs=knobs_mod.Knobs(temperature=0.4))
        self.assertEqual(post.calls[0]['body']['generationConfig']['temperature'], 0.4)

    def test_knob_seed_refused_on_gemini_drops_and_retries(self):
        err = ProviderHTTPError(400, json.dumps({'error': {'message': 'Unknown name "seed": Cannot find field.'}}))
        post = FakePost([err, gemini_payload()])
        msg = io.StringIO()
        with contextlib.redirect_stderr(msg):
            self.ask('gemini', post, knobs=knobs_mod.Knobs(seed=7))
        self.assertEqual(len(post.calls), 2)
        self.assertNotIn('seed', post.calls[1]['body']['generationConfig'])
        self.assertIn('knob --seed refused', msg.getvalue())

    def test_knob_stop_applied_on_gemini(self):
        post = FakePost([gemini_payload()])
        self.ask('gemini', post, knobs=knobs_mod.Knobs(stop=['STOP']))
        self.assertEqual(post.calls[0]['body']['generationConfig']['stopSequences'], ['STOP'])

    def test_knob_service_tier_on_gemini(self):
        post = FakePost([gemini_payload()])
        self.ask('gemini', post, knobs=knobs_mod.Knobs(service_tier='priority'))
        self.assertEqual(post.calls[0]['body']['service_tier'], 'priority')

    def test_prefill_forces_opening(self):
        post = FakePost([gemini_payload('read and write for the owner.'),
                         gemini_payload('read and write for the owner.')])
        reply, _ = self.ask('gemini', post, knobs=knobs_mod.Knobs(prefill='Short answer:'))
        self.assertTrue(reply.direct_answer.startswith('Short answer:'))

    def test_openrouter_seed_drop_retry_on_live_rejection(self):
        client = FakeChat([bad_request('Unknown name "seed": Cannot find field.'), chat_resp(document())])
        msg = io.StringIO()
        with contextlib.redirect_stderr(msg):
            self.ask('openrouter', client, knobs=knobs_mod.Knobs(seed=5))
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn('seed', client.calls[1])
        self.assertIn('knob --seed refused', msg.getvalue())

    def test_openrouter_service_tier_maps_to_nitro(self):
        client = FakeChat([chat_resp(document())])
        self.ask('openrouter', client, knobs=knobs_mod.Knobs(service_tier='priority'))
        self.assertTrue(client.calls[0]['model'].endswith(':nitro'))
        self.assertEqual(client.calls[0]['extra_body']['provider']['sort'], 'throughput')

    def test_vertex_maps_stop_to_stop_sequences(self):
        post = FakePost([vertex_payload()])
        self.ask('vertex', post, knobs=knobs_mod.Knobs(stop=['END']))
        self.assertEqual(post.calls[0]['body']['stop_sequences'], ['END'])

    def test_vertex_service_tier_fast_maps_to_speed(self):
        post = FakePost([vertex_payload()])
        self.ask('vertex', post, knobs=knobs_mod.Knobs(service_tier='fast'))
        self.assertEqual(post.calls[0]['body']['speed'], 'fast')

    def test_glm_unsupported_knobs_noted(self):
        client = FakeChat([chat_resp('Owner can read and write.')])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.ask('glm', client, knobs=knobs_mod.Knobs(seed=1, stop=['X']))
        self.assertIn('--seed not supported', err.getvalue())
        self.assertIn('--stop not supported', err.getvalue())

    # ---- builtin knob resolution (unchanged lanes) ----
    def test_resolve_builtin_openai(self):
        wire, notes = knobs_mod.resolve_builtin('openai', knobs_mod.Knobs(temperature=0.3, service_tier='priority'))
        self.assertEqual(wire, {'service_tier': 'priority'})
        self.assertTrue(any('temperature refused' in n for n in notes))

    def test_resolve_builtin_anthropic(self):
        wire, notes = knobs_mod.resolve_builtin('anthropic', knobs_mod.Knobs(stop=['X'], service_tier='auto'))
        self.assertEqual(wire, {'stop_sequences': ['X'], 'service_tier': 'auto'})
        self.assertEqual(notes, [])

    def test_resolve_builtin_anthropic_fast_is_speed(self):
        wire, _ = knobs_mod.resolve_builtin('anthropic', knobs_mod.Knobs(service_tier='fast'))
        self.assertEqual(wire, {'speed': 'fast'})

    def test_image_rejected_on_glm(self):
        client = FakeChat([chat_resp(document())])
        with self.assertRaises(h.HarnessError):
            self.ask('glm', client, attachments=[{'kind': 'image', 'path': '/x', 'sha256': '0', 'size_bytes': 1,
                                                  'media_type': 'image/png'}])


class BothTests(unittest.TestCase):
    def test_select_lanes_explicit_order(self):
        self.assertEqual(both.select_lanes('anthropic,openai'), ['openai', 'anthropic'])

    def test_select_lanes_unknown(self):
        with self.assertRaises(h.HarnessError):
            both.select_lanes('nope')

    def test_both_fan_out(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        self.addCleanup(tmp.cleanup)
        args = NS(lanes='gemini,openai', session=None, no_normalize=True, effort='max', timeout=90,
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
        err = io.StringIO()
        with patch.object(h, 'STATE', root / 'state'), patch.object(h, 'request_reply', fake_reply), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = both.run(args, 'Explain chmod 640.')
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertNotIn('──',text)
        self.assertIn('── openai',err.getvalue())
        self.assertIn('gemini', text)
        self.assertIn('openai', text)
        self.assertIn('Answer from gemini.', text)
        self.assertIn('Answer from openai.', text)
        sessions = {p.name for p in (root / 'state' / 'sessions').glob('*.json')}
        self.assertIn('both-gemini.json', sessions)
        self.assertIn('both-openai.json', sessions)


if __name__ == '__main__':
    unittest.main()
