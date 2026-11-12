#!/data/data/com.termux/files/usr/bin/python
"""Live proof of the second gate: the judge, /wrong with a fact, /wrong with a habit, and the cache.

  python verify_second_gate.py --engine anthropic --case judge
  python verify_second_gate.py --engine openai --case fact
  python verify_second_gate.py --engine openai --case habit

--engine is the working lane; the judge is always the other engine.

judge   A planted wrong-question reply stands in for the working model's first reply. The judge call is
        real, and so is the working model's corrective retry. A planted right reply must pass.
        This case imports the client, so it runs on the Debian side; from native Termux it goes through the bridge.
fact    Through this checkout's real launcher, --effort max --loop -y, isolated HARNESS_STATE_DIR: a question,
        then /wrong with a fact, then a new session that must state the fact. The new-session question is
        asked twice; the second call's cache read is recorded with the lessons page in place.
habit   The same way: an answer that ends with a sign-off, /wrong, then a new session whose reply must lose
        the sign-off. fact and habit start the launcher, so they run in native Termux.

The lesson and the rule a case causes are removed from this installation's state when the case ends.
Reports: state/second-gate-checks/STAMP-ENGINE-CASE/report.json. Keys come from the environment, this
checkout's state folder, or --keys DIR. No key is printed or written.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
LIVE_STATE = Path('/data/data/com.termux/files/home/interaction-harness/state')
KEY_FILES = {'OPENAI_API_KEY': 'api-key', 'ANTHROPIC_API_KEY': 'anthropic-api-key'}
QUESTION = 'What is the capital of France? Answer in one short sentence.'
PLANTED_WRONG = 'chmod 640 gives the owner read and write access, the group read access, and everyone else no access.'
PLANTED_RIGHT = 'The capital of France is Paris.'


def key_environment(folder):
    """The two API keys as environment values. The key text never leaves this process's memory and its children."""
    values = {}
    for variable, name in KEY_FILES.items():
        if os.environ.get(variable):
            values[variable] = os.environ[variable]
            continue
        for place in ([Path(folder)] if folder else []) + [ROOT / 'state', LIVE_STATE]:
            try:
                text = (place / name).read_text().strip()
            except OSError:
                continue
            if text:
                values[variable] = text
                break
    return values


def on_debian_side():
    return os.access(ROOT / '.venv' / 'bin' / 'python', os.X_OK)


def rows(database):
    if not Path(database).exists():
        return []
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(history)')}
        wanted = [name for name in ('id', 'status', 'engine', 'model', 'session_id', 'raw_input', 'direct_answer',
                                    'execution_payload', 'execution_result', 'gate_json', 'cache_read_tokens',
                                    'input_tokens', 'error') if name in columns]
        return [dict(row) for row in db.execute('SELECT ' + ','.join(wanted) + ' FROM history ORDER BY id')]
    finally:
        db.close()


def events(path):
    try:
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    except OSError:
        return []


def cache_read(event):
    usage = event.get('usage') or {}
    return usage.get('cache_read_input_tokens', 0) + (usage.get('input_tokens_details') or {}).get('cached_tokens', 0)


def launch(args, env, options, stdin_text=None, timeout=2400):
    command = [str(ROOT / 'harness'), '--engine', args.engine, '--effort', args.effort, '--loop', '-y', *options]
    try:
        run = subprocess.run(command, input=stdin_text, capture_output=True, text=True, env=env, timeout=timeout)
        return {'command': command[1:], 'exit_code': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr}
    except subprocess.TimeoutExpired as exc:
        return {'command': command[1:], 'exit_code': 124, 'stdout': (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''),
                'stderr': 'timed out'}


def tool(env, *command):
    run = subprocess.run([str(ROOT / 'toolbox' / 'bin' / command[0]), *command[1:]], capture_output=True, text=True, env=env, timeout=300)
    return {'command': list(command), 'exit_code': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr}


