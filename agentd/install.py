"""`agentd install`: put the service on this phone. Safe to run again."""
from __future__ import annotations

import os
import subprocess

from . import config

TIMER_ID = '7742'
TIMER_PERIOD_MS = '900000'  # 15 minutes, the shortest period Android allows
ALIAS_BEGIN = '# BEGIN interaction-harness agentd'
ALIAS_END = '# END interaction-harness agentd'
ALIAS_BLOCK = f"{ALIAS_BEGIN}\nalias jobs='job list'\n{ALIAS_END}\n"


def add_alias_block(text: str) -> str:
    """~/.bashrc with the `jobs` alias block in place. `jobs` is a bash builtin, so only an alias can take the name."""
    if ALIAS_BEGIN in text and ALIAS_END in text:
        start, end = text.index(ALIAS_BEGIN), text.index(ALIAS_END) + len(ALIAS_END)
        return text[:start] + ALIAS_BLOCK.rstrip('\n') + text[end:]
    return text + ('' if text.endswith('\n') or not text else '\n') + '\n' + ALIAS_BLOCK


def step(label, argv, timeout=120) -> bool:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        ok, note = done.returncode == 0, (done.stdout + done.stderr).strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, note = False, [type(exc).__name__]
    print(f"{'ok ' if ok else 'NOT DONE'}  {label}" + (f': {note[-1]}' if note and not ok else ''))
    return ok


def install(paths=None) -> int:
    home, root = config.TERMUX_HOME, config.ROOT
    results = [step('commands linked into the Termux path (job, jobs, agentd, talk)', [config.TERMUX_BIN + '/sh', str(root / 'toolbox' / 'install.sh')])]
    boot = home / '.termux' / 'boot' / '20-agentd'
    try:
        boot.parent.mkdir(parents=True, exist_ok=True)
        if boot.is_symlink() or boot.exists():
            boot.unlink()
        boot.symlink_to(root / 'agentd' / 'boot' / '20-agentd')
        print(f'ok   boot script: {boot}')
        results.append(True)
    except OSError as exc:
        print(f'NOT DONE  boot script: {type(exc).__name__}')
        results.append(False)
    results.append(step(f'phone timer {TIMER_ID}: the keeper runs every 15 minutes',
                        [str(home / '.local' / 'bin' / 'timer-add'), TIMER_ID, TIMER_PERIOD_MS, str(root / 'agentd' / 'keeper.sh')]))
    bashrc = home / '.bashrc'
    try:
        before = bashrc.read_text(encoding='utf-8') if bashrc.exists() else ''
        after = add_alias_block(before)
        if after != before:
            temporary = bashrc.with_name('.bashrc.agentd-part')
            temporary.write_text(after, encoding='utf-8')
            os.chmod(temporary, 0o600)
            os.replace(temporary, bashrc)
        print("ok   ~/.bashrc: alias jobs='job list' (new windows; in an open one run: . ~/.bashrc)")
        results.append(True)
    except OSError as exc:
        print(f'NOT DONE  ~/.bashrc alias: {type(exc).__name__}')
        results.append(False)
    results.append(step('service started', [config.TERMUX_BIN + '/sh', str(root / 'agentd' / 'keeper.sh'), 'start']))
    return 0 if all(results) else 1
