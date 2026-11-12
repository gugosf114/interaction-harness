#!/usr/bin/python3
"""Debian side of the Google account commands: google-accounts, google-signin, mail-unread, google-mail,
google-calendar and google-drive.

The accounts are listed in one file on the phone, never in git: /root/.gmail/accounts.json
  {"client": "/FULL/PATH/the OAuth client file",
   "accounts": {"NAME": {"address": "...", "old_token": "/FULL/PATH (optional)", "service_key": "/FULL/PATH (optional)"}}}
A sign-in saves the account's token as /root/.gmail/accounts/NAME.json. No key value is stored in this file.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REGISTRY = Path(os.environ.get('GOOGLE_ACCOUNTS_FILE', '/root/.gmail/accounts.json'))
AUTH = 'https://www.googleapis.com/auth/'
SCOPES = {
    'mail': [AUTH + 'gmail.readonly', AUTH + 'gmail.send', AUTH + 'gmail.modify'],
    'calendar': [AUTH + 'calendar'],
    'drive': [AUTH + 'drive'],
}
ENOUGH = {
    'mail': {AUTH + 'gmail.readonly', AUTH + 'gmail.modify', 'https://mail.google.com/'},
    'calendar': {AUTH + 'calendar'},
    'drive': {AUTH + 'drive'},
}
KINDS = ('mail', 'calendar', 'drive')
API = {'mail': ('gmail', 'v1'), 'calendar': ('calendar', 'v3'), 'drive': ('drive', 'v3')}
PORT = 8765
GOOGLE_FILES = {
    'application/vnd.google-apps.document': ('document', 'text/plain'),
    'application/vnd.google-apps.spreadsheet': ('spreadsheet', 'text/csv'),
    'application/vnd.google-apps.presentation': ('presentation', 'text/plain'),
}
USAGE = {
    'accounts': 'usage: google-accounts',
    'signin': 'usage: google-signin [--print] [--wait SECONDS] [NAME ...]',
    'unread': 'usage: mail-unread NAME|all [N]',
    'mail': 'usage: google-mail NAME test | list N [QUERY] | thread THREAD_ID | unread [N] | markread ID ... | send MESSAGE_ID /FULL/PATH/body.txt',
    'calendar': "usage: google-calendar NAME|all today|tomorrow|YYYY-MM-DD\n"
                "       google-calendar NAME list [DAYS] | read EVENT_ID | create 'TITLE' 'YYYY-MM-DD HH:MM' 'YYYY-MM-DD HH:MM' ['PLACE']",
    'drive': "usage: google-drive NAME list [N] ['WORDS'] | read FILE_ID [/FULL/PATH/out] | create /FULL/PATH/file ['TITLE']",
}


class Stop(Exception):
    """A plain sentence for the caller and an exit code."""
    def __init__(self, text, code=1):
        super().__init__(text)
        self.code = code


def load_registry(path=None):
    path = Path(path or REGISTRY)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise Stop(f'The account list {path} does not exist.')
    except json.JSONDecodeError as problem:
        raise Stop(f'The account list {path} is not valid JSON: {problem}')
    if not isinstance(data.get('accounts'), dict) or not data['accounts']:
        raise Stop(f'The account list {path} names no account.')
    data['folder'] = path.parent / 'accounts'
    return data


def entry(registry, name):
    if name not in registry['accounts']:
        raise Stop(f"No account is named {name}. The names: {' '.join(registry['accounts'])}", 2)
    return registry['accounts'][name]


def token_files(registry, name):
    """The account's token files, the newest sign-in first."""
    found = [registry['folder'] / (name + '.json')]
    if entry(registry, name).get('old_token'):
        found.append(Path(entry(registry, name)['old_token']))
    return [path for path in found if path.is_file()]


def kinds_in(scopes):
    scopes = set(scopes or [])
    return [kind for kind in KINDS if scopes & ENOUGH[kind]]


