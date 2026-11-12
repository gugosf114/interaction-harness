"""The chat's screen, command registry and measured status. No reply bypasses a gate."""
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import shlex
import sys
import threading
import time

import chat_progress
from chat_input import ChatInput, InputTooLong

# One registry drives /help, dispatch, and unknown-command detection. New owners
# register here (or call register); every recognized slash command has help.
COMMANDS = {}

def register(name, syntax, description, owner='screen'):
    COMMANDS[name] = (syntax, description, owner)

for _name, _syntax, _description in [
    ('help', '', 'List every chat command.'), ('model', 'NAME', 'Change the model and its lane.'),
    ('effort', 'LEVEL', 'Change thinking: low, medium, high, xhigh, max.'),
    ('new', '', 'Start a fresh session.'), ('sessions', '', 'List saved sessions.'),
    ('session', 'NAME', 'Open or create a named session.'), ('continue', '', 'Open the last saved session.'),
    ('recall', 'WORDS', 'Find saved answers.'), ('cost', '', 'Show known costs for this turn and session.'),
    ('status', '', 'Show every setting and its value.'), ('clear', '', 'Clear only the screen.'),
    ('copy', '', 'Copy the last answer to the phone clipboard.'), ('save', 'FILE', 'Save the last answer to a file.'),
    ('retry', '', 'Ask the last message again.'), ('edit', '', 'Bring back the last message to edit.'),
    ('paste', '', 'Read a block; finish with a line containing a dot.'),
    ('exit', '', 'Leave the chat.'), ('quit', '', 'Leave the chat.')]:
    register(_name, _syntax, _description)
for _name, _syntax, _description, _owner in [
    ('on', 'NAME', 'Turn on a tool, mod, recall, judge or stamp.', 'switch'),
    ('off', 'NAME', 'Turn off a tool, mod, recall, judge or stamp.', 'switch'),
    ('tools', '', 'List API tools and their state.', 'api'),
    ('advisor', '[QUESTION]', 'Ask the other lane to review this session.', 'advisor'),
    ('wrong', 'WORDS', 'Save a correction and act on it.', 'turn'),
    ('fork', '[NAME]', 'Copy this session and continue in the copy.', 'recall'),
    ('rewind', '[N]', 'Remove the last N exchanges from this session.', 'recall'),
    ('mods', '', 'List the add-ons and their state.', 'mods'),
    ('where', '', 'Show the topic trail.', 'mods'), ('up', '', 'Go up one topic.', 'mods'),
    ('voice', 'on|off|full|short', 'Set spoken answers.', 'mods'),
    ('usage', '[--local]', 'Show token use today, this week and this month.', 'mods'),
    ('usage-alarm', '[test]', 'Save the token meter; test sends a phone reading.', 'mods'),
    ('autopilot', 'GOAL|status|go', 'Run or resume the saved goal.', 'mods'),
    ('both', 'QUESTION', 'Ask the selected lanes the same question.', 'both'),
    ('image', 'PATH [WORDS]', 'Attach a picture.', 'attachment'),
    ('file', 'PATH [WORDS]', 'Attach a PDF.', 'attachment')]:
    register(_name, _syntax, _description, _owner)
for _name, _syntax, _description in [
    ('temperature', 'N|off', 'Set sampling temperature.'), ('seed', 'N|off', 'Set the sampling seed.'),
    ('stop', 'WORDS|off', 'Set a stop string.'), ('prefill', 'WORDS|off', 'Set the answer opening.'),
    ('service-tier', 'TIER|off', 'Set the provider service tier.')]:
    register(_name, _syntax, _description, 'knob')

COLORS = {'prompt':'96', 'answer':'97', 'command':'93', 'output':'92',
          'sources':'95', 'error':'91', 'status':'37', 'phase':'96'}
def model_metadata(name):
    try: return json.loads(Path(__file__).with_name('prices.json').read_text()).get('models', {}).get(name, {})
    except (OSError, ValueError): return {}
