# browsers — every Chrome the agent can drive, its port, and George's browser scripts

Which browser for what (checked 2026-11-19)
  Chrome Beta on the phone's hidden screen "web", port 9335. Signed in as George. up.
      The everyday one. Read: `card phone-browser`. Click and type: `card web-hands`.
  The laptop's headed Chrome, port 9222 on the laptop. Signed in to LinkedIn. It passes sites that block robots. up.
  The laptop's headless Chrome, port 9224 on the laptop. Google's consoles (Analytics, Search Console). up.
  George's own phone Chrome (com.android.chrome), port 9336. His daily browser, on his visible screen.
  The Linux hidden browser inside Debian, port 9222 here. No Google sign-in. down.
  Bright Data's fetcher: reads a page that blocks all of the above. No clicks, no sign-in.

The laptop's headed Chrome
  deb bash -c 'ssh wimlaptop "curl -s -m 5 http://127.0.0.1:9222/json/version"'      is it up; changes nothing
  deb bash /root/phone-chrome-agent/scripts/laptop_chrome.sh 'https://example.com'
      Starts it when needed, opens the tunnel 127.0.0.1:19222, opens the page and puts the window in front on
      George's laptop screen. Listed, not run.
  Then, through that tunnel: deb bash -c 'cd /root/.play && CDP_PORT=19222 node cdp.cjs "example.com" "document.title" - 300'

The laptop's headless Chrome (Google consoles)
  deb google-console status                    -> "status": "ready", "googleSessionPresent": true
  deb google-console --help                    every command as JSON: analytics-home, search-overview,
                                               search-inspect URL, and more. The how-to note:
  deb cat /root/.claude/projects/-root/memory/laptop-headless-browser.md

George's own phone Chrome
  deb bash /root/phone-chrome-agent/scripts/chrome.sh ['URL']
      Forwards its debug socket to 127.0.0.1:9336 and lists the tabs. With a URL it opens that page in his
      Chrome. It brings Chrome to the front of his screen when the socket is dead. Listed, not run.

Bright Data (Debian side; the sign-in is kept by the program)
  deb bdata budget                             -> "Balance $20.01"
  deb bdata scrape 'https://example.com'       the page as clean text. About $8 per GB.
  deb bdata --help                             search, zones, browser

George's scripts in /root/phone-chrome-agent/scripts (run with: deb bash, or deb node; the repo is
gugosf114/phone-chrome-agent, its README is the guide)
  cdpx.cjs, findclick.sh, fill.sh, clickread.cjs      click and type inside frames such as Google's payment box
  human.cjs                                           the library every new script uses: pointer path, key-by-key typing
  gather.cjs, gather_api.cjs                          read-only LinkedIn job gather through the laptop Chrome (CDP_PORT=19222)
  map_easy_apply.cjs                                  walks LinkedIn Easy Apply forms to Review; --submit sends a real application
  stage_ashby.cjs, stage_greenhouse.cjs               fill one application up to the Submit button; they never press it
  make_pdf.cjs, push_apply_files.sh                   make a job's PDFs and copy them to the laptop
  floorplan.cjs                                       read-only site crawler
  anti_freeze.sh                                      one-time phone settings against app freezing. It changes the phone.
  Each acts on a real site as George. Listed, not run. Recipes: /root/phone-chrome-agent/recipes.

The Linux hidden browser
  deb bash /root/hchrome/start.sh              starts it on port 9222 (deb bash /root/hchrome/start.sh stop stops it)
  The boot file tries this after every restart. Both tries on 2026-11-19 logged "hidden chrome did NOT come up".
  Log: ~/.agent-bridge/hidden-chrome.log. Its web-booking scripts (webfast.cjs, pg.cjs, ot_book.cjs) need it.

Known failure
  "no debug socket answered as Chrome Beta": `card phone-browser`. A laptop line that times out: `card doors`.