def token_scopes(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('scopes') or []
    except (OSError, json.JSONDecodeError):
        return []


def allowed(registry, name):
    """What the account lets this phone do: a dict kind -> 'sign-in', 'service key' or None."""
    result = dict.fromkeys(KINDS)
    for path in token_files(registry, name):
        for kind in kinds_in(token_scopes(path)):
            result[kind] = result[kind] or 'sign-in'
    if entry(registry, name).get('service_key') and not result['mail']:
        result['mail'] = 'service key'
    return result


def token_for(registry, name, kind):
    for path in token_files(registry, name):
        if kind in kinds_in(token_scopes(path)):
            return path
    return None


def not_allowed(name, kind):
    return f'{name}: {kind} is not allowed yet. George taps Allow on the Google page that opens with: google-signin {name}'


def service(registry, name, kind):
    """An API client for one account, or Stop with a plain sentence."""
    path = token_for(registry, name, kind)
    if not path and not (kind == 'mail' and entry(registry, name).get('service_key')):
        raise Stop(not_allowed(name, kind))
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    if path:
        from google.oauth2.credentials import Credentials
        credentials = Credentials.from_authorized_user_file(str(path))
        if not credentials.valid:
            credentials.refresh(Request())
            path.write_text(credentials.to_json(), encoding='utf-8')
    else:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            entry(registry, name)['service_key'], scopes=[AUTH + 'gmail.readonly'], subject=entry(registry, name)['address'])
    return build(*API[kind], credentials=credentials, cache_discovery=False)


def explain(problem, name):
    """One plain line for a Google error."""
    text = str(problem)
    if 'invalid_grant' in text:
        return f'{name}: the Google sign-in is no longer valid (invalid_grant). George taps Allow again with: google-signin {name}'
    status = getattr(getattr(problem, 'resp', None), 'status', None)
    if status:
        reason = getattr(problem, 'reason', '') or text
        return f'{name}: Google answered HTTP {status}: {reason}'
    return f'{name}: {type(problem).__name__}: {text[:300]}'


def names_for(registry, word):
    return list(registry['accounts']) if word == 'all' else [word]


# ---------------------------------------------------------------- accounts

def cmd_accounts(registry, args):
    if args:
        raise Stop(USAGE['accounts'], 2)
    for name in registry['accounts']:
        has = allowed(registry, name)
        parts = [f"{kind}: {has[kind] or 'no'}" for kind in KINDS]
        print(f"{name} | {entry(registry, name)['address']} | " + ' | '.join(parts))
    return 0


# ---------------------------------------------------------------- mail

def cmd_unread(registry, args):
    if not args or len(args) > 2 or (len(args) == 2 and not args[1].isdigit()):
        raise Stop(USAGE['unread'], 2)
    everyone = args[0] == 'all'
    count = int(args[1]) if len(args) == 2 else (0 if everyone else 5)
    status = 0
    for name in names_for(registry, args[0]):
        address = entry(registry, name)['address']
        if everyone and not allowed(registry, name)['mail']:
            print(f'{name} ({address}): not connected for mail. Sign-in: google-signin {name}')
            continue
        try:
            gmail = service(registry, name, 'mail')
            inbox = gmail.users().labels().get(userId='me', id='INBOX').execute()
            print(f"{address}: {inbox['messagesUnread']} unread in the inbox ({inbox['messagesTotal']} messages in the inbox)")
            if not count:
                continue
            found = gmail.users().messages().list(userId='me', q='is:unread in:inbox', maxResults=min(count, 50)).execute()
            for item in found.get('messages', []):
                message = gmail.users().messages().get(userId='me', id=item['id'], format='metadata',
                                                       metadataHeaders=['From', 'Subject', 'Date']).execute()
                head = {h['name'].lower(): h['value'] for h in message['payload'].get('headers', [])}
                print(f"{item['id']} | {head.get('date', '')[:25]} | {head.get('from', '')[:40]} | {head.get('subject', '')[:90]}")
        except Stop as problem:
            print(problem, file=sys.stderr); status = problem.code
        except Exception as problem:  # one account's failure does not hide the others
            print(explain(problem, name), file=sys.stderr); status = 1
    return status


def cmd_mail(registry, args):
    verbs = ('test', 'list', 'thread', 'unread', 'markread', 'send')
    if len(args) < 2 or args[1] not in verbs or (args[1] == 'send' and len(args) != 4):
        raise Stop(USAGE['mail'], 2)
    name = args[0]
    path = token_for(registry, name, 'mail')
    if not path:
        if entry(registry, name).get('service_key'):
            raise Stop(f'{name} reads mail with a service key, through its own reader: '
                       'deb python3 /root/.gmail/mail.py test | inbound N | sent N "QUERY"', 2)
        raise Stop(not_allowed(name, 'mail'))
    if args[1] == 'send' and AUTH + 'gmail.send' not in token_scopes(path):
        raise Stop(f'{name}: sending is not allowed by this sign-in.')
    environment = {**os.environ, 'BMAIL_TOKEN': str(path), 'BMAIL_FROM': entry(registry, name)['address']}
    script = '/root/.gmail/bsend.py' if args[1] == 'send' else '/root/.gmail/bmail.py'
    rest = args[2:] if args[1] == 'send' else args[1:]
    sys.stdout.flush()
    os.execve('/usr/bin/python3', ['python3', script, *rest], environment)


