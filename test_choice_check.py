"""The choice check: an instruction is carried out, not answered with a request for leave.

Permission-asking and trailing offers are rejected and get the gate's one corrective retry.
A question about a missing fact is allowed.
"""
import json
from pathlib import Path
import tempfile
import unittest

import choice_check
import harness as h
from test_harness import FakeClient, document, response

ORDER = 'Delete the temp file in my home folder.'
CONTINUATION = ('Continue the original task using the recorded execution observation. '
                'Return execution_payload null when finished. This is model turn 2 of 5.')

ASKS_LEAVE = [
    'Do you want me to delete the file?',
    'This removes the folder. Should I proceed?',
    'Shall I run it now?',
    'Would you like me to install the package?',
    "The command is ready. Let me know when you'd like me to run it.",
    'I found the log. Want me to open it?',
    'I can restart the service if you want.',
    "If you'd like, I can also clean the cache.",
    'Ready to proceed when you are.',
    'Please confirm and I will send it.',
    'Is it okay if I overwrite the file?',
    'The file is 3 MB. Proceed?',
    'Can I go ahead and push?',
    'Do you want me to proceed, or should I wait?',
    'Should I delete it or not?',
    'How would you like me to proceed?',
    'The folder has two files. What should I do next?',
    "I'll delete it once you confirm.",
    'Would you like a summary of the log?',
    'Awaiting your confirmation.',
    '**Should I proceed?**',
    'Do I have your permission to remove it?',
    'With your approval, the next step removes the folder.',
]
OFFERS_AT_THE_END = [
    'The fix is one line. I can apply it for you.',
    'The log is 40 lines long. I could also remove the old backups.',
    'The folder holds two files. I am ready to delete both.',
    'Next, I can run the cleanup script.',
]
MISSING_FACT_QUESTIONS = [
    'Which file or directory should be deleted?',
    'Which mailbox do you want me to check: Berkeley or Gmail?',
    'Should I use the main branch or the dev branch?',
    'What should I name the file?',
    'Where is the log file?',
    'How many lines should the summary have?',
    'Would you like the Berkeley or the Gmail mailbox?',
    'Can I see the full error text?',
    'Let me know which file you mean.',
    'Two files match. Which one: notes.txt or notes.bak?',
]
PLAIN_CONTENT = [
    'The folder holds two files.',
    'This deletes the temp file.',
    'The script prints "Do you want me to continue?" and waits for input.',
    'The prompt `Should I proceed?` comes from the installer.',
    'apt asks: Do you want to continue? [Y/n]. This command answers yes.',
    'It is unclear whether I should proceed past the failed step; the log shows exit code 2.',
    "I can't reach the laptop: ssh timed out.",
    'I can see two entries in the folder.',
    'I can tell the file is empty from its size.',
    'I could not find the file.',
    'I can find no error in the log.',
    'The log confirms the path, and I see no errors.',
    'I can confirm the file exists and I checked the mode.',
    'This prints setup.sh. It has not run yet.',
]


def reply(answer, payload=None):
    return document(intent='action_request' if payload else 'observation', direct_answer=answer, execution_payload=payload)


class WordingTests(unittest.TestCase):
    def test_permission_asking_is_found(self):
        for answer in ASKS_LEAVE + OFFERS_AT_THE_END:
            with self.subTest(answer=answer):
                self.assertIsNotNone(choice_check.permission_phrase(answer))
                self.assertIn('asks leave', choice_check.violation(answer, ORDER))

    def test_a_question_about_a_missing_fact_is_allowed(self):
        for answer in MISSING_FACT_QUESTIONS:
            with self.subTest(answer=answer):
                self.assertIsNone(choice_check.permission_phrase(answer))
                self.assertIsNone(choice_check.violation(answer, ORDER))

    def test_plain_content_quotes_and_log_text_are_allowed(self):
        for answer in PLAIN_CONTENT:
            with self.subTest(answer=answer):
                self.assertIsNone(choice_check.violation(answer, ORDER))

    def test_the_same_words_separate_by_what_they_ask(self):
        pairs = [
            ('Should I delete it?', 'Should I delete notes.txt or notes.bak?'),
            ('Do you want me to check the mailbox?', 'Which mailbox do you want me to check?'),
            ('Would you like me to rename it?', 'What should I rename it to?'),
            ('Shall I send the report?', 'Who should get the report?'),
            ('Can I go ahead and push?', 'Which branch should I push: main or dev?'),
        ]
        for permission, fact in pairs:
            with self.subTest(permission=permission):
                self.assertIsNotNone(choice_check.violation(permission, ORDER))
                self.assertIsNone(choice_check.violation(fact, ORDER))

    def test_an_offer_counts_only_as_the_last_sentence(self):
        self.assertIsNone(choice_check.violation('I can run it with bash. The command below does that.', ORDER))
        self.assertIsNotNone(choice_check.violation('The command below does that. I can run it with bash.', ORDER))

    def test_orders_are_recognized(self):
        for asked in ('Delete the temp file.', 'so can you please go ahead and check the logs', 'I want the unread count',
                      'run it', 'ok now push it', 'Please list the files', "don't stop", 'give me the show mod command',
                      'yes, do it', "Let's rebase", 'audit device permissions and credentials for local terminal',
                      'The build broke again. Fix it.'):
            with self.subTest(asked=asked):
                self.assertTrue(choice_check.is_instruction(asked))

    def test_questions_and_observations_are_not_orders(self):
        for asked in ('what does chmod 640 mean', 'the tail scale dot on flip is green', 'I think that API key might be missing',
                      "don't run anything, what does show mod six four zero mean", 'is the server up?', 'why did it fail',
                      'Do you know the port?', 'do we have a backup?'):
            with self.subTest(asked=asked):
                self.assertFalse(choice_check.is_instruction(asked))
                self.assertIsNone(choice_check.violation('Do you want me to check?', asked))

    def test_skipped_when_the_operator_asked_to_be_asked(self):
        answer = 'Three files match. Do you want me to delete them?'
        for asked in ('Delete the old logs, but ask me before you delete anything.', 'Clean the folder. Check with me first.',
                      "Find the stale branches. Don't delete anything yet.", 'Show me the plan first, then wait for my go-ahead.',
                      'Explain this command; do not run it.', 'Draft the reply. Do not send it until I say so.'):
            with self.subTest(asked=asked):
                self.assertIsNone(choice_check.violation(answer, asked))
        self.assertIsNotNone(choice_check.violation(answer, "Delete the old logs and don't touch the reports."))

    def test_no_request_means_no_check(self):
        self.assertIsNone(choice_check.violation('Should I proceed?', None))
        self.assertIsNone(choice_check.violation('Should I proceed?', ''))


