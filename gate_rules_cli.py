"""The `rule` command: add, list, drop and test the operator's gate rules (gate_rules.py).

  rule add NAME --row N --action strip_sentence|reject --pattern 'REGEX' --bad 'SENTENCE' [--bad 'SENTENCE' ...]
  rule list
  rule drop NAME
  rule test [NAME] [--text 'WORDS']

Exit codes: 0 worked; 1 refused, or a rule failed its test; 2 wrong use.
"""
from __future__ import annotations

import argparse
import sys

import gate_admin
import gate_rules

USAGE = __doc__.split('\n\n')[1]


class Parser(argparse.ArgumentParser):
    stream = None

    def error(self, message):
        print(message + '\n' + USAGE, file=Parser.stream or sys.stderr)
        raise SystemExit(2)


def build_parser() -> Parser:
    parser = Parser(prog='rule', add_help=False)
    commands = parser.add_subparsers(dest='command', parser_class=Parser)
    add = commands.add_parser('add', add_help=False)
    add.add_argument('name')
    add.add_argument('--row', type=int, required=True)
    add.add_argument('--action', required=True)
    add.add_argument('--pattern', required=True)
    add.add_argument('--bad', action='append', required=True)
    commands.add_parser('list', add_help=False)
    drop = commands.add_parser('drop', add_help=False)
    drop.add_argument('name')
    test = commands.add_parser('test', add_help=False)
    test.add_argument('name', nargs='?')
    test.add_argument('--text')
    return parser


def main(argv=None, *, rules_file=None, history=None, good=None, out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    rules_file = rules_file or gate_admin.config_dir() / 'gate_rules.json'
    Parser.stream = err
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        Parser.stream = None
    if args.command is None:
        print(USAGE, file=err)
        return 2
    try:
        if args.command == 'add':
            row = gate_admin.history_row(args.row, history)
            if row is None:
                print(f'No history row {args.row}. A rule names the history row that caused it; nothing was added.', file=err)
                return 1
            rule = gate_rules.add_rule(rules_file, name=args.name, pattern=args.pattern, action=args.action,
                                       bad=args.bad, history_row=args.row, date=gate_admin.today(), good=good)
            if row['status'] == gate_admin.CORRECTION:
                gate_admin.record_outcome(args.row, {'bin': 'habit', 'rule': rule.name, 'action': rule.action,
                                                     'date': rule.date}, history)
            print(f'Added rule "{rule.name}" ({rule.action}) for history row {rule.history_row}. '
                  f'It matched {len(rule.bad)} bad sentence' + ('s' if len(rule.bad) > 1 else '')
                  + ' and no known-good sentence. The gate uses it from the next reply.', file=out)
            return 0
        if args.command == 'list':
            rules, problems = gate_rules.load(rules_file)
            for rule in rules:
                print(f'{rule.name}  {rule.action}  {rule.date}  row {rule.history_row}  /{rule.pattern}/', file=out)
                for text in rule.bad:
                    print('    bad: ' + text, file=out)
            if not rules and not problems:
                print('No rules.', file=out)
            for problem in problems:
                print(problem, file=err)
            return 1 if problems else 0
        if args.command == 'drop':
            entry = gate_rules.drop_rule(rules_file, args.name)
            print(f'Dropped rule "{entry["name"]}".', file=out)
            return 0
        rules, problems = gate_rules.load(rules_file)
        if args.name and not any(rule.name == args.name for rule in rules):
            print(f'No rule named "{args.name}".', file=err)
            return 1
        failed = bool(problems)
        for problem in problems:
            print(problem, file=err)
        known = gate_rules.known_good() if good is None else good
        for rule in rules:
            if args.name and rule.name != args.name:
                continue
            found = gate_rules.self_test(rule, known)
            failed = failed or bool(found)
            print((f'FAIL {rule.name}: ' + ' '.join(found)) if found else f'ok {rule.name}', file=out)
        if args.text is not None:
            chosen = [rule for rule in rules if not args.name or rule.name == args.name]
            shown, reason = gate_rules.apply_rules(args.text, chosen)
            fired = gate_rules.drain()
            if reason:
                print('rejected: ' + reason, file=out)
            elif fired:
                for item in fired:
                    print(f'cut by {item["name"]}: {item["text"]}', file=out)
                print('shown: ' + shown, file=out)
            else:
                print('no rule matched. shown: ' + shown, file=out)
        return 1 if failed else 0
    except gate_rules.RuleError as exc:
        print(str(exc), file=err)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
