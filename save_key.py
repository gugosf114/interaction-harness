#!/usr/bin/env python3
"""Save a deliberately supplied key without displaying it."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
engine = sys.argv[1] if len(sys.argv) > 1 else 'openai'
if engine not in {'openai', 'anthropic'}:
    sys.exit('Unknown engine.')
variable = 'OPENAI_API_KEY' if engine == 'openai' else 'ANTHROPIC_API_KEY'
key = os.environ.get(variable, '').strip()
if not key or '\n' in key or '\r' in key:
    sys.exit(variable + ' is empty or contains a line break.')
state = root / 'state'
state.mkdir(mode=0o700, exist_ok=True)
os.chmod(state, 0o700)
path = state / ('api-key' if engine == 'openai' else 'anthropic-api-key')
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
fd = os.open(path, flags, 0o600)
with os.fdopen(fd, 'w') as f:
    os.fchmod(f.fileno(), 0o600)
    f.write(key + '\n')
print('Key saved for this harness.', file=sys.stderr)