def case_judge(args, folder):
    """Runs inside the client: a planted first reply, a real judge, a real corrective retry."""
    sys.path.insert(0, str(ROOT))
    os.environ.update(key_environment(args.keys))
    os.environ['HARNESS_STATE_DIR'] = str(folder / 'runtime')
    import harness as h
    import reply_judge
    reply_judge.LIVE = True
    model = h.DEFAULT_MODEL if args.engine == 'openai' else h.ANTHROPIC_MODEL
    results = []
    for name, planted_text in (('planted_wrong_question', PLANTED_WRONG), ('planted_right_answer', PLANTED_RIGHT)):
        planted = h.validate_reply(json.dumps({'intent': 'observation', 'cleaned_input': QUESTION, 'direct_answer': planted_text,
                                               'execution_payload': None}), QUESTION)
        real, calls = h.request_reply, []

        def working_model(current, **kwargs):
            calls.append(current)
            if len(calls) == 1:
                return planted          # the planted reply stands in for the working model's first reply
            return real(current, **kwargs)

        h.request_reply = working_model
        second, log, turn_events = reply_judge.Second(), folder / 'runtime' / (name + '.usage.jsonl'), []
        try:
            reply = second.request_reply(QUESTION, judge_turn={'turns': [], 'step': 1, 'loop': False}, engine=args.engine, model=model,
                                         effort=args.effort, timeout=args.timeout, log_path=log, events=turn_events, history=[],
                                         request_context=QUESTION)
        finally:
            h.request_reply = real
        results.append({'name': name, 'planted_reply': planted_text, 'working_engine': args.engine, 'working_model': model,
                        'verdicts': second.records, 'working_model_calls': len(calls), 'shown_answer': reply.direct_answer,
                        'retry_events': [{key: event.get(key) for key in ('status', 'engine', 'model_returned', 'usage', 'elapsed_ms')}
                                         for event in turn_events],
                        'judge_log': events(folder / 'runtime' / 'judge.jsonl')})
    wrong, right = results
    checks = {
        'judge_failed_the_planted_wrong_question_reply': wrong['verdicts'][0]['verdict'] == 'fail',
        'judge_gave_a_reason': bool(wrong['verdicts'][0]['reason']),
        'working_model_was_retried_once': wrong['working_model_calls'] == 2,
        'shown_answer_names_paris': 'paris' in wrong['shown_answer'].lower(),
        'judge_passed_the_corrected_reply': len(wrong['verdicts']) == 2 and wrong['verdicts'][1]['verdict'] == 'pass',
        'judge_passed_the_planted_right_answer': [v['verdict'] for v in right['verdicts']] == ['pass'],
        'right_answer_made_no_working_model_call_after_the_plant': right['working_model_calls'] == 1,
        'judge_is_the_other_engine': wrong['verdicts'][0]['engine'] != args.engine,
    }
    return {'results': results, 'checks': checks}


def case_fact(args, folder, env):
    marker = 'marzipan-' + uuid.uuid4().hex[:8]
    build = 'build ' + uuid.uuid4().hex[:6]
    question = f'What is the code word for {build}? One short sentence.'
    chat = launch(args, env, ['--chat', '--session', 'fact-case'],
                  f'{question}\n/wrong the code word for {build} is {marker}\nexit\n')
    listing = tool(env, 'lesson', 'list')
    first = launch(args, env, ['--new', question])
    second = launch(args, env, ['--new', question])
    history = rows(folder / 'runtime' / 'history.db')
    usage = events(folder / 'runtime' / 'usage.jsonl')
    case = next((row for row in history if row['status'] == 'correction'), None)
    last_two = [event for event in usage if event.get('status') == 'accepted'][-2:]
    lesson_lines = [line for line in listing['stdout'].splitlines() if marker in line]
    cleanup = []
    for line in reversed(lesson_lines):
        cleanup.append(tool(env, 'lesson', 'drop', line.split('.', 1)[0]))
    checks = {
        'chat_exit_0': chat['exit_code'] == 0,
        'first_answer_did_not_know_the_fact': marker not in chat['stdout'].split('\n')[0],
        'correction_row_saved': bool(case) and case['raw_input'].startswith('/wrong '),
        'lesson_line_names_the_correction_row': bool(case) and any(f'(row {case["id"]})' in line for line in lesson_lines),
        'correction_row_records_the_lesson': bool(case) and '"bin": "fact"' in (case.get('gate_json') or ''),
        'new_session_states_the_fact': first['exit_code'] == 0 and marker in first['stdout'],
        'lessons_page_is_last_on_both_calls': len(last_two) == 2 and all((event.get('pages') or [{}])[-1].get('label') == 'lessons' for event in last_two),
        'second_call_reads_the_cache': len(last_two) == 2 and cache_read(last_two[1]) > 0,
        'lesson_removed_after_the_case': bool(cleanup) and all(step['exit_code'] == 0 for step in cleanup),
    }
    return {'marker': marker, 'question': question, 'chat': chat, 'lesson_list': listing, 'new_session_first': first,
            'new_session_second': second, 'history': history, 'cleanup': cleanup,
            'cache': [{'pages': [page.get('label') for page in event.get('pages') or []], 'cache_read_tokens': cache_read(event),
                       'usage': event.get('usage')} for event in last_two],
            'judge_log': events(folder / 'runtime' / 'judge.jsonl'), 'checks': checks}


