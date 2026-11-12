"""The `lesson` command: add, list and drop lines on the lessons page (lessons.py).

  lesson add --row N 'ONE PLAIN SENTENCE'
  lesson list
  lesson drop NUMBER

Exit codes: 0 worked; 1 refused; 2 wrong use.
"""
from __future__ import annotations

import sys

import gate_admin
import lessons

USAGE = __doc__.split('\n\n')[1]


def main(argv=None, *, config=None, history=None, out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    config = config or gate_admin.config_dir()
    try:
        if argv[:1] == ['list'] and len(argv) == 1:
            found = lessons.entries(config)
            for entry in found:
                print(f'{entry["number"]}. {entry["date"]} (row {entry["row"]}): {entry["text"]}', file=out)
            if not found:
                print('No lessons.', file=out)
            return 0
        if argv[:1] == ['drop'] and len(argv) == 2 and argv[1].isdigit():
            gone = lessons.drop(config, int(argv[1]))
            print(f'Dropped lesson {gone["number"]}: {gone["text"]}', file=out)
            return 0
        if argv[:1] == ['add'] and len(argv) == 4 and '--row' in argv[1:]:
            rest = argv[1:]
            at = rest.index('--row')
            if at == 2 or not rest[at + 1].isdigit():
                print(USAGE, file=err)
                return 2
            row_id = int(rest[at + 1])
            text = rest[0] if at == 1 else rest[2]
            row = gate_admin.history_row(row_id, history)
            if row is None:
                print(f'No history row {row_id}. A lesson names the history row that caused it; nothing was added.', file=err)
                return 1
            entry = lessons.add(config, text, row_id, gate_admin.today())
            if row['status'] == gate_admin.CORRECTION:
                gate_admin.record_outcome(row_id, {'bin': 'fact', 'lesson': entry['line'], 'date': entry['date']}, history)
            print(f'Added lesson {entry["number"]}: {entry["line"][2:]}\nEvery later call carries it, in every session.', file=out)
            return 0
    except lessons.LessonError as exc:
        print(str(exc), file=err)
        return 1
    print(USAGE, file=err)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
