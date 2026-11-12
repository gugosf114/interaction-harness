"""The narrator, rebuilt from the narrator mod for the lanes: one plain sentence for a shell command.

In Claude Code it redraws each tool row as a sentence. The lanes have one tool, the shell, so the sentence
comes from the command's first word. It prints on stderr just before the command runs. No model call.
(The mod's step count and time-saved line in the status bar was muted by George on 11/5; it stays muted.)
"""
from __future__ import annotations

import re
import shlex


def _clip(text: str, n: int) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _base(path: str) -> str:
    parts = [p for p in str(path).split('/') if p]
    return parts[-1] if parts else str(path)


def _words(command: str) -> list[str]:
    first = re.split(r'\s*(?:&&|\|\||;|\|)\s*', command.strip(), maxsplit=1)[0]
    try:
        words = shlex.split(first)
    except ValueError:
        words = first.split()
    while words and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]):
        words.pop(0)   # FOO=bar cmd
    while words and words[0] in ('sudo', 'time', 'timeout', 'env', 'nice', 'command', 'exec'):
        words.pop(0)
        if words and re.match(r'^\d+[smh]?$', words[0]):
            words.pop(0)   # timeout 30 cmd
    return words


def describe(command: str) -> str:
    command = command.strip()
    if re.match(r'^cd\s+\S+\s*&&', command):
        command = command.split('&&', 1)[1]
    words = _words(command)
    if not words:
        return 'Ran a command.'
    head, rest = words[0], words[1:]
    arg = rest[0] if rest else ''
    if head == 'deb' and rest:
        return 'On the Debian side: ' + describe(' '.join(shlex.quote(w) for w in rest))
    if head == 'card' and arg:
        return f'Read the {arg} card'
    if head == 'cards':
        return 'Listed the tool cards'
    if head == 'gh':
        return 'Asked GitHub: ' + _clip(' '.join(rest[:3]), 40)
    if head == 'git':
        return 'Used git: ' + _clip(' '.join(rest[:2]), 40)
    if head == 'screen' and arg:
        return {'snap': 'Took a picture of the screen', 'tap': 'Tapped the screen', 'swipe': 'Swiped the screen',
                'text': 'Typed on the screen', 'key': 'Pressed a key on the screen',
                'size': 'Measured the screen'}.get(arg, 'Used the screen: ' + arg)
    if head == 'look' and arg:
        return 'Looked at ' + _base(arg)
    if head in ('cat', 'head', 'tail', 'less', 'more', 'bat') and rest:
        return 'Read ' + _base(rest[-1])
    if head in ('ls', 'tree', 'find') and True:
        return 'Listed ' + (_base(arg) if arg and not arg.startswith('-') else 'the folder')
    if head in ('grep', 'rg', 'ag'):
        pattern = next((w for w in rest if not w.startswith('-')), '')
        return f'Searched for "{_clip(pattern, 40)}"'
    if head in ('curl', 'wget'):
        url = next((w for w in rest if re.match(r'https?://', w)), '')
        host = re.match(r'https?://([^/]+)', url)
        return 'Read a web page: ' + (host.group(1) if host else _clip(' '.join(rest), 40))
    if head in ('page-text',):
        return 'Read a web page in the phone browser'
    if head == 'mail-unread':
        return f'Checked the {arg or "mail"} inbox'
    if head in ('python', 'python3', 'node', 'bash', 'sh'):
        script = next((w for w in rest if not w.startswith('-')), '')
        return 'Ran ' + (_base(script) if script else 'a ' + head + ' script')
    if head in ('mkdir', 'touch'):
        return 'Made ' + _base(rest[-1]) if rest else 'Made a file'
    if head in ('cp', 'mv', 'rm'):
        verb = {'cp': 'Copied', 'mv': 'Moved', 'rm': 'Deleted'}[head]
        return verb + ' ' + _clip(' '.join(_base(w) for w in rest if not w.startswith('-')), 50)
    if head == 'edit-exact' and arg:
        return 'Edited ' + _base(arg)
    if head in ('echo', 'printf'):
        return 'Printed text' + (' to ' + _base(command.rsplit('>', 1)[1].strip()) if '>' in command else '')
    if head in ('say',):
        return 'Spoke out loud'
    if head.startswith('termux-'):
        return 'Used the phone: ' + head[len('termux-'):]
    if head == 'mcp' and arg:
        return 'Used the phone: ' + arg
    return 'Ran a command — ' + _clip(command, 60)
