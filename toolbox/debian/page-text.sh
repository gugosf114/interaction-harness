#!/bin/bash
# Debian side of page-text. Opens URL in the signed-in phone Chrome (Chrome Beta on the hidden screen "web"),
# prints the title, the final address and the page text, then closes the tab it opened.
set -u
url=${1:-}; wait_ms=${2:-4000}
case "$url" in http://*|https://*) ;; *) echo 'usage: page-text URL [WAIT_MS]' >&2; exit 2 ;; esac
bash /root/hidden-operator/web/phone-chrome.sh up >/dev/null 2>&1 || { bash /root/hidden-operator/web/phone-chrome.sh up >&2; exit 1; }
cd /root/.play || exit 1
out=$(node cdp.cjs "new:$url" 'JSON.stringify({title:document.title,url:location.href,text:document.body?document.body.innerText:""})' - "$wait_ms" 2>&1)
code=$?
printf '%s\n' "$out" | python3 -c '
import json, sys
for line in sys.stdin:
    if line.startswith("RESULT "):
        try:
            page = json.loads(json.loads(line[7:]))
        except (ValueError, TypeError):
            print(line.strip()); sys.exit(1)
        print("TITLE: " + page["title"]); print("URL: " + page["url"]); print(); print(page["text"]); sys.exit(0)
sys.stderr.write(sys.stdin.read() or "The page did not answer.\n"); sys.exit(1)
' || { printf '%s\n' "$out" >&2; exit ${code:-1}; }
final=$(printf '%s\n' "$out" | sed -n 's/^PAGE \(.*\) | .*$/\1/p' | head -1)
[ -n "$final" ] && node cdp.cjs "$final" close >/dev/null 2>&1
exit 0
