#!/usr/bin/python3
"""Debian side of the mail trigger: the newest inbox messages of one mailbox as JSON. Marks nothing read.

mail_new.py berkeley|gmail [N]  ->  [{"id", "from", "subject", "date", "snippet"}, ...] oldest first.
It reuses the token and the Gmail client of /root/.gmail/bmail.py, like toolbox/debian/mail-unread.py.
"""
import importlib.util
import json
import os
import sys

BOXES = {'berkeley': None, 'gmail': '/root/.gmail/gmail_token.json'}


def main(argv):
    if len(argv) < 2 or argv[1] not in BOXES:
        print('usage: mail_new.py berkeley|gmail [N]', file=sys.stderr)
        return 2
    count = max(1, min(int(argv[2]) if len(argv) > 2 else 15, 50))
    if BOXES[argv[1]]:
        os.environ['BMAIL_TOKEN'] = BOXES[argv[1]]
    spec = importlib.util.spec_from_file_location('bmail', '/root/.gmail/bmail.py')
    bmail = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmail)
    service = bmail.svc()
    found = service.users().messages().list(userId='me', q='in:inbox', maxResults=count).execute()
    items = []
    for item in found.get('messages', []):
        message = service.users().messages().get(userId='me', id=item['id'], format='metadata').execute()
        head = bmail.headers(message)
        items.append({'id': item['id'], 'from': head.get('from'), 'subject': head.get('subject'), 'date': head.get('date'),
                      'snippet': message.get('snippet', '')})
    print(json.dumps(list(reversed(items))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
