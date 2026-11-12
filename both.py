"""Ask every working lane the same question at once.

`both "QUESTION"` on the command line, and `/both QUESTION` in a chat, send one
question to each selected lane in parallel. Each answer passes the display gate on
its own, prints under a fixed label line naming the model, and is saved to that
lane's own session and to history. `--lanes a,b,c` picks the set; the default is
every lane that has a usable key (plus the public GLM lane).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sys
import threading

import harness as h
import extra_lanes
import lane_base
import knobs as knobs_mod
import recall_notes
import reply_judge
import lane_mods
from copy import copy
from phonetics import normalize
from lookup_gate import turn_metadata
from storage import Store, history_messages, atomic_json

# Fixed lane order for display and default selection.
LANE_ORDER = ['openai', 'anthropic', 'gemini', 'openrouter', 'glm', 'vertex']

# Opening a SQLite store sets WAL mode and may run a one-time migration, which needs a
# brief write lock. Serialize just the open so parallel lanes do not race that setup.
_OPEN_LOCK = threading.Lock()


def has_credentials(engine: str) -> bool:
    try:
        if engine in ('openai', 'anthropic'):
            return bool(h.load_key(engine))
        lane = extra_lanes.LANES[engine]
        if not lane_base.needs_key(lane):
            return True  # public endpoint (glm) or ambient credential
        return bool(lane_base.lane_key(lane))
    except Exception:
        return False


def default_lanes():
    # Every lane that can be called now, minus vertex (no key; request it by name).
    return [e for e in LANE_ORDER if e not in ('vertex','glm') and has_credentials(e)]


def select_lanes(spec):
    if not spec:
        lanes = default_lanes()
        if not lanes:
            raise h.HarnessError('No lane has a usable key.')
        return lanes
    chosen = [part.strip() for part in spec.split(',') if part.strip()]
    valid = set(['openai', 'anthropic', *extra_lanes.LANES.keys()])
    for engine in chosen:
        if engine == 'glm':
            raise h.HarnessError('GLM is not available in this installation.')
        if engine not in valid:
            raise h.HarnessError(f'Unknown lane {engine!r}. Choose from: ' + ', '.join(sorted(valid)) + '.')
    # Keep a stable order for printing.
    return [e for e in LANE_ORDER if e in chosen]


def resolve_model(engine, requested):
    if engine in extra_lanes.LANES:
        return extra_lanes.lane_model(extra_lanes.LANES[engine], requested)
    import os
    return requested or os.environ.get('OPENAI_MODEL' if engine == 'openai' else 'ANTHROPIC_MODEL') \
        or (h.DEFAULT_MODEL if engine == 'openai' else h.ANTHROPIC_MODEL)


def label(engine, model):
    return f'── {engine} · {model} ' + '─' * max(2, 40 - len(engine) - len(model))


def _one_lane(engine, cleaned, raw, args, kb, base):
    # Each lane uses its own default model; a single --model cannot fit every provider.
    model = resolve_model(engine, None)
    with _OPEN_LOCK:
        store = Store(h.STATE)   # its own sqlite connection, used only in this thread
    try:
        sid = f'{base}-{engine}'
        events = []
        with store.session(sid, args.turns) as session:
            row_id = store.begin(raw, cleaned, engine, model, sid)
            past = history_messages(session['turns'])
            recalled = recall_notes.for_turn(cleaned, state=h.STATE, session=session, before_row=row_id,
                                             log_path=args.usage_log, enabled=not getattr(args, 'no_recall', False))
            if recalled: past.append(recall_notes.message(recalled))
            second = reply_judge.Second()
            reply = second.request_reply(cleaned, judge_turn={'turns': session['turns'], 'step': 1,
                                         'loop': False, 'recall_notes': recalled},
                                    engine=engine, model=model, effort=args.effort,
                                    timeout=args.timeout, log_path=args.usage_log, events=events, history=past,
                                    request_context=cleaned, web=not args.no_web, web_max=args.web_max, knobs=kb)
            store.finish(row_id, reply, events)
            metadata = turn_metadata(events)
            exchange = {'history_row': row_id, 'history_timestamp': store.db.execute('SELECT timestamp FROM history WHERE id=?',(row_id,)).fetchone()[0], 'raw_input': raw, 'normalized_input': cleaned, 'reply': reply.model_dump(),
                        'engine': engine, 'model': model}
            if recalled: exchange['recall_notes'] = recalled
            exchange.update(metadata)
            second.record(store, row_id, exchange)
            store.save_session(session, exchange, args.turns)
            text = h.display_text(reply, metadata['sources'])
        return engine, model, text, (sid, reply), None
    except Exception as exc:
        if 'row_id' in locals():
            store.finish(row_id, events=events, error=str(exc))
        return engine, model, None, None, str(exc)
    finally:
        store.close()


def run(args, question):
    """Called from cli.main when --both is set. Returns a process exit code."""
    try:
        lanes = select_lanes(getattr(args, 'lanes', None))
    except h.HarnessError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    raw = question
    cleaned = raw if args.no_normalize else normalize(raw)
    if not cleaned.strip():
        print('Input is empty.', file=sys.stderr)
        return 2
    base = args.session if args.session else 'both'
    kb = knobs_mod.from_args(args)
    results = {}
    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        futures = [pool.submit(_one_lane, engine, cleaned, raw, args, kb, base) for engine in lanes]
        for future in futures:
            engine, model, text, final, error = future.result()
            results[engine] = (model, text, error, final)
    status = 0
    for engine in lanes:
        model, text, error, final = results[engine]
        print(label(engine, model),file=sys.stderr,flush=True)
        if error:
            print(f'[error: {error}]',file=sys.stderr,flush=True)
            status = 2
        else:
            sys.stdout.write(text if text.endswith('\n') else text + '\n')
            sys.stdout.flush()
            sid, reply = final
            lane_args = copy(args)
            lane_args.engine = engine
            from receipt_context import messages_from_turns
            store = Store(h.STATE)
            try:
                with store.session(sid,args.turns) as session:
                    lane_mods.turn_end(lane_args,session,cleaned,reply,messages_from_turns(session['turns']),
                                      lambda:atomic_json(store.sessions/(sid+'.json'),session))
            finally:
                store.close()
        sys.stdout.write('\n')
    sys.stdout.flush()
    return status
