"""Offline checks of gates and real CLI behavior; no network calls or keys."""
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import harness as h


def document(**changes):
    value = dict(intent='observation', cleaned_input='Explain the mode.',
                 direct_answer='The owner can read and write the file.', execution_payload=None)
    value.update(changes)
    return json.dumps(value)


def response(text=None, *, refusal=False, status='completed', cached=0):
    usage = SimpleNamespace(model_dump=lambda **_: {
        'input_tokens': 2100, 'output_tokens': 80,
        'input_tokens_details': {'cached_tokens': cached},
    })
    content = [SimpleNamespace(type='refusal', refusal='Test refusal.')] if refusal else []
    return SimpleNamespace(
        id='offline-fixture', model=h.DEFAULT_MODEL, status=status, usage=usage,
        output=[SimpleNamespace(type='message', content=content)],
        output_text=text if text is not None else document(),
    )


class FakeClient:
    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs)))
        return self.queue.pop(0)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'events.jsonl'
        self.state_patch = patch.object(h, 'STATE', Path(self.tmp.name) / 'state')
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.tmp.cleanup()

    def ask(self, client, raw='Explain the permission mode.', **kwargs):
        return h.request_reply(raw, client=client, log_path=self.log, **kwargs)

    def test_prefix_is_frozen(self):
        self.assertIn('FROZEN PREFIX V4', h.load_prefix())

    def test_changed_prefix_stops_before_api(self):
        client = FakeClient([])
        with patch.object(h, 'PREFIX_SHA256', '0' * 64):
            with self.assertRaisesRegex(h.HarnessError, 'prefix changed'):
                self.ask(client)
        self.assertEqual(client.calls, [])

    def test_schema_has_exact_required_fields(self):
        schema = h.HarnessReply.model_json_schema()
        self.assertEqual(set(schema['required']), {'intent', 'cleaned_input', 'direct_answer', 'execution_payload'})
        self.assertFalse(schema['additionalProperties'])

    def test_observation_cannot_carry_command(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(execution_payload='touch unwanted-file'))

    def test_invalid_intent_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(intent='maybe_execute'))

    def test_extra_fields_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(greeting='Hello'))

    def test_invalid_json_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply('Here is your answer.')

    def test_whitespace_answer_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(direct_answer='   '))

    def test_opening_only_reply_is_not_an_empty_success(self):
        for answer in ['Certainly!', 'Hello George!', 'As an AI,',
                       'The value is 640. I hope this helps.']:
            with self.subTest(answer=answer), self.assertRaises(h.GateError):
                h.validate_reply(document(direct_answer=answer))

    def test_fact_changing_words_are_preserved(self):
        answer = 'The file may be missing; the supplied log does not show its existence.'
        result = h.validate_reply(document(direct_answer=answer))
        self.assertEqual(result.direct_answer, answer)

    def test_false_execution_claim_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(direct_answer='Done. I audited your device.'))

    def test_terminal_escape_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(direct_answer='Result\x1b[2J'))

    def test_empty_command_rejected(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(intent='action_request', execution_payload=' '))

    def test_code_fences_rejected_in_payload(self):
        with self.assertRaises(h.GateError):
            h.validate_reply(document(intent='action_request', execution_payload='```sh\nid\n```'))

    def test_action_command_is_printed_and_never_executed(self):
        target = Path(self.tmp.name) / 'must-not-exist'
        command = f'touch {target}'
        reply = self.ask(FakeClient([response(document(intent='action_request', execution_payload=command))]))
        self.assertIn(command, h.display_text(reply))
        self.assertFalse(target.exists())

    def test_observation_display_is_only_answer(self):
        reply = h.validate_reply(document())
        self.assertEqual(h.display_text(reply), reply.direct_answer + '\n')

    def test_action_display_contains_only_answer_and_payload(self):
        reply = h.validate_reply(document(intent='action_request', direct_answer='This prints your identity.', execution_payload='id'))
        self.assertEqual(h.display_text(reply), 'This prints your identity.\n\nid\n')

    def test_one_retry_replaces_rejected_answer(self):
        client = FakeClient([response(document(intent='invalid_intent')), response()])
        result = self.ask(client)
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn('Certainly', h.display_text(result))
        self.assertEqual(client.calls[0]['input'][0], client.calls[1]['input'][0])

    def test_two_failed_replies_stop(self):
        client = FakeClient([response('bad'), response('bad')])
        with self.assertRaisesRegex(h.HarnessError, 'Both replies'):
            self.ask(client)
        self.assertEqual(len(client.calls), 2)

    def test_refusal_is_reported_and_not_retried(self):
        client = FakeClient([response(refusal=True)])
        with self.assertRaisesRegex(h.HarnessError, 'refused'):
            self.ask(client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(json.loads(self.log.read_text())['status'], 'refusal')

    def test_incomplete_response_is_not_displayed(self):
        with self.assertRaisesRegex(h.HarnessError, 'incomplete'):
            self.ask(FakeClient([response(status='incomplete')]))

    def test_empty_input_never_calls_api(self):
        client = FakeClient([])
        with self.assertRaisesRegex(h.HarnessError, 'empty'):
            self.ask(client, '   ')
        self.assertEqual(client.calls, [])

    def test_oversize_input_never_calls_api(self):
        client = FakeClient([])
        with self.assertRaisesRegex(h.HarnessError, 'exceeds'):
            self.ask(client, 'x' * (h.MAX_INPUT_CHARS + 1))
        self.assertEqual(client.calls, [])

    def test_oversize_whitespace_cannot_hide_truncated_instructions(self):
        client = FakeClient([])
        with self.assertRaisesRegex(h.HarnessError, 'exceeds'):
            self.ask(client, 'Delete the file.' + ' ' * h.MAX_INPUT_CHARS)
        self.assertEqual(client.calls, [])

    def test_identical_prefix_and_schema_across_requests(self):
        client = FakeClient([response(), response(cached=2048)])
        self.ask(client, 'First observation.')
        self.ask(client, 'A different observation.')
        for key in ['text', 'prompt_cache_key', 'model', 'reasoning']:
            self.assertEqual(client.calls[0][key], client.calls[1][key])
        self.assertEqual(client.calls[0]['input'][0], client.calls[1]['input'][0])

    def test_usage_log_has_cache_counts_but_no_prompt_or_reply(self):
        self.ask(FakeClient([response(cached=2048)]), 'UNIQUE_PRIVATE_INPUT_812')
        raw = self.log.read_text()
        data = json.loads(raw)
        self.assertEqual(data['usage']['input_tokens_details']['cached_tokens'], 2048)
        self.assertNotIn('UNIQUE_PRIVATE_INPUT_812', raw)
        self.assertNotIn('The owner can', raw)

    def test_cli_argument_output(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', return_value=h.validate_reply(document())) as ask:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(['Explain', 'the mode.'])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), '')
        self.assertEqual(out.getvalue(), 'The owner can read and write the file.\n')
        self.assertEqual(ask.call_args.args[0], 'Explain the mode.')

    def test_cli_stdin_output(self):
        out = io.StringIO()
        with patch.object(h.sys, 'stdin', io.StringIO('Noisy spoken input')):
            with patch.object(h, 'request_reply', return_value=h.validate_reply(document())) as ask:
                with contextlib.redirect_stdout(out):
                    self.assertEqual(h.main([]), 0)
        self.assertEqual(ask.call_args.args[0], 'Noisy spoken input')

    def test_cli_failure_leaves_stdout_empty(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=h.HarnessError('The model refused this request.')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(['A test input'])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(), 'The model refused this request.\n')

    def test_all_ten_frozen_examples_pass_gate(self):
        examples = [line[8:] for line in h.load_prefix().splitlines() if line.startswith('OUTPUT: ')]
        self.assertEqual(len(examples), 10)
        for raw in examples:
            h.validate_reply(raw)

    def test_missing_key_does_not_print_secret_or_call_api(self):
        with patch.object(h, 'STATE', Path(self.tmp.name)), patch.dict(h.os.environ, {}, clear=True):
            with self.assertRaisesRegex(h.HarnessError, 'Export OPENAI_API_KEY'):
                h.load_key()

    def test_environment_key_takes_priority(self):
        with patch.dict(h.os.environ, {'OPENAI_API_KEY': 'offline-test-key'}):
            self.assertEqual(h.load_key(), 'offline-test-key')

    def test_saved_key_requires_private_permissions(self):
        key = Path(self.tmp.name) / 'api-key'
        key.write_text('offline-test-key\n')
        key.chmod(0o644)
        with patch.object(h, 'STATE', Path(self.tmp.name)), patch.dict(h.os.environ, {}, clear=True):
            with self.assertRaisesRegex(h.HarnessError, 'mode 600'):
                h.load_key()
            key.chmod(0o600)
            self.assertEqual(h.load_key(), 'offline-test-key')

    def test_unexpected_error_keeps_stdout_empty(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(h, 'request_reply', side_effect=TypeError('private debug data')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = h.main(['A test input'])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(), 'Unexpected client error (TypeError).\n')


if __name__ == '__main__':
    unittest.main()
