# mail — read George's mailboxes and send a reply

Berkeley: gugosf@berkeley.edu
  mail-unread berkeley 5
      First line, for example: "gugosf@berkeley.edu: 98 unread in the inbox (7348 messages in the inbox)".
      Then the newest unread inbox mail, newest first: id | date | from | subject. It marks nothing as read.
  deb python3 /root/.gmail/bmail.py test                        the address, the total, the three newest
  deb python3 /root/.gmail/bmail.py list 5 "GMAIL QUERY"        one JSON object per line: id, threadId, from,
                                                                to, subject, date, text, attachments
  deb python3 /root/.gmail/bmail.py thread THREAD_ID            every message in one thread
  deb python3 /root/.gmail/bmail.py markread ID ID              takes the unread mark off those messages

  Send a reply
  deb python3 /root/.gmail/bsend.py MESSAGE_ID /FULL/PATH/body.txt
      This sends a real email at once from gugosf@berkeley.edu, as a reply inside that thread.
      There is no draft step. To, Subject and threading come from the message being answered.
      Prints one JSON object: sent_id, threadId, to, subject.

Gmail: gugosf@gmail.com (the same verbs)
  mail-unread gmail 5
  deb /root/.gmail/gmail test | list 5 "QUERY" | thread THREAD_ID | markread ID
  deb /root/.gmail/gmail send MESSAGE_ID /FULL/PATH/body.txt    This sends a real email at once.

Bakery: info@mybakingcreations.com (read)
  deb python3 /root/.gmail/mail.py test                         the address, the total, the three newest sent
  deb python3 /root/.gmail/mail.py inbound 5                    newest mail from customers, JSON per line
  deb python3 /root/.gmail/mail.py sent 5 "QUERY"               newest sent mail
  The house voice for bakery replies: deb cat /root/.gmail/voice-sheet.md

Where the keys live
  /root/.gmail/berkeley_token.json, /root/.gmail/gmail_token.json, /root/.gmail/sa.json (bakery).

Known failure
  "invalid_grant" on Berkeley or Gmail: the Google sign-in expired (it lasts 7 days). Renew it:
  deb bash -c 'cd /root/.gmail && WAIT=540 ./berkeley_auth.py'
  That opens Google's consent page on the phone, and George taps Allow.
  /root/.gmail/venv is gone, so run the scripts with python3 as written here.
