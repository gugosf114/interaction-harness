# THE CEILING RUN: finish George's API route, every box, in one pass

Written 2026-11-23 by the session that built the operator pages and mapped the ceiling. You are a fresh Claude Code session on George's Pixel. You have none of that context. This brief is everything you need. George's rules (CLAUDE.md) and the memory index load on their own; follow them.

## 1. The job, in one paragraph

George runs his own program on this phone, `interaction-harness`, that talks to models with his own API keys. `g2` is Claude Opus 5.5. `g1` is GPT-6.1 Sol. He calls it the API route. He wants it finished to its ceiling: every control the API road can give him, built, tested and proven, so he can stop thinking about it. The ceiling is a closed list of 18 boxes. Five are already done. Two need his own hands. Eleven are yours. Do all eleven in this one run, in the order given, without stopping to ask. Every decision is already made in section 5.

**The last sentence of your last message is fixed.** When every one of your eleven boxes has its proof written in the progress file, your final message starts with exactly:

> George, everything is done perfectly. The ceiling is reached.

A false "done" is the deepest wound in George's record with models. So that sentence is earned, never assumed. If any box lacks its proof, your final message starts instead with "George, N of 11 boxes are closed." and names each open box and the exact thing in its way. Section 8 has the full ending.

## 2. Read these first, in this order

1. `/root/.claude/projects/-root/memory/interaction-harness.md` (the note on this project).
2. In the repo `gugosf114/interaction-harness` on GitHub (clone it fresh; GitHub is the source of truth): `handoff/HANDOFF-2026-11-19.md`, then `handoff/HANDOFF-2026-11-12.md`, then the whole `README.md`, then `TOOLS_AUDIT_2026-11-19.md`.
3. `https://github.com/gugosf114/my-failures-2026-11-21` (public). It is the list of what the last session got wrong with George. The main one: he gave a clear order about his own property eight times and the model kept reviewing it. Do what the brief says. Add no checks, scans, warnings or smaller versions that nobody ordered.
4. The code you will touch, before you touch it. Read the file, then the tests for it.

State you inherit, checked on 2026-11-23: GitHub `main` and the live folder are both at `4bf585b`. The full suite ran green that day: 860 tests. Nothing is uncommitted in the live folder. No side branch holds unmerged work.

## 3. This environment

- You run in Debian (proot) on the Pixel 11. Native Termux: `ssh -i /root/.ssh/termux -p 8022 127.0.0.1 'COMMAND'`. Shell shortcuts such as `g2` need `bash -ic '...'` there.
- adb for this phone: `adb -s 127.0.0.1:5555`. Other phones are listed too; always name this one. If that door is shut, read `/root/.claude/projects/-root/memory/dev-options-off-closes-door.md`.
- The live folder: `/data/data/com.termux/files/home/interaction-harness`. **Never edit it in place.** Clone, branch, pull request, squash-merge, then `git -C <live> pull --ff-only`.
- Full test suite, from your clone: `ln -sfn <live>/.venv .venv`, then `.venv/bin/python -B -m unittest` with every `test_*.py` module except `test_native_terminal`. About three to seven minutes. Send output to a file and read the real exit code. Never pipe it through `tail`. The suite must be green before every merge.
- A real lane question: `bash -ic 'g1 "QUESTION"'` in Termux. Sol answers in about 25 seconds. Opus takes one to two minutes and its proof helper can add three more, so give commands at least 400 seconds. The lanes read answers aloud by default. George has a standing rule against audio he did not ask for: find the quiet switch (`verify_quiet.py` and the README describe it) and use it for every test call.
- Request order per lane call: the frozen first page (`prefix_block.txt`, pinned by `PREFIX_SHA256` in `harness.py`), the tools index (`tools_block.txt`), the operator pages from `state/pages.json`, the full chat, recall notes, the new message, then the rules stamp (`stamp.py`). Replies come back in a four-box form and pass a local gate (`answer_checks.py`, `habit_checks.py`, `choice_check.py`, `gate_rules.py`) and a second reader on the other engine (`reply_judge.py`, `second_gate.py`).
- Key files live in `<live>/state/` (`anthropic-api-key`, `api-key`, `gemini-api-key`). Never print a key or token value, anywhere, ever.
- GitHub shows UTC. Subtract 8 hours before you tell George a time.
- His Claude account was approved for Anthropic's Cyber Verification Program (Defense Access) on 2026-11-22. If a reply of yours is still stopped by the safety filter, do not rewrite and retry it. Note it in the progress file in one line and go on with the next step. Keep your written summaries of phone-control work short and plain; long descriptions of switched-off protections are what tripped it before.

