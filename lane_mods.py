"""George's Claude Code mods and hooks, rebuilt around each lane turn. Every one ships on; /on NAME, /off NAME.

Where each piece sits:
  gate (answer_checks.py, called from harness.request_reply)   length, plain-words, receipts, no-background, undertaker
  before a command runs (before_command)                       narrator
  after a command runs (after_command)                         memory-version
  after the turn's final answer (turn_end)                     proof, tree, voice
  when a chat opens (session_start)                            reindex, voiceline
  chat lines (chat_line)                                       /on /off /mods /where /up /voice /usage /autopilot, v
Everything shown to George here goes to stderr; stdout stays answer-and-command only.
A mod never breaks a turn: each hook catches its own failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import mod_switches
import narrator
import proof_marks
import thread_tree
import helper_model
import memory_versions

SAY = '/usr/local/bin/say'
MEMORY_VERSION = '/root/.claude/memory-version.sh'
REINDEX = ['/usr/bin/python3', '/root/reindex_incremental.py']
VOICELINE_WANTED = '/root/.vapi/bridge/WANTED'
VOICELINE = ('tmux new-session -d -s vboot "bash /root/.vapi/bridge/phone.sh on > /root/.vapi/bridge/boot.log 2>&1" '
             '2>/dev/null; true')
AUTOPILOT_MAX_STEPS = 150
AUTOPILOT_MAX_HOURS = 10


def _h():
    import harness
    return harness


def on(name: str) -> bool:
    h = _h()
    return h.MODS_ON and mod_switches.is_on(name, h.STATE)


def say_err(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _color() -> bool:
    return sys.stderr.isatty() and not os.environ.get('NO_COLOR')


# ------------------------------------------------------------------ commands
def before_command(command: str) -> None:
    if on('narrator'):
        try:
            say_err('» ' + narrator.describe(command))
        except Exception:
            pass


def after_command(execution: dict) -> None:
    if on('memory-version'):
        try:
            result = memory_versions.snapshot(_h().STATE)
            _hook_event('memory-version', result)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            _hook_event('memory-version', {'status': 'error', 'error': str(exc)})


def _hook_event(name, result):
    from datetime import datetime, timezone
    _h().record_event({'time_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hook:' + name, **result})


# ------------------------------------------------------------------ turn end
def spoken(text: str, full: bool) -> str:
    """speak.py's clean() and shorten(): markdown out, words kept; short mode is the first sentence."""
    import re
    text = re.sub(r'```.*?```', ' Code block skipped. ', text, flags=re.S)
    text = re.sub(r'^\s*\|[-:| ]+\|\s*$', ' ', text, flags=re.M)
    text = re.sub(r'^\s*\|(.*)\|\s*$', lambda m: ' ' + m.group(1).replace('|', ', ') + '. ', text, flags=re.M)
    text = re.sub(r'^\s*#{1,6}\s*(.+)$', r' \1. ', text, flags=re.M)
    text = re.sub(r'^\s*[-*]\s+', ' ', text, flags=re.M)
    text = re.sub(r'^\s*\d+[.)]\s+', ' ', text, flags=re.M)
    text = re.sub(r'https?://\S+', ' link ', text)
    text = re.sub(r'[*_`#>\[\]]', '', text)
    text = re.sub(r'\s*\n\s*\n\s*', '. ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\.\s*\.', '.', text)
    if full or not text:
        return text
    match = re.match(r'(.{15,}?[.!?])(\s|$)', text)
    return (match.group(1) if match else text)[:220]


def speak(answer: str) -> None:
    if os.environ.get('HARNESS_SPEECH_OWNER') == 'agentd':
        return  # The job service serializes speech and reads George's existing voice switch.
    h = _h()
    line = spoken(answer, mod_switches.setting('voice-mode', h.STATE) != 'short')
    if not line or not os.path.exists(SAY):
        return
    from cli import native
    try:
        result=native({'op':'speak','text':line,'state':str(h.STATE.resolve()),
                       'generation':mod_switches.setting('voice-generation',h.STATE)})
        _hook_event('voice',{'status':'queued','characters':len(line),**result})
    except Exception as exc:
        _hook_event('voice',{'status':'error','error':str(exc)})


