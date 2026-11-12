"""The Google account commands: the account list, what each sign-in allows, the day window, the calendar
merge, the consent link and the sign-in bookkeeping. No test reaches Google."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import harness as h

SCRIPT = h.ROOT / 'toolbox' / 'debian' / 'google-accounts.py'
spec = importlib.util.spec_from_file_location('google_accounts', SCRIPT)
ga = importlib.util.module_from_spec(spec)
written, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # leave no cache folder beside the shipped commands
try:
    spec.loader.exec_module(ga)
finally:
    sys.dont_write_bytecode = written
MAIL, CALENDAR, DRIVE = ga.SCOPES['mail'], ga.SCOPES['calendar'], ga.SCOPES['drive']


def make_registry(folder, tokens=None):
    """An account list in a temp folder. tokens maps a file path (relative) to its scopes."""
    folder = Path(folder)
    listing = {'client': str(folder / 'client.json'), 'accounts': {
        'work': {'address': 'work@example.com', 'old_token': str(folder / 'old-work.json')},
        'shop': {'address': 'shop@example.com', 'service_key': str(folder / 'key.json')},
        'home': {'address': 'home@example.com'}}}
    (folder / 'accounts.json').write_text(json.dumps(listing), encoding='utf-8')
    (folder / 'client.json').write_text(json.dumps({'installed': {
        'client_id': 'client-id', 'client_secret': 'client-secret', 'auth_uri': 'https://accounts.example/auth',
        'token_uri': 'https://accounts.example/token'}}), encoding='utf-8')
    for name, scopes in (tokens or {}).items():
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'refresh_token': 'r', 'scopes': scopes}), encoding='utf-8')
    return ga.load_registry(folder / 'accounts.json')


class FakeCall:
    def __init__(self, answer):
        self.answer = answer

    def execute(self):
        return self.answer


class FakeCalendar:
    """Answers calendarList().list() and events().list() the way the Calendar API shapes them."""
    def __init__(self, calendars, events):
        self.calendars, self.pages, self.asked = calendars, events, []

    def calendarList(self):
        return self

    def events(self):
        return self

    def list(self, **options):
        if 'calendarId' not in options:
            return FakeCall({'items': self.calendars})
        self.asked.append((options['calendarId'], options.get('pageToken')))
        pages = self.pages.get(options['calendarId'], [[]])
        index = int(options.get('pageToken') or 0)
        answer = {'items': pages[index]}
        if index + 1 < len(pages):
            answer['nextPageToken'] = str(index + 1)
        return FakeCall(answer)


class AccountListTests(unittest.TestCase):
    def test_what_each_account_allows_comes_from_its_sign_in_files(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = make_registry(folder, {'old-work.json': MAIL, 'accounts/work.json': CALENDAR + DRIVE})
            self.assertEqual(ga.allowed(registry, 'work'), {'mail': 'sign-in', 'calendar': 'sign-in', 'drive': 'sign-in'})
            self.assertEqual(ga.allowed(registry, 'shop'), {'mail': 'service key', 'calendar': None, 'drive': None})
            self.assertEqual(ga.allowed(registry, 'home'), {'mail': None, 'calendar': None, 'drive': None})

    def test_the_newest_sign_in_is_used_first_and_the_old_one_still_serves_mail(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = make_registry(folder, {'old-work.json': MAIL, 'accounts/work.json': CALENDAR})
            self.assertEqual(ga.token_for(registry, 'work', 'calendar').name, 'work.json')
            self.assertEqual(ga.token_for(registry, 'work', 'mail').name, 'old-work.json')
            self.assertIsNone(ga.token_for(registry, 'work', 'drive'))
            Path(folder, 'accounts', 'work.json').write_text(json.dumps({'scopes': MAIL + CALENDAR + DRIVE}), encoding='utf-8')
            self.assertEqual(ga.token_for(registry, 'work', 'mail').name, 'work.json')

    def test_an_unknown_name_stops_with_the_names_and_exit_two(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = make_registry(folder)
            with self.assertRaises(ga.Stop) as caught:
                ga.entry(registry, 'nobody')
            self.assertEqual(caught.exception.code, 2)
            self.assertIn('work shop home', str(caught.exception))

    def test_a_missing_or_empty_account_list_stops_with_a_plain_sentence(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ga.Stop):
                ga.load_registry(Path(folder, 'none.json'))
            Path(folder, 'empty.json').write_text('{"accounts": {}}', encoding='utf-8')
            with self.assertRaises(ga.Stop):
                ga.load_registry(Path(folder, 'empty.json'))

    def test_an_account_needs_a_sign_in_until_one_file_holds_all_three(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = make_registry(folder, {'old-work.json': MAIL + CALENDAR + DRIVE, 'accounts/home.json': MAIL + CALENDAR})
            self.assertTrue(ga.needs_signin(registry, 'work'))
            self.assertTrue(ga.needs_signin(registry, 'home'))
            Path(folder, 'accounts', 'home.json').write_text(json.dumps({'scopes': MAIL + CALENDAR + DRIVE}), encoding='utf-8')
            self.assertFalse(ga.needs_signin(registry, 'home'))

    def run_tool(self, folder, *arguments):
        environment = {**os.environ, 'GOOGLE_ACCOUNTS_FILE': str(Path(folder, 'accounts.json'))}
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, env=environment, timeout=60)

    def test_the_account_listing_and_the_all_forms_name_what_is_not_connected(self):
        with tempfile.TemporaryDirectory() as folder:
            make_registry(folder, {'old-work.json': MAIL})
            listing = self.run_tool(folder, 'accounts')
            self.assertEqual(listing.returncode, 0)
            self.assertEqual(listing.stdout.splitlines(), [
                'work | work@example.com | mail: sign-in | calendar: no | drive: no',
                'shop | shop@example.com | mail: service key | calendar: no | drive: no',
                'home | home@example.com | mail: no | calendar: no | drive: no'])
            day = self.run_tool(folder, 'calendar', 'all', 'tomorrow')
            self.assertEqual(day.returncode, 0)
            self.assertEqual(day.stdout.count('not connected for calendar'), 3)
            self.assertRegex(day.stdout.splitlines()[0], r'^Phone clock: .+\. Tomorrow is \w{3} \w{3} \d{2} \d{4}\.$')
            one = self.run_tool(folder, 'calendar', 'home', 'tomorrow')
            self.assertEqual(one.returncode, 1)
            self.assertIn('home: calendar is not allowed yet', one.stderr)
            self.assertEqual(self.run_tool(folder, 'drive', 'home', 'list').returncode, 1)
            self.assertEqual(self.run_tool(folder, 'mail', 'shop', 'test').returncode, 2)

    def test_wrong_use_exits_two(self):
        with tempfile.TemporaryDirectory() as folder:
            make_registry(folder)
            for arguments in (['unread', 'nobody'], ['unread', 'work', 'many'], ['mail', 'work', 'send', 'one'],
                              ['calendar', 'work', 'nextweek'], ['calendar', 'all', 'list'], ['calendar', 'work', 'create', 'x'],
                              ['drive', 'work', 'delete'], ['signin', '--loud'], ['signin', 'nobody'], ['accounts', 'extra']):
                with self.subTest(arguments=arguments):
                    self.assertEqual(self.run_tool(folder, *arguments).returncode, 2)


class CalendarTests(unittest.TestCase):
    def test_the_day_window_is_local_midnight_to_the_next_local_midnight(self):
        today = datetime.date(2026, 11, 11)
        day, start, end = ga.day_window('tomorrow', today)
        self.assertEqual(day, datetime.date(2026, 11, 12))
        self.assertEqual((start.date(), start.hour, start.minute, end.date(), end.hour), (day, 0, 0, datetime.date(2026, 11, 13), 0))
        self.assertIsNotNone(start.tzinfo)
        self.assertEqual(ga.day_window('today', today)[0], today)
        self.assertEqual(ga.day_window('2026-12-01', today)[0], datetime.date(2026, 12, 1))
        with self.assertRaises(ga.Stop):
            ga.day_window('someday', today)

    def test_the_first_line_names_the_phone_clock_and_the_day_meant(self):
        now = datetime.datetime(2026, 11, 11, 21, 48).astimezone()
        line = ga.clock_line('tomorrow', datetime.date(2026, 11, 12), now)
        self.assertEqual(line, f'Phone clock: Wed Nov 11 2026 21:48 {now.tzname()}. Tomorrow is Thu Nov 12 2026.')

    def test_a_whole_day_event_counts_only_on_its_own_days(self):
        trip = {'start': {'date': '2026-11-12'}, 'end': {'date': '2026-11-14'}}
        self.assertFalse(ga.covers(trip, datetime.date(2026, 11, 11)))
        self.assertTrue(ga.covers(trip, datetime.date(2026, 11, 12)))
        self.assertTrue(ga.covers(trip, datetime.date(2026, 11, 13)))
        self.assertFalse(ga.covers(trip, datetime.date(2026, 11, 14)))
        self.assertTrue(ga.covers({'start': {'dateTime': '2026-11-12T09:00:00-08:00'}}, datetime.date(2026, 11, 11)))

    def test_events_come_from_every_shown_calendar_in_time_order_across_pages(self):
        noon = datetime.datetime(2026, 11, 12, 12, 0).astimezone()
        def timed(hour, title):
            return {'id': title, 'summary': title, 'start': {'dateTime': noon.replace(hour=hour).isoformat()},
                    'end': {'dateTime': noon.replace(hour=hour + 1).isoformat()}}
        calendar = FakeCalendar(
            [{'id': 'me', 'primary': True, 'summary': 'me'}, {'id': 'team', 'selected': True, 'summary': 'Team'},
             {'id': 'hidden', 'summary': 'Hidden'}],
            {'me': [[timed(15, 'late')], [timed(9, 'early')]],
             'team': [[{'id': 'off', 'summary': 'Day off', 'start': {'date': '2026-11-12'}, 'end': {'date': '2026-11-13'}},
                       {'id': 'next', 'summary': 'Next day', 'start': {'date': '2026-11-13'}, 'end': {'date': '2026-11-14'}},
                       timed(11, 'standup')]],
             'hidden': [[timed(10, 'secret')]]})
        day, start, end = ga.day_window('2026-11-12')
        rows = ga.events_between(calendar, start, end, day)
        self.assertEqual([(event['summary'], name) for event, name in rows],
                         [('Day off', 'Team'), ('early', 'main'), ('standup', 'Team'), ('late', 'main')])
        self.assertEqual(calendar.asked, [('me', None), ('me', '1'), ('team', None)])

    def test_an_event_line_holds_time_title_place_calendar_and_id(self):
        start = datetime.datetime(2026, 11, 12, 9, 0).astimezone()
        event = {'id': 'abc', 'summary': 'Dentist\nvisit', 'location': '5 Main St', 'start': {'dateTime': start.isoformat()},
                 'end': {'dateTime': (start + datetime.timedelta(minutes=45)).isoformat()}}
        self.assertEqual(ga.event_line(event, 'main', False), '09:00-09:45 | Dentist visit | 5 Main St | main | abc')
        self.assertEqual(ga.event_line(event, 'main', True), 'Thu Nov 12 09:00-09:45 | Dentist visit | 5 Main St | main | abc')
        whole = {'id': 'd', 'start': {'date': '2026-11-12'}, 'end': {'date': '2026-11-13'}}
        self.assertEqual(ga.event_line(whole, 'Team', False), 'all day | (no title) | - | Team | d')

    def test_a_new_event_takes_local_times_or_whole_days_with_the_last_day_included(self):
        self.assertEqual(ga.event_time('2026-11-20'), {'date': '2026-11-20'})
        self.assertEqual(ga.event_time('2026-11-21', closing=True), {'date': '2026-11-22'})
        moment = datetime.datetime.fromisoformat(ga.event_time('2026-11-20 14:30')['dateTime'])
        self.assertEqual((moment.hour, moment.minute, moment.utcoffset()), (14, 30, datetime.datetime(2026, 11, 20, 14, 30).astimezone().utcoffset()))
        with self.assertRaises(ga.Stop):
            ga.event_time('next tuesday')


class DriveAndSignInTests(unittest.TestCase):
    def test_search_words_are_quoted_for_drive(self):
        self.assertEqual(ga.drive_query(''), 'trashed = false')
        self.assertEqual(ga.drive_query("it's 5\\6"), "fullText contains 'it\\'s 5\\\\6' and trashed = false")
        self.assertEqual(ga.short_type('application/vnd.google-apps.spreadsheet'), 'spreadsheet')
        self.assertEqual(ga.short_type('application/vnd.google-apps.folder'), 'folder')
        self.assertEqual(ga.short_type('application/pdf'), 'pdf')

    def test_the_consent_link_asks_for_mail_calendar_and_drive_for_that_address(self):
        client = {'client_id': 'client-id', 'auth_uri': 'https://accounts.example/auth'}
        link = ga.consent_url(client, 'home@example.com', 'home')
        base, _, query = link.partition('?')
        fields = dict(ga.urllib.parse.parse_qsl(query))
        self.assertEqual(base, 'https://accounts.example/auth')
        self.assertEqual(fields['scope'].split(), MAIL + CALENDAR + DRIVE)
        self.assertEqual((fields['login_hint'], fields['state'], fields['redirect_uri'], fields['access_type'], fields['prompt']),
                         ('home@example.com', 'home', 'http://localhost:8765/', 'offline', 'consent'))

    def finish(self, folder, scopes, address='home@example.com', refresh='lasting'):
        registry = make_registry(folder)
        client = json.loads(Path(folder, 'client.json').read_text())['installed']
        old = ga.post_form, ga.signed_in_address
        ga.post_form = lambda url, fields: {'access_token': 'short', 'refresh_token': refresh, 'scope': ' '.join(scopes)}
        ga.signed_in_address = lambda token: address
        try:
            return ga.finish_signin(registry, client, 'home', 'code'), Path(folder, 'accounts', 'home.json')
        finally:
            ga.post_form, ga.signed_in_address = old

    def test_a_full_sign_in_is_saved_for_the_owner_only(self):
        with tempfile.TemporaryDirectory() as folder:
            (ok, line), path = self.finish(folder, MAIL + CALENDAR + DRIVE)
            self.assertEqual((ok, line), (True, 'home: connected for mail, calendar and drive.'))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            saved = json.loads(path.read_text())
            self.assertEqual((saved['refresh_token'], saved['scopes']), ('lasting', MAIL + CALENDAR + DRIVE))

    def test_unticked_boxes_are_named_and_the_part_allowed_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            (ok, line), path = self.finish(folder, MAIL + CALENDAR)
            self.assertFalse(ok)
            self.assertEqual(line, 'home: connected for mail, calendar. The boxes for drive were left unticked.')
            self.assertTrue(path.is_file())

    def test_a_sign_in_as_another_address_or_without_a_lasting_token_saves_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            (ok, line), path = self.finish(folder, MAIL + CALENDAR + DRIVE, address='other@example.com')
            self.assertFalse(ok)
            self.assertIn('other@example.com, a different account', line)
            self.assertFalse(path.exists())
            (ok, line), path = self.finish(folder, MAIL + CALENDAR + DRIVE, refresh=None)
            self.assertFalse(ok)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
