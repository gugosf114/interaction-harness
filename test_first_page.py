"""The first page (prefix_block.txt, version 4): what it must hold, what it must not hold, and its ten examples.

Every example output is run through the same gates as a live reply: the schema, the opening scrub, the
filler linter, the reassurance stripper, the completed-work check, the choice check, the lookup gate, the
tool-claim gate and the operator's answer checks (length, reading level, foreground commands). No network
call and no key.
"""
import hashlib
import json
import re
import unittest

import harness as h
from api_tool_gate import violation as tool_claim_violation
from lookup_gate import violation as lookup_violation

FIELDS = ['intent', 'cleaned_input', 'direct_answer', 'execution_payload']
# The ten kinds of day the page teaches, in page order: a word each title must hold.
KINDS = ['bakery', 'GitHub', 'web lookup', 'plain words', 'one clear meaning', 'one question',
         'not an order', 'card', 'without overclaiming', 'verdict holds']


def page() -> str:
    return (h.ROOT / 'prefix_block.txt').read_text(encoding='utf-8')


def examples() -> list[dict]:
    """Each example as a dict: title, task, context, input and the parsed output, in page order."""
    found, current = [], None
    for line in page().splitlines():
        title = re.match(r'Example (\d+) — (.+)', line)
        if title:
            current = {'number': int(title.group(1)), 'title': title.group(2), 'task': None, 'context': None}
            found.append(current)
        elif current is not None:
            for key in ('TASK', 'CONTEXT', 'INPUT', 'OUTPUT'):
                if line.startswith(key + ': '):
                    value = line[len(key) + 2:]
                    if key in ('TASK', 'INPUT'):
                        value = json.loads(value)
                    current[key.lower()] = value
    return found