def grade(engine: str, answer: str, history: list, log_path) -> None:
    lines = proof_marks.content_lines(answer)
    if not lines:
        return
    raw = helper_model.complete(engine, 'proof', proof_marks.SYSTEM,
                                proof_marks.grade_prompt(proof_marks.evidence(history), lines),
                                effort='max', log_path=log_path)
    marks = proof_marks.parse(raw, len(lines))
    if marks:
        say_err(proof_marks.render(lines, marks, _color()))


def track(engine: str, session: dict, message: str, answer: str, log_path) -> None:
    tree = session.get('thread_tree') or thread_tree.empty()
    raw = helper_model.complete(engine, 'tree', thread_tree.SYSTEM, thread_tree.move_prompt(tree, message, answer),
                                effort='max', log_path=log_path)
    tree, done = thread_tree.update(tree, raw, message)
    session['thread_tree'] = tree
    line = thread_tree.after_turn_line(tree, done)
    if line:
        say_err(line)


def turn_end(args, session: dict, message: str, reply, history: list, save) -> None:
    """After the final answer of a turn. save() writes the session file (it holds the thread tree)."""
    for name, step in (('proof', lambda: grade(args.engine, reply.direct_answer, history, args.usage_log)),
                       ('tree', lambda: (track(args.engine, session, message, reply.direct_answer, args.usage_log), save())),
                       ('voice', lambda: speak(reply.direct_answer))):
        if on(name):
            try:
                step()
            except Exception:
                pass