# ---------------------------------------------------------------- calendar

def local(moment):
    return moment.astimezone()


def day_window(word, today=None):
    """Local midnight to the next local midnight for today, tomorrow or YYYY-MM-DD."""
    today = today or datetime.date.today()
    if word == 'today':
        day = today
    elif word == 'tomorrow':
        day = today + datetime.timedelta(days=1)
    else:
        try:
            day = datetime.date.fromisoformat(word)
        except ValueError:
            raise Stop(USAGE['calendar'], 2)
    start = local(datetime.datetime(day.year, day.month, day.day))
    following = day + datetime.timedelta(days=1)
    return day, start, local(datetime.datetime(following.year, following.month, following.day))


def clock_line(word, day, now=None):
    """The phone's own date and time, and the day that today or tomorrow means on that clock."""
    now = now or local(datetime.datetime.now())
    return f"Phone clock: {now:%a %b %d %Y %H:%M} {now.tzname()}. {word.capitalize()} is {day:%a %b %d %Y}."


def event_line(event, calendar_name, with_date):
    start, end = event.get('start', {}), event.get('end', {})
    if 'dateTime' in start:
        begin = local(datetime.datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00')))
        finish = local(datetime.datetime.fromisoformat(end.get('dateTime', start['dateTime']).replace('Z', '+00:00')))
        when = f'{begin:%H:%M}-{finish:%H:%M}'
        day = begin.date()
    else:
        when = 'all day'
        day = datetime.date.fromisoformat(start.get('date', '1970-01-01'))
    if with_date:
        when = f'{day:%a %b %d} {when}'
    parts = [when, event.get('summary') or '(no title)', event.get('location') or '-', calendar_name, event.get('id', '')]
    return ' | '.join(part.replace('\n', ' ') for part in parts)


def event_start(event):
    """(local day, 0 for a whole-day event or 1, local moment) for sorting and for the day filter."""
    start = event.get('start', {})
    if 'dateTime' in start:
        moment = local(datetime.datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00')))
        return moment.date(), 1, moment
    day = datetime.date.fromisoformat(start.get('date', '1970-01-01'))
    return day, 0, local(datetime.datetime(day.year, day.month, day.day))


def covers(event, day):
    """True unless this is a whole-day event that does not include that day."""
    start, end = event.get('start', {}), event.get('end', {})
    if 'date' not in start:
        return True
    first = datetime.date.fromisoformat(start['date'])
    last = datetime.date.fromisoformat(end['date']) if end.get('date') else first + datetime.timedelta(days=1)
    return first <= day < last


def events_between(calendar, start, end, day=None):
    """Every event in the window on every calendar the account shows, soonest first."""
    rows = []
    calendars = calendar.calendarList().list(maxResults=250).execute().get('items', [])
    for item in calendars:
        if not (item.get('primary') or item.get('selected')):
            continue
        name = 'main' if item.get('primary') else (item.get('summaryOverride') or item.get('summary') or item['id'])
        page = None
        while True:
            found = calendar.events().list(calendarId=item['id'], timeMin=start.isoformat(), timeMax=end.isoformat(),
                                           singleEvents=True, orderBy='startTime', maxResults=250, pageToken=page).execute()
            for event in found.get('items', []):
                if day is None or covers(event, day):
                    rows.append((*event_start(event), event, name))
            page = found.get('nextPageToken')
            if not page:
                break
    rows.sort(key=lambda row: row[:3])
    return [(row[3], row[4]) for row in rows]


def cmd_calendar(registry, args):
    if len(args) < 2:
        raise Stop(USAGE['calendar'], 2)
    who, verb, rest = args[0], args[1], args[2:]
    if verb in ('list', 'read', 'create'):
        if who == 'all':
            raise Stop(USAGE['calendar'], 2)
        entry(registry, who)
        right = {'list': len(rest) == 0 or (len(rest) == 1 and rest[0].isdigit()), 'read': len(rest) == 1,
                 'create': len(rest) in (3, 4)}[verb]
        if not right:
            raise Stop(USAGE['calendar'], 2)
        if verb == 'create':
            body = {'summary': rest[0], 'start': event_time(rest[1]), 'end': event_time(rest[2], closing=True)}
            if len(rest) == 4:
                body['location'] = rest[3]
        calendar = service(registry, who, 'calendar')
        if verb == 'list':
            days = int(rest[0]) if rest else 7
            now = local(datetime.datetime.now())
            rows = events_between(calendar, now, now + datetime.timedelta(days=days))
            print(f"{who} ({entry(registry, who)['address']}): {len(rows)} events in the next {days} days")
            for event, name in rows:
                print('  ' + event_line(event, name, True))
            return 0
        if verb == 'read':
            return read_event(calendar, who, rest[0])
        made = calendar.events().insert(calendarId='primary', body=body, sendUpdates='none').execute()
        print(f"created: {made['id']} | {made.get('htmlLink', '')}")
        return 0
    if rest:
        raise Stop(USAGE['calendar'], 2)
    day, start, end = day_window(verb)
    if verb in ('today', 'tomorrow'):
        print(clock_line(verb, day))
    status = 0
    for name in names_for(registry, who):
        address = entry(registry, name)['address']
        if who == 'all' and not allowed(registry, name)['calendar']:
            print(f'{name} ({address}): not connected for calendar. Sign-in: google-signin {name}')
            continue
        try:
            rows = events_between(service(registry, name, 'calendar'), start, end, day)
            print(f'{name} ({address}): {len(rows)} events on {day:%a %b %d %Y}')
            for event, calendar_name in rows:
                print('  ' + event_line(event, calendar_name, False))
        except Stop as problem:
            print(problem, file=sys.stderr); status = problem.code
        except Exception as problem:
            print(explain(problem, name), file=sys.stderr); status = 1
    return status


def event_time(text, closing=False):
    """'YYYY-MM-DD HH:MM' in the phone's own time zone, or 'YYYY-MM-DD' for a whole day."""
    try:
        if len(text) == 10:
            day = datetime.date.fromisoformat(text)
            return {'date': (day + datetime.timedelta(days=1 if closing else 0)).isoformat()}
        return {'dateTime': local(datetime.datetime.strptime(text, '%Y-%m-%d %H:%M')).isoformat()}
    except ValueError:
        raise Stop(USAGE['calendar'], 2)


def read_event(calendar, who, event_id):
    from googleapiclient.errors import HttpError
    ids = ['primary'] + [item['id'] for item in calendar.calendarList().list(maxResults=250).execute().get('items', [])
                         if not item.get('primary')]
    for calendar_id in ids:
        try:
            event = calendar.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except HttpError as problem:
            if problem.resp.status == 404:
                continue
            raise
        start, end = event.get('start', {}), event.get('end', {})
        lines = [('title', event.get('summary')), ('start', start.get('dateTime') or start.get('date')),
                 ('end', end.get('dateTime') or end.get('date')), ('place', event.get('location')),
                 ('status', event.get('status')), ('organizer', (event.get('organizer') or {}).get('email')),
                 ('guests', ', '.join(f"{g.get('email')} ({g.get('responseStatus')})" for g in event.get('attendees', []))),
                 ('meeting link', event.get('hangoutLink')), ('link', event.get('htmlLink')), ('notes', event.get('description'))]
        for label, value in lines:
            if value:
                print(f'{label}: {value}')
        return 0
    raise Stop(f'{who}: no event has the id {event_id}.')


# ---------------------------------------------------------------- drive

def short_type(mime):
    if mime in GOOGLE_FILES:
        return GOOGLE_FILES[mime][0]
    if mime == 'application/vnd.google-apps.folder':
        return 'folder'
    return mime.split('/')[-1][:24]


def drive_query(words):
    if not words:
        return 'trashed = false'
    safe = words.replace('\\', '\\\\').replace("'", "\\'")
    return f"fullText contains '{safe}' and trashed = false"


def cmd_drive(registry, args):
    if len(args) < 2 or args[1] not in ('list', 'read', 'create'):
        raise Stop(USAGE['drive'], 2)
    who, verb, rest = args[0], args[1], args[2:]
    entry(registry, who)
    if verb == 'list':
        if len(rest) > 2 or (rest and not rest[0].isdigit()):
            raise Stop(USAGE['drive'], 2)
        count = min(int(rest[0]), 200) if rest else 10
        words = rest[1] if len(rest) == 2 else ''
        options = dict(q=drive_query(words), pageSize=count, fields='files(id,name,mimeType,modifiedTime,size)',
                       supportsAllDrives=True, includeItemsFromAllDrives=True)
        if not words:
            options['orderBy'] = 'modifiedTime desc'
        files = service(registry, who, 'drive').files().list(**options).execute().get('files', [])
        print(f"{who} ({entry(registry, who)['address']}): {len(files)} files" + (f' with the words "{words}"' if words else ', newest change first'))
        for item in files:
            changed = item.get('modifiedTime', '')
            if changed:
                changed = f"{local(datetime.datetime.fromisoformat(changed.replace('Z', '+00:00'))):%Y-%m-%d %H:%M}"
            print(f"  {item['id']} | {changed} | {short_type(item['mimeType'])} | {item.get('size', '-')} | {item['name']}")
        return 0
    if verb == 'read':
        if len(rest) not in (1, 2):
            raise Stop(USAGE['drive'], 2)
        drive = service(registry, who, 'drive')
        item = drive.files().get(fileId=rest[0], fields='id,name,mimeType,size', supportsAllDrives=True).execute()
        mime = item['mimeType']
        if mime == 'application/vnd.google-apps.folder':
            raise Stop(f"{item['name']} is a folder. Its files: google-drive {who} list 50, or search by words.")
        if mime in GOOGLE_FILES:
            data = drive.files().export(fileId=rest[0], mimeType=GOOGLE_FILES[mime][1]).execute()
        elif mime.startswith('application/vnd.google-apps.'):
            raise Stop(f"{item['name']} is a Google {short_type(mime)} file. Google gives no text form of it.")
        else:
            data = drive.files().get_media(fileId=rest[0], supportsAllDrives=True).execute()
        if isinstance(data, str):
            data = data.encode('utf-8')
        if len(rest) == 2:
            Path(rest[1]).write_bytes(data)
            print(f"saved {len(data)} bytes of {item['name']} to {rest[1]}")
            return 0
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            raise Stop(f"{item['name']} is not text ({mime}, {len(data)} bytes). Save it: google-drive {who} read {rest[0]} /FULL/PATH/out")
        sys.stdout.write(text if text.endswith('\n') else text + '\n')
        return 0
    if len(rest) not in (1, 2) or not Path(rest[0]).is_file():
        raise Stop(USAGE['drive'], 2)
    from googleapiclient.http import MediaFileUpload
    body = {'name': rest[1] if len(rest) == 2 else Path(rest[0]).name}
    made = service(registry, who, 'drive').files().create(
        body=body, media_body=MediaFileUpload(rest[0], resumable=False), fields='id,name,webViewLink').execute()
    print(f"created: {made['id']} | {made['name']} | {made.get('webViewLink', '')}")
    return 0


# ---------------------------------------------------------------- sign-in

def every_scope():
    return [scope for kind in KINDS for scope in SCOPES[kind]]


def needs_signin(registry, name):
    path = registry['folder'] / (name + '.json')
    return not path.is_file() or kinds_in(token_scopes(path)) != list(KINDS)


def consent_url(client, address, name, port=PORT):
    query = {'client_id': client['client_id'], 'redirect_uri': f'http://localhost:{port}/', 'response_type': 'code',
             'scope': ' '.join(every_scope()), 'access_type': 'offline', 'prompt': 'consent', 'login_hint': address, 'state': name}
    return client['auth_uri'] + '?' + urllib.parse.urlencode(query)


def post_form(url, fields):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return json.loads(answer.read())
    except urllib.error.HTTPError as problem:
        raise Stop('Google refused the sign-in code: ' + problem.read().decode('utf-8', 'replace')[:300])


def signed_in_address(access_token):
    request = urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                                     headers={'Authorization': 'Bearer ' + access_token})
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read())['emailAddress']


