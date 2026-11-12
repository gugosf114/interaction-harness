"""Small faults the first-page live proof turned up, each pinned by a test.

1. A loop task whose words repeat an earlier task in the same session was sent without its own
   agent_loop record, yet saved with one. The next request then no longer began with the bytes of
   the one before it, and the provider cache missed.
2. An OpenAI web item the installed SDK does not know yet (a weather source of type "api") made the
   SDK print serialization warnings on stderr, on the operator's screen.
3. Every mod ships on, so each live verifier read its test answers aloud on the phone speaker, and
   the lines the mods print around an answer and their usage records broke the verifiers' checks.
   A verifier's own state folder now starts with the four mods around the answer off, and the
   verifiers count model turns only (verify_quiet.py).
4. "what's the weather in Daly City right now" on g1: the hosted lookup ran, but OpenAI's weather
   result carries no web address. The judge saw an empty source list, called the answer an
   unsupported claim twice, and the lane paid for a second full reply. The packet now says how
   many hosted lookups ran (context.web_lookups).
5. On george, a reply that did the work and then shared an idea with its confidence and its catch,
   as the operator's fourth core rule asks and the stamp repeats on every turn, was failed by the
   judge as an "unsolicited warning". The judge cannot see the operator's pages, so its prompt
   now says that such an idea is not an unasked limit.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from typing import Union
import unittest
from unittest.mock import patch

from pydantic import BaseModel

import cli
import harness as h
import senses
from test_harness import FakeClient, document, response


class _Page(BaseModel):
    url: str


class _Find(BaseModel):
    pattern: int


class _Search(BaseModel):
    item: Union[_Page, _Find]


class RepeatedTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        patcher = patch.object(h, 'STATE', self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, text):
        """One --loop run in the same session; returns the messages that were really sent."""
        client = FakeClient([response(document(direct_answer='The answer.'))])
        real = h.request_reply

        def through_fake(*args, **kwargs):
            kwargs.pop('client', None)
            return real(*args, client=client, **kwargs)
        with patch.object(h, 'request_reply', side_effect=through_fake), patch.object(h, 'load_tools', return_value=None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = h.main(['--usage-log', str(Path(self.tmp.name) / 'usage.jsonl'), '--no-web', '--loop', '--session', 'same', text])
        self.assertEqual(code, 0)
        return client.calls[0]['input'][1:]  # without the frozen first page

    def test_the_same_task_typed_twice_keeps_each_request_a_prefix_of_the_next(self):
        first, second, third = self.ask('continue'), self.ask('continue'), self.ask('continue')
        record = json.dumps({'client_mode': 'agent_loop', 'original_task': 'continue', 'max_turns': 200})
        self.assertEqual([m['content'] for m in first], [record, 'continue'])
        self.assertEqual(sum(m['content'] == record for m in second), 2, 'the second task brings its own record')
        self.assertEqual(sum(m['content'] == record for m in third), 3)
        self.assertEqual(second[:len(first)], first)
        self.assertEqual(third[:len(second)], second)

    def test_a_later_step_of_one_task_does_not_repeat_its_record(self):
        answers = [h.validate_reply(document(intent='action_request', direct_answer='This runs the step.', execution_payload='true')),
                   h.validate_reply(document(direct_answer='The step exited 0.'), execution_confirmed=True)]
        client = FakeClient([response(json.dumps(a.model_dump())) for a in answers])
        real = h.request_reply

        def through_fake(*args, **kwargs):
            kwargs.pop('client', None)
            return real(*args, client=client, **kwargs)
        result = dict(approved=True, stdout='', stderr='', exit_code=0)
        with patch.object(h, 'request_reply', side_effect=through_fake), patch.object(h, 'load_tools', return_value=None), \
                patch.object(cli, 'native', side_effect=[result]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = h.main(['--usage-log', str(Path(self.tmp.name) / 'usage.jsonl'), '--no-web', '--loop', '--session', 'one', 'Run the step.'])
        self.assertEqual(code, 0)
        second = client.calls[1]['input']
        self.assertEqual(sum('"client_mode": "agent_loop"' in m['content'] for m in second if m['role'] == 'user'), 1)
        self.assertEqual(second[:len(client.calls[0]['input'])], client.calls[0]['input'])


class QuietDumpTests(unittest.TestCase):
    def test_a_provider_object_is_dumped_without_sdk_warnings(self):
        seen = {}

        class Item:
            def model_dump(self, **kwargs):
                seen.update(kwargs)
                return {'type': 'web_search_call'}
        self.assertEqual(senses.dump(Item()), {'type': 'web_search_call'})
        self.assertEqual(seen, {'exclude_none': True, 'warnings': False})

    def test_an_item_the_installed_sdk_does_not_know_prints_nothing(self):
        """An item of a kind the model's field does not declare: pydantic warns, the dump stays silent."""
        import warnings
        odd = _Search.model_construct(item='oai-weather')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            odd.model_dump(exclude_none=True)
        self.assertTrue(caught, 'this is the warning the fix keeps off the screen')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self.assertEqual(senses.dump(odd), {'item': 'oai-weather'})
        self.assertEqual(caught, [])


