"""The phone's own commands, behind one small object so tests can swap the runner."""
from __future__ import annotations

import json
import os
import subprocess

from .config import TERMUX_BIN, TERMUX_HOME

DEB = [TERMUX_BIN + '/proot-distro', 'login', 'debian', '--']


def run_command(argv, timeout=60, input_text=None):
    """Run one command. Returns (exit code, stdout, stderr) and never raises: 127 not found, 124 timed out."""
    try:
        done = subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=timeout,
                              stdin=None if input_text is not None else subprocess.DEVNULL)
        return done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        return 127, '', f'{argv[0]}: not found'
    except subprocess.TimeoutExpired:
        return 124, '', 'timed out'
    except OSError as exc:
        return 126, '', type(exc).__name__


def no_phone(argv, timeout=60, input_text=None):
    return 0, '', ''


class Phone:
    def __init__(self, run=None):
        # Test seam: AGENTD_NO_PHONE=1 makes every phone command a no-op.
        self.run = run or (no_phone if os.environ.get('AGENTD_NO_PHONE') == '1' else run_command)

    # --- notifications -------------------------------------------------------------------------------------
    def notify(self, ident, title, content, *, ongoing=False, action=None, priority='high', sound=False):
        argv = [TERMUX_BIN + '/termux-notification', '--id', str(ident), '--title', title, '--content', content or ' ',
                '--priority', priority]
        if ongoing:
            argv.append('--ongoing')
        if sound:
            argv.append('--sound')
        if action:
            argv.extend(['--action', action])
        return self.run(argv, 30)[0] == 0

    def remove_notification(self, ident):
        return self.run([TERMUX_BIN + '/termux-notification-remove', str(ident)], 30)[0] == 0

    def notifications(self):
        """The notifications on the phone now, from the phone's MCP server (android_notification_list)."""
        code, out, _ = self.run([str(TERMUX_HOME / '.local/bin/agentbridge-call'), 'android_notification_list', '{}'], 60)
        if code != 0:
            return None
        return parse_notification_list(out)

    # --- voice ---------------------------------------------------------------------------------------------
    def voice_state(self) -> str:
        """'off', 'first' (first line of every answer) or 'full' (the whole answer). From `deb voice`."""
        flags = voice_flags()
        if flags is not None:
            return flags
        code, out, _ = self.run([*DEB, 'voice'], 60)
        return parse_voice_state(out) if code == 0 else 'off'

    def say(self, text):
        return self.run([*DEB, 'say', text], 600)[0] == 0

    # --- texts ---------------------------------------------------------------------------------------------
    def sms_inbox(self, limit=40):
        code, out, _ = self.run([TERMUX_BIN + '/termux-sms-list', '-l', str(limit), '-t', 'inbox'], 60)
        if code != 0:
            return None
        try:
            data = json.loads(out)
        except ValueError:
            return None
        return data if isinstance(data, list) else None

    def sms_send(self, number, text):
        return self.run([TERMUX_BIN + '/termux-sms-send', '-n', number, text], 60)[0] == 0

    def own_number(self):
        """The SIM's own number, when Termux:API may read it. None otherwise."""
        code, out, _ = self.run([TERMUX_BIN + '/termux-telephony-deviceinfo'], 30)
        if code != 0:
            return None
        try:
            value = json.loads(out).get('phone_number')
        except (ValueError, AttributeError):
            return None
        return value if isinstance(value, str) and value.strip() else None

    def wake_lock(self):
        return self.run([TERMUX_BIN + '/termux-wake-lock'], 30)[0] == 0


def voice_flags(claude_dir=None):
    """The switch files `voice` keeps (/root/.claude/.voice-on, .voice-full), read straight from the Debian folder.
    None when the folder cannot be seen; then `deb voice` answers."""
    from .config import DEBIAN_ROOTFS
    from pathlib import Path
    folder = Path(claude_dir) if claude_dir else next((p for p in (DEBIAN_ROOTFS / 'root/.claude', Path('/root/.claude')) if p.is_dir()), None)
    if folder is None:
        return None
    if not (folder / '.voice-on').exists():
        return 'off'
    return 'full' if (folder / '.voice-full').exists() else 'first'


def parse_voice_state(output: str) -> str:
    lines = [line.strip() for line in (output or '').splitlines()]
    if 'Voice is ON' not in lines:
        return 'off'
    return 'full' if any(line.startswith('Full: EVERY') for line in lines) else 'first'


def parse_notification_list(output: str):
    """The MCP tool prints one notice line, then one JSON object. Returns the list of notifications, or None."""
    for line in (output or '').splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        items = data.get('notifications') if isinstance(data, dict) else None
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return None
