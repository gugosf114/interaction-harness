"""Corrections: /wrong WORDS turns George's correction into a fact on the lessons page or a rule in the gate.

In chat, `/wrong WORDS` does two things.
  1. It saves a correction case as its own history row (status "correction"): the previous request,
     the previous answer, and George's words.
  2. It turns the line into a loop task for the same lane. The lane sorts the correction into a bin and acts:
       a fact   ->  lesson add --row N 'THE FACT'          (state/lessons.md, on every later call)
       a habit  ->  rule add NAME --row N ...              (state/gate_rules.json, applied by the gate)
       a habit no regular expression can express  ->  card self: the check is written in code and landed
                                                       with self-update --row N
Every lesson and rule names the correction's history row. `lesson add` and `rule add` refuse without one,
and they write what they added back onto that row (gate_json.outcomes). self-update --row N does the
same for a code change: the commit message names the row and the row gets the commit.
"""
from __future__ import annotations

import json
import sys

import gate_admin
import harness as h
from storage import Store

TRIGGER = '/wrong'
TASK = """/wrong: George marked your previous answer wrong. The client built this message from his /wrong line. Act on it now, in this loop run.

Correction case: history row {row}

His request was:
<<<
{request}
>>>

Your answer was:
<<<
{answer}
>>>

George's words about it:
<<<
{words}
>>>

Sort the correction into one bin, then run the command for that bin.

1. A fact. His words state something about the world that the answer got wrong or did not know: a name, a place, a number, who owns what, which account. Run:
   lesson add --row {row} 'THE FACT AS ONE PLAIN SENTENCE'
   Every later call carries that line, in every session and on both lanes.

2. A habit. His words name a kind of sentence or move to stop. Print `card lessons` for the exact form, then run:
   rule add NAME --row {row} --action strip_sentence --pattern 'REGEX' --bad 'A SENTENCE FROM YOUR ANSWER THAT HE WANTS GONE'
   Take the --bad sentences from your own answer above. The command tests the rule first. It refuses a rule that misses one of its bad sentences or that matches a known-good sentence; then fix the pattern and run it again.

3. A habit that no regular expression can express. Print `card self`, write the check in code, and land it with:
   self-update --row {row} 'ONE LINE THAT SAYS WHAT CHANGED'

Pick the bin yourself. Nothing is added without --row {row}. When the command has exited 0, finish with one short line that says what was added."""


def is_trigger(line: str) -> bool:
    return line == TRIGGER or line.startswith(TRIGGER + ' ') or line.startswith(TRIGGER + '\t')


def previous_exchange(turns: list) -> tuple[str, str]:
    """The request George made and the answer he got: for a loop run, the original task and the final reply."""
    last = turns[-1]
    request = last['normalized_input']
    if last.get('loop_step'):
        for exchange in reversed(turns):
            if exchange.get('loop_step') == 1:
                request = exchange['normalized_input']
                break
            if not exchange.get('loop_step'):
                break
    return request, last['reply']['direct_answer']


def save_case(store, session_id: str, session: dict, words: str, engine: str, model: str) -> tuple[int, str, str]:
    """Write the correction row. Returns its id, the previous request and the previous answer."""
    request, answer = previous_exchange(session['turns'])
    gate_admin.ensure_columns(store.db)
    target = store.db.execute(
        "SELECT id FROM history WHERE session_id=? AND direct_answer=? AND status IN ('accepted','loop_limit') "
        "ORDER BY id DESC LIMIT 1", (session_id, answer)).fetchone()
    row_id = store.begin(TRIGGER + ' ' + words, words, engine, model, session_id)
    with store.db:
        store.db.execute('UPDATE history SET status=?, cleaned_input=?, direct_answer=?, gate_json=? WHERE id=?',
                         (gate_admin.CORRECTION, request, answer,
                          json.dumps({'corrects_row': target[0] if target else None, 'outcomes': []}), row_id))
    return row_id, request, answer


def typed(args, model) -> int | None:
    """Called by the client for the typed line. Returns an exit code when the line is finished here.

    /wrong WORDS saves the correction case, rewrites args so the line becomes the correction loop task,
    and returns None: the client then runs it as a loop. Any other line returns None untouched.
    """
    if not args.text or args.listen:
        return None
    line = ' '.join(args.text).strip()
    if not is_trigger(line):
        return None
    words = line[len(TRIGGER):].strip()
    if not words:
        print('Say what was wrong: /wrong WORDS', file=sys.stderr)
        return 2
    if not (args.session or args.continuing):
        print('/wrong corrects the last answer of a session: type it in a chat, or add -c or --session NAME.', file=sys.stderr)
        return 2
    store = None
    try:
        store = Store(h.STATE)
        session_id = store.select_session(args.session, args.continuing)
        with store.session(session_id, args.turns) as session:
            if not session['turns']:
                print('Nothing to correct yet: this session has no exchange.', file=sys.stderr)
                return 2
            row_id, request, answer = save_case(store, session_id, session, words, args.engine, model)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()
    print(f'Correction saved as history row {row_id}.', file=sys.stderr)
    # The line now runs as a loop task on this lane. Quoted text inside it must stay exact.
    args.text = [TASK.format(row=row_id, request=request, answer=answer, words=words)]
    args.session, args.continuing = session_id, False
    args.loop = args.execute = True
    args.no_normalize = True
    return None
