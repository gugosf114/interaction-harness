"""Paths, lanes and settings of the always-on service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parent.parent
TERMUX_HOME = Path('/data/data/com.termux/files/home')
TERMUX_BIN = '/data/data/com.termux/files/usr/bin'
DEBIAN_ROOTFS = Path('/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs')
DEFAULT_PORT = 8377
MAX_TASK_CHARS = 1000000  # the harness input cap (harness.MAX_INPUT_CHARS)
SESSION_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')  # the harness session rule (storage.NAME)
ALIAS_BEGIN = '# BEGIN interaction-harness shortcuts'
ALIAS_END = '# END interaction-harness shortcuts'
# Used when ~/.bashrc has no managed block. The block wins, so a lane added there is a job lane at once.
BUILTIN_LANES = {
    'g2': ['--engine', 'anthropic', '--model', 'claude-opus-5-5', '--effort', 'max', '--loop', '-y'],
    'g1': ['--engine', 'openai', '--model', 'gpt-6.1-sol', '--effort', 'max', '--loop', '-y'],
}


class ConfigError(Exception):
    """A short, user-visible configuration failure."""


def state_dir() -> Path:
    return Path(os.environ.get('HARNESS_STATE_DIR', str(ROOT / 'state'))).expanduser()


class Paths:
    """Every file the service owns, under one harness state folder."""

    def __init__(self, state=None):
        self.state = Path(state) if state else state_dir()
        self.home = self.state / 'agentd'
        self.db = self.home / 'queue.db'
        self.jobs = self.home / 'jobs'
        self.pid = self.home / 'daemon.pid'
        self.lock = self.home / 'daemon.lock'
        self.log = self.home / 'daemon.log'
        self.web_token = self.home / 'web-token'
        self.history = self.state / 'history.db'
        self.settings = self.state / 'agentd.json'
        self.inbox = self.state / 'inbox'
        self.outbox = self.state / 'outbox'
        self.schedule = self.state / 'schedule.json'
        self.triggers = self.state / 'triggers.json'
        self.doors = self.state / 'doors.json'

    def make(self):
        for folder in (self.state, self.home, self.jobs, self.inbox, self.outbox):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self


def load_settings(paths: Paths) -> dict:
    """state/agentd.json. A missing file is an empty dict. A broken file is an error with one short line."""
    try:
        data = json.loads(paths.settings.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ConfigError(f'{paths.settings} cannot be read as JSON.') from exc
    if not isinstance(data, dict):
        raise ConfigError(f'{paths.settings} must hold one JSON object.')
    return data


def alias_lanes(text: str) -> dict:
    """Lanes from the managed alias block of ~/.bashrc: alias NAME='/path/harness FLAGS'."""
    found, inside = {}, False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == ALIAS_BEGIN:
            inside = True
            continue
        if stripped == ALIAS_END:
            inside = False
            continue
        match = re.match(r'alias\s+([A-Za-z0-9][A-Za-z0-9_-]*)=(.+)$', stripped) if inside else None
        if not match:
            continue
        try:
            words = shlex.split(' '.join(shlex.split(match.group(2))))
        except ValueError:
            continue
        if words and Path(words[0]).name == 'harness':
            found[match.group(1)] = words[1:]
    return found


def job_flags(flags) -> list:
    """A job always runs as a loop with every command approved, and never as a chat."""
    flags = [flag for flag in flags if flag not in ('--chat', '--interactive')]
    if '--loop' not in flags:
        flags.append('--loop')
    if '-y' not in flags and '--yes' not in flags:
        flags.append('-y')
    return flags


def lanes(settings=None, bashrc=None) -> dict:
    """Lane name -> harness flags. Order: built-in, then the alias block, then settings['lanes']."""
    table = {name: list(flags) for name, flags in BUILTIN_LANES.items()}
    path = Path(bashrc or os.environ.get('AGENTD_BASHRC') or TERMUX_HOME / '.bashrc')
    try:
        table.update(alias_lanes(path.read_text(encoding='utf-8', errors='replace')))
    except OSError:
        pass
    extra = (settings or {}).get('lanes') or {}
    if isinstance(extra, dict):
        for name, flags in extra.items():
            if isinstance(name, str) and isinstance(flags, list) and all(isinstance(flag, str) for flag in flags):
                table[name] = list(flags)
    return {name: job_flags(flags) for name, flags in table.items()}


def default_lane(settings=None, table=None) -> str:
    table = table if table is not None else lanes(settings)
    wanted = (settings or {}).get('default_lane')
    if isinstance(wanted, str) and wanted in table:
        return wanted
    return 'g2' if 'g2' in table else sorted(table)[0]


def harness_command(settings=None) -> list:
    """The command that starts one harness run. settings['harness'] replaces it (a list, used by the tests)."""
    custom = (settings or {}).get('harness')
    if isinstance(custom, list) and custom and all(isinstance(word, str) for word in custom):
        return list(custom)
    return [str(ROOT / 'harness')]


PROFILE_FILES = (DEBIAN_ROOTFS / 'root/.local/state/phone-errands/profile.json',
                 Path('/root/.local/state/phone-errands/profile.json'))
DOORS_DEFAULT = {
    'web': {'password': None},
    'sms': {'keyword': 'lane', 'numbers': None},
    'telegram': {'chat_ids': []},
    'voice': {'key': None},
}


def own_numbers(files=PROFILE_FILES) -> list:
    """George's own numbers from the phone's records: the errand profile's identity.phone."""
    for path in files:
        try:
            phone = json.loads(Path(path).read_text(encoding='utf-8')).get('identity', {}).get('phone')
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(phone, str) and phone.strip():
            return [phone.strip()]
    return []


def write_private_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.part')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


def load_doors(paths, numbers=None, make=True) -> dict:
    """state/doors.json. Missing parts are filled once and written back: a web password, George's numbers, door keys."""
    import secrets
    try:
        data = json.loads(paths.doors.read_text(encoding='utf-8'))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        raise ConfigError(f'{paths.doors} cannot be read as JSON.') from exc
    if not isinstance(data, dict):
        raise ConfigError(f'{paths.doors} must hold one JSON object.')
    changed = False
    for name, defaults in DOORS_DEFAULT.items():
        part = data.get(name)
        if not isinstance(part, dict):
            part, changed = {}, True
            data[name] = part
        for key, value in defaults.items():
            if key not in part:
                part[key], changed = value, True
    if data['web'].get('password') is None:
        data['web']['password'], changed = secrets.token_urlsafe(9), True
    if data['sms'].get('numbers') is None:
        data['sms']['numbers'], changed = list(own_numbers() if numbers is None else numbers), True
    if data['voice'].get('key') is None:
        data['voice']['key'], changed = secrets.token_urlsafe(18), True
    if changed and make:
        write_private_json(paths.doors, data)
    return data


def digits(number) -> str:
    """A phone number reduced to its last ten digits, so +1 415..., 1-415... and (415)... compare equal."""
    only = re.sub(r'\D', '', str(number or ''))
    return only[-10:] if len(only) >= 10 else only


def number_allowed(number, allowed) -> bool:
    allowed = allowed or []
    if '*' in allowed:
        return True
    mine = digits(number)
    return bool(mine) and any(mine == digits(entry) for entry in allowed)


def port(settings=None) -> int:
    value = (settings or {}).get('port', DEFAULT_PORT)
    return value if isinstance(value, int) and 1 <= value <= 65535 else DEFAULT_PORT
