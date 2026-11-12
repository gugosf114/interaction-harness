CAPABILITY LIST AND OPEN IDEAS
interaction-harness, Nov 11, 2026. Written by Claude (Fable 5.2), the orchestrating session.

Part 1 is the full list of what George's subscription setup can do, row by row, against what the API lanes (george and g1) can do. The list was first written at 4:19 pm. The "API now" lines are updated to the state at about 6 pm the same day.
Part 2 is every idea raised in the session that was never picked up.

"Here" means the subscription setup (Claude Code on the phone).
"API now" means what george and g1 can do today.


============================================================
PART 1: THE CAPABILITY LIST (45 ROWS)
============================================================

A. CONTROL

1. All permissions on auto.
   Here: yes. Settings say bypassPermissions.
   API now: HAS IT. Both shortcuts start with --loop -y.

2. Model and thinking level per model.
   Here: yes.
   API now: HAS IT. Thinking is set to max on both lanes.

3. The whole conversation stays in view.
   Here: yes. Auto-compact is off.
   API now: PARTLY. 50 exchanges and 200,000 characters. Those are the code's ceilings today.

4. Status line at the bottom.
   Here: yes.
   API now: none.

5. Drive the session from another device. Push alerts.
   Here: yes.
   API now: none. Phone alerts are reachable; in the toolbox task.

B. THE FRIDGE: RULES AND MEMORY

6. The rules file, loaded every session.
   Here: yes.
   API now: HAS IT. Five sections of the rules file and the one-page profile go out on every call (commit bca648e).

7. The four rules stamped on every turn by a hook.
   Here: yes.
   API now: none. The rules load once per call, with no per-turn stamp.

8. Memory: an index plus about 200 note files, read and write.
   Here: yes.
   API now: READ ONLY. The tools page says how to read a note (commit 22e7225). No way to save a new one.

9. Every memory edit is versioned by a hook.
   Here: yes.
   API now: none.

10. Search of all past chats (recall, search-chats).
    Here: yes.
    API now: HAS IT. Listed on the tools page (commit 22e7225).

11. Fork a saved session. Rewind. Golden sessions.
    Here: yes.
    API now: named sessions only.

C. HANDS

12. Shell.
    Here: yes.
    API now: HAS IT.

13. File read, write and edit tools.
    Here: yes.
    API now: through shell commands. An exact-edit tool is being built in the toolbox task.

14. Eyes: images, screenshots, PDFs.
    Here: yes.
    API now: BUILT by Astra, passing its tests, landing.

15. Web search.
    Here: yes.
    API now: BUILT by Astra, passing its tests, landing.

16. Web page fetch.
    Here: yes.
    API now: BUILT by Astra, passing its tests, landing.

17. Make PDFs, QR codes, download video.
    Here: yes.
    API now: in the toolbox task.

18. Timers: wake-ups, scheduled jobs, watch a thing until it changes.
    Here: yes.
    API now: in the toolbox task (run a command later).

19. Send a file to George's device.
    Here: yes.
    API now: can write to Downloads by shell.

20. Published web pages and documents.
    Here: yes.
    API now: none. Tied to Claude's own app.

21. About 90 skills: Word, Excel, PowerPoint, PDF, deep research, code review, legal, data, design.
    Here: yes.
    API now: none. Not in any task.

22. Helper agents and workflows.
    Here: exists. George turned these off by rule.
    API now: none.

D. ACCOUNTS

23. Gmail: search, read, draft, send, label, trash.
    Here: yes, by connector.
    API now: read, and send a reply, by George's two scripts. No draft, label or trash.

24. Google Calendar.
    Here: yes.
    API now: none. Not in any task.

25. Google Drive.
    Here: yes.
    API now: none. Not in any task.

26. PayPal: connector, plus live keys on the phone.
    Here: yes.
    API now: in the toolbox task.

27. Canva, Figma, Claude Docs.
    Here: yes.
    API now: none. Tied to Claude's own app.

28. GitHub, both owners.
    Here: yes.
    API now: HAS IT.

29. Google Cloud: gcloud, the secret store, the backup bucket.
    Here: yes.
    API now: listed, through the Debian bridge.

30. Cloudflare, Bing, Bright Data, Hugging Face, RunPod, Modal, Twilio keys.
    Here: yes.
    API now: in the toolbox task.

31. Installed but never signed in: Slack, Notion, Linear, Atlassian, Intercom, Hex, Amplitude, Adobe, Guru, Egnyte, Microsoft 365.
    Here: unusable until signed in.
    API now: none.

32. Broken here today: browser-use, definite, pdf-viewer.
    API now: none.

