"""Habits written as code (habit_checks.py). A lane that adds a sentence or a check adds its test here."""
import json
import unittest

import gate_rules
import habit_checks
import harness as h


def shown(answer, asked=None):
    """What the gate shows for this answer."""
    raw = json.dumps({'intent': 'observation', 'cleaned_input': 'x', 'direct_answer': answer, 'execution_payload': None})
    return h.validate_reply(raw, asked).direct_answer


class ShippedListTests(unittest.TestCase):
    def test_every_listed_sentence_is_cut_and_the_rest_of_the_answer_stays(self):
        for sentence in habit_checks.CUT_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertEqual(shown('The mode is 640. ' + sentence), 'The mode is 640.')

    def test_every_listed_sentence_is_a_whole_sentence_listed_once(self):
        plain = [habit_checks.plain(sentence) for sentence in habit_checks.CUT_SENTENCES]
        self.assertEqual(len(plain), len(set(plain)))
        for sentence in habit_checks.CUT_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertEqual(len(gate_rules.sentences(sentence)), 1)
                self.assertGreaterEqual(len(sentence.split()), 2)

    def test_no_listed_sentence_is_a_known_good_sentence(self):
        listed = {habit_checks.plain(sentence) for sentence in habit_checks.CUT_SENTENCES}
        for sentence in gate_rules.known_good():
            self.assertNotIn(habit_checks.plain(sentence), listed)

    def test_every_check_is_a_function_that_passes_a_plain_answer(self):
        for check in habit_checks.CHECKS:
            with self.subTest(check=getattr(check, '__name__', 'check')):
                self.assertTrue(callable(check))
                self.assertIsNone(check('The owner can read and write the file.', 'what does chmod 640 mean'))


# Tests for single sentences and checks go below, one test per addition.


class LetMeKnowHowItGoesTests(unittest.TestCase):
    def test_let_me_know_how_it_goes_is_listed_and_cut(self):
        listed = {habit_checks.plain(sentence) for sentence in habit_checks.CUT_SENTENCES}
        self.assertIn(habit_checks.plain('Let me know how it goes.'), listed)
        self.assertEqual(shown('The mode is 640. Let me know how it goes.'), 'The mode is 640.')
        self.assertEqual(shown('The mode is 640. **let me know how it goes.**'), 'The mode is 640.')


if __name__ == '__main__':
    unittest.main()
