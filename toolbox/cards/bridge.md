# bridge — George's Agent Bridge command and the tools it carries; which parts work on this phone today

Runs on: the Termux side. The command is `agent-bridge` (the repo calls it `bridge`). The repo is
gugosf114/agent-bridge; the installed copy is ~/.local/share/agent-bridge. Checked 2026-11-19.

Works today
  agent-bridge status                -> "Agent: codex available / Laptop: connected / Phone ADB: connected /
                                         Always-on box: connected"
  agent-bridge tools                 the list of tool groups
  agent-bridge gmail test            the bakery mailbox reader (the same as `card mail`)
  agent-bridge google --help         Analytics and Search Console through the laptop (the same as deb google-console)
  agent-bridge checkpoint --help     saved tasks with proof: check, run, resume, status, events, replay, permit, revoke
  agent-bridge jobs --help           the job application door (the same as job-apply --help): find, queue, start,
                                     prepare, stage, review, approve, submit, status CASE, and a reply loop
      `job-apply approve-and-submit` sends a real job application. Listed, not run.
  ~/godmode                          a health line for adb, the laptop and Codex's settings
  agent-bridge here "TASK"           starts a Codex worker on this phone with the task. It acts without asking.
  agent-bridge laptop "TASK"         the same on the laptop. For the laptop use `card laptop` (laptop_task.sh).
  agent-bridge screen | tap X Y | open URL      a picture of, a tap on, a page opened on George's visible screen
  The last five lines are listed, not run.

Not working on this phone today (each answer is the program's own)
  agent-bridge learn, agent-bridge browse    the installed copy has no such tool; it prints its usage line
  agent-bridge voice                 "Agent Bridge tool voice is not installed. Run: bridge setup-tools"
                                     Speaking works another way: `card voice`.
  agent-bridge cookies status        "no usable Chromium executable was found"
  browser-headless --profile default status      the same Chromium message
  browser-runner --profile job-applications --backend laptop-chrome status
                                     "backend 'laptop-chrome' requires a running browser-runner-daemon"
  linkedin-headless, play-headless status, bing-places-headless status
                                     "the full Playwright Chromium executable is missing"
  foursquare-headless api-status     "the Foursquare service key is missing; run `foursquare-headless set-key`"
  pinterest-headless api-status      "Pinterest API 401: Authentication failed."
  firebase                           "Cannot find module 'semver'"
  These lost their browser or key in the move from the Z Flip 7 to the Pixel 11. What does the same job today:
  a signed-in website: `card web-hands`. LinkedIn and job forms: `card browsers`. Google Play: `deb play`
  (`card bakery`). Pinterest numbers: bakery-stats.

Help that works with no browser
  foursquare-headless --help ; bing-places-headless --help ; play-headless --help ; browser-headless --help

Known failure
  "BROWSER_ROUTE_REQUIRED choose --backend ...": browser-runner needs --backend phone-headless,
  android-chrome, laptop-chrome or cdp on every call.