def finish_signin(registry, client, name, code, port=PORT):
    """Trade the code for a token, check whose it is, save it. Returns one result line."""
    answer = post_form(client['token_uri'], {'code': code, 'client_id': client['client_id'], 'client_secret': client['client_secret'],
                                             'redirect_uri': f'http://localhost:{port}/', 'grant_type': 'authorization_code'})
    scopes = answer.get('scope', '').split()
    got = kinds_in(scopes)
    if 'mail' in got:
        address = signed_in_address(answer['access_token'])
        if address.lower() != entry(registry, name)['address'].lower():
            return False, f"{name}: the page was allowed as {address}, a different account. Nothing was saved."
    if not answer.get('refresh_token'):
        return False, f'{name}: Google sent no lasting token. Nothing was saved.'
    registry['folder'].mkdir(mode=0o700, exist_ok=True)
    path = registry['folder'] / (name + '.json')
    path.touch(mode=0o600)
    os.chmod(path, 0o600)
    path.write_text(json.dumps({'token': answer['access_token'], 'refresh_token': answer['refresh_token'],
                                'token_uri': client['token_uri'], 'client_id': client['client_id'],
                                'client_secret': client['client_secret'], 'scopes': scopes}), encoding='utf-8')
    missing = [kind for kind in KINDS if kind not in got]
    if missing:
        return False, f"{name}: connected for {', '.join(got) or 'nothing'}. The boxes for {', '.join(missing)} were left unticked."
    return True, f'{name}: connected for mail, calendar and drive.'