class GateTests(unittest.TestCase):
    def test_permission_asking_is_rejected_by_the_local_gate(self):
        for answer in ('This removes the file. Should I proceed?', 'Do you want me to delete the file?'):
            with self.subTest(answer=answer), self.assertRaisesRegex(h.GateError, 'asks leave'):
                h.validate_reply(reply(answer), ORDER)

    def test_a_real_clarifying_question_passes_the_local_gate(self):
        out = h.validate_reply(reply('Which file or directory should be deleted?'), 'delete it, that one we were talking about')
        self.assertEqual(out.direct_answer, 'Which file or directory should be deleted?')

    def test_a_command_with_a_permission_question_is_still_rejected(self):
        with self.assertRaisesRegex(h.GateError, 'asks leave'):
            h.validate_reply(reply('This removes the file. Shall I run it?', 'rm -- ~/temp.txt'), ORDER)
        out = h.validate_reply(reply('This removes the file.', 'rm -- ~/temp.txt'), ORDER)
        self.assertEqual(out.execution_payload, 'rm -- ~/temp.txt')

    def test_a_question_is_not_checked_as_an_order(self):
        out = h.validate_reply(reply('It gives the owner read and write access. Do you want me to show an example?'),
                               'what does chmod 640 mean')
        self.assertIn('Do you want me to', out.direct_answer)

    def test_loop_continuation_uses_the_original_task(self):
        with self.assertRaisesRegex(h.GateError, 'asks leave'):
            h.validate_reply(reply('The file holds alpha. Do you want me to delete it?'), CONTINUATION, request_context=ORDER)
        kept = h.validate_reply(reply('The file holds alpha. Do you want me to delete it?'), CONTINUATION,
                                request_context='what is in the temp file?')
        self.assertIn('Do you want me to', kept.direct_answer)

    def test_the_gate_without_a_request_is_unchanged(self):
        self.assertEqual(h.validate_reply(reply('Should I proceed?')).direct_answer, 'Should I proceed?')


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'usage.jsonl'

    def test_one_corrective_retry_replaces_the_permission_question(self):
        client = FakeClient([response(reply('This removes the file. Should I proceed?')),
                             response(reply('This removes the file.', 'rm -- ~/temp.txt'))])
        out = h.request_reply(ORDER, client=client, log_path=self.log)
        self.assertEqual(out.execution_payload, 'rm -- ~/temp.txt')
        self.assertEqual(len(client.calls), 2)
        correction = client.calls[1]['input'][-1]['content']
        self.assertIn('Local validation rejected the reply', correction)
        self.assertIn('asks leave', correction)
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([event['status'] for event in events], ['gate_rejected', 'accepted'])
        self.assertIn('asks leave', events[0]['gate_reason'])

    def test_two_permission_questions_show_nothing(self):
        client = FakeClient([response(reply('Should I proceed?')), response(reply('Shall I run it?'))])
        with self.assertRaisesRegex(h.HarnessError, 'Both replies'):
            h.request_reply(ORDER, client=client, log_path=self.log)
        self.assertEqual(len(client.calls), 2)

    def test_a_clarifying_question_needs_no_retry(self):
        client = FakeClient([response(reply('Which file or directory should be deleted?'))])
        out = h.request_reply('delete it, that one we were talking about', client=client, log_path=self.log)
        self.assertEqual(out.direct_answer, 'Which file or directory should be deleted?')
        self.assertEqual(len(client.calls), 1)


if __name__ == '__main__':
    unittest.main()
