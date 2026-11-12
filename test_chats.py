"""chat-list and chat-tail read saved session files and change nothing."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOL = ROOT / 'toolbox/bin/chat-list'


def run(name, *args, env):
    link = Path(env['TMP']) / name
    if not link.exists():
        link.symlink_to(TOOL)
    return subprocess.run([sys.executable, str(link), *args], capture_output=True, text=True, env={**os.environ, **env})


class ChatTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = Path(self.tmp.name)
        (t / 'claude').mkdir(); (t / 'codex/2026/11/11').mkdir(parents=True)
        rows = [
            {'type': 'user', 'timestamp': '2026-11-11T10:00:00Z', 'message': {'role': 'user', 'content': 'list the files'}},
            {'type': 'assistant', 'timestamp': '2026-11-11T10:00:05Z', 'message': {'role': 'assistant', 'content': [
                {'type': 'thinking', 'thinking': 'SECRET THOUGHT'}, {'type': 'text', 'text': 'Here they are.'},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls -la', 'description': 'List files'}}]}},
            {'type': 'user', 'timestamp': '2026-11-11T10:00:06Z', 'message': {'role': 'user', 'content': '<system-reminder>x</system-reminder>'}},
            {'type': 'assistant', 'isSidechain': True, 'timestamp': '2026-11-11T10:00:07Z', 'message': {'role': 'assistant', 'content': 'side work'}},
        ]
        (t / 'claude/abcdef12-0000.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        crow = [
            {'timestamp': '2026-11-11T11:00:00Z', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': 'build it'}]}},
            {'timestamp': '2026-11-11T11:00:09Z', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'text': 'Built.'}]}},
            {'timestamp': '2026-11-11T11:00:10Z', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': 'git status'}},
        ]
        (t / 'codex/2026/11/11/rollout-2026-11-11T11-00-00-99887766-aaaa.jsonl').write_text('\n'.join(json.dumps(r) for r in crow) + '\n')
        self.env = {'CHAT_CLAUDE_DIR': str(t / 'claude'), 'CHAT_CODEX_DIR': str(t / 'codex'), 'TMP': str(t)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_shows_both_kinds_with_first_words(self):
        r = run('chat-list', env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('claude abcdef12', r.stdout); self.assertIn('list the files', r.stdout)
        self.assertIn('codex', r.stdout); self.assertIn('build it', r.stdout)

    def test_tail_prints_speech_and_commands_and_skips_thinking_and_side_work(self):
        r = run('chat-tail', 'abcdef12', env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('George: list the files', r.stdout); self.assertIn('Claude: Here they are.', r.stdout)
        self.assertIn('[ran Bash: List files]', r.stdout)
        for hidden in ('SECRET THOUGHT', 'system-reminder', 'side work'):
            self.assertNotIn(hidden, r.stdout)

    def test_tail_reads_codex_and_limits_the_count(self):
        r = run('chat-tail', '99887766', '2', env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('build it', r.stdout); self.assertIn('Codex: Built.', r.stdout); self.assertIn('[ran exec: git status]', r.stdout)

    def test_unknown_id_and_missing_id_fail_plainly(self):
        self.assertEqual(run('chat-tail', 'nope', env=self.env).returncode, 1)
        self.assertEqual(run('chat-tail', env=self.env).returncode, 2)


if __name__ == '__main__':
    unittest.main()
