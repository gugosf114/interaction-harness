"""Operator pages: read at run time from the operator's own files, sent after the tools page, never logged.

No test here reads the installation's real state/pages.json. Every test points the page list at a
temporary folder, and a plain import leaves the page list off.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import harness as h
import pages
from test_harness import FakeClient, response
from test_tools_block import AnthropicFake

RULES_FILE = """# Operating rules

Intro line that is not in any section.

## Core rules

1. **Clarify first.** Ask when unclear. PRIVATE-RULES-MARK-71
2. Answer first — short sentences.

### A sub-heading stays inside its section

Still the core section.

## Tools the harness lacks

Skip this section. PRIVATE-SKIPPED-MARK-55

## Evidence

Never invent a result.
"""
PROFILE_FILE = "---\nname: who\n---\n\n# Who\n\nLives somewhere. PRIVATE-PROFILE-MARK-93\n"
CORE = ('## Core rules\n\n1. **Clarify first.** Ask when unclear. PRIVATE-RULES-MARK-71\n'
        '2. Answer first — short sentences.\n\n### A sub-heading stays inside its section\n\nStill the core section.')
EVIDENCE = '## Evidence\n\nNever invent a result.'


class PageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules = self.root / 'rules.md'
        self.rules.write_text(RULES_FILE, encoding='utf-8')
        self.profile = self.root / 'profile.md'
        self.profile.write_text(PROFILE_FILE, encoding='utf-8')
        self.list = self.root / 'state' / 'pages.json'
        self.list.parent.mkdir()
        self.log = self.root / 'usage.jsonl'

    def wire(self, entries):
        self.list.write_text(entries if isinstance(entries, str) else json.dumps(entries), encoding='utf-8')

    def two_pages(self):
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Core rules', '## Evidence']},
                   {'label': 'profile', 'path': str(self.profile)}])

    def ask(self, engine='openai', tools='TOOLS PAGE', listed=True):
        client = FakeClient([response()]) if engine == 'openai' else AnthropicFake()
        with patch.object(h, 'PAGES_FILE', self.list if listed else None), patch.object(h, 'load_tools', return_value=tools):
            h.request_reply('Explain chmod 640.', client=client, engine=engine, log_path=self.log)
        return client.calls[0]

    def refused(self, pattern):
        client = FakeClient([])
        with patch.object(h, 'PAGES_FILE', self.list), patch.object(h, 'load_tools', return_value='TOOLS PAGE'):
            with self.assertRaisesRegex(h.HarnessError, pattern):
                h.request_reply('Explain chmod 640.', client=client, log_path=self.log)
        self.assertEqual(client.calls, [], 'the API must not be called')


class ReadingTests(PageCase):
    def test_a_plain_import_leaves_the_page_list_off(self):
        self.assertIsNone(h.PAGES_FILE)
        self.assertEqual(h.load_pages(), [])

    def test_missing_empty_or_blank_list_sends_nothing_extra(self):
        baseline = {engine: self.ask(engine, listed=False) for engine in ('openai', 'anthropic')}
        for content in (None, '', '  \n', '[]'):
            if content is None:
                self.list.unlink(missing_ok=True)
            else:
                self.wire(content)
            for engine in ('openai', 'anthropic'):
                with self.subTest(content=content, engine=engine):
                    self.assertEqual(self.ask(engine), baseline[engine])

    def test_whole_file_page_is_sent_word_for_word(self):
        self.wire([{'label': 'profile', 'path': str(self.profile)}])
        page, = pages.read_pages(self.list)
        self.assertEqual(page.label, 'profile')
        self.assertEqual(page.text, PROFILE_FILE.strip())
        self.assertEqual(page.sha256, hashlib.sha256(PROFILE_FILE.strip().encode('utf-8')).hexdigest())

    def test_section_page_takes_only_the_named_sections_in_listed_order(self):
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Core rules', '## Evidence']}])
        page, = pages.read_pages(self.list)
        self.assertEqual(page.text, CORE + '\n\n' + EVIDENCE)
        self.assertNotIn('PRIVATE-SKIPPED-MARK-55', page.text)
        self.assertNotIn('Intro line', page.text)
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Evidence', '## Core rules']}])
        page, = pages.read_pages(self.list)
        self.assertEqual(page.text, EVIDENCE + '\n' + CORE)

    def test_a_section_runs_to_the_end_of_a_file_that_has_no_final_newline(self):
        self.rules.write_text('## One\n\nfirst\n\n## Two\n\nlast line', encoding='utf-8')
        self.wire([{'label': 'r', 'path': str(self.rules), 'sections': ['## Two', '## One']}])
        page, = pages.read_pages(self.list)
        self.assertEqual(page.text, '## Two\n\nlast line\n## One\n\nfirst')


class LimitTests(PageCase):
    def test_missing_file_stops_before_the_api(self):
        self.wire([{'label': 'ghost', 'path': str(self.root / 'absent.md')}])
        self.refused('Page "ghost": the file is missing or unreadable')

    def test_missing_heading_stops_before_the_api(self):
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Core rules', '## Not there']}])
        self.refused('Page "rules": heading not found: ## Not there')

    def test_heading_must_match_the_whole_line(self):
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Core']}])
        self.refused('heading not found: ## Core')

    def test_repeated_heading_stops_before_the_api(self):
        self.rules.write_text('## Same\n\na\n\n## Same\n\nb\n', encoding='utf-8')
        self.wire([{'label': 'rules', 'path': str(self.rules), 'sections': ['## Same']}])
        self.refused('heading appears more than once: ## Same')

    def test_oversize_page_is_refused_and_never_cut(self):
        self.profile.write_text('x' * pages.MAX_PAGE_CHARS, encoding='utf-8')
        self.wire([{'label': 'profile', 'path': str(self.profile)}])
        self.assertEqual(len(pages.read_pages(self.list)[0].text), pages.MAX_PAGE_CHARS)
        self.profile.write_text('x' * (pages.MAX_PAGE_CHARS + 1), encoding='utf-8')
        self.refused('Page "profile" exceeds 20000 characters')

    def test_combined_cap_is_refused_and_never_cut(self):
        entries = []
        for name in ('a', 'b', 'c'):
            path = self.root / (name + '.md')
            path.write_text(name * pages.MAX_PAGE_CHARS if name != 'c' else 'c', encoding='utf-8')
            entries.append({'label': name, 'path': str(path)})
        self.wire(entries[:2])
        self.assertEqual(sum(len(page.text) for page in pages.read_pages(self.list)), pages.MAX_TOTAL_CHARS)
        self.wire(entries)
        self.refused('The extra pages together exceed 40000 characters')

    def test_control_characters_are_refused(self):
        self.profile.write_text('fine text \x1b[31m red', encoding='utf-8')
        self.wire([{'label': 'profile', 'path': str(self.profile)}])
        self.refused('Page "profile" contains control characters')

    def test_empty_page_is_refused(self):
        self.profile.write_text(' \n\n', encoding='utf-8')
        self.wire([{'label': 'profile', 'path': str(self.profile)}])
        self.refused('Page "profile" is empty')

    def test_malformed_lists_are_refused(self):
        good = {'label': 'p', 'path': str(self.profile)}
        cases = {
            '{not json': 'not valid JSON',
            json.dumps({'pages': [good]}): 'must be a JSON list',
            json.dumps([{**good, 'section': ['## Who']}]): 'entry 1 may hold only label, path and sections',
            json.dumps(['just a string']): 'entry 1 may hold only',
            json.dumps([{'path': str(self.profile)}]): 'entry 1 needs a label',
            json.dumps([{**good, 'label': 'bad label!'}]): 'entry 1 needs a label',
            json.dumps([good, good]): 'Page "p" is listed twice',
            json.dumps([{**good, 'path': 'relative/profile.md'}]): 'Page "p" needs an absolute file path',
            json.dumps([{**good, 'sections': '## Who'}]): 'sections must be a list of headings',
            json.dumps([{**good, 'sections': []}]): 'sections must be a list of headings',
        }
        for content, pattern in cases.items():
            with self.subTest(content=content):
                self.wire(content)
                self.refused(pattern)


class RequestTests(PageCase):
    def test_openai_order_is_prefix_tools_rules_profile_then_the_request(self):
        self.two_pages()
        sent = self.ask('openai')['input']
        self.assertEqual([m['role'] for m in sent], ['system'] * 4 + ['user'])
        self.assertEqual([m['content'] for m in sent[:4]],
                         [h.load_prefix(), 'TOOLS PAGE', CORE + '\n\n' + EVIDENCE, PROFILE_FILE.strip()])
        self.assertEqual(sent[-1]['content'], 'Explain chmod 640.')

    def test_anthropic_order_is_the_same_and_only_two_pages_carry_a_cache_marker(self):
        self.two_pages()
        sent = self.ask('anthropic')
        self.assertEqual([b['text'] for b in sent['system']],
                         [h.load_prefix(), 'TOOLS PAGE', CORE + '\n\n' + EVIDENCE, PROFILE_FILE.strip()])
        self.assertEqual(['cache_control' in b for b in sent['system']], [False, True, False, True])
        self.assertEqual(sent['system'][1]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(sent['system'][3]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual([m['role'] for m in sent['messages']], ['user'])

    def test_marker_rule(self):
        self.assertEqual(pages.cache_marked(1, 1), {0})          # prefix only
        self.assertEqual(pages.cache_marked(2, 2), {0, 1})       # prefix + tools: unchanged
        self.assertEqual(pages.cache_marked(3, 2), {1, 2})       # one operator page
        self.assertEqual(pages.cache_marked(4, 2), {1, 3})       # rules + profile
        self.assertEqual(pages.cache_marked(9, 2), {1, 8})
        self.assertEqual(pages.cache_marked(3, 1), {0, 2})       # no tools page
        self.assertEqual(pages.cache_marked(4), {1, 3})          # base defaults to prefix + tools
        self.assertEqual(pages.cache_marked(2), {0, 1})
        for count in range(1, 12):
            for base in (1, 2):
                self.assertLessEqual(len(pages.cache_marked(count, base)), 2)

    def test_without_a_tools_page_the_prefix_and_the_last_page_are_marked(self):
        self.two_pages()
        sent = self.ask('anthropic', tools=None)
        self.assertEqual(len(sent['system']), 3)
        self.assertEqual(['cache_control' in b for b in sent['system']], [True, False, True])

    def test_usage_record_holds_labels_and_digests_and_no_page_text(self):
        self.two_pages()
        for engine in ('openai', 'anthropic'):
            self.ask(engine)
        raw = self.log.read_text()
        for line in raw.splitlines():
            event = json.loads(line)
            self.assertEqual(event['pages'], [
                {'label': 'rules', 'sha256': hashlib.sha256((CORE + '\n\n' + EVIDENCE).encode('utf-8')).hexdigest()},
                {'label': 'profile', 'sha256': hashlib.sha256(PROFILE_FILE.strip().encode('utf-8')).hexdigest()}])
        for secret in ('PRIVATE-RULES-MARK-71', 'PRIVATE-PROFILE-MARK-93', 'Clarify first', 'Lives somewhere', 'Never invent'):
            self.assertNotIn(secret, raw)

    def test_usage_record_without_pages_has_an_empty_list(self):
        self.ask('openai', listed=False)
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1])['pages'], [])

    def test_pages_are_read_fresh_on_every_call(self):
        self.wire([{'label': 'profile', 'path': str(self.profile)}])
        first = self.ask('openai')['input'][2]['content']
        self.profile.write_text('A newer profile.', encoding='utf-8')
        second = self.ask('openai')['input'][2]['content']
        self.assertEqual((first, second), (PROFILE_FILE.strip(), 'A newer profile.'))


class RepositoryTests(unittest.TestCase):
    def test_git_ignores_the_state_folder_that_holds_the_page_list(self):
        self.assertIn('state/', (h.ROOT / '.gitignore').read_text().splitlines())

    def test_the_command_line_entry_point_switches_the_page_list_on(self):
        """Run a copy of the client in a temporary folder: its own state/pages.json is read, and a bad page stops it."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'client'
            copy.mkdir()
            for item in h.ROOT.iterdir():
                if item.is_file() and item.suffix in {'.py', '.txt'}:
                    shutil.copy(item, copy / item.name)
            (copy / 'state').mkdir()
            (copy / 'state' / 'pages.json').write_text(json.dumps([{'label': 'ghost', 'path': str(copy / 'absent.md')}]))
            env = {**os.environ, 'OPENAI_API_KEY': 'offline-test-key', 'HARNESS_STATE_DIR': str(Path(tmp) / 'run-state')}
            env.pop('HARNESS_BRIDGE_FD', None)
            run = subprocess.run([sys.executable, '-B', str(copy / 'harness.py'), '--engine', 'openai', 'Explain chmod 640.'],
                                 capture_output=True, text=True, timeout=120, env=env, cwd=copy)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertEqual(run.stdout, '')
            self.assertEqual(run.stderr.strip(), 'Page "ghost": the file is missing or unreadable.')


if __name__ == '__main__':
    unittest.main()