E. DEVICES

33. Phone: screenshots, taps, hidden screens, texts, phone-do, phone-ask.
    Here: yes.
    API now: adb is listed. The rest is in the toolbox task.

34. The signed-in phone Chrome.
    Here: yes.
    API now: in the toolbox task.

35. Laptop: shell, files, its own browser.
    Here: yes.
    API now: in the toolbox task.

36. Yana's phone.
    Here: yes.
    API now: in the toolbox task.

37. TV and casting: tv, catt.
    Here: yes.
    API now: in the toolbox task.

F. VOICE AND CALLS

38. Ava reads answers aloud. say, voice on/off.
    Here: yes.
    API now: in the toolbox task.

39. George speaks, the model gets text.
    Here: yes.
    API now: George uses WiM for this. The harness also has a -l flag.

40. The phone line that calls Claude. The caller that phones for George.
    Here: yes.
    API now: in the toolbox task.

G. OTHER MODELS

41. Codex, Gemini, Grok, George's own GLM model, from the shell.
    Here: yes.
    API now: g1 is OpenAI. The rest is in the toolbox task.

42. Messages between live sessions (po).
    Here: yes.
    API now: in the toolbox task.

H. GEORGE'S OWN TOOLS

43. mbc-stats, Business Profile edits, Play Console, bakery mailbox, invoices, indexing pushes.
    Here: yes.
    API now: in the toolbox task.

44. Hooks on disk but not wired: answer-length, plain-words, no-background, receipts-gate, recall-inject.
    Here: not wired.
    API now: the harness gate does part of this in code.

45. Mods: proof-marks, narrator, thread-tree, roster, autopilot, usage-alarm.
    Here: yes.
    API now: none.

WHO HAS WHAT

- Astra: rows 14, 15, 16. Built and passing. Landing.
- Other Claude: rows 6, 8 (read), 10 landed. Toolbox under way: rows 5, 13, 17, 18, 26, 30, 33 to 38, 40 to 43.
- Claude (orchestrator): rows 1, 2, 3, mail in 23, the tools page, the reassurance rule. Done.
- Not assigned to anyone: rows 4, 7, 9, 11, 20, 21, 24, 25, 27, 31, 32, 44, 45, and the write side of row 8.


============================================================
PART 2: IDEAS RAISED AND NEVER PICKED UP
============================================================

HARNESS

- A lessons file. When George corrects a lane, it saves the lesson, and the next session loads it. Build it as two bins: fact lessons go on a page; habit lessons become a code rule with a test. A page alone does not stop a habit.
- Stop the comfort line at the source. One sentence in the first page: "Do not say a command is safe or read-only unless asked." Today only the code filter catches it.
- The screen. A status line with model, tokens, cache and cost. Colors. Slash commands inside the chat. A long paste kept as one message.
- The four rules stamped on every turn.
- Writing to memory. The lanes can read notes and cannot save one.
- Skills, Calendar and Drive. Rows 21, 24, 25.
- A later trial of the Agent SDK, for the Claude lane only. Parked.
- The handoff files are stale. They still say 125 tests and list the comfort-line leak as open.
- Turn off the checkers nobody needs. Raised by George. Not started.

WAITING FOR ASTRA TO LAND, THEN CLAUDE DOES THEM

- Raise four numbers that sit in Astra's files: the memory ceiling (50 exchanges, 200,000 characters), the wait ceiling (300 seconds), and how much of a command's output the model sees (8,000 characters).
- Take the "no web search" line off the tools page.
- Rewrite the first page. Today it tells the model it is a log-audit and device-admin helper, and all ten examples are computer-admin tasks.
- Cache the conversation on the Claude lane. The pages are cached; the history is not.

SWITCHES OFF IN THE SUBSCRIPTION SETUP, NEVER DECIDED

- The advisor tool, a second model Claude can ask. Off in the settings file.
- browser-use. Broken: a program called uvx is missing.
- pdf-viewer and definite. Broken connections.
- Five hooks on disk and not wired: answer-length, plain-words, no-background, receipts-gate, recall-inject.

BAKERY SITE (FROM THE NOV 10 AUDIT)

- Fix the $85 cake price and the 3-review count in the home page schema. The page's own FAQ says $250 to $650.
- Make the minimum order, cake price and lead time match on every page.
- Remove the purchase-order line and the lead-time numbers still live on the site. ChatGPT told a buyer the bakery accepts purchase orders.
- Get listed on third-party pages that say "Bay Area logo cookies." National shippers win those plain searches.
- Rerun the AI search test logged out, from another city.
- Claude's search does not find the bakery. The cause was never looked into.
