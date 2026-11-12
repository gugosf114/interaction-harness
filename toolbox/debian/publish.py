#!/usr/bin/python3
"""Debian side of publish: put an HTML or Markdown file on a public web address.

  publish FILE [NAME]      FILE.html as it is, FILE.md turned into a page; prints https://abrahamyants.github.io/harness-pages/NAME/
  publish --list           every published page with its link
  publish --remove NAME    takes the page down

The pages live in the public GitHub repo abrahamyants/harness-pages (GitHub Pages, branch main), written with gh
as gugosf114. A page is live when GitHub's Pages build has finished; publish waits for that and fetches the link.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import makers_common as common  # noqa: E402

REPO = os.environ.get('PUBLISH_REPO', 'abrahamyants/harness-pages')
SITE = 'https://{}.github.io/{}/'.format(*REPO.split('/'))
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
USAGE = 'usage: publish FILE.html|FILE.md [NAME]  |  publish --list  |  publish --remove NAME'


class PublishError(Exception):
    pass


def gh(*args, data=None, run=subprocess.run):
    """One gh api call. Returns the parsed JSON, or None for a 404."""
    command = ['gh', 'api', *args]
    if data is not None:
        command += ['--input', '-']
    done = run(command, input=json.dumps(data) if data is not None else None, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        if 'HTTP 404' in done.stderr or '"status":"404"' in done.stdout:
            return None
        raise PublishError('GitHub: ' + (done.stderr.strip() or done.stdout.strip())[-500:])
    return json.loads(done.stdout) if done.stdout.strip() else {}


def slug(text):
    value = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:63]
    if not NAME.fullmatch(value or ''):
        raise PublishError(f'NAME must be letters, digits and dashes: {text!r}')
    return value


def page_html(path):
    text = Path(path).read_text(encoding='utf-8')
    if path.lower().endswith(('.md', '.markdown')):
        import office
        title = next((line.lstrip('# ').strip() for line in text.splitlines() if line.startswith('# ')), Path(path).stem)
        html = office.markdown_html(text).replace('<head>', '<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>'
                                                  + title.replace('&', '&amp;').replace('<', '&lt;') + '</title>', 1)
        return html.replace('@page{size:Letter;margin:1in}', 'body{max-width:46rem;margin:2rem auto;padding:0 1rem}', 1)
    if path.lower().endswith(('.html', '.htm')):
        return text
    raise PublishError('FILE must end in .html, .htm, .md or .markdown.')


def fetch(url, opener=urllib.request.urlopen):
    try:
        with opener(urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'harness-publish'}), timeout=30) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b''
    except (urllib.error.URLError, OSError):
        return 0, b''


def wait_for(url, want, sleep=time.sleep, opener=urllib.request.urlopen, tries=60):
    """Wait until url answers as wanted: ('live', bytes) or ('gone', None). About five minutes at most."""
    for _ in range(tries):
        status, body = fetch(url + '?t=' + str(time.time_ns()), opener)
        if want == 'gone' and status == 404:
            return status
        if want != 'gone' and status == 200 and want in body:
            return status
        sleep(5)
    return None


def publish(path, name):
    html = page_html(path)
    stamp = f'<!-- published {time.strftime("%Y-%m-%dT%H:%M:%S")} -->'
    data = (html.rstrip() + '\n' + stamp + '\n').encode('utf-8')
    target = f'repos/{REPO}/contents/{name}/index.html'
    old = gh(target)
    body = {'message': f'publish {name}', 'content': base64.b64encode(data).decode(), 'branch': 'main'}
    if old and old.get('sha'):
        body['sha'] = old['sha']
    gh('-X', 'PUT', target, data=body)
    url = SITE + name + '/'
    status = wait_for(url, stamp.encode())
    if status is None:
        print(f'{url}  sent; GitHub Pages had not served it after 5 minutes')
        return 1
    print(f'{url}  live (HTTP 200, {len(data)} bytes)')
    return 0


def listing():
    items = gh(f'repos/{REPO}/contents/') or []
    names = sorted(item['name'] for item in items if item.get('type') == 'dir')
    for name in names:
        print(f'{name}  {SITE}{name}/')
    if not names:
        print('No pages are published.')
    return 0


def remove(name):
    target = f'repos/{REPO}/contents/{name}/index.html'
    old = gh(target)
    if not old:
        raise PublishError(f'No page named {name}. publish --list shows them.')
    gh('-X', 'DELETE', target, data={'message': f'remove {name}', 'sha': old['sha'], 'branch': 'main'})
    url = SITE + name + '/'
    status = wait_for(url, 'gone')
    print(f'{url}  removed' + ('; the link answers 404' if status else '; GitHub Pages still served it after 5 minutes'))
    return 0 if status else 1


def main(argv):
    try:
        if argv == ['--list']:
            return listing()
        if len(argv) == 2 and argv[0] == '--remove':
            return remove(slug(argv[1]))
        if not 1 <= len(argv) <= 2 or argv[0].startswith('--') or (len(argv) == 2 and argv[1].startswith('--')):
            print(USAGE, file=sys.stderr)
            return 2
        path = os.path.abspath(os.path.expanduser(argv[0]))
        if not os.path.isfile(path):
            print(f'No file {argv[0]}.', file=sys.stderr)
            return 2
        name = slug(argv[1] if len(argv) == 2 else Path(path).stem)
        return publish(path, name)
    except (PublishError, common.MakerError, UnicodeDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2 if isinstance(exc, PublishError) and str(exc).startswith(('FILE must', 'NAME must')) else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