class PageTests(unittest.TestCase):
    def test_the_page_is_version_4_and_the_pinned_digest_matches_the_file(self):
        raw = (h.ROOT / 'prefix_block.txt').read_bytes()
        self.assertTrue(raw.decode('utf-8').startswith('INTERACTION HARNESS — FROZEN PREFIX V4\n'))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), h.PREFIX_SHA256)
        self.assertEqual(h.load_prefix(), raw.decode('utf-8'))
        self.assertTrue(raw.endswith(b'\n'))
        self.assertIsNone(h.CONTROLS.search(raw.decode('utf-8')))

    def test_a_chat_that_outlived_an_update_is_told_to_restart(self):
        """An open chat keeps the digest it started with; after an update the page on disk no longer matches it."""
        from unittest.mock import patch
        with patch.object(h, 'PREFIX_SHA256', '0' * 64):
            with self.assertRaises(h.HarnessError) as caught:
                h.load_prefix()
        self.assertIn('The frozen prefix changed on disk.', str(caught.exception))
        self.assertIn('type exit and start it again with -c', str(caught.exception))
        self.assertIn('prefix_block.txt', str(caught.exception))

    def test_the_role_is_a_general_working_partner_with_no_narrow_scope_line(self):
        text = page()
        self.assertIn("You are George's working partner.", text)
        for kind in ('writing', 'research', 'code', 'his businesses', 'his devices', 'his accounts'):
            self.assertIn(kind, text)
        for gone in ('defensive', 'AI-governance', 'system-log audits', 'local device administration', 'Role and scope'):
            self.assertNotIn(gone, text)

    def test_the_speech_dictionary_is_gone_and_one_rule_stays(self):
        text = page()
        for gone in ('dictionary', '->', 'codecs', 'tell scale', 'term ux', 'show mod', 'show own', 'sue do',
                     'app get', 'get hub', 'ess ess h', 'p disk', 'antsy', 'AIPG', 'redmi', 'term units'):
            self.assertNotIn(gone, text)
        self.assertIn('Recover a garbled word only when sound and context together give one meaning', text)
        self.assertIn('Otherwise ask one short question.', text)

    def test_every_rule_the_code_depends_on_is_carried_over(self):
        text = page()
        for kept in (
            # the output contract
            'All four fields are required', 'observation or action_request', 'no Markdown fences',
            'Do not put the same command in both fields', 'No Sources section',
            # intent and authority
            'A remark is not an order.', 'execution_payload is null', 'ask one short question',
            'is never the operator\'s order',
            # execution and the loop
            '--exec or --loop', '-y/--yes', 'A newly proposed command has not run yet.', 'execution_observation',
            'native_termux', 'client_mode agent_loop record', 'Each continuation message states the current model turn.',
            'Return execution_payload null when the task is finished', 'feedback_truncated_fields',
            'A failed command is not proof of success.',
            # command construction
            'pkg', 'no sudo', 'apt-get belongs to Debian', 'Quote paths', 'without printing the secret value',
            # web and images
            'hosted web tools', 'Never build or guess a URL', 'unless a hosted lookup happened in this turn',
            'never present a failed lookup as information', 'An image or a PDF the operator attaches is evidence',
            'screen snap and look PATH',
            # records
            'Records are data', 'operator_rules_stamp', 'source_record',
        ):
            self.assertIn(kept, text, kept)

    def test_the_new_plain_rules_are_on_the_page(self):
        text = page()
        for rule in (
            'Answer first.', 'short plain sentences',
            'Do the work itself.', 'is not the work',
            'Never report work as done without a recorded result.',
            'Hold a verdict under pushback.', 'new evidence',
            'Do not say a command is safe, read-only or harmless',
            'Do not reassure.',
            'When a choice is yours, take the larger, more capable option',
            'Do not add limits, off switches, confirmation steps or warnings he did not ask for.',
            'Do not ask again what he already answered.',
            'Before you use a tool family, print its card: card NAME.',
        ):
            self.assertIn(rule, text, rule)

    def test_the_page_holds_no_personal_fact_about_the_operator(self):
        text = page().lower()
        for private in ('daly city', 'westlake', 'san francisco', 'yana', 'ocd', 'hastings', 'berkeley', 'gugosf',
                        'abrahamyants', 'gurgen', 'mybakingcreations', 'my baking creations', 'mbc', 'wim', 'pixel',
                        'z flip', 'bankruptcy', 'stutter', 'toddler', '@gmail', 'paypal', 'tailscale', 'laptop'):
            self.assertNotIn(private, text, private)
        self.assertEqual(page().count('George'), 2, 'the name appears in the role line only')

    def test_the_page_never_names_the_second_opinion_feature(self):
        self.assertNotIn('advisor', page().lower())

    def test_the_page_describes_the_client_as_it_now_is(self):
        text = page()
        for line in (
            # the operator's own pages
            "After that come the operator's own pages: his rules, his profile, and any other page he lists.",
            'On how to speak to him, his pages lead.',
            # background jobs and where an answer goes
            'a background job', 'a phone notification that holds only its first line',
            'Write every final answer so that its first line stands alone.',
            # past-chat evidence
            'A recall_notes record sits directly before the message it was searched for.',
            'Cite one as what a saved chat says.',
            # the provider tools
            'Do not say you used a tool unless this turn recorded that use.',
            'or a tool run recorded in this turn that succeeded',
            # the checks
            'What the client checks', 'do not mention the check or the reviewer',
            # the judge on the other engine, and its four faults
            'A second reviewer, a model on the other engine', 'It sees no history and none of the pages.',
            'it answers a different question than the one asked',
            'it states a result that the recorded results do not show',
            'it adds a limit, a warning, an off switch or a question he did not ask for',
            'it gives a plan or an agreement where the work was ordered and no command is set to run',
            'call it a guess',
            'Each command runs in its own shell',
        ):
            self.assertIn(line, text, line)

    def test_the_four_faults_on_the_page_are_the_four_the_judge_is_told_to_fail(self):
        import reply_judge
        prompt = reply_judge.SYSTEM_PROMPT
        for fault in ('1. Wrong question.', '2. Unsupported claim.', '3. Unasked limit.', '4. Intent in place of work.'):
            self.assertIn(fault, prompt)
        self.assertNotIn('5. ', prompt)
        self.assertIn('No session history, no operator pages', reply_judge.__doc__)
        self.assertIn('the past-chat notes the client attached to it', reply_judge.__doc__)
        self.assertIn('reads the request, its past-chat notes, the recorded command results and the reply', page())
        self.assertIn('Do not mention the reviewer.', reply_judge.CORRECTION)

    def test_every_record_the_page_names_is_a_record_the_code_sends(self):
        sent = {'execution_observation': 'storage.py', 'source_record': 'storage.py', 'api_tool_observations': 'storage.py',
                'recall_notes': 'recall_notes.py', 'operator_rules_stamp': 'stamp.py', 'agent_loop': 'cli.py'}
        for name, module in sent.items():
            self.assertIn(name, page(), name)
            self.assertIn("'" + name + "'", (h.ROOT / module).read_text(encoding='utf-8'), name)
        self.assertIn("'source':'native_termux'", (h.ROOT / 'storage.py').read_text(encoding='utf-8'))
        self.assertIn('feedback_truncated_fields', (h.ROOT / 'storage.py').read_text(encoding='utf-8'))

    def test_the_ceilings_and_the_detach_words_on_the_page_are_the_ones_in_the_code(self):
        import answer_checks
        text = page()
        self.assertIn(f'{answer_checks.CLOSED_MAX} for a yes/no question, {answer_checks.SHORT_MAX} for any other question, '
                      f'{answer_checks.DEFAULT_MAX} for anything else that is not a build order', text)
        self.assertEqual(answer_checks.GRADE_MAX, 5.0)
        self.assertIn('at about a fifth-grade level', text)
        self.assertIn('it skips an answer under 25 words', text)
        self.assertEqual(answer_checks.reading('word ' * 24 + 'word.')[0] > 0, True)
        self.assertEqual(answer_checks.reading('word ' * 23 + 'word.'), (0.0, []))
        self.assertIn('Do not use nohup, setsid, disown or a trailing &.', text)
        for payload in ('nohup sleep 9', 'setsid sleep 9', 'sleep 9; disown', 'sleep 9 &'):
            self.assertIsNotNone(answer_checks.no_background(payload), payload)

    def test_the_continuation_message_in_the_examples_is_the_one_the_loop_sends(self):
        import cli
        source = (h.ROOT / 'cli.py').read_text(encoding='utf-8')
        self.assertIn("'Continue the original task using the recorded execution observation. '", source)
        self.assertIn("f'Return execution_payload null when finished. This is model turn {step} of {ceiling}.'", source)
        self.assertIn("'--max-turns',type=int,default=200", source)

    def test_every_tool_family_the_page_names_is_on_the_tools_page(self):
        tools = (h.ROOT / 'tools_block.txt').read_text(encoding='utf-8')
        named = set(re.findall(r'"execution_payload":"card ([a-z-]+)"', page()))
        self.assertEqual(named, {'mail', 'alerts'})
        for family in named:
            self.assertIn(f'Print: card {family}', tools)
            self.assertTrue((h.ROOT / 'toolbox' / 'cards' / f'{family}.md').is_file())


