"""Receive the inherited pipe inside Debian and enter the selected client."""
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
if len(sys.argv) < 4 or sys.argv[3] not in {'harness.py', 'verify_live.py'}:
    sys.exit('Unknown harness entry point.')
with os.fdopen(int(sys.argv[1])) as stream:
    values = json.load(stream)
for name in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','DEFAULT_ENGINE','OPENAI_MODEL','ANTHROPIC_MODEL','HARNESS_STATE_DIR'):
    if values.get(name): os.environ[name]=values[name]
os.environ['HARNESS_BRIDGE_FD']=sys.argv[2]
target = ROOT / sys.argv[3]
sys.argv = [str(target), *sys.argv[4:]]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(target), run_name='__main__')
