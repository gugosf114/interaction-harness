# calendar — Google Calendar for each account: a day's events, the days ahead, one event, a new event

NAME is an account name from `google-accounts` (see `card mail`). The word all asks every account.
Type each command as written, with no deb in front.

One day
  google-calendar all tomorrow           first line: "Phone clock: Wed Nov 11 2026 21:48 PST. Tomorrow is Thu Nov 12 2026."
                                         then every account, one block each:
                                         "berkeley (ADDRESS): 2 events on Thu Nov 12 2026"
                                         "  09:00-10:00 | Title | Place | main | EVENT_ID"
  google-calendar all today
  google-calendar NAME 2026-11-20        one account, one date
      Today and tomorrow are George's days, on the phone's clock in San Francisco. The UTC date is a day
      ahead of it every evening. Times are in the phone's own time zone. A whole-day event says "all day".
      "main" is the account's own calendar. Any other word names another calendar the account shows.
      An account with no calendar sign-in says "not connected for calendar".

The days ahead
  google-calendar NAME list              from now, 7 days: "Thu Nov 12 09:00-10:00 | Title | Place | main | EVENT_ID"
  google-calendar NAME list 30           from now, 30 days

One event
  google-calendar NAME read EVENT_ID     title, start, end, place, status, organizer, guests, meeting link,
                                         link, notes

A new event
  google-calendar NAME create 'TITLE' '2026-11-20 14:00' '2026-11-20 15:00' 'PLACE'
      This adds a real event to that account's main calendar at once. It invites nobody.
      Whole days: google-calendar NAME create 'TITLE' 2026-11-20 2026-11-21      (both days included)
      Prints: created: EVENT_ID | link

Where the keys live
  /root/.gmail/accounts/NAME.json, written by google-signin.

Known failure
  "calendar is not allowed yet": that account has no calendar sign-in. google-signin NAME opens Google's
  page on George's screen, and George taps Allow.
  "no event has the id": the id belongs to another account.
