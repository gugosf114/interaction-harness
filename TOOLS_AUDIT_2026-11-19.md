# Tools audit, Nov 19, 2026

The lanes (`g2`, `g1`) learn their tools from one index page and the cards. This audit checked the index and all 46 cards against the real phone, fixed them, and proved the fix.

- Who ran it: a Claude Code session on the Pixel 11, from the brief `/root/.claude/briefs/tools-audit-2026-11-19.md`.
- When: 4:18 pm to about 8 pm Pacific. The phone restarted by itself at 4:54 pm (battery at 9% at 4:35 pm). Checks after 5 pm are after that restart.
- How each command was run: in native Termux through the harness's own runner, `python ~/interaction-harness/toolbox/hrun.py 'COMMAND'`. The exit code after each line below is the one the runner printed. A command piped into `head` or `cut` shows the pipe's exit code, so an error text can sit next to exit 0; the text is quoted where that happened.
- Raw output of every batch is on the phone in `/root/work/audit-raw/` (`b1.out` to `b12.out`). Three values that showed up there were blanked: the service page password, a login code from a text, and map coordinates.
- Nothing that sends, calls, pays, posts, deletes or uninstalls was run. Those are on the cards as "listed, not run".

## Counts

- List A, on the phone and on no card: 46 lines.
- List B, on a card and broken or gone today: 17 lines. 6 repaired, 4 pointed at a working command, 7 still broken.
- List C, on a card with a stale fact: 27 lines.
- Cards: 46 before, 53 after. 7 new, 27 corrected, 19 unchanged.
- Index: 6,487 characters before, 7,503 after (cap 8,000). Largest card: 3,966 characters (cap 4,000).

## The two repositories George ordered read

Both were cloned fresh from GitHub for this audit and read from those clones, not from the copies on the phone.

- `gugosf114/phone-chrome-agent` at `247fc0a` (Oct 29). Read in full: `README.md`, `the-map.md`, `journal.md`, every file in `recipes/`, `picks/README.md`, and the folded `hidden-operator/` documents (`README.md`, `HIDDEN-SCREEN.md`, `FOLDED.md`, `LEARNING.md`, `web/README.md`, `tools/hidden-display/README.md` and `TEACH.md`, `runtime/task-engine/README.md`, `bin/op`). Every script: its header and usage lines, and a search of every text file for port numbers.
- `gugosf114/agent-bridge` at `ad7b18c` (Oct 26). Read in full: `README.md`, `START_HERE.md`, `RUNBOOK.md`, `BROWSER-TASKS.md` (first part), `docs/tool-consolidation.md`, `tools/session-toolkit/README.md`. The `bridge` command's verb table, every script name, and the same port search.
- Not read: `HISTORY.md` and `docs/agent_bridge_v2_blueprint.md` (build history and a design paper), the test folders, and in phone-chrome-agent the data folders `apply/`, `me/`, `logs/`, `research/`, `floor-plans/` and `picks/*.json` (job packets, the dossier, logs). Script bodies were not read line by line.

Ports the two repositories name, and where each now sits: 5555, 5037, 8022, 8080 (phone); 9335, 9336, 9222, 9333, 9223, 9225 (phone browsers and helpers); 22, 9222, 9224, 9226, 9227, 8081, 8000, 11434 (laptop); 19222, 19224, 15555 (tunnels from the phone); 8787, 18080 (the box); 6080, 5905 (the old sign-in viewer). All are on `card doors` except 9333, 9223, 6080, 5905, 8000, 11434 and 15555: nothing listens on those today and nothing on the phone uses them.

## List A: on the phone, on no card

Each line: the tool, the command run and its exit code, and the card it is on now.

The lane's own commands
1. `job`, `job list`, `job show`: `job list | head -4`, exit 0, six jobs listed. Card `always-on`.
2. `agentd`: `agentd status`, exit 0. It prints the page password in its output; the card says so. Card `always-on`.
3. `talk`: `talk --help`, exit 0. Card `always-on`.
4. This client's other engines: `harness --engine gemini --effort low 'Reply with the single word OK'`, exit 0, "OK". Card `models`.
5. `harness --both`: `harness --help | grep -A2 -e --both`, exit 0. No `both` command is on the path (`both --help`, "command not found"). README.