def cmd_signin(registry, args):
    args, show_only, wait = list(args), False, 540
    while args and args[0].startswith('--'):
        flag = args.pop(0)
        if flag == '--print':
            show_only = True
        elif flag == '--wait' and args and args[0].isdigit():
            wait = int(args.pop(0))
        else:
            raise Stop(USAGE['signin'], 2)
    names = args or [name for name in registry['accounts'] if needs_signin(registry, name)]
    for name in names:
        entry(registry, name)
    if not names:
        print('Every account is connected for mail, calendar and drive.')
        return 0
    client = json.loads(Path(registry['client']).read_text(encoding='utf-8'))
    client = client.get('installed') or client.get('web') or client
    pending, results = list(names), {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *ignored):
            pass

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            name = (query.get('state') or [''])[0]
            if url.path != '/' or name not in pending:
                self.send_response(404); self.end_headers()
                return
            if 'code' in query:
                try:
                    ok, line = finish_signin(registry, client, name, query['code'][0])
                except Exception as problem:
                    ok, line = False, f'{name}: {problem}'
            else:
                ok, line = False, f"{name}: Google sent back {(query.get('error') or ['no code'])[0]}."
            results[name] = (ok, line)
            pending.remove(name)
            print(line, flush=True)
            if pending:
                self.send_response(302)
                self.send_header('Location', consent_url(client, entry(registry, pending[0])['address'], pending[0]))
                self.end_headers()
                return
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(b'<h2>All the Google pages are finished. You can close this tab.</h2>')

    server = HTTPServer(('127.0.0.1', PORT), Handler)
    first = consent_url(client, entry(registry, names[0])['address'], names[0])
    print(f"{len(names)} Google pages, one after another: {' '.join(names)}", flush=True)
    if show_only:
        print('OPEN: ' + first, flush=True)
    else:
        device = os.environ.get('ADB_DEV', '127.0.0.1:5555')
        shown = subprocess.run(['adb', '-s', device, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', shlex.quote(first)],
                               capture_output=True, text=True, timeout=30)
        if shown.returncode != 0 or 'Error' in shown.stdout + shown.stderr:
            print('The page did not open by itself: ' + (shown.stdout + shown.stderr).strip()[:200], flush=True)
            print('OPEN: ' + first, flush=True)
    print(f'Waiting up to {wait} seconds for the taps.', flush=True)
    deadline = time.time() + wait
    while pending and time.time() < deadline:
        server.timeout = max(1, min(30, deadline - time.time()))
        server.handle_request()
    server.server_close()
    for name in pending:
        print(f'{name}: no tap arrived.')
    return 0 if not pending and all(ok for ok, _ in results.values()) else 1


COMMANDS = {'accounts': cmd_accounts, 'signin': cmd_signin, 'unread': cmd_unread, 'mail': cmd_mail,
            'calendar': cmd_calendar, 'drive': cmd_drive}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print('usage: google-accounts.py accounts|signin|unread|mail|calendar|drive ...', file=sys.stderr)
        return 2
    if argv[1] not in ('accounts', 'signin') and len(argv) < 3:
        print(USAGE[argv[1]], file=sys.stderr)
        return 2
    try:
        registry = load_registry()
        if argv[1] not in ('accounts', 'signin') and argv[2] != 'all':
            entry(registry, argv[2])
        return COMMANDS[argv[1]](registry, argv[2:])
    except Stop as problem:
        print(problem, file=sys.stderr)
        return problem.code
    except Exception as problem:
        name = argv[2] if len(argv) > 2 else 'google'
        print(explain(problem, name), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