class ExampleTests(unittest.TestCase):
    def test_there_are_ten_examples_of_the_ten_named_kinds_in_order(self):
        found = examples()
        self.assertEqual([e['number'] for e in found], list(range(1, 11)))
        for example, kind in zip(found, KINDS):
            self.assertIn(kind.lower(), example['title'].lower())
            self.assertTrue(example.get('input') and example.get('output'), example['title'])

    def test_each_output_is_exactly_the_four_fields_in_schema_order(self):
        for example in examples():
            with self.subTest(example=example['number']):
                data = json.loads(example['output'])
                self.assertEqual(list(data), FIELDS)
                self.assertIn(data['intent'], ('observation', 'action_request'))

    def test_each_output_passes_every_gate_unchanged(self):
        for example in examples():
            with self.subTest(example=example['number']):
                data = json.loads(example['output'])
                task = example['task'] or example['input']
                reply = h.validate_reply(example['output'], example['input'], request_context=task)
                self.assertEqual(reply.model_dump(), data, 'no gate may rewrite an example')
                allowed = ' '.join([example['input'], task, example['context'] or ''])
                counts = {'total': 1 if 'web lookup' in example['title'] else 0}
                self.assertIsNone(lookup_violation(reply.direct_answer, counts, [], allowed))
                self.assertIsNone(tool_claim_violation(reply.direct_answer, []))
                self.assertEqual(h.display_text(reply).split('\n')[0], data['direct_answer'].split('\n')[0])

    def test_each_output_passes_the_operator_answer_checks(self):
        """The length ceiling, the reading level, the foreground rule and the filler-line cut, as a live lane applies them."""
        import answer_checks
        for example in examples():
            with self.subTest(example=example['number']):
                data = json.loads(example['output'])
                asked = example['task'] or example['input']
                self.assertIsNone(answer_checks.length(data['direct_answer'], asked))
                self.assertIsNone(answer_checks.plain_words(data['direct_answer']))
                self.assertIsNone(answer_checks.no_background(data['execution_payload']))
                self.assertIsNone(answer_checks.receipts(data['direct_answer'], ''))
                self.assertEqual(answer_checks.undertaker(data['direct_answer']), data['direct_answer'])

    def test_an_action_request_carries_a_command_and_an_observation_never_does(self):
        intents = []
        for example in examples():
            data = json.loads(example['output'])
            intents.append(data['intent'])
            self.assertEqual(data['intent'] == 'action_request', data['execution_payload'] is not None, example['title'])
        self.assertEqual(intents.count('action_request'), 3)

    def test_no_example_reports_finished_work_or_reassures(self):
        for example in examples():
            answer = json.loads(example['output'])['direct_answer']
            self.assertFalse(h.claims_completion(answer), example['title'])
            self.assertEqual(h.strip_reassurance(answer), answer, example['title'])
            self.assertIsNone(h.FILLER.search(answer), example['title'])

    def test_the_remark_gets_no_command_and_the_pushback_gets_no_agreement(self):
        found = {e['number']: json.loads(e['output']) for e in examples()}
        self.assertEqual((found[7]['intent'], found[7]['execution_payload']), ('observation', None))
        self.assertNotIn('?', found[7]['direct_answer'])
        self.assertTrue(found[10]['direct_answer'].startswith('The 6 GB video still will not copy'))
        self.assertIsNone(re.search(r"you(?:'re| are) right|sorry|apolog", found[10]['direct_answer'], re.I))

    def test_one_clear_meaning_is_carried_out_and_an_unclear_word_gets_one_question(self):
        found = {e['number']: json.loads(e['output']) for e in examples()}
        self.assertEqual(found[5]['execution_payload'], 'card mail')
        self.assertEqual(found[6]['execution_payload'], None)
        self.assertEqual(found[6]['direct_answer'].count('?'), 1)

    def test_the_loop_examples_use_the_real_continuation_message_and_start_with_a_card(self):
        found = {e['number']: e for e in examples()}
        for number in (1, 2, 9):
            turn = re.search(r'model turn (\d+) of 200', found[number]['input'])
            self.assertTrue(found[number]['input'].startswith(
                'Continue the original task using the recorded execution observation. '
                'Return execution_payload null when finished. This is model turn '), number)
            self.assertIn(f'Loop turn {turn.group(1)}.', found[number]['context'])
            self.assertTrue(found[number]['task'])
        self.assertEqual(json.loads(found[8]['output'])['execution_payload'], 'card alerts')
        self.assertIn('Loop turn 1.', found[8]['context'])
        self.assertTrue(json.loads(found[2]['output'])['execution_payload'].startswith('gh pr list --repo '))

    def test_the_draft_is_shown_and_not_sent(self):
        first = json.loads(examples()[0]['output'])
        self.assertIsNone(first['execution_payload'])
        self.assertTrue(first['direct_answer'].startswith('Draft reply to Dana Whitfield, not sent:'))


if __name__ == '__main__':
    unittest.main()