def case_habit(args, folder, env):
    tag = uuid.uuid4().hex[:6]
    sign_off = f'Stay sharp out there, crew {tag}.'
    question = 'What does chmod {mode} mean? Two short sentences. Then end your answer with this exact sentence: ' + sign_off
    chat = launch(args, env, ['--chat', '--session', 'habit-case'],
                  question.format(mode=640) + f'\n/wrong Stop adding sign-off lines like "{sign_off}" to your answers. Cut that kind of sentence.\nexit\n')
    listing = tool(env, 'rule', 'list')
    after = launch(args, env, ['--new', question.format(mode=600)])
    history = rows(folder / 'runtime' / 'history.db')
    case = next((row for row in history if row['status'] == 'correction'), None)
    try:
        stored = json.loads((ROOT / 'state' / 'gate_rules.json').read_text())
    except (OSError, ValueError):
        stored = []
    mine = [entry for entry in stored if case and entry.get('history_row') == case['id'] and any(tag in text for text in entry.get('bad', []))]
    last = history[-1] if history else {}
    cleanup = [tool(env, 'rule', 'drop', entry['name']) for entry in mine]
    checks = {
        'chat_exit_0': chat['exit_code'] == 0,
        'first_answer_held_the_sign_off': sign_off in chat['stdout'],
        'correction_row_saved': bool(case) and case['raw_input'].startswith('/wrong '),
        'rule_names_the_correction_row_and_the_bad_sentence': bool(mine),
        'correction_row_records_the_rule': bool(case) and '"bin": "habit"' in (case.get('gate_json') or ''),
        'new_session_exit_0': after['exit_code'] == 0,
        'next_reply_lost_the_sign_off': after['exit_code'] == 0 and bool(after['stdout'].strip()) and tag not in after['stdout'],
        'history_shows_the_rule_fired': '"rules_fired"' in (last.get('gate_json') or '') or any(
            event.get('status') == 'gate_rejected' and 'gate rule' in (event.get('gate_reason') or '')
            for event in events(folder / 'runtime' / 'usage.jsonl')),
        'rule_removed_after_the_case': bool(cleanup) and all(step['exit_code'] == 0 for step in cleanup),
    }
    return {'sign_off': sign_off, 'chat': chat, 'rule_list': listing, 'new_session': after, 'rules_for_this_case': mine,
            'history': history, 'cleanup': cleanup, 'judge_log': events(folder / 'runtime' / 'judge.jsonl'), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--engine', choices=['openai', 'anthropic'], required=True)
    parser.add_argument('--case', choices=['judge', 'fact', 'habit'], required=True)
    parser.add_argument('--effort', default='max')
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--keys', help='Folder that holds the saved key files, when this checkout has none.')
    parser.add_argument('--folder', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.case == 'judge' and not on_debian_side():
        # The client's Python lives on the Debian side. It reads the saved key files there itself; no key is an argument.
        folder = args.folder or str(new_folder(args))
        command = ['proot-distro', 'login', 'debian', '--', str(ROOT / '.venv' / 'bin' / 'python'), '-B',
                   str(Path(__file__).resolve()), '--engine', args.engine, '--case', 'judge', '--effort', args.effort,
                   '--timeout', str(args.timeout), '--folder', folder, *(['--keys', args.keys] if args.keys else [])]
        return subprocess.run(command).returncode
    if args.case != 'judge' and on_debian_side():
        print('The fact and habit cases start the real launcher. Run them in native Termux.', file=sys.stderr)
        return 2
    folder = Path(args.folder) if args.folder else new_folder(args)
    (folder / 'runtime').mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.case == 'judge':
        report = case_judge(args, folder)
    else:
        env = os.environ.copy()
        env.pop('LD_LIBRARY_PATH', None)
        env.update(key_environment(args.keys))
        env['HARNESS_STATE_DIR'] = str(folder / 'runtime')
        report = (case_fact if args.case == 'fact' else case_habit)(args, folder, env)
    report.update(case=args.case, engine=args.engine, effort=args.effort, checkout=str(ROOT),
                  time_utc=datetime.now(timezone.utc).isoformat(), passed=all(report['checks'].values()))
    (folder / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + '\n')
    for name, ok in report['checks'].items():
        print(('ok    ' if ok else 'FAIL  ') + name)
    print('report: ' + str(folder / 'report.json'))
    return 0 if report['passed'] else 1


def new_folder(args):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT / 'state' / 'second-gate-checks' / f'{stamp}-{args.engine}-{args.case}-{uuid.uuid4().hex[:6]}'
    folder.mkdir(parents=True, mode=0o700)
    return folder


if __name__ == '__main__':
    raise SystemExit(main())