class JudgeSeesLookupsTests(unittest.TestCase):
    def packet(self, metadata):
        import reply_judge
        reply = h.validate_reply(document(direct_answer='It is clear and 57 degrees there now.'))
        return json.loads(reply_judge.build_packet(request="what's the weather right now", reply=reply, earlier=[], metadata=metadata,
                                                   loop=False, step=1, earlier_conversation=False, attachments=0, removed=[]))

    def test_a_lookup_that_returned_no_address_is_still_counted_for_the_judge(self):
        context = self.packet({'sources': [], 'lookup_counts': {'total': 1, 'search': 1, 'fetch': 0, 'find': 0}})['context']
        self.assertEqual(context['web_sources'], [])
        self.assertEqual(context['web_lookups'], 1)

    def test_no_lookup_is_zero_and_addresses_are_still_listed(self):
        self.assertEqual(self.packet({})['context']['web_lookups'], 0)
        context = self.packet({'sources': [{'url': 'https://example.com/a', 'title': 'A'}], 'lookup_counts': {'total': 2}})['context']
        self.assertEqual((context['web_sources'], context['web_lookups']), (['https://example.com/a'], 2))

    def test_the_judge_is_told_what_the_count_means(self):
        import reply_judge
        self.assertIn('context.web_lookups counts the hosted lookups of this turn', reply_judge.SYSTEM_PROMPT)
        self.assertIn('can return no address', reply_judge.SYSTEM_PROMPT)
        self.assertIn('A statement that could rest on one of those is not an unsupported claim.', reply_judge.SYSTEM_PROMPT)


class JudgeKnowsTheIdeaRuleTests(unittest.TestCase):
    def test_an_idea_with_its_confidence_and_catch_is_not_an_unasked_limit(self):
        import reply_judge
        prompt = reply_judge.SYSTEM_PROMPT
        self.assertIn("share a useful idea after the answer, with its confidence and its main catch", prompt)
        self.assertIn('is not an unasked limit, warning or question, and its catch is not a warning', prompt)
        # The rule it mirrors is the fourth headline the stamp carries; the judge still fails a real unasked limit.
        self.assertIn('3. Unasked limit.', prompt)
        self.assertLess(prompt.index('3. Unasked limit.'), prompt.index('share a useful idea after the answer'))


class QuietVerifierTests(unittest.TestCase):
    def test_a_verifier_state_folder_starts_with_the_four_mods_around_the_answer_off(self):
        import mod_switches
        from verify_quiet import AROUND_THE_ANSWER, quiet
        self.assertEqual(AROUND_THE_ANSWER, ('voice', 'proof', 'tree', 'narrator'))
        with tempfile.TemporaryDirectory() as tmp:
            runtime = quiet(Path(tmp) / 'runtime')
            for name in mod_switches.MODS:
                self.assertEqual(mod_switches.is_on(name, runtime), name not in AROUND_THE_ANSWER, name)
            for kept in ('length', 'plain-words', 'receipts', 'no-background', 'undertaker'):
                self.assertTrue(mod_switches.is_on(kept, runtime), kept)

    def test_an_existing_switch_file_is_left_as_it_is(self):
        from verify_quiet import quiet
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / 'runtime'
            runtime.mkdir()
            (runtime / 'mods.json').write_text('{"voice": true}\n')
            quiet(runtime)
            self.assertEqual(json.loads((runtime / 'mods.json').read_text()), {'voice': True})

    def test_only_model_turns_are_counted_in_the_usage_log(self):
        from verify_quiet import turn_events
        turn = {'status': 'accepted', 'model_returned': 'gpt-6.1-sol', 'effort': 'max'}
        log = [{'kind': 'recall', 'status': 'attached'}, turn, {'kind': 'mod:proof', 'model_returned': 'gpt-6-luna'},
               {'kind': 'mod:tree', 'model_returned': 'gpt-6-luna'}]
        self.assertEqual(turn_events(log), [turn])
        self.assertEqual(turn_events([]), [])

    def test_the_line_of_a_bounced_answer_check_is_not_an_error_and_not_part_of_the_answer(self):
        from verify_quiet import without_check_lines
        self.assertEqual(without_check_lines('answer check: answer too long - asked again\n'), '')
        self.assertEqual(without_check_lines('answer check: plain words - asked again\r\nThe answer.\r\n\r\necho hi\r\n'),
                         'The answer.\n\necho hi\n')
        self.assertEqual(without_check_lines('The API connection failed.\n'), 'The API connection failed.\n')
        # The exact line harness.py prints when a check bounces an answer.
        self.assertIn("print('answer check: '+soft.split(' - ',1)[0]+' - asked again',file=sys.stderr,flush=True)",
                      (h.ROOT / 'harness.py').read_text(encoding='utf-8'))

    def test_all_five_live_verifiers_use_it(self):
        for name in ('verify_live.py', 'verify_loop.py', 'verify_repl.py', 'verify_smoke.py', 'verify_senses.py'):
            source = (h.ROOT / name).read_text(encoding='utf-8')
            self.assertIn('from verify_quiet import quiet', source, name)
            self.assertIn("quiet(folder/'runtime')", source, name)
        for name in ('verify_live.py', 'verify_repl.py', 'verify_smoke.py', 'verify_senses.py'):
            self.assertIn('turn_events(', (h.ROOT / name).read_text(encoding='utf-8'), name)


if __name__ == '__main__':
    unittest.main()
