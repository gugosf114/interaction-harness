"""self-clone and self-update: a lane changes the harness's own code and lands it.

  self-clone [DIR]              make (or refresh) a working copy of the harness. Default DIR: ~/harness-self
  self-update [--dir DIR] [--row N] 'COMMIT MESSAGE'
                                commit the working copy's changes, rebase onto origin/main, run the full
                                test suite, push to main, fast-forward the live folder.
                                --row N names the /wrong correction that caused the change: the commit
                                message names the row, and the landed commit is written on that history row.

self-update refuses only when a test fails: then nothing is pushed. The live folder is the installation
this command belongs to. When the live folder ends at the very commit the suite just passed on, the code
there is the code that was tested. When it ends anywhere else (more landed in between, or there was
nothing to land), the suite runs once in the live folder too. An open chat keeps the old code until it
is reopened.

Exit codes of self-update: 0 landed (or nothing to land); 1 a test failed, nothing pushed; 2 wrong use;
3 the rebase hit a conflict, nothing pushed; 4 git or GitHub refused a step; 5 the change is on main and
in the live folder, and the suite fails there.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_WORK = Path.home() / 'harness-self'
SUITE_TIMEOUT = 1500
TAIL_LINES = 60


def git(folder, *arguments, check=True):
    done = subprocess.run(['git', '-C', str(folder), *arguments], capture_output=True, text=True, timeout=600)
    if check and done.returncode:
        raise GitError(f'git {" ".join(arguments)} failed (exit {done.returncode}): ' + (done.stderr or done.stdout).strip())
    return done


class GitError(Exception):
    pass


def identity(folder) -> list[str]:
    """Git needs a name on a commit. When this side has none configured, the commit is signed as the lane."""
    if git(folder, 'config', 'user.email', check=False).stdout.strip():
        return []
    return ['-c', 'user.name=harness lane', '-c', 'user.email=harness-lane@localhost']


def test_modules(folder) -> list[str]:
    return sorted(path.stem for path in Path(folder).glob('test_*.py') if path.stem != 'test_native_terminal')


def run_suite(folder) -> tuple[int, str]:
    """The full suite the way the README runs it: the unittest modules in Debian, then the native test in Termux."""
    folder = Path(folder)
    modules = test_modules(folder)
    python = folder / '.venv' / 'bin' / 'python'
    if os.access(python, os.X_OK):
        command = [str(python), '-B', '-m', 'unittest', *modules]
        native = None
    else:
        command = ['proot-distro', 'login', 'debian', '--', 'sh', '-c',
                   'cd "$1" && shift && exec .venv/bin/python -B -m unittest "$@"', 'suite', str(folder), *modules]
        native = [sys.executable, '-B', str(folder / 'test_native_terminal.py')]
    output = ''
    for step in filter(None, (command, native)):
        try:
            done = subprocess.run(step, cwd=folder, capture_output=True, text=True, timeout=SUITE_TIMEOUT, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, output + f'\nThe test run did not finish in {SUITE_TIMEOUT} seconds.'
        output += done.stdout + done.stderr
        if done.returncode:
            return done.returncode, output
    return 0, output


def tail(text: str) -> str:
    return '\n'.join(text.rstrip().splitlines()[-TAIL_LINES:])


def summary(output: str) -> str:
    lines = [line for line in output.splitlines() if line.startswith('Ran ')]
    return '; '.join(lines) if lines else 'tests ran'


def link_environment(work, live) -> None:
    """The working copy runs its tests with the installation's Python environment."""
    link = Path(work) / '.venv'
    if not link.exists() and not link.is_symlink():
        link.symlink_to(Path(live) / '.venv')


def is_work_tree(folder) -> bool:
    return Path(folder).is_dir() and git(folder, 'rev-parse', '--is-inside-work-tree', check=False).stdout.strip() == 'true'