Agent Bridge and its tools
6. `agent-bridge` (the repo's `bridge`): `agent-bridge status`, exit 0, laptop, adb and box "connected". Card `bridge`.
7. `agent-bridge tools`: exit 0, fifteen tool groups. Card `bridge`.
8. `agent-bridge checkpoint`: `agent-bridge checkpoint --help`, exit 0. Card `bridge`.
9. `job-apply`: `job-apply --help`, exit 0. Card `bridge`.
10. `browser-runner`, `browser-runner-daemon`, `browser-daemon`: `browser-runner --profile job-applications --backend laptop-chrome status`, exit 0, "requires a running browser-runner-daemon". Card `bridge`, under not working.
11. `browser-headless`, `browser-cookie-import`: `browser-headless --profile default status`, exit 0, "no usable Chromium executable was found". Card `bridge`, under not working.
12. `linkedin-headless`, `linkedin-daemon`: `linkedin-headless --help`, exit 0, "daemon did not become ready"; its log says "the full Playwright Chromium executable is missing". Card `bridge`, under not working.
13. `play-headless`: `play-headless status`, exit 0, same Chromium message. Card `bridge`, under not working.
14. `bing-places-headless`: `bing-places-headless status`, exit 0, same message. Card `bridge`, under not working.
15. `foursquare-headless`: `foursquare-headless api-status`, exit 0, "the Foursquare service key is missing". Card `bridge`, under not working.
16. `pinterest-headless`: `pinterest-headless api-status`, exit 0, "Pinterest API 401: Authentication failed." Card `bridge`, under not working.
17. `firebase`: `firebase --version`, exit 1, "Cannot find module 'semver'". Cards `bridge` and `programs`.
18. `~/godmode`: exit 0, three health lines. Card `bridge`.

Hidden screens
19. The one door `op`: `deb bash /root/hidden-operator/bin/op`, exit 0; `op screen list`, exit 0; `op keeper status`, exit 0. Card `hidden-screens`.
20. `hidden_display.sh` verbs the cards did not have (grid, zoom, status, id, swipe, key, ensure, stopall, reap, tall screens): `... grid -n web 200 FILE`, exit 0, a 148 KB picture; `... id -n web`, exit 0, "4"; `... zoom -n web 540 1200 130 4`, exit 0, "no frame" (it needs a grid first). Card `hidden-screens`.
21. `read_all.sh` (Termux side only): `bash ~/hidden-operator/scripts/read_all.sh -n apps 1`, exit 0, "0 screens, 0 rows". Card `hidden-screens`.
22. Saved app maps in `/root/.hidden-maps`: `deb ls /root/.hidden-maps`, exit 0, three maps. Card `hidden-screens`.

Browsers
23. The laptop's headed Chrome on 9222 (task `GeorgeJobApplicationsChrome`): `deb bash -c 'ssh wimlaptop "curl -s -m 5 http://127.0.0.1:9222/json/version"'`, exit 0, Chrome 157. Cards `browsers`, `doors`.
24. `laptop_chrome.sh` and `chrome.sh` (George's own Chrome, port 9336): listed, not run; both put a window in front on a screen George uses. Card `browsers`.
25. The phone-chrome-agent scripts (`cdpx.cjs`, `findclick.sh`, `fill.sh`, `clickread.cjs`, `human.cjs`, `gather.cjs`, `gather_api.cjs`, `map_easy_apply.cjs`, `stage_ashby.cjs`, `stage_greenhouse.cjs`, `make_pdf.cjs`, `push_apply_files.sh`, `floorplan.cjs`, `anti_freeze.sh`): present in `/root/phone-chrome-agent/scripts` (`ls`, exit 0); listed, not run. Card `browsers`.
26. Bright Data: `deb bdata budget`, exit 0, "$20.01"; `deb bdata scrape 'https://example.com'`, exit 0, the page text. Cards `browsers`, `research`.
27. `google-console status`: exit 0, "ready", session present. Card `browsers`.

Doors and the network
28. The voice line's server on 8790 and its two tunnels: `curl ... http://127.0.0.1:8790/`, exit 0, 200. Card `doors`.
29. The lane service's page on 8377: `curl ... http://127.0.0.1:8377/`, exit 0, 401. Cards `doors`, `always-on`.
30. The listener list: `adb -s 127.0.0.1:5555 shell 'ss -ltnH'`, exit 0. Port 9080 and a few high ports listen and no file on the phone names their owner. Card `doors`.
31. The laptop's scheduled tasks: `deb ssh wimlaptop 'schtasks /query /fo csv /nh | findstr ...'`, exit 0, four tasks. Card `laptop`.
32. Tailscale's state and its new keeper: `ping -c 1 -W 3 100.100.100.100`, exit 0; `sh ~/bin/tailscale_keeper.sh once`, exit 0. Cards `devices`, `doors`, `boot`.
33. `adb-connect-existing`, `ts-fix`, `flip-red`: read, not run. Card `devices`.

Timers and boot
34. Timers the card did not name: 7730 mailcheck, 9106 watch-heartbeat, 7732 droidrun-watch, 7743 usage-watch: `termux-job-scheduler --pending`, exit 0. Card `timers`.
35. Boot file `20-agentd`: `ls ~/.termux/boot`, exit 0. Card `boot`.

Keys, by name only
36. Key files no card named (`/root/.twilio/password`, `/root/.ga4/*`, `/root/.google-search/env`, `/root/.keys/*`, `/root/.mbc/listings.env`, `/root/.openai-key`, `/root/.cloudflared`, `/root/.brightdata`, the voice line's key files, the harness's own key files): `deb ls /root/.ga4 /root/.keys ...`, exit 0. Card `keys`.
37. The 46 secret names (the cloud card had only the count): `deb gcloud secrets list ...`, exit 0. Card `keys`.

Models and windows
38. `glm`, `glmplain`, `glmoff`, `glm-mirror`: `cat ~/.glm_url`, "No such file", so the first two answer "not live". `glmoff` ends a rented machine: listed, not run. Card `models`.
39. `brain`, `fork-mcfly`, `launch`, `reasoning-trace`, `~/.shortcuts`, the voice line's tmux rooms: `tmux -L vapi-line ls`, exit 0, four rooms. Card `sessions`.
40. `codex-session-message`: `~/bin/codex-session-message --list`, exit 1, "No live raw-Termux Codex sessions found." Card `sessions`.

Calls, mail, bakery, TV
41. `voice-session` and `/root/.vapi/place_call.py`: listed, not run (see "My mistake" below). Card `calls`.
42. `/root/.gmail/idraft.py`, `isend.py`, `bsend.py`, and the 30-minute `mailcheck.sh`: read, not run. Card `mail`.
43. `/root/.play/aso_app.py`, `aso_rank.sh`: read, not run. Card `bakery`.
44. `bscpylgtvcommand`: `deb bscpylgtvcommand --help`, exit 0. Card `tv`.

Phone
45. Termux:API commands on no card: `termux-telephony-cellinfo` (exit 0, `[]`), `termux-media-scan -h` (exit 0), `termux-notification-channel -h` (exit 0), `termux-wake-lock`, `termux-storage-get`, the seven `termux-saf-*` file commands, `termux-infrared-transmit`. Card `phone-hardware`.

Claude Code's connectors
46. What George's Claude Code sessions have and the lanes lack. Has an equal on a card: Gmail (`google-mail`), Calendar (`google-calendar`), Drive (`google-drive`), PayPal (`paypal-get` and the curl lines), web search and fetch, a browser with hands, PDF tools, pictures, skills, background runs. No equal on the phone: Canva, Figma, Adobe, Claude Docs and Artifacts, Microsoft 365, Slack, Notion, Linear, Atlassian, Intercom. Gaps inside the equals: no mail draft step for the personal accounts, no calendar update or delete, no Drive share or move, no PayPal payment links or disputes. Card `connectors`.

Two smaller additions: `~/.local/bin/berkeley-job-mail-watch` (alerts on a job-mail notification; no timer runs it) is on `card timers`, and the conductor's extra endpoints (`/dash/laptop/job`, `/dash/cmd`, `/dash/missions`, `/dash/watch`, `/dash/memory`, `/dash/outbox`) are on `card agent-box`. Both are listed, not run.

## List B: on a card, broken or gone today

Repaired
1. Every `rish` line (cards `shizuku`, `phone-settings`, `boot`, `alerts`, `apps`): `rish -c id`, exit 1, "Request timeout. The connection between the current app (com.termux) and Shizuku app may be blocked". Shizuku's permit file held no entries (changed Nov 16, 5:43 am). After the repair: `rish -c id`, exit 0, `uid=2000(shell)`.
2. The MCP camera tools (cards `mcp-see`, `mcp-apps`): `mcp android_list_cameras`, exit 0, "CAMERA permission not granted". After the grant: exit 0, two cameras listed.
3. The MCP location tool (card `mcp-see`): `mcp android_get_location '{"fresh_fix":false}'`, exit 0, "Location permission not granted". After the grant: exit 0, a position.
4. The boot card's "start-agent-bridge.off, switched off": it was not off. At the 4:54 pm restart it started `signal.sh --watch`, `brain_beacon.sh` and timer 7919, which George had stopped that day (`ps -eo pid,etime,args | grep ...`, two processes, 2 hours old; `termux-job-scheduler --pending`, job 7919 listed). Stopped again; file moved out of the boot folder. After: `ps ... | wc -l`, 0; `termux-job-scheduler --pending | grep -c 'Job 7919'`, 0.
5. Tailscale after a restart (cards `laptop`, `devices`, `yana-phone`, `agent-box` all depend on it): at 6:57 pm `ping` to three tailnet addresses lost every packet and `deb ssh wimlaptop ...` timed out (exit 0 through a pipe, "Connection timed out"). Tailscale was off after the restart. Turned on, set as the always-on VPN, keeper added. After: `deb ssh -o ConnectTimeout=10 wimlaptop hostname`, exit 0.
6. The phone settings Bluetooth line (card `phone-settings`): `rish -c 'dumpsys bluetooth_manager' | grep -A12 'Bonded devices'`, exit 0, "grep: (standard input): binary file matches". With `grep -a`: exit 0, four devices.

Pointed at a working command
7. Hidden-screen scripts by their old path (card `agent-scripts`): `deb bash /root/agent-bridge/scripts/hidden_drive.sh read web`, exit 0 through a pipe, "adb: more than one device/emulator". The copies in `/root/hidden-operator/scripts` run; the new card `hidden-screens` uses them.
8. Reading texts by the old path (card `agent-scripts`): `deb bash /root/agent-bridge/scripts/read_sms_code.sh latest 2`, exit 0, "[sms] no live adb — skip". `deb bash /root/hidden-operator/scripts/read_sms_code.sh latest 2`, exit 0, two texts.
9. Which Google account the hidden browser holds (card `phone-browser`): `deb bash /root/hidden-operator/web/phone-chrome.sh check`, exit 0, "could not read accounts: {}". Working: `page-text 'https://myaccount.google.com/email' 5000`, exit 0, the account's address.
10. Location through Termux (card `phone-hardware`): `termux-location -p network -r last`, exit 0, `"API_ERROR": "Failed to get location"`; `-r once`, exit 124 (timed out). The card now leads with the MCP tool.

Still broken
11. `agy --print 'QUESTION'` (card `models`): exit 0, "Authentication required. Please visit the URL to log in ... Error: authentication timed out." Needs George's sign-in.
12. `grok -p 'QUESTION'` (card `models`): exit 1, "Not signed in." Same as Nov 11. Needs George.
13. PayPal transactions (card `money`): `paypal-get '/v1/reporting/transactions?...'`, exit 0 through a pipe, `NOT_AUTHORIZED`. Same as Nov 11. Needs George in the PayPal developer dashboard.
14. The name reader for hidden screens (cards `agent-scripts`, now `hidden-screens`): `deb bash /root/hidden-operator/scripts/hidden_drive.sh read web`, exit 0, prints nothing. Two `hidden_display.sh ensure` processes sat stuck for 1 and 3 hours trying to restart it.
15. The Linux hidden browser on 9222 (cards `boot`, now `browsers`): `deb curl -s -m 4 ... http://127.0.0.1:9222/json/version`, exit 7. The boot log says "hidden chrome did NOT come up" for both starts that day.
16. `inception status` (card `programs`): exit 0 through a pipe, "codex app-server daemon version failed".
17. `phone-chrome.sh up` (card `phone-browser`): exit 1, "no debug socket answered as Chrome Beta", three times out of six. `page-text` and `page-open` reopen the browser themselves and worked every time (exit 0).

The status-light scripts on `card agent-scripts` (`signal.sh --setup`, `--state`, `status_beacon.sh`) are not broken; George had them stopped. The card now says "Stopped on George's word. Do not start them."

## List C: on a card, with a stale fact

1. `boot`: "No keeper loop is running." `ps -eo args | grep -E '[s]hizuku_keeper|...'`, exit 0, six loops at 4:26 pm, seven after the restart, eight with the Tailscale keeper.
2. `boot`: the hidden-screen keeper "watch: DEAD". `bash ~/hidden-operator/scripts/hidden_supervisor.sh status`, exit 0, "apps: UP, web: UP, watch: ALIVE".
3. `boot`: "the voice line is down." `deb bash /root/.vapi/bridge/phone.sh status`, exit 0, room up, server up, tunnel up.
4. `calls`: "server down, tunnel down, room brain gone." Same command, same answer; `deb voice-list`, exit 0, "★ brain [up]".
5. `boot`, `timers`: "Android lists no scheduled timers", "the table holds seven timers". `wc -l ~/.local/share/timers.tsv`, exit 0, 9 (10 with the new one); `termux-job-scheduler --pending | wc -l`, exit 0, 9.
6. `models`: Claude Code "prints a notice that this sign-in ends between 2026-11-17 and 2026-11-20". `claude -p 'Reply with the single word OK'`, exit 0, "OK" and nothing else.
7. `models`: Google's Antigravity "prints the answer only, about 6 seconds". See B 11.
8. `agent-scripts`: `droidrun.sh status` "is not enabled as an accessibility service". `deb bash /root/agent-bridge/scripts/droidrun.sh status`, exit 0, "Portal is installed and accessible."
9. `agent-scripts`: the status light and the laptop beacon shown as live tools. George had them stopped on Nov 19.
10. `programs`: `deb assistant jobs` and `status` "Connection refused". `deb assistant status`, exit 0, a status object; `deb assistant jobs`, exit 0, a job list.
11. `devices`: the adb list. `adb devices -l` at 4:33 pm, exit 0: this phone and Yana's only. At 7:07 pm, exit 0: this phone, the Flip, and Yana's by her home Wi-Fi address. `emulator-5554` no longer shows.
12. `devices`: the Flip "Still on, still on the private network". At 4:35 pm `adb -s 100.81.55.57:5555 shell getprop ro.product.model`, exit 1, "device not found", and ssh, exit 255. At 7:07 pm both, exit 0. The gap was this phone's Tailscale (B 5) and the Flip's own state before that.
13. `phone`: "Four devices are listed". Two to three.
14. `phone-hardware`: "the 37 sensors". `termux-sensor -l | grep -c '"'`, exit 0, 38 lines.
15. `phone-hardware`: `termux-telephony-deviceinfo` "every field is null on this phone". Exit 0, the fields are filled.
16. `money`: "total_items (210 on 2026-11-11)". `paypal-get '/v2/invoicing/invoices?page_size=1&total_required=true'`, exit 0, 215.
17. `memory`: "The index is about 18,700 characters." `deb bash -c 'wc -c .../MEMORY.md'`, exit 0, 19,555; 248 files.
18. `mail`: the example line shows Berkeley with mail only. `google-accounts`, exit 0: five accounts, each with mail, calendar and drive.
19. `skills` and the README: 317 skills. `skill groups`, exit 0, "335 skills in all."
20. `voice`: `deb voice` has a third line the card did not show. Exit 0, "Voice is OFF / Full: EVERY session / Lane: CAR (alarm, phone speaker)".
21. `tv`: the known failure now carries both results: `deb tv scan`, exit 0, "No devices found" away from home; exit 0 and the Chromecast at home.
22. `yana-phone`, `mcp-see`, `mcp-apps`, `cloud`, `models`: "checked 2026-11-11" lines. Each command was run again (all exit 0) and the dates now read 2026-11-19.
23. `laptop`: "ssh times out while Tailscale shows the laptop green: restart Tailscale". The cause seen today was Tailscale off on this phone; the card names the keeper line.
24. `phone-browser`: the card had no word on how often the debug socket drops. It does (B 17).
25. README, "More lanes": shortcuts `g3`, `g4`, `g5`, `gv`. `grep` of `~/.bashrc`: only `g1` and `g2`. The README now gives the `harness --engine NAME` form.
26. README, "Ask several at once": `both "QUESTION"` as a command. `both --help`, "command not found". The README now gives `harness --both`.
27. README, "Toolbox": "Thirty-six families and 5,171 characters". Fifty-three and 7,503.

One thing seen and not settled: at 4:40 pm `~/.local/bin/session-message --list` printed nothing (exit 0) while a `codex --yolo` window was open. After the restart no Codex window was open, so it could not be tried again. The card says what an empty answer means.

## Repairs made on the phone

1. Shizuku's permit for Termux. `/data/user_de/0/com.android.shell/shizuku.json` held `"packages":[]`. Termux's entry (uid 10344) was written back through adb and the helper restarted with its own starter. The emptied file is kept at `/data/local/tmp/shizuku.json.before-audit-1119`.
2. The MCP app's permissions: `pm grant` of CAMERA, ACCESS_FINE_LOCATION and ACCESS_COARSE_LOCATION.
3. Tailscale, on George's order during the audit ("always on, even after reboot"), on the Pixel and the Z Flip 7: Android's always-on VPN setting names Tailscale; Tailscale is exempt from battery limits; a keeper (`~/bin/tailscale_keeper.sh`) looks every 60 seconds and switches it back on; boot file `17-tailscale-keeper`; timer 7736. Proof on the Pixel: Tailscale switched off by its own broadcast, one keeper look, back up in about 10 seconds. Not proven: a real restart, on either phone.
4. The boot file that was not off: `signal.sh --watch` and `brain_beacon.sh` stopped, timer 7919 cancelled, the link moved to `~/.termux/boot-off/start-agent-bridge`.

Undo for each: restore the kept `shizuku.json`; `pm revoke` the three permissions; `settings delete secure always_on_vpn_app`, remove the boot file, `termux-job-scheduler --cancel --job-id 7736` and the table line; move the link back into `~/.termux/boot`.

## My mistakes during the audit

1. `deb voice-session --help`. The script has no help form. It opened a new Claude room named `--help` and pointed the phone line at it. Undone within three minutes: the room closed, `rooms.txt` and `active.txt` back to `brain`; `deb voice-list`, exit 0, "★ brain [up]". The card now warns about it.
2. Before the Shizuku cause was found, about 25 `rish` calls each opened Shizuku's permission box on George's visible screen for a few seconds.
3. Three private values printed into the raw output files (the page password from `agentd status`, a login code from `read_sms_code.sh code`, coordinates from the location tool). Blanked in the files. None is in this repository.

## What needs George's hand

- `agy`: open the address it prints and sign in.
- `grok login --device-code`.
- PayPal: tick "Transaction search" for the app "Invoice Tool".
- Z Flip 7: add Tailscale to Samsung's "Never sleeping apps" list. The shell cannot write that list.
- One real restart of each phone, to prove Tailscale comes back.
- A decision on the tools that lost their browser in the move to the Pixel (`linkedin-headless`, `play-headless`, `bing-places-headless`, `browser-headless`, the Linux hidden browser): install a Chromium for them, or retire them. The signed-in Chrome on the hidden screen and the laptop's Chromes do those jobs today.
- Keys that are missing: OpenRouter (open-models engine), Foursquare, and a fresh Pinterest sign-in for `pinterest-headless`.

## Proof

- Full suite, from the working copy, every `test_*.py` module except `test_native_terminal` (49 modules): `Ran 858 tests in 411.373s`, `OK`, exit 0. `test_toolbox.py` now names 53 families.
- Landed as pull request #4, squash commit `514a1c3`. The live folder was pulled with `git pull --ff-only` and sits at `514a1c3`; `cards | wc -l` on the phone prints 53.
- Lane proof, real launcher, real settings, after the cards were live (about 7:40 pm):
  - `g2` (Claude Opus 5.5): "Is the voice line server on this phone answering on its port right now? Tell me the port number and the HTTP code it answers with." It printed `card calls; card doors`, said "The doors card names port 8790 as the voice line's server", ran `curl -s -m 4 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8790/`, and answered "Yes. The voice line server answers on port 8790 with HTTP code 200." Exit 0. Direct check right after: the same curl, 200. Port 8790 was on no card before this audit.
  - `g1` (GPT-6.1 Sol): "Which hidden screens are up on this phone right now? Give each one by name with its display number." It printed `card hidden-screens`, ran `deb bash /root/hidden-operator/bin/op screen list`, and answered "Two hidden screens are up. apps: display 3. web: display 4." Exit 0. Direct check: `deb bash /root/hidden-operator/scripts/hidden_display.sh list`, exit 0, `apps id=3 UP`, `web id=4 UP`. The `op` door was on no card before this audit, and the old card's path for these scripts failed.