## 4. How to work

- **Foreground only.** No background jobs, no subagents, no workflows. That is George's standing rule. If a command outlives its time limit and slides into the background, stop it and run it again with a longer limit.
- **One box at a time, in order.** Each box ends with: tests added, full suite green, pull request merged, live folder pulled, live proof run, proof written to the progress file, progress file pushed.
- **The progress file is your memory.** Create `handoff/CEILING-RUN-2026-11-23.md` in the repo at the start. After every box, write: box number, what changed (commit hash), the proof you ran and what you saw, and any trap you hit. Push it. This run is long and your context will be summarized; after a summary, read that file before you do anything else.
- **Proof means the far end.** A box is closed when the thing was used the way George will use it and you saw the result. "It compiles" and "tests pass" are stages, and you name the stage you reached.
- **No questions to George.** The decisions are below. A question is allowed only for a thing no code can reach: his fingerprint, a login that needs his face, a payment. Those are listed in section 7 and you stage them for the end.
- **Money.** Lane calls spend his API credit. Budget for this whole run: 40 dollars. Read the usage meter (card `usage`) before and after each proof batch and write the totals in the progress file. Stop a batch that would pass the budget and say so there.
- **Scope.** Do not change `tools_block.txt` unless a line in it would be false after your change; George said that page stays. Keep it under 8,000 characters. Do not change the visibility of any repository. Do not touch the bakery, WiM, or anything outside this job.
- When a box gets hard: three honest attempts with different designs. Then write what failed in the progress file, go on to the next box, and come back to it before the wrap-up.

## 5. The decisions (already made, do not reopen)

- Box 2: trim the first page. Yes, and keep the trim only if the numbers in box 16 are no worse.
- Box 8: add Fable 5.2 as a switch. Opus 5.5 stays the default brain on `g2`.
- Box 9: Gemini gets a working shortcut. A lane with no working key is marked parked in the help and on its card; its code stays.
- Box 10: prepare everything for the API account's cyber application up to George's hand. Do not drive the application portal.
- Box 13: the face is the real Claude Code screen, talking to the API through the harness.
- Box 15: run the bare test.

## 6. The eleven boxes, in running order

### Box 5. Bring the second reader and the README up to six rules

- **Why:** on Nov 19 George removed "share a useful idea after the answer" from his rules and added rules 5 and 6. The second reader still tells itself that an idea tacked on after the work is fine.
- **Where:** `reply_judge.py`, the paragraph that begins "George's standing rules tell the working model to share a useful idea after the answer". `README.md`, the line that says his setup "stamps his four core rules" and any other text that describes the old rule 4.
- **Do:** remove that allowance from the judge's instructions. Make the README say six rules and describe rule 4 as it stands now ("George decides"). Read the current rules in `/root/.claude/CLAUDE.md`, section "Core interaction contract"; that text is the truth.
- **Proof:** a test that the judge prompt no longer carries the allowance. One real `g1` and one real `g2` question; both pass the judge.

### Box 4. A code check for rule 6

