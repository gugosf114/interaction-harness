# phone-browser — the signed-in Chrome on the phone's hidden screen

What it is
  Chrome Beta on the hidden screen "web". It is signed in with the phone's own Google accounts, so it opens
  Google pages and other signed-in sites as George. George does not see it. Debug port: 127.0.0.1:9335.

Start it, or make sure it runs
  deb bash /root/hidden-operator/web/phone-chrome.sh up
  -> "phone chrome up: cdp=127.0.0.1:9335 (Chrome Beta, pid N, socket ..., hidden screen web)"

Which Google account is signed in
  page-text 'https://myaccount.google.com/email' 5000
  -> "TITLE: Email", then the page text with the account's address. A sign-in page means it is signed out.
  deb bash /root/hidden-operator/web/phone-chrome.sh check answers "could not read accounts: {}" unless the
  first open tab is a Google page (checked 2026-11-19).

Open a URL and read the page text
  page-text 'https://example.com'
  page-text 'https://example.com' 8000        wait 8 more seconds after the page loads (default 4000 ms)
  Prints "TITLE: ...", "URL: ...", a blank line, then the visible text. It closes the tab it opened.

Run JavaScript in a page, click, or take a picture of it
  deb bash -c 'cd /root/.play && node cdp.cjs "new:https://URL" "document.title" /sdcard/Download/page.png 3000'
  First argument: "new:URL" opens a tab; or a piece of the address of a tab that is already open.
  Second: a JavaScript expression; "close" closes that tab. Third: a PNG path, or - for none. Fourth: wait in ms.
  Prints RESULT (the value as JSON), PAGE (address | title) and SHOT (the picture path).

List the open tabs
  deb bash -c "curl -s -m 8 127.0.0.1:9335/json/list | jq -r '.[] | select(.type==\"page\") | .url'"

Facts
  A click or a form sent from here acts on that site as George.
  The browser's user agent is a phone. Pages load in their mobile layout.

Other browsers (the laptop's two Chromes, George's own phone Chrome, Bright Data): `card browsers`.

Known failure
  "no debug socket answered as Chrome Beta": Android froze the browser. Reopen it, then run `up` again:
  deb bash /root/hidden-operator/scripts/hidden_display.sh launch -n web com.chrome.beta
  Seen three times on 2026-11-19. page-text and page-open reopen it by themselves and worked each time.
  After it, cdp.cjs says "no Chrome on port 9335" until `up` has run.
