"""On the operator's own install every API tool starts on; scratch state folders start from the table."""
import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

import api_tools_config as cfg


class DefaultOnTests(unittest.TestCase):
    def test_scratch_state_starts_from_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = cfg.Settings(Path(tmp) / 'state', 'anthropic')
            self.assertFalse(s.enabled['memory']); self.assertTrue(s.enabled['web_search'])

    def test_the_install_state_starts_with_everything_on_except_the_two_that_squeeze_the_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'api_tools_config.py'
            with patch.object(cfg, '__file__', str(fake)):
                s = cfg.Settings(Path(tmp) / 'state', 'openai')
            saved = json.loads((Path(tmp) / 'state/tools.json').read_text())
            for name in cfg.TOOLS:
                self.assertEqual(saved[name], name not in cfg.ALWAYS_OFF, name)
            self.assertFalse(s.enabled['compaction'])

    def test_a_tool_that_is_on_with_no_address_steps_aside_and_stops_only_when_asked_by_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({**{n: False for n in cfg.TOOLS}, 'mcp_remote': True}))
            quiet = cfg.Settings(state, 'openai')
            self.assertFalse(any(t.get('type') == 'mcp' for t in cfg.provider_tools(quiet, [])))
            asked = cfg.Settings(state, 'openai', {'mcp_remote': True})
            with self.assertRaises(ValueError):
                cfg.provider_tools(asked, [])

    def test_everything_on_with_nothing_set_up_builds_a_request_on_both_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({n: n not in cfg.ALWAYS_OFF for n in cfg.TOOLS}))
            for engine in ('openai', 'anthropic'):
                s = cfg.Settings(state, engine)
                self.assertEqual({'skills', 'file_search', 'mcp_remote'} & s.effective, set(), engine)
                tools = cfg.provider_tools(s, [])
                kinds = [t.get('type') for t in tools]
                self.assertNotIn('file_search', kinds); self.assertNotIn('mcp', kinds); self.assertNotIn('mcp_toolset', kinds)
                if engine == 'openai':
                    self.assertEqual(s.unset & {'code_execution', 'shell', 'hosted_shell'}, {'shell', 'hosted_shell'})
                    self.assertIn('code_interpreter', kinds); self.assertNotIn('shell', kinds)
                    self.assertTrue({'custom', 'namespace'} <= set(kinds))
                else:
                    self.assertTrue({'code_execution_20260521', 'bash_20250124'} <= set(kinds))
                self.assertIn('steps aside', s.listing('model'))

    def test_skills_and_file_search_stop_the_call_only_when_asked_by_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({n: False for n in cfg.TOOLS}))
            for name in ('skills', 'file_search'):
                self.assertIn(name, cfg.Settings(state, 'openai', {name: True}).effective)
            self.assertIn('skills', cfg.Settings(state, 'anthropic', {'skills': True}).effective)

    def test_the_shell_asked_for_by_flag_wins_and_asking_for_both_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({**{n: False for n in cfg.TOOLS}, 'shell': True, 'hosted_shell': True}))
            self.assertEqual(cfg.Settings(state, 'openai', {'hosted_shell': True}).unset, {'shell'})
            self.assertEqual(cfg.Settings(state, 'openai', {'shell': True}).unset, {'hosted_shell'})
            self.assertEqual(cfg.Settings(state, 'openai').unset, {'hosted_shell'})
            with self.assertRaises(ValueError):
                cfg.provider_tools(cfg.Settings(state, 'openai', {'shell': True, 'hosted_shell': True}), [])
            (state / 'tools.json').write_text(json.dumps({**{n: False for n in cfg.TOOLS}, 'shell': True, 'code_execution': True}))
            self.assertEqual(cfg.Settings(state, 'openai').unset, {'shell'})
            self.assertEqual(cfg.Settings(state, 'openai', {'shell': True}).unset, {'code_execution'})
            self.assertEqual(cfg.Settings(state, 'anthropic').unset, set())
            with self.assertRaises(ValueError):
                cfg.provider_tools(cfg.Settings(state, 'openai', {'shell': True, 'code_execution': True}), [])

    def test_skills_that_are_set_up_keep_the_hosted_shell_on_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({**{n: n not in cfg.ALWAYS_OFF for n in cfg.TOOLS},
                                                          'options': {'openai_skills': [{'type': 'skill_reference', 'skill_id': 's', 'version': '1'}]}}))
            s = cfg.Settings(state, 'openai')
            self.assertEqual(s.unset & {'code_execution', 'shell', 'hosted_shell'}, {'code_execution', 'shell'})
            self.assertIn('skills', s.effective)

    def test_openai_remote_mcp_runs_without_asking(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'; state.mkdir()
            (state / 'tools.json').write_text(json.dumps({**{n: False for n in cfg.TOOLS}, 'mcp_remote': True,
                                                          'options': {'mcp_url': 'https://mcp.example/mcp'}}))
            tool = [t for t in cfg.provider_tools(cfg.Settings(state, 'openai'), []) if t.get('type') == 'mcp'][0]
            self.assertEqual(tool['require_approval'], 'never')


if __name__ == '__main__':
    unittest.main()