ACTIVE = None


def help_text():
    return '\n'.join('/' + name + (' '+syntax if syntax else '') + ' — ' + desc
                     for name, (syntax, desc, _) in COMMANDS.items())


def safe(text):
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', str(text))


def context_tokens(events):
    # A turn may have several provider calls and retries. The window holds the
    # last request, not the sum of billed input across those calls.
    for event in reversed(events):
        reports = (event.get('lookup_counts') or {}).get('provider_reports') or []
        usage = reports[-1].get('usage', {}) if reports else event.get('usage') or {}
        if usage:
            return int(usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0)
                       + usage.get('cache_creation_input_tokens', 0))
    return None


def status_text(args, sid, exchange, events, seconds, off, money=''):
    from storage import request_metrics
    metrics = request_metrics(events)
    def number(key):
        value = metrics.get(key)
        return '?' if value is None else f'{value:,}'
    window = model_metadata(args.model).get('window_tokens')
    bound = False
    tokens = context_tokens(events)
    fill = '?' if window is None or tokens is None else ('≤' if bound else '') + f'{100*tokens/window:.2f}%'
    text = (f'{args.engine}/{args.model} · {args.effort} · {sid} #{exchange} · '
            f'in {number("input_tokens")} out {number("output_tokens")} cache {number("cache_read_tokens")} · '
            f'ctx {fill} · {seconds:.1f}s · off: {",".join(off) or "none"}')
    return text + (' · '+money if money else '')


class Screen:
    def __init__(self, args, state):
        self.args, self.state = args, Path(state)
        self.out, self.err = sys.stdout, sys.stderr
        self.tty = self.out.isatty() and self.err.isatty()
        self.colors = self.tty and not args.plain and 'NO_COLOR' not in os.environ
        self.started = time.monotonic()
        self.name, self.detail = '', ''
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None
        self.last_status = ''
        self.last_answer = ''
        self.cost_events = []

    def color(self, kind, text, readline=False):
        if not self.colors: return text
        left, right = ('\001', '\002') if readline else ('', '')
        return f'{left}\033[{COLORS[kind]}m{right}{text}{left}\033[0m{right}'

    def clear_phase(self):
        with self.lock:
            if self.name and self.tty:
                self.err.write('\r\033[2K'); self.err.flush()
            self.name = ''

    def phase(self, name, detail=''):
        with self.lock:
            self.name, self.detail = safe(name), safe(detail)
            self.paint()

    def paint(self):
        if not self.tty or not self.name: return
        try: width = os.get_terminal_size(self.err.fileno()).columns
        except OSError: width = 80
        label = self.name + (': '+self.detail if self.detail else '') + f' · {time.monotonic()-self.started:.0f}s'
        self.err.write('\r\033[2K' + self.color('phase', label[:max(10, width-1)])); self.err.flush()

    def tick(self):
        while not self.stop.wait(1):
            with self.lock: self.paint()

    def track(self, event):
        if event.get('usage') or event.get('kind') != 'recall':
            self.cost_events.append(json.loads(json.dumps(event)))

    def begin(self):
        self.cost_events = []
        self.has_receipt = False
        self.started = time.monotonic()
        self.phase('Thinking')
        if self.tty and self.worker is None:
            self.worker = threading.Thread(target=self.tick, daemon=True); self.worker.start()

    def note(self, text, kind='status'):
        self.clear_phase()
        print(self.color(kind, str(text)), file=self.err, flush=True)

    def finish(self):
        self.stop.set()
        if self.worker: self.worker.join(timeout=2)
        self.clear_phase()


def begin_turn():
    if ACTIVE: ACTIVE.begin()


def error(text):
    if ACTIVE: ACTIVE.note(text, 'error')
    else: print(text, file=sys.stderr)