def clone(work=None, live=None, out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    work, live = Path(work or DEFAULT_WORK).expanduser(), Path(live or ROOT)
    try:
        if not work.exists():
            url = git(live, 'remote', 'get-url', 'origin').stdout.strip()
            done = subprocess.run(['git', 'clone', '--quiet', url, str(work)], capture_output=True, text=True, timeout=900)
            if done.returncode:
                print('git clone failed: ' + done.stderr.strip(), file=err)
                return 4
            link_environment(work, live)
            print(f'Working copy ready: {work}\nIt is at {git(work, "rev-parse", "--short", "HEAD").stdout.strip()}, the tip of main.', file=out)
            return 0
        if not is_work_tree(work) or work.resolve() == live.resolve():
            print(f'{work} is not a working copy of the harness.', file=err)
            return 2
        link_environment(work, live)
        git(work, 'fetch', '--quiet', 'origin')
        changed = git(work, 'status', '--porcelain').stdout.strip()
        ahead = int(git(work, 'rev-list', '--count', 'origin/main..HEAD').stdout.strip() or 0)
        if not changed and not ahead:
            git(work, 'merge', '--quiet', '--ff-only', 'origin/main')
            print(f'Working copy ready: {work}\nIt is at {git(work, "rev-parse", "--short", "HEAD").stdout.strip()}, the tip of main.', file=out)
        else:
            print(f'Working copy: {work}\nIt holds work that is not on main: {ahead} commit(s) ahead, and these changed files:\n'
                  + (changed or '(none)'), file=out)
        return 0
    except GitError as exc:
        print(str(exc), file=err)
        return 4


USAGE = "usage: self-update [--dir DIR] [--row N] 'COMMIT MESSAGE'"


def note_row(row, landed, message, history=None, out=None) -> None:
    """Write the landed commit on the correction's history row (gate_json.outcomes), next to lessons and rules."""
    import gate_admin
    found = gate_admin.history_row(row, history)
    if not found or found['status'] != gate_admin.CORRECTION:
        print(f'History row {row} is not a correction case; the commit was not written on it.', file=out or sys.stdout)
        return
    gate_admin.record_outcome(row, {'bin': 'code', 'commit': landed, 'message': message.strip(), 'date': gate_admin.today()}, history)
    print(f'Written on history row {row}: commit {landed}.', file=out or sys.stdout)


def update(message: str, work=None, live=None, suite=run_suite, out=None, err=None, row=None, history=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    work, live = Path(work or DEFAULT_WORK).expanduser(), Path(live or ROOT)
    if not message or not message.strip():
        print(USAGE, file=err)
        return 2
    if not is_work_tree(work):
        print(f'No working copy at {work}. Make one with: self-clone', file=err)
        return 2
    if work.resolve() == live.resolve():
        print('That folder is the live installation. Change the code in a working copy: self-clone', file=err)
        return 2
    try:
        link_environment(work, live)
        git(work, 'add', '-A')
        if git(work, 'diff', '--cached', '--quiet', check=False).returncode:
            said = message.strip() + (f'\n\nCorrection: history row {row}' if row else '')
            git(work, *identity(work), 'commit', '--quiet', '-m', said)
        landed = tested = None
        for attempt in range(1, 6):
            git(work, 'fetch', '--quiet', 'origin')
            if int(git(work, 'rev-list', '--count', 'origin/main..HEAD').stdout.strip() or 0) == 0:
                break  # nothing of ours is ahead of main
            rebase = git(work, *identity(work), 'rebase', 'origin/main', check=False)
            if rebase.returncode:
                files = git(work, 'diff', '--name-only', '--diff-filter=U', check=False).stdout.split()
                git(work, 'rebase', '--abort', check=False)
                print('The change conflicts with main in: ' + (', '.join(files) or 'unknown files')
                      + '. Nothing was pushed. Bring the change up to date in the working copy and run self-update again.', file=err)
                return 3
            code, output = suite(work)
            if code:
                print(tail(output), file=err)
                print(f'Tests failed in the working copy (exit {code}). Nothing was pushed.', file=err)
                return 1
            print(f'Working copy on the tip of main: {summary(output)}, all passed.', file=out)
            passed = summary(output)
            push = git(work, 'push', 'origin', 'HEAD:main', check=False)
            if push.returncode == 0:
                landed = git(work, 'rev-parse', '--short', 'HEAD').stdout.strip()
                tested = git(work, 'rev-parse', 'HEAD').stdout.strip()
                break
            if attempt == 5 or 'rejected' not in push.stderr and 'fetch first' not in push.stderr:
                print('git push failed: ' + push.stderr.strip(), file=err)
                return 4
        pull = git(live, 'pull', '--quiet', '--ff-only', 'origin', 'main', check=False)
        if pull.returncode:
            print(('main holds the change. ' if landed else '') + 'The live folder did not fast-forward: ' + pull.stderr.strip(), file=err)
            return 4
        at = git(live, 'rev-parse', '--short', 'HEAD').stdout.strip()
        if tested and git(live, 'rev-parse', 'HEAD').stdout.strip() == tested:
            # The live folder holds exactly the commit the suite just passed on.
            print(f'Landed {landed} on main: {message.strip()}', file=out)
            if row:
                note_row(row, landed, message, history, out)
            print(f'The live folder is at {at}, the commit the suite passed on: {passed}, all passed.\n'
                  'Tell George: type exit, then reopen the chat with -c. The open chat runs the old code until then.', file=out)
            return 0
        code, output = suite(live)
        if code:
            print(tail(output), file=err)
            print(f'main and the live folder are at {at}, and the suite fails in the live folder (exit {code}).', file=err)
            return 5
        if landed:
            print(f'Landed {landed} on main: {message.strip()}', file=out)
            if row:
                note_row(row, landed, message, history, out)
        else:
            print('Nothing to land: the working copy has no change on top of main.', file=out)
        print(f'The live folder is at {at}: {summary(output)}, all passed.\n'
              'Tell George: type exit, then reopen the chat with -c. The open chat runs the old code until then.', file=out)
        return 0
    except GitError as exc:
        print(str(exc), file=err)
        return 4


def main_update(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    work = row = None
    while len(argv) >= 2 and argv[0] in ('--dir', '--row'):
        if argv[0] == '--dir':
            work = argv[1]
        elif argv[1].isdigit() and int(argv[1]) > 0:
            row = int(argv[1])
        else:
            print(USAGE, file=sys.stderr)
            return 2
        argv = argv[2:]
    if len(argv) != 1 or argv[0].startswith('--'):
        print(USAGE, file=sys.stderr)
        return 2
    return update(argv[0], work, row=row)


def main_clone(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) > 1 or argv[:1] in (['-h'], ['--help']):
        print('usage: self-clone [DIR]', file=sys.stderr)
        return 2
    return clone(argv[0] if argv else None)
