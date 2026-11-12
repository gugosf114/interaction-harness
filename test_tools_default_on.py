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


if __name__ == '__main__':
    unittest.main()
