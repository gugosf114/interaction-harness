#!/data/data/com.termux/files/usr/bin/python
"""hrun.py 'COMMAND' [TIMEOUT] : run one command exactly the way the harness runs it, and show the exit code.

Same runner (native_tools.run_bounded), same shell (Termux bash --noprofile --norc -c), same PATH.
Use it in native Termux before a command goes on a card:  python ~/interaction-harness/toolbox/hrun.py 'deb uname -o'
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['PATH'] = '/data/data/com.termux/files/usr/bin'
import native_tools  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print("usage: hrun.py 'COMMAND' [TIMEOUT_SECONDS]", file=sys.stderr)
        return 2
    result = native_tools.run_bounded([native_tools.PREFIX + '/bin/bash', '--noprofile', '--norc', '-c', argv[1]],
                                      timeout=int(argv[2]) if len(argv) > 2 else 120)
    print(f"EXIT={result['exit_code']}" + (' (timed out)' if result['timed_out'] else ''))
    if result['stdout']:
        print('--- stdout'); print(result['stdout'].rstrip('\n'))
    if result['stderr']:
        print('--- stderr'); print(result['stderr'].rstrip('\n'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