def display_reply(reply, sources=()):
    import harness as h
    plain = h.display_text(reply, sources)
    if not ACTIVE: return plain
    ACTIVE.clear_phase()
    answer = h.scrub_opening(reply.direct_answer)
    ACTIVE.last_answer = answer
    text = ACTIVE.color('answer', plain[:len(answer)])
    if reply.execution_payload:
        command = reply.execution_payload.strip()
        start = len(plain)-len(command)-1
        between = plain[len(answer):start]
        text += ACTIVE.color('sources', between) if sources else between
        text += ACTIVE.color('command', command) + '\n'
    else:
        tail = plain[len(answer):]
        text += ACTIVE.color('sources', tail) if sources else tail
    return text


def command_output(text, error=False):
    if ACTIVE:
        ACTIVE.clear_phase()
        return ACTIVE.color('error' if error else 'output', text)
    return text


def switches(args, state):
    import api_tools_cli
    import mod_switches
    import recall_notes
    config = api_tools_cli.settings(args, state)
    values = {'tool.'+k.replace('_','-'): v for k, v in config.enabled.items()
              if args.engine in api_tools_cli.TOOLS[k][0]}
    values.update({'mod.'+k: mod_switches.is_on(k, state) for k in mod_switches.MODS})
    try: saved = json.loads((Path(state)/'switches.json').read_text())
    except (OSError, ValueError): saved = {}
    values.update({'judge': saved.get('judge', True), 'stamp': saved.get('stamp', True),
                   'recall': not args.no_recall and recall_notes.is_on(state), 'normalize': not args.no_normalize})
    return values


def after_reply(args, session, events, lane=None):
    if not ACTIVE: return
    import session_tools
    elapsed = time.monotonic() - ACTIVE.started
    values = switches(args, ACTIVE.state)
    off = [name for name, on in values.items() if not on]
    # This receipt is display metadata, kept outside the four-field reply.
    row = {'session': session['id'], 'exchange': len(session_tools.groups(session['turns'])),
           'engine': lane[0] if lane else args.engine, 'model': lane[1] if lane else (args.model or ACTIVE.args.model), 'effort': args.effort,
           'seconds': elapsed, 'events': events, 'off': off}
    from types import SimpleNamespace
    shown_args = SimpleNamespace(engine=row['engine'], model=row['model'], effort=row['effort'])
    from chat_cost import total, prior_cost, record
    cost_events = ACTIVE.cost_events or events
    amount = total(cost_events, None if lane else args.service_tier)
    prior = prior_cost(ACTIVE.state, row['session'])
    money = ''
    if amount is not None:
        money = f'${amount:.5f}/turn'
        if prior is not None: money += f' ${prior+amount:.5f}/session'
    row.update(cost_events=cost_events, cost_usd=amount)
    import mod_switches
    text = status_text(shown_args, row['session'], row['exchange'], events, elapsed,
                       off if mod_switches.is_on('roster',ACTIVE.state) else [], money)
    ACTIVE.last_status = text
    if mod_switches.is_on('status-line',ACTIVE.state): ACTIVE.note(text)
    record(ACTIVE.state, row['session'], amount)
    ACTIVE.has_receipt = True
    path = ACTIVE.state/'chat-status.jsonl'
    fd = os.open(path, os.O_CREAT|os.O_APPEND|os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'a') as file:
        file.write(json.dumps({**row, 'line': text}, ensure_ascii=False)+'\n')


def display_advice(label, advice):
    if not ACTIVE: return label + '\n' + advice + '\n'
    ACTIVE.note(label)
    ACTIVE.last_answer = advice
    return ACTIVE.color('answer', advice) + '\n'