# ------------------------------------------------------------------ chat open
def session_start() -> None:
    if on('reindex') and os.path.exists(REINDEX[1]):
        try:
            result=subprocess.run(REINDEX, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            _hook_event('reindex', {'status':'ok' if result.returncode==0 else 'error','exit_code':result.returncode,
                                    'error':result.stderr.strip()})
        except (OSError, subprocess.SubprocessError) as exc:
            _hook_event('reindex', {'status':'error','error':str(exc)})
    if on('voiceline') and os.path.exists(VOICELINE_WANTED):
        try:
            result=subprocess.run(['bash', '-c', VOICELINE], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
            _hook_event('voiceline', {'status':'ok' if result.returncode==0 else 'error','exit_code':result.returncode})
        except (OSError, subprocess.SubprocessError) as exc:
            _hook_event('voiceline', {'status':'error','error':str(exc)})
    elif on('voiceline'):
        _hook_event('voiceline', {'status':'not_requested'})


# ------------------------------------------------------------------ session file
def _session_file(sid: str) -> Path:
    return _h().STATE / 'sessions' / (sid + '.json')


def read_tree(sid: str) -> dict:
    try:
        return json.loads(_session_file(sid).read_text()).get('thread_tree') or thread_tree.empty()
    except (OSError, ValueError):
        return thread_tree.empty()


def edit_session(sid: str, change) -> None:
    from storage import Store, atomic_json
    store = Store(_h().STATE)
    try:
        if not _session_file(sid).exists():
            return
        with store.session(sid, 10 ** 9) as data:   # every exchange kept; only the tree changes
            change(data)
            atomic_json(_session_file(sid), data)
    finally:
        store.close()


def last_answer(sid: str) -> str:
    try:
        turns = json.loads(_session_file(sid).read_text()).get('turns') or []
        return turns[-1]['reply']['direct_answer'] if turns else ''
    except (OSError, ValueError, KeyError, TypeError):
        return ''


# ------------------------------------------------------------------ autopilot
def autopilot_step(goal: str, folder: Path) -> str:
    return f"""You are George's AUTOPILOT. You work one step at a time, over and over, until the goal is done or George stops you. Make real progress each step.

GOAL:
{goal}

DO THIS STEP:
- Take the next concrete step toward the goal, and actually do it: write the code, run the tests, do the research, draft the thing.
- Append to a running log at {folder}/log.md: what you did this step, and what's next.

AT A FORK (a choice George would normally make):
- Do NOT stop to ask. Make the most reasonable REVERSIBLE choice, write the question AND the assumption you made to {folder}/questions.md, and keep going. A wrong guess on reversible work costs time, not damage; George decides at sunup.

WHERE YOU WORK:
- Existing repo: work on a NEW BRANCH, never on main. George reviews and merges at sunup.
- Brand-new thing (nothing exists yet): build freely.
- Either way the knives stay sheathed: no sending email, no sending or paying invoices, no posting, no merging to main, no deploying, no deleting, no force-push, no taps on the phone screen. Stage those for George's tap.

END THIS STEP with exactly ONE of these, alone on the last line of direct_answer:
  AUTOPILOT: CONTINUE   (more work to do)
  AUTOPILOT: COMPLETE   (goal fully done)
  AUTOPILOT: BLOCKED    (truly cannot make ANY reversible progress without George)
Before COMPLETE or BLOCKED, write a short summary to {folder}/result.md."""


def outcome(answer: str) -> str:
    import re
    last=answer.strip().splitlines()[-1] if answer.strip() else ''
    if re.fullmatch(r'AUTOPILOT:\s*COMPLETE', last, re.I):
        return 'complete'
    if re.fullmatch(r'AUTOPILOT:\s*BLOCKED', last, re.I):
        return 'blocked'
    return 'continue'


def autopilot(goal: str, sid: str, run_turn, clock=time.monotonic) -> int:
    """Foreground: one loop run per step until COMPLETE, BLOCKED, 150 steps, 10 hours, or Ctrl-C."""
    h = _h()
    folder = h.STATE / 'autopilot'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = folder / 'run.json'
    started, status = clock(), 0
    for step in range(1, AUTOPILOT_MAX_STEPS + 1):
        if clock() - started >= AUTOPILOT_MAX_HOURS * 3600:
            record.write_text(json.dumps({'goal':goal,'session':sid,'step':step,'state':'time_limit'})+'\n')
            say_err(f'Autopilot stopped: time cap ({AUTOPILOT_MAX_HOURS}h). Progress is in {folder}/log.md.')
            return status
        record.write_text(json.dumps({'goal': goal, 'session': sid, 'step': step, 'state': 'running'}) + '\n')
        say_err(f'AUTOPILOT step {step} · {goal[:60]}')
        status = run_turn(autopilot_step(goal, folder))
        if status == 130:
            record.write_text(json.dumps({'goal': goal, 'session': sid, 'step': step, 'state': 'stopped'}) + '\n')
            say_err('Autopilot stopped.')
            return 130
        if status:
            record.write_text(json.dumps({'goal':goal,'session':sid,'step':step,'state':'error','exit_code':status})+'\n')
            say_err(f'Autopilot stopped: step exited {status}.')
            return status
        result = outcome(last_answer(sid))
        if result != 'continue':
            record.write_text(json.dumps({'goal': goal, 'session': sid, 'step': step, 'state': result}) + '\n')
            say_err(f'Autopilot stopped: {"goal complete" if result == "complete" else "blocked, needs you"} - see {folder}/result.md.')
            return status
    record.write_text(json.dumps({'goal':goal,'session':sid,'step':AUTOPILOT_MAX_STEPS,'state':'step_limit'})+'\n')
    say_err(f'Autopilot stopped: step cap ({AUTOPILOT_MAX_STEPS} steps). Progress is in {folder}/log.md.')
    return status


# ------------------------------------------------------------------ chat lines
def mods_listing() -> str:
    state = _h().STATE
    lines = ['Mods (each: /on NAME, /off NAME):']
    for name, line in mod_switches.MODS.items():
        lines.append(f'  {"on " if mod_switches.is_on(name, state) else "off"}  {name:<15}{line}')
    lines.append(f'  voice mode: {mod_switches.setting("voice-mode", state)}')
    return '\n'.join(lines)


def listen(native) -> str:
    try:
        return (native({'op': 'listen', 'timeout': 90}).get('text') or '').strip()
    except Exception:
        return ''


def chat_line(raw: str, sid: str, run_turn, native=None):
    """(handled, replacement). handled=True: the line was a mod command; replacement: text to send instead."""
    h = _h()
    line = raw.strip()
    if line.lower() in ('v', 'в') and h.MODS_ON and mod_switches.is_on('voice-v', h.STATE) and native is not None:
        said = listen(native)
        if not said:
            say_err('The mic heard nothing.')
            return True, None
        say_err('heard: ' + said)
        return False, said
    if not line.startswith('/'):
        return False, None
    try:
        words = shlex.split(line)
    except ValueError:
        return False, None
    head, rest = words[0].lower(), words[1:]
    state = h.STATE
    aliases={'proof-marks':'proof','thread-tree':'tree','answer-length':'length','receipts-gate':'receipts','speak':'voice'}
    if head in ('/on','/off') and len(rest)==1:
        rest=[aliases.get(rest[0],rest[0])]
        if rest[0] in ('watcher','drift-monitor'):
            import reply_judge
            reply_judge.chat_switch(head+' judge',state)
            return True,None
    if head in ('/on', '/off') and len(rest) == 1 and rest[0] in mod_switches.MODS:
        mod_switches.set_value(rest[0], head == '/on', state)
        print(f'{rest[0]} {"on" if head == "/on" else "off"}.')
        return True, None
    if head == '/mods' and not rest:
        print(mods_listing())
        return True, None
    if head == '/where' and not rest:
        print(thread_tree.render(read_tree(sid)))
        return True, None
    if head == '/up' and not rest:
        result = {}
        edit_session(sid, lambda data: result.update(parent=thread_tree.up(data.setdefault('thread_tree', thread_tree.empty()))))
        print(f'↑ back to: {result["parent"]}' if result.get('parent') else 'Already at the top topic.')
        return True, None
    if head == '/voice' and len(rest) == 1 and rest[0] in ('on', 'off', 'full', 'short'):
        if rest[0] in ('on', 'off'):
            mod_switches.set_value('voice', rest[0] == 'on', state)
            if rest[0] == 'off' and os.path.exists(SAY):
                subprocess.run([SAY, '-s'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            mod_switches.set_value('voice', True, state)
            mod_switches.set_value('voice-mode', rest[0], state)
        print(f'voice {rest[0]}.' if rest[0] in ('on', 'off') else f'voice on, {rest[0]}: '
                + ('the whole answer.' if rest[0] == 'full' else 'the first sentence.'))
        return True, None
    if head == '/usage':
        import usage_meter
        print(usage_meter.report(state, h.ROOT / 'state', providers='--local' not in rest).rstrip())
        return True, None
    if head == '/usage-alarm':
        import usage_watch
        result=usage_watch.tick(state,notify=rest==['test'])
        print('Usage meter '+result['status']+'.')
        return True, None
    if head == '/autopilot':
        if not mod_switches.is_on('autopilot', state):
            say_err('autopilot is off. /on autopilot')
            return True, None
        arg = ' '.join(rest).strip()
        record = state / 'autopilot' / 'run.json'
        try:
            last = json.loads(record.read_text())
        except (OSError, ValueError):
            last = {}
        if arg.lower() == 'status':
            print(f'Autopilot {last.get("state", "idle")} · step {last.get("step", 0)}\nGoal: {last.get("goal", "-")}' if last
                    else 'Autopilot is idle. Start it: /autopilot GOAL')
        elif arg.lower() == 'stop':
            last.update(state='stopped')
            record.parent.mkdir(parents=True,exist_ok=True)
            record.write_text(json.dumps(last)+'\n')
            print('Autopilot stopped.')
        elif arg.lower() == 'go':
            if last.get('goal'):
                autopilot(last['goal'], sid, run_turn)
            else:
                say_err('Nothing to resume. Start one: /autopilot GOAL')
        elif not arg:
            say_err('Give it a goal: /autopilot GOAL. Ctrl-C stops it.')
        else:
            autopilot(arg, sid, run_turn)
        return True, None
    return False, None
