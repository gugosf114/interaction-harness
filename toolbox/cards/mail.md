# mail — read George's Google mailboxes by account name, count the unread, send a reply

Accounts
  google-accounts            every account: name | address | mail | calendar | drive, for example
                             "berkeley | gugosf@berkeley.edu | mail: sign-in | calendar: no | drive: no"
  NAME below is a name from that list. The list is the file /root/.gmail/accounts.json.
  Type the google- and mail-unread commands as written, with no deb in front.

Unread
  mail-unread all            one line per account: "ADDRESS: 98 unread in the inbox (7348 messages in the inbox)"
                             An account with no sign-in says "not connected for mail".
  mail-unread all 3          the same, and under each count the newest 3 unread: id | date | from | subject
  mail-unread NAME 5         one account. It marks nothing as read.

Read
  google-mail NAME test                      the address, the total, the three newest
  google-mail NAME list 5 "GMAIL QUERY"      one JSON object per line: id, threadId, from, to, subject, date,
                                             text, attachments
  google-mail NAME thread THREAD_ID          every message in one thread
  google-mail NAME unread 10                 the newest unread: id | date | from | subject
  google-mail NAME markread ID ID            takes the unread mark off those messages

Send a reply
  google-mail NAME send MESSAGE_ID /FULL/PATH/body.txt
      This sends a real email at once from that account, as a reply inside that thread.
      There is no draft step. To, Subject and threading come from the message being answered.
      The sender name is "George Abrahamyants". Prints one JSON object: sent_id, threadId, to, subject.

Bakery: info@mybakingcreations.com reads with a service key, through its own reader
  deb python3 /root/.gmail/mail.py test                 the address, the total, the three newest sent
  deb python3 /root/.gmail/mail.py inbound 5            newest mail from customers, JSON per line
  deb python3 /root/.gmail/mail.py sent 5 "QUERY"       newest sent mail
  The house voice for bakery replies: deb cat /root/.gmail/voice-sheet.md
  After a sign-in for bakery, the google-mail lines work for it too.

Connect an account, or add calendar and drive to one
  google-signin              opens Google's consent page on George's screen for every account that lacks
                             mail, calendar or drive, one page after another, and waits 9 minutes.
                             George taps: Advanced, Go to Newton Bridge, Select all, Continue.
  google-signin NAME         one account.
  A new account: add its name and address to /root/.gmail/accounts.json, then google-signin NAME.

The older forms still work
  deb python3 /root/.gmail/bmail.py test | list 5 "QUERY" | thread ID | markread ID        Berkeley
  deb /root/.gmail/gmail test | list 5 "QUERY" | thread ID | markread ID                   Gmail

Where the keys live
  /root/.gmail/accounts/NAME.json (one per sign-in), /root/.gmail/berkeley_token.json,
  /root/.gmail/gmail_token.json, /root/.gmail/sa.json (bakery).

Known failure
  "is not allowed yet" or "not connected": that account has no sign-in for that service. google-signin NAME.
  "invalid_grant": Google ended that sign-in. google-signin NAME opens the page again.
  "no tap arrived": the page opened and nobody tapped within the wait.
