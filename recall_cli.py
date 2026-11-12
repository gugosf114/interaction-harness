"""Command-line wiring for past-chat recall and for session fork, rewind and the golden session.

cli.py calls into this file at five small points; the logic lives in recall_notes.py and session_tools.py.
"""
import sys

import harness as h
import recall_notes
import session_tools

COMMANDS = {
    '/on recall': 'Search past chats before each message (the default).',
    '/off recall': 'Stop the past-chat search.',
    '/fork [NEWNAME]': 'Continue this chat in a new session that starts as a full copy. The original is unchanged.',
    '/rewind [N]': 'Drop the last N exchanges from this session (default 1). They stay in history.db.',
}


def add_flags(parser):
    parser.add_argument('--no-recall', action='store_true', help='Skip the past-chat search for this run. In chat: /off recall, /on recall.')
    parser.add_argument('--fork', nargs='+', default=None, metavar=('SESSION', 'NEWNAME'),
                        help='Start in a new session that is a full copy of SESSION. The original is untouched. '
                             'A question goes after --. In chat: /fork [NEWNAME].')
    parser.add_argument('--from', dest='from_session', default=None, metavar='NAME',
                        help='A new session starts as a copy of NAME. `session golden NAME` makes this the default for every new chat; --new skips it.')
    parser.epilog = (parser.epilog or '') + (' Past chats: before each message the client searches the saved chats and sends the best passages as'
                                             ' a recall_notes data message. In chat: /off recall, /on recall, /fork [NEWNAME], /rewind [N].'
                                             ' Session commands: sessions, session show|export|fork|rewind|cut|splice|golden (card lanes).'
                                             ' Notes: note add|show|list (card memory).')


def validate_args(parser, args):
    if args.fork is None:
        return
    if args.continuing or args.session or args.from_session:
        parser.error('--fork names its own source and new session; leave out -c, --session and --from.')
    if args.recall is not None or args.advisor is not None:
        parser.error('--fork starts a chat or a question; it does not go with --recall or --advisor.')
    # --fork SESSION [NEWNAME] QUESTION...: a second word that can be a session name is NEWNAME; the rest is the question.
    words = list(args.fork)
    source = words.pop(0)
    new = words.pop(0) if words and session_tools.NAME.fullmatch(words[0]) else None
    args.fork = (source, new)
    if words:
        args.text = [*words, *args.text]


def common_options(args):
    return ['--no-recall'] if args.no_recall else []


def start_session(args):
    """--fork, --from and the golden session: create the seeded session, then the run is an ordinary --session run.

    Returns None to carry on, or an exit code when the source cannot be used.
    """
    if args.recall is not None or args.advisor is not None:
        return None
    try:
        if args.fork is not None:
            source, new = args.fork
            name, count = session_tools.fork(h.STATE, source, new)
            print(f'Forked {source} -> {name} ({session_tools.plural(count)}). {source} is unchanged.', file=sys.stderr)
            args.session, args.fork = name, None
            return None
        if args.continuing:
            return None
        # --new asks for an empty session, so the golden default does not apply to it. --from still does.
        source = args.from_session or (None if getattr(args, 'new', False) else session_tools.golden(h.STATE))
        if not source:
            return None
        name = args.session or session_tools.new_session_name()
        if args.from_session and session_tools.exists(h.STATE, name):
            raise session_tools.SessionError(f'--from starts a new session, and {name} already exists.')
        if args.from_session or session_tools.exists(h.STATE, source):
            session_tools.seed(h.STATE, name, source)   # an existing session is left as it is
        args.session, args.from_session = name, None
        return None
    except session_tools.SessionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'File error: {exc.strerror or exc}', file=sys.stderr)
        return 2


def pinned_session(options):
    return options[options.index('--session') + 1]


def chat_command(line, options, args):
    """A chat line this module owns. Returns None when the line is not one of them, else the status code.

    /fork changes the --session entry of `options`, so the rest of the chat runs in the copy.
    """
    words = line.split()
    if not words:
        return None
    try:
        if recall_notes.is_trigger(line):
            print(recall_notes.chat_command(line, h.STATE), file=sys.stderr)
            return 0
        if words[0] == '/fork':
            if len(words) > 2:
                print('Use /fork or /fork NEWNAME.', file=sys.stderr)
                return 2
            source = pinned_session(options)
            name, count = session_tools.fork(h.STATE, source, words[1] if len(words) == 2 else None)
            options[options.index('--session') + 1] = name
            print(f'Forked {source} -> {name} ({session_tools.plural(count)}). This chat continues in {name}; {source} is unchanged.',
                  file=sys.stderr)
            return 0
        if words[0] == '/rewind':
            if len(words) > 2 or (len(words) == 2 and not (words[1].isdigit() and int(words[1]) >= 1)):
                print('Use /rewind or /rewind N, with N 1 or more.', file=sys.stderr)
                return 2
            name = pinned_session(options)
            data, removed = session_tools.rewind(h.STATE, name, int(words[1]) if len(words) == 2 else 1)
            left = len(session_tools.groups(data['turns']))
            print(f'Rewound {name}: {session_tools.plural(left)} left.', file=sys.stderr)
            if removed:
                print(session_tools.describe(removed), file=sys.stderr)
            return 0
    except session_tools.SessionError as exc:
        text = str(exc)
        if text.startswith('No session named'):
            text = 'This chat has no saved exchange yet.'
        print(text, file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'File error: {exc.strerror or exc}', file=sys.stderr)
        return 2
    return None


def notes(args, session, text, row_id):
    """The recall_notes message text for this operator message, or None. Never raises."""
    return recall_notes.for_turn(text, state=h.STATE, session=session, before_row=row_id, log_path=args.usage_log,
                                 enabled=not args.no_recall)