- **Why:** rule 6 says "Never say what you did not do, did not check, or cannot do. Do it instead. Say only what you did and saw. Never bring up the fixed limits." George's experience is that a rule in words gets read and still broken. A check in code runs every time.
- **Where:** `habit_checks.py` (habits a plain pattern cannot hold) with tests in `test_habit_checks.py`. Read `gate_rules.py` and `gate_known_good.txt` for how a check proves it does not hit good sentences.
- **Do, with care:** two different actions.
  - A sentence that lists undone work ("I did not run the tests", "I haven't checked X", "I can't reach Y", a heading such as "What I did not do"): **reject the reply and send it back** with a short instruction: do that work now if it is reachable, then answer with what you did and saw. Never strip such a sentence silently. Cutting it would make unfinished work look finished, which is a false "done".
  - A sentence that brings up a fixed limit nobody asked about: cut the sentence.
  - Let these through untouched: a reply to a question George asked about what was skipped or what is possible; a line that hands him a step only he can do (a tap, a login, a decision); quoted text; code.
  - If the retry budget runs out, show the reply with the sentence kept.
- **Proof:** tests for each case above, including ten ordinary good sentences that must pass. One real question on each lane that tempts the habit (for example, ask for a job the lane can only half do in one step) and the gate's record of what it did.

### Box 14. Telegram on the cloud box answers to the new names

- **Why:** the lane was renamed from `george` to `g2` on Nov 19. The adapter on the phone knows `/g2`. The copy on the always-on cloud box still says `/george`.
- **Where:** `/root/agent-bridge/scripts/telegram_lane.py` and `telegram_bridge.py` hold the updated code, uncommitted. The box login is `gugosf@100.123.176.12` (not root). `scripts/deploy_box.sh` in `gugosf114/agent-bridge` is how files reach the box.
- **Do:** land those two files in `agent-bridge` through a pull request. Deploy to the box. Restart only the Telegram service. George switched the Agent Bridge notifications off on purpose (`signal.sh --watch`, `brain_beacon.sh`, timer 7919); leave them off.
- **Proof:** on the box, the adapter's own handler accepts `/g2` and `/g1` and rejects `/george` (call the handler in a test or dry run; do not send George a Telegram message). The service is active after the restart.

### Box 18. A locked backup, so the route survives a lost phone

- **Why:** the keys, the sign-in tokens, the shortcuts and the settings exist only on this phone.
- **Where:** the method already used is in the private repo `gugosf114/box-backup` (a gpg-encrypted tar as a dated release asset) and in the memory note `phone-backup-1029.md`. Use the same method and the same secret. Never print it.
- **What goes in:** `<live>/state/`, Termux `~/.bashrc`, `~/.termux/boot` and `boot-off`, `~/.local/share/timers.tsv`, `/root/.claude` without transcripts (rules, hooks, mods, lane pages, briefs, memory), `/root/.gmail` tokens, and the uncommitted files in `/root/agent-bridge`.
- **Proof:** decrypt the uploaded asset into a scratch folder and compare the file list and checksums with the originals. Write the restore command into the progress file and into the harness README. Record the repo's visibility as you found it; do not change it.

### Box 15. The bare test

- **Why:** George wants to see what his three pages do alone, without the harness's first page, four boxes and checks, next to what the subscription gives.
- **Do:** pick five real questions from his archive (`~/conversation-corpus/data/training/2026-11-11/` holds 167 clean pairs; choose ones that drew hedges or wall talk). For each: (a) one plain API call to Opus 5.5 whose whole system text is the three pages from `state/pages.json` and nothing else, no tools; (b) the same to Sol; (c) the subscription, with `claude -p "QUESTION"` from this box.
- **Proof and product:** one file in his Downloads, `bare-test-2026-11-23.md`: each question, then the three answers in full, then a count per answer of the sentences the gate's own checks would have cut. No verdict from you on which is better; he reads it. Run `termux-media-scan` on the file so it shows.

### Box 16. Twenty old prompts, old pages against new pages

