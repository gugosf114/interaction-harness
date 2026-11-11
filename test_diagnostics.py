"""Regression checks for epistemic wording and persisted API diagnostics."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import harness as h
from storage import Store
from test_harness import document, FakeClient, response


class UncertaintyGateTests(unittest.TestCase):
    def test_factual_uncertainty_survives_unchanged(self):
        answers = [
            'Probably the token expired; inspect the response log.',
            'Maybe the configured port is wrong; the configuration was not supplied.',
            'The request failed. Probably the token expired.',
            'There is no definitive data in the supplied log.',
            'No empirical data covers this device; the sample is missing.',
            'While there is no trace, the cause cannot be determined.',
            'The failure probability is 0.2 under the stated assumptions.',
            'The port and hostname are missing; provide both parameters.',
            'Generally speaking, retries help only for transient errors.',
        ]
        for answer in answers:
            with self.subTest(answer=answer):
                reply = h.validate_reply(document(direct_answer=answer))
                self.assertEqual(reply.direct_answer, answer)
                self.assertEqual(h.display_text(reply), answer+'\n')

    def test_only_opening_filler_is_removed(self):
        examples = {
            'Sure, probably the token expired.': 'probably the token expired.',
            'Certainly! Inspect the log first.': 'Inspect the log first.',
            'Hello George! The port is missing.': 'The port is missing.',
            "You're right, my mistake. Inspect the log.": 'Inspect the log.',
            'I apologize for the confusion. The cause is unknown.': 'The cause is unknown.',
            'As an AI, I need the log to determine the cause.': 'I need the log to determine the cause.',
            'It is important to note that the cause is unknown.': 'the cause is unknown.',
            'This is not legal advice. The deadline is not supplied.': 'The deadline is not supplied.',
            '**Certainly!** The log is missing.': 'The log is missing.',
            'Sure,\n\nMaybe the port is wrong.': 'Maybe the port is wrong.',
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(h.validate_reply(document(direct_answer=raw)).direct_answer, expected)

    def test_empty_filler_is_error_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            client=FakeClient([response(document(direct_answer='Certainly!'))])
            with self.assertRaises(h.OpeningScrubError):
                h.request_reply('Explain.',client=client,log_path=Path(tmp)/'usage.jsonl')
            self.assertEqual(len(client.calls),1)

    def test_uncertainty_needs_no_corrective_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            client=FakeClient([response(document(direct_answer='Probably a timeout; inspect the log.'))])
            h.request_reply('Explain.',client=client,log_path=Path(tmp)/'usage.jsonl')
            self.assertEqual(len(client.calls),1)

    def test_content_that_looks_like_filler_is_kept(self):
        answers = [
            'Certainly not. The mode is 600.',
            'Sure signs of corruption are absent from the log.',
            'Of course not; the key is never printed.',
            'The host is www.hello.com and it answers on port 443.',
            'hello.txt is missing from the folder.',
            'The log is short.\nhello.txt is missing.',
        ]
        for answer in answers:
            with self.subTest(answer=answer):
                self.assertEqual(h.validate_reply(document(direct_answer=answer)).direct_answer, answer)

    def test_apology_agreement_and_praise_openers_are_removed(self):
        examples = {
            "I'm sorry, I can't tell from this log.": "I can't tell from this log.",
            'I am sorry, but the log is incomplete.': 'the log is incomplete.',
            'I apologize, but the cause is unknown.': 'the cause is unknown.',
            'Apologies, the log is incomplete.': 'the log is incomplete.',
            "You're right. The port is 22.": 'The port is 22.',
            'You are absolutely right, the port is 22.': 'the port is 22.',
            "You're right that the port is 22.": 'the port is 22.',
            'Good catch. The port is 22.': 'The port is 22.',
            'Happy to help. The port is 22.': 'The port is 22.',
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(h.validate_reply(document(direct_answer=raw)).direct_answer, expected)

    def test_apology_agreement_and_praise_are_blocked_later_in_the_answer(self):
        for answer in ["The port is 22. I'm sorry.", "The port is 22. You're right.",
                       'The port is 22. Good catch.', 'The port is 22. I hope that clears things up.']:
            with self.subTest(answer=answer), self.assertRaises(h.GateError):
                h.validate_reply(document(direct_answer=answer))

    def test_doubt_about_a_past_action_is_not_a_completion_claim(self):
        answers = [
            'There is no record that I ran that command.',
            'I cannot confirm that I executed anything.',
            'It is unknown whether I deleted the file or it never existed.',
            'No evidence shows I installed the package.',
            'I ran no commands.',
            'The log line reads "I deleted the cache" at 10:02.',
        ]
        for answer in answers:
            with self.subTest(answer=answer):
                self.assertEqual(h.validate_reply(document(direct_answer=answer)).direct_answer, answer)

    def test_completion_claims_need_a_successful_result(self):
        claims = ['Done.', 'Finished.', 'All done.', 'I ran the command and it worked.',
                  'I created the file and verified its contents.', 'I verified the file.',
                  "I've run the audit.", 'I have already installed the package.']
        for claim in claims:
            with self.subTest(claim=claim):
                with self.assertRaises(h.GateError):
                    h.validate_reply(document(direct_answer=claim))
                confirmed = h.validate_reply(document(direct_answer=claim), execution_confirmed=True)
                self.assertEqual(confirmed.direct_answer, claim)

    def test_payload_and_prompt_echo_contract_unchanged(self):
        raw=document(intent='action_request',cleaned_input='Print maybe.',
                     direct_answer='Print maybe.\nSure, this prints literal text.',
                     execution_payload="printf '%s\\n' 'Maybe, sure, probably'")
        reply=h.validate_reply(raw,'Print maybe.')
        self.assertEqual(reply.direct_answer,'this prints literal text.')
        self.assertEqual(reply.execution_payload,"printf '%s\\n' 'Maybe, sure, probably'")


class PersistedMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def finish(self,engine,events):
        store=Store(self.root)
        try:
            idx=store.begin('raw','clean',engine,'test')
            reply=h.validate_reply(document())
            store.finish(idx,reply,events)
            first=dict(store.db.execute('SELECT * FROM history WHERE id=?',(idx,)).fetchone())
            store.finish(idx,reply,events,execution={'approved':False})
            second=dict(store.db.execute('SELECT * FROM history WHERE id=?',(idx,)).fetchone())
            self.assertEqual(first['tokens_used'],second['tokens_used'])
            self.assertEqual(first['latency_ms'],second['latency_ms'])
            return second
        finally:store.close()

    def test_openai_cache_is_subset_of_input(self):
        row=self.finish('openai',[{'engine':'openai','elapsed_ms':120,'usage':{
            'input_tokens':2000,'output_tokens':30,'total_tokens':2030,
            'input_tokens_details':{'cached_tokens':1536}}}])
        self.assertEqual((row['input_tokens'],row['output_tokens'],row['tokens_used']),(2000,30,2030))
        self.assertEqual((row['cache_read_tokens'],row['cache_hit_requests'],row['latency_ms']),(1536,1,120))

    def test_anthropic_cache_is_added_to_uncached_input(self):
        row=self.finish('anthropic',[{'engine':'anthropic','elapsed_ms':210,'usage':{
            'input_tokens':10,'output_tokens':30,'cache_read_input_tokens':1500,'cache_creation_input_tokens':200}}])
        self.assertEqual((row['input_tokens'],row['output_tokens'],row['tokens_used']),(1710,30,1740))
        self.assertEqual((row['cache_creation_tokens'],row['cache_read_tokens']),(200,1500))

    def test_retries_accumulate_metrics_and_latency_once(self):
        row=self.finish('openai',[
            {'elapsed_ms':101,'usage':{'input_tokens':100,'output_tokens':10}},
            {'elapsed_ms':202,'usage':{'input_tokens':120,'output_tokens':20,'input_tokens_details':{'cached_tokens':100}}},
        ])
        self.assertEqual((row['input_tokens'],row['output_tokens'],row['tokens_used'],row['latency_ms']),(220,30,250,303))
        self.assertEqual(row['cache_hit_requests'],1)

    def test_old_database_migrates_without_losing_rows_or_recall(self):
        db=sqlite3.connect(self.root/'history.db')
        db.execute('''CREATE TABLE history(id INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,engine TEXT NOT NULL,
            session_id TEXT,raw_input TEXT NOT NULL,cleaned_input TEXT,intent TEXT,direct_answer TEXT,
            execution_payload TEXT,tokens_used INTEGER NOT NULL DEFAULT 0,cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            normalized_input TEXT,model TEXT,status TEXT NOT NULL DEFAULT 'pending',error TEXT,execution_result TEXT)''')
        db.execute("INSERT INTO history(timestamp,engine,raw_input,direct_answer) VALUES('old','openai','legacy','Saved solution.')")
        db.commit();db.close()
        for _ in range(2):
            store=Store(self.root)
            try:
                row=dict(store.db.execute('SELECT * FROM history WHERE id=1').fetchone())
                self.assertEqual(row['direct_answer'],'Saved solution.')
                self.assertIsNone(row['latency_ms'])
                idx=store.begin('new searchable solution','new','openai','test')
                store.finish(idx,h.validate_reply(document()),[])
                self.assertTrue(store.recall('searchable'))
            finally:store.close()


if __name__=='__main__':unittest.main()
