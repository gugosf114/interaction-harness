#!/usr/bin/python3
"""Debian side of mail-unread. Prints how many unread messages sit in the inbox, then the newest ones.

mail-unread berkeley [N]   gugosf@berkeley.edu      mail-unread gmail [N]   gugosf@gmail.com
Read-only: it marks nothing as read. It reuses the token and the Gmail client of /root/.gmail/bmail.py.
"""
import importlib.util
import os
import sys

BOXES = {'berkeley': None, 'gmail': '/root/.gmail/gmail_token.json'}


def main(argv):
    if len(argv) < 2 or argv[1] not in BOXES:
        print('usage: mail-unread berkeley|gmail [N]', file=sys.stderr)
        return 2
    count = int(argv[2]) if len(argv) > 2 else 5
    if BOXES[argv[1]]:
        os.environ['BMAIL_TOKEN'] = BOXES[argv[1]]
    spec = importlib.util.spec_from_file_location('bmail', '/root/.gmail/bmail.py')
    bmail = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmail)
    service = bmail.svc()
    profile = service.users().getProfile(userId='me').execute()
    inbox = service.users().labels().get(userId='me', id='INBOX').execute()
    print(f"{profile['emailAddress']}: {inbox['messagesUnread']} unread in the inbox ({inbox['messagesTotal']} messages in the inbox)")
    found = service.users().messages().list(userId='me', q='is:unread in:inbox', maxResults=max(1, min(count, 50))).execute()
    for item in found.get('messages', []):
        head = bmail.headers(service.users().messages().get(userId='me', id=item['id'], format='metadata').execute())
        print(f"{item['id']} | {head['date'][:25]} | {head['from'][:40]} | {head['subject'][:90]}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
