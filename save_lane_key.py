#!/usr/bin/env python3
"""Save a lane's key (and optional base URL) without displaying it.

Usage, in native Termux after exporting the key variable:
    OPENROUTER_API_KEY=... python save_lane_key.py openrouter
    OPENROUTER_BASE_URL=... OPENROUTER_API_KEY=... python save_lane_key.py openrouter
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extra_lanes  # noqa: E402

root = Path(__file__).resolve().parent
engine = sys.argv[1] if len(sys.argv) > 1 else ''
if engine not in extra_lanes.LANES:
    sys.exit('Unknown lane. Choose from: ' + ', '.join(extra_lanes.LANES))
lane = extra_lanes.LANES[engine]
if lane.key_file is None:
    sys.exit(f'The {engine} lane needs no saved key.')

key = os.environ.get(lane.key_env or '', '').strip()
if not key or '\n' in key or '\r' in key:
    sys.exit(f'{lane.key_env} is empty or contains a line break.')

state = root / 'state'
state.mkdir(mode=0o700, exist_ok=True)
os.chmod(state, 0o700)


def write_private(name, value):
    path = state / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'w') as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(value + '\n')


write_private(lane.key_file, key)
if lane.base_env and os.environ.get(lane.base_env, '').strip() and lane.base_file:
    write_private(lane.base_file, os.environ[lane.base_env].strip())
    print(f'Key and base URL saved for the {engine} lane.', file=sys.stderr)
else:
    print(f'Key saved for the {engine} lane.', file=sys.stderr)