- **Why:** the operator pages went live on Nov 19 on George's order, written from Anthropic's guidance and his record. Nothing has measured them.
- **Do:** twenty real prompts from the same archive, covering his usual asks. Run each on both lanes twice: once with the old page list (`state/pages.json.before-operator-page-20261119`), once with the current one. Use a private copy of the state folder for the old-list runs so the live settings are never changed. Record, per run: sentences the gate cut, rejects, judge fails, and words in the final answer.
- **Proof and product:** `pages-test-2026-11-23.md` in Downloads with the table of counts and the five largest differences quoted. Keep the script in the repo (`verify_pages.py`) so the test can be run again.

### Box 2. Trim the first page

- **Why:** the first page is 3,322 words. About 13 percent of it repeats what George's own pages now say.
- **Where:** `prefix_block.txt`, `PREFIX_SHA256` in `harness.py`, and every test that pins the hash.
- **Do:** cut only text that restates the operator, rules or answering pages. Keep everything the program needs to read a reply: the four-box form, its field rules, its examples. Update the pin and the tests.
- **Proof:** full suite green. Run box 16's script again with the trimmed page. Keep the trim only if cuts, rejects and judge fails are no worse than before; otherwise restore the old page and say so in the progress file. Then one real question on each lane.

### Box 9. The other lanes: working shortcut or parked