def run_chat(args, model, cli):
    global ACTIVE
    from storage import Store
    import harness as h
    import api_tools_cli, advisor, recall_cli, stamp, reply_judge, senses_cli, lane_mods, knobs
    import session_tools
    try:
        store = Store(h.STATE)
        try: sid = store.select_session(args.session, args.continuing)
        finally: store.close()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 2
    args.model = model
    screen = Screen(args, h.STATE)
    old_active, old_listener, old_usage = ACTIVE, chat_progress.listener, chat_progress.usage_listener
    ACTIVE, chat_progress.listener, chat_progress.usage_listener = screen, screen.phase, screen.track
    editor = ChatInput(h.STATE, screen.color, h.MAX_INPUT_CHARS)
    last_status, last_input, last_literal = 0, '', False

    def options(force_loop=False):
        result = ['--engine', args.engine, '--model', args.model, '--effort', args.effort,
            '--timeout', str(args.timeout), '--usage-log', str(args.usage_log), '--session', sid,
            '--exec-timeout', str(args.exec_timeout)]
        if args.turns is not None: result += ['--turns', str(args.turns)]
        if args.history_chars is not None: result += ['--history-chars', str(args.history_chars)]
        if args.plain: result.append('--plain')
        if args.no_normalize: result.append('--no-normalize')
        if args.execute: result.append('--exec')
        if args.loop or force_loop: result += ['--loop', '--max-turns', str(args.max_turns)]
        if args.yes: result.append('--yes')
        return result + senses_cli.common_options(args) + recall_cli.common_options(args) + knobs.from_args(args).cli_options()

    def call(text, extra=(), force_loop=False, literal=False):
        nonlocal last_status
        screen.begin()
        try:
            with redirect_stdout(screen.out):
                last_status = cli.main([*options(force_loop), *api_tools_cli.options(args), *extra, '--', text], literal=literal)
        finally:
            screen.clear_phase()
            if not screen.has_receipt:
                from chat_cost import record, total
                record(h.STATE,sid,total(screen.cost_events,args.service_tier))
        return last_status

    def select(name=None, continuing=False):
        nonlocal sid, last_input, last_literal
        store = Store(h.STATE)
        try: sid = store.select_session(name, continuing)
        finally: store.close()
        last_input = ''; last_literal = False; screen.last_answer = ''; screen.last_status = ''
        try:
            turns = session_tools.read(h.STATE, sid)['turns']
            if turns:
                from chat_cost import old_session
                old_session(h.STATE,sid)
                screen.last_answer = turns[-1]['reply']['direct_answer']
                for turn in reversed(turns):
                    if turn.get('loop_step', 1) == 1:
                        last_input = turn.get('raw_input', ''); last_literal = turn.get('literal_input',False); break
        except session_tools.SessionError: pass
        screen.note('Session '+sid+'.')

    def native_screen(command):
        result = cli.native({'op':'exec', 'command':command, 'timeout':30, 'auto_confirm':True})
        if result.get('exit_code') != 0:
            raise ValueError(result.get('stderr') or 'Phone command failed.')
        return result

    try:
        lane_mods.session_start()
        # Seed /copy, /edit and /retry when a saved session was reopened.
        try:
            turns = session_tools.read(h.STATE, sid)['turns']
            if turns:
                from chat_cost import old_session
                old_session(h.STATE,sid)
                screen.last_answer = turns[-1]['reply']['direct_answer']
                last_input = next((x.get('raw_input','') for x in reversed(turns) if x.get('loop_step',1)==1), '')
                last_literal = next((x.get('literal_input',False) for x in reversed(turns) if x.get('loop_step',1)==1),False)
        except session_tools.SessionError: pass
        if args.text:
            last_input = ' '.join(args.text); editor.remember(last_input)
            call(last_input, senses_cli.attachment_options(args))
        while True:
            try:
                raw = editor.read()
                if getattr(raw,'literal',False):
                    if raw.strip():
                        last_input, last_literal = str(raw), True
                        editor.remember(str(raw)); call(str(raw),literal=True)
                    continue
                if raw.strip().lower() in {'exit', 'quit', '/exit', '/quit'}: return last_status
                if not raw.strip(): continue
                head, _, rest = raw.strip().partition(' ')
                name = head[1:].lower() if head.startswith('/') else None
                if name is not None: raw = '/' + name + (' '+rest if rest else '')
                if name is not None and name not in COMMANDS:
                    screen.note('Unknown command: '+safe(head), 'error'); screen.note(help_text()); continue
                if name == 'help': screen.note(help_text()); continue
                if name in ('new', 'session', 'continue'):
                    if name == 'session' and not rest: raise ValueError('Use /session NAME.')
                    select(rest if name == 'session' else None, name == 'continue'); continue
                if name == 'sessions': screen.note(session_tools.listing_text(h.STATE)); continue
                if name == 'model':
                    if not rest or len(rest.split()) != 1: raise ValueError('Use /model NAME.')
                    aliases = {'g1':('openai',h.DEFAULT_MODEL), 'openai':('openai',h.DEFAULT_MODEL),
                               'george':('anthropic',h.ANTHROPIC_MODEL), 'anthropic':('anthropic',h.ANTHROPIC_MODEL)}
                    engine, chosen = aliases.get(rest, (args.engine, rest))
                    if rest.startswith(('gpt-', 'o1', 'o3', 'o4')): engine = 'openai'
                    elif rest.startswith('claude-'): engine = 'anthropic'
                    elif rest.startswith('gemini-'): engine = 'gemini'
                    if engine != args.engine:
                        if getattr(args, '_history_chars_default', False): args.history_chars = cli.HISTORY_CHARS_DEFAULT.get(engine)
                        for key, spec in api_tools_cli.TOOLS.items():
                            if engine not in spec[0]: setattr(args, 'api_'+key, None)
                    args.engine, args.model = engine, chosen
                    screen.note(engine+'/'+chosen+'.'); continue
                if name == 'effort':
                    if rest not in ('low','medium','high','xhigh','max'): raise ValueError('Use /effort low|medium|high|xhigh|max.')
                    args.effort = rest; screen.note('Thinking '+rest+'.'); continue
                if name == 'status':
                    import mod_switches, recall_notes
                    screen.note('\n'.join(f'{key}: {value}' for key,value in sorted(vars(args).items()) if not key.startswith('_') and key != 'text'))
                    screen.note('session: '+sid)
                    screen.note('colors: '+('on' if screen.colors else 'off')+'\nNO_COLOR: '+('set' if 'NO_COLOR' in os.environ else 'unset'))
                    screen.note('voice-mode: '+str(mod_switches.setting('voice-mode',h.STATE)))
                    screen.note('Recall settings: '+json.dumps(recall_notes.settings(h.STATE),sort_keys=True))
                    screen.note('Model limits: '+json.dumps({k:v for k,v in model_metadata(args.model).items() if k in ('window_tokens','max_input_tokens','max_output_tokens','window_source')}))
                    screen.note('\n'.join(f'{key}: {"on" if value else "off"}' for key,value in switches(args,h.STATE).items()))
                    config = api_tools_cli.settings(args,h.STATE)
                    screen.note('API options: '+json.dumps(config.options, ensure_ascii=False, sort_keys=True))
                    screen.note('API tools waiting for setup or another runtime: '+', '.join(sorted(config.unset)))
                    if screen.last_status: screen.note(screen.last_status)
                    continue
                if name == 'cost':
                    from chat_cost import report
                    screen.note(report(h.STATE,sid)); continue
                if name == 'clear':
                    if screen.tty: screen.err.write('\033[2J\033[H'); screen.err.flush()
                    continue
                if name in ('copy','save'):
                    if not screen.last_answer: raise ValueError('This session has no answer yet.')
                    if name == 'copy':
                        result = native_screen('printf %s '+shlex.quote(screen.last_answer)+' | termux-clipboard-set && termux-clipboard-get')
                        if result.get('stdout','').rstrip('\n') != screen.last_answer.rstrip('\n'):
                            raise ValueError('The phone clipboard did not keep the answer. Unlock the phone and use /copy again.')
                        screen.note('Copied the last answer.')
                    else:
                        words = shlex.split(rest)
                        if len(words) != 1: raise ValueError('Use /save FILE.')
                        path = Path(words[0].replace('~', '/data/data/com.termux/files/home',1) if words[0].startswith('~/') else words[0])
                        if not path.is_absolute(): path = Path(os.environ.get('HARNESS_CALLER_CWD', os.getcwd()))/path
                        fd = os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
                        with os.fdopen(fd,'w') as file: file.write(screen.last_answer+'\n')
                        screen.note('Saved '+str(path)+'.')
                    continue
                if name in ('edit','retry'):
                    if not last_input: raise ValueError('This session has no message yet.')
                    if name == 'edit':
                        editor.initial = last_input
                        editor.initial_literal = last_literal
                        if not editor.readline: screen.note(last_input)
                        continue
                    if last_literal:
                        call(last_input,literal=True); continue
                    raw = last_input; name = None
                if name == 'recall':
                    if not rest: raise ValueError('Use /recall WORDS.')
                    last_status = cli.main(['--recall',rest]); continue
                if name and COMMANDS[name][2] == 'knob':
                    key = name.replace('-','_')
                    if not rest: raise ValueError('Use /'+name+' '+COMMANDS[name][0]+'.')
                    value = None if rest == 'off' else rest
                    if value is not None and key == 'temperature':
                        value = float(value)
                        if not 0 <= value <= 2: raise ValueError('Temperature must be 0 to 2.')
                    if value is not None and key == 'seed': value = int(value)
                    if value is not None and key == 'stop': value = [value]
                    setattr(args,key,value); screen.note(name+': '+str(value)); continue
                # Existing owners keep their behavior. Their control output is decoration.
                with redirect_stdout(screen.err):
                    handled, spoken = lane_mods.chat_line(raw,sid,lambda text:call(text,force_loop=True),cli.native)
                if handled: continue
                if spoken: raw = spoken
                opts = options()
                handled = recall_cli.chat_command(raw,opts,args)
                sid = recall_cli.pinned_session(opts)
                if handled is None: handled = reply_judge.chat_switch(raw,h.STATE)
                if handled is not None: last_status=handled; continue
                if advisor.is_trigger(raw):
                    screen.begin(); chat_progress.phase('Waiting on advisor')
                    try: last_status=cli.main([*options(),*advisor.chat_arguments(raw,args)])
                    finally:
                        screen.clear_phase()
                        if not screen.has_receipt:
                            from chat_cost import record, total
                            record(h.STATE,sid,total(screen.cost_events))
                    continue
                if stamp.is_switch(raw): last_status=stamp.run_switch(raw,h.STATE); continue
                with redirect_stdout(screen.err): handled=api_tools_cli.chat_command(raw,args,h.STATE,args.model)
                if handled: continue
                if name == 'both':
                    if not rest: raise ValueError('Use /both QUESTION.')
                    bopts = [x for x in options() if x not in ('--exec','--yes')]
                    if '--loop' in bopts:
                        bopts.remove('--loop'); idx=bopts.index('--max-turns'); del bopts[idx:idx+2]
                    last_status=cli.main([*bopts,'--both','--',rest]); continue
                flags, text = senses_cli.chat_input(raw)
                last_input = raw; last_literal = False; editor.remember(raw)
                call(text,flags)
            except EOFError: return last_status
            except KeyboardInterrupt:
                screen.clear_phase(); screen.note('Stopped.', 'error'); last_status=130
            except (ValueError,OSError,h.HarnessError) as exc:
                screen.note(str(exc),'error'); last_status=2
    finally:
        screen.finish(); ACTIVE, chat_progress.listener, chat_progress.usage_listener = old_active, old_listener, old_usage
