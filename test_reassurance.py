"""Unrequested reassurance is removed in code; content and requested answers are kept."""
import json
import unittest

import harness as h


def reply(answer, payload=None, intent=None):
    return json.dumps({'intent': intent or ('action_request' if payload else 'observation'),
                       'cleaned_input': 'x', 'direct_answer': answer, 'execution_payload': payload})


TASK = 'Check what files are in the current directory and explain why the setup might fail'


class StripReassuranceTests(unittest.TestCase):
    def test_sentences_seen_in_live_runs_are_removed(self):
        cases = {
            'This command lists every entry in the current directory. It does not change any files. Which setup are you running?':
                'This command lists every entry in the current directory. Which setup are you running?',
            'First step: this prints the current directory. It changes nothing. Possible failures come after the output.':
                'First step: this prints the current directory. Possible failures come after the output.',
            'The project needs a requirements.txt in this directory. I did not change anything.':
                'The project needs a requirements.txt in this directory.',
            'These checks are read-only and do not show any key values:\n1. Search setup.log for error lines.\n2. Show requirements.lock.':
                '1. Search setup.log for error lines.\n2. Show requirements.lock.',
            'This lists the files. Nothing was changed.': 'This lists the files.',
            'This lists the files. No files were modified.': 'This lists the files.',
            'This prints the log tail. It will not modify them.': 'This prints the log tail.',
            'This reports key presence. It does not print the key values.': 'This reports key presence.',
            'This lists the files. The command is read-only.': 'This lists the files.',
            'This lists the files. It is safe to run.': 'This lists the files.',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(h.strip_reassurance(text, TASK), expected)

    def test_trailing_clauses_are_removed_and_the_sentence_survives(self):
        self.assertEqual(
            h.strip_reassurance('This prints the contents of setup.sh and README.txt without changing them.', TASK),
            'This prints the contents of setup.sh and README.txt.')
        self.assertEqual(
            h.strip_reassurance('This lists all files with their permissions, and it does not change any files.', TASK),
            'This lists all files with their permissions.')

    def test_content_that_only_looks_similar_is_kept(self):
        for text in (
            'The file list alone does not show the cause.',
            'It does not show any error.',
            'Restarting does not change the result.',
            'It does not change the outcome of the build.',
            'setup.sh is mode 644, so it is not executable.',
            'I did not check whether pip is installed.',
            'The .env.example file is empty, but setup.sh never uses it.',
            'The mount is read-only, so the write fails with EROFS.',
            'chmod 640 gives the owner read and write access.',
            'No command has run yet, so there is no file listing yet.',
        ):
            with self.subTest(text=text):
                self.assertEqual(h.strip_reassurance(text, TASK), text)

    def test_kept_when_the_operator_asked_about_it(self):
        text = 'This lists the directory entries. It does not change any files.'
        for asked in ("list the files here, don't change any of them", 'is this command safe to run?',
                      'show a read-only check', 'check the key is set but do not print the key'):
            with self.subTest(asked=asked):
                self.assertEqual(h.strip_reassurance(text, asked), text)

    def test_list_structure_and_blank_lines_survive(self):
        text = 'Three causes:\n1. setup.sh has mode 644.\n2. There is no .env file.\n\nNext step: this prints setup.sh.'
        self.assertEqual(h.strip_reassurance(text, TASK), text)


class GateIntegrationTests(unittest.TestCase):
    def test_validate_reply_removes_the_sentence(self):
        out = h.validate_reply(reply('This lists every entry here. It does not change any files.', 'ls -la'), TASK)
        self.assertEqual(out.direct_answer, 'This lists every entry here.')
        self.assertEqual(out.execution_payload, 'ls -la')

    def test_loop_continuation_uses_the_original_task(self):
        continuation = 'Continue the original task using the recorded execution observation. This is model turn 2 of 5.'
        answer = 'The log shows no failure. These checks are read-only.'
        out = h.validate_reply(reply(answer), continuation, request_context=TASK)
        self.assertEqual(out.direct_answer, 'The log shows no failure.')
        kept = h.validate_reply(reply(answer), continuation, request_context='run only read-only checks on the log')
        self.assertEqual(kept.direct_answer, answer)

    def test_answer_that_is_only_reassurance_is_rejected_without_display(self):
        with self.assertRaises(h.OpeningScrubError):
            h.validate_reply(reply('It does not change any files.'), TASK)

    def test_execution_payload_is_never_touched(self):
        payload = "echo 'It does not change any files.'"
        out = h.validate_reply(reply('This prints one line.', payload), TASK)
        self.assertEqual(out.execution_payload, payload)


if __name__ == '__main__':
    unittest.main()