- **Where:** `extra_lanes.py`, `gemini_lane.py` (shortcut `g5`), `glm_lane.py` (`g4`, George's own fine-tuned model on Modal), `openrouter_lane.py` (`g3`, no key on file), `vertex_lane.py` (`gv`, returned 429 on Nov 12). Only `g1` and `g2` exist as shortcuts in Termux `~/.bashrc`. `test_extra_lanes.py` pins the shortcut list.
- **Do:** call each lane once for real. A lane that answers gets a shortcut in `~/.bashrc` (back the file up first, with the date in the name) and a true line in `help.txt` and on the card `toolbox/cards/lanes.md`. A lane that does not answer is marked "parked" in those same places with the exact error and date. Its code stays.
- **Proof:** for each working lane, the real answer to one real question through its shortcut. For each parked lane, the error as returned.

### Box 8. Fable 5.2 as a switch

- **Do:** make `claude-fable-5-2` selectable on the Claude lane, by `/model` inside a chat and by a shortcut `gf`. Opus 5.5 stays the default on `g2`. Read the official model and pricing pages before you write a price into `usage_meter.py`; do not price from memory.
- **Proof:** one real call on George's key that returns an answer and shows the model name in the record; the usage meter prices that call; `g2` still reports Opus.

### Box 13. The face: the real Claude Code screen on the API road

This is the largest box. Read the official Claude Code documentation for every setting you rely on (custom API address, a separate config folder, the key helper, turning off automatic compaction, model names). Use the web for the docs. Do not work from memory here.

- **Goal:** George types `g2` and gets the same screen he uses on the subscription: Claude Code, with its thinking view, slash commands, colors, hooks and voice. Every call goes out on his API key, with his three pages on top and the harness's checks on the way back. `g1` gives the same screen with Sol behind it.
- **Part A, the wire gate.** A small local server in the harness repo (`wire_gate.py`), listening on 127.0.0.1 only. Claude Code talks to it as if it were Anthropic's Messages API, streaming included. For each request it:
  - puts George's three pages (read live from `state/pages.json`) first in the system text, ahead of Claude Code's own, and adds the rules stamp the same way the lanes do, either-or line included;
  - forwards to the real API with the key from the state folder;
  - passes tool calls through untouched;
  - holds the final text of a turn until it is complete, runs the gate's sentence checks on it (box 4 included), and releases the result;
  - runs the second reader when a turn ends with no tool call;
  - writes each call to the usage meter so `usage` shows the cost;
  - never trims or drops a message. Nothing squeezes his chats.
- **Part B, a second profile.** Claude Code for the API road runs with its own config folder, so the subscription login is never touched and never logged out. That profile carries the same handbook: his CLAUDE.md, the memory folder, hooks, mods and settings. Automatic compaction is off in it. The key reaches Claude Code only inside the launcher.
- **Part C, Sol behind the same screen.** The wire gate translates between the Anthropic message format Claude Code speaks and OpenAI's, both ways: text, tool calls, tool results, images, streaming. Reuse the harness's OpenAI adapter.
- **Part D, the shortcuts.** Back up `~/.bashrc` first. `g2` and `g1` open the new face. The old chat screens stay reachable as `g2-classic` and `g1-classic`. `gf` opens the new face on Fable. The always-on service, the voice line and Telegram keep using the harness lanes directly; do not reroute them. Switch `g2` and `g1` over only after the proofs below pass.
- **Proof:**
  - Tests against a fake upstream: pages come first; the stamp is present; tool blocks are byte-identical; a comfort line is cut; a rule-6 line causes one retry; the stream is well formed; no message is dropped; the key never appears in a log.
  - A live print-mode call through the new profile that needs a tool (for example, "how many tool cards are in the harness folder?"), with the answer checked against the folder itself, a wire-gate record for the call and a usage-meter row on the API key.
  - The subscription profile still answers and is still signed in to the subscription.
  - The same live call with Sol behind the screen.
  - A screenshot of the real `g2` screen answering a question, saved to Downloads as `g2-new-face-2026-11-23.png`. Take it on a hidden screen (`hidden-operator`), not on George's visible screen.

### Box 10. The API account's cyber application, staged to George's hand

- **Why:** the Nov 22 approval covers his Claude account. Anthropic's page says the API account is a separate organization and needs its own application, and that Defense Access requires API keys replaced at least every seven days, with long-lived keys not allowed from December 15, 2026.
- **Do:** read the current program page (`support.claude.com`, "Cyber Verification Program") and quote the exact requirements with the date you read them. Work out what this phone's lanes would need to meet them and build what code can build (for example, a key swap command that takes a new key from George and updates every place the lanes read it, with a test). Adapt his approved answers (in Downloads: `cvp-application-questions-and-answers-2026-11-22.pdf`) for the API account and save them as a PDF in Downloads, `cvp-api-account-2026-11-23.pdf`.
- **Do not** open, sign in to or fill the application portal. The identity check and the submit are George's.
- **Proof:** the PDF opens and has every question with its answer; the requirements note is in the repo at `handoff/API-CYBER-PROGRAM-2026-11-23.md`; the key swap command passes its test with a dummy key.

## 7. George's two boxes (stage them, do not count them)

- **Box 12, three sign-ins:** `agy` and `grok` need his login; PayPal's developer dashboard needs "Transaction search" ticked. At the end, tell him each one as the smallest step, in one line each.
- **Box 17, one real day:** he uses `g2` and `g1` for a day and sends each bother through `/wrong`. The gate holds zero learned rules today because that day has not happened. No build stands in for it.

## 8. The wrap-up and the ending

1. Full suite green on final `main`. Live folder pulled and at the same commit.
2. One real question on `g2`, one on `g1`, one on each working extra lane, all through the final shortcuts.
3. README brought up to date for everything you changed. A new handoff, `handoff/HANDOFF-2026-11-23.md`, in plain words: what exists now, how to start each thing, what is George's. Update the memory note `interaction-harness.md` and its line in `MEMORY.md`.
4. Every file meant for George is in his Downloads and media-scanned. When you name a file to him, say "in your Downloads, named X". Paths and links mean nothing to him.
5. Your final message, in his language: short sentences, small words, bullets, no tables.
   - If all eleven boxes have proof: first line exactly **"George, everything is done perfectly. The ceiling is reached."** Then at most ten short lines: what he can type now and what each does. Then "Your hand:" with the three sign-ins and the real day.
   - If not: first line **"George, N of 11 boxes are closed."** Then each open box with the one thing in its way.

Tokens and time are not a limit. Take the whole job in one run.
