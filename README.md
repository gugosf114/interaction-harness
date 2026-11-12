# Interaction harness

A native Termux command with OpenAI and Anthropic backends, a shared four-field reply schema, a local display gate, six-exchange sessions, SQLite recall, confirmed shell execution, and Android dictation.

## Quick use

```sh
~/interaction-harness/harness "Explain chmod 640."
~/interaction-harness/harness --engine anthropic "Explain chmod 640."
python ~/interaction-harness/harness.py "Read this observation."
printf '%s\n' 'Explain this permission mode.' | ~/interaction-harness/harness
```

The default is OpenAI (`gpt-6.1-sol`). Anthropic defaults to the latest Opus tier verified during setup, `claude-opus-5-5`. `--model MODEL` selects a model on the chosen engine. Both require support for their strict-output and cache parameters. Both engines default to `max` effort. OpenAI receives `reasoning.effort`; Anthropic receives adaptive thinking plus `output_config.effort`. `--effort low|medium|high|xhigh|max` overrides the level. The output budget is 128,000 tokens, thinking included. That is the highest value both providers accepted in a live call.

```sh
export DEFAULT_ENGINE=anthropic
export ANTHROPIC_MODEL=claude-opus-5-5
export OPENAI_MODEL=gpt-6.1-sol
```

These exports are read by the Termux launcher and passed into the isolated Debian Python environment through a private pipe. Native execution and speech capture run in Termux, not Debian.

## Interactive chat and short commands

The managed aliases in `~/.bashrc` are:

```sh
george                         # Claude Opus 5.5, high thinking
g1                            # GPT-6.1 Sol, high reasoning
george "my quick question"      # One answer, then exit
g1 "my quick question"         # One answer, then exit
```

In an existing Bash window, load the new aliases once with `. ~/.bashrc`. New Bash windows load them automatically. `g1` is the selected OpenAI shortcut from the requested `codex`/`g1` alternatives.

Launching either shortcut with no question opens a continuous chat. Type a message at `> ` and press Enter. The same session stays attached to every turn. Type `exit` or `quit` to leave; Ctrl-D also leaves. No `-c` is needed between messages. Prompts go to stderr; stdout remains answer-and-command text only. There is no greeting banner.

Each launch starts a new session unless you use `george -c`, `g1 -c`, or `--session NAME`. The existing rolling six-exchange window and SQLite history apply to chat mode. API/gate errors are shown briefly and the next input remains available. Exit returns the last turn's status; Ctrl-C returns 130.

```sh
george --session audit
g1 --session work
~/interaction-harness/harness --chat
printf '%s\n' 'First message' 'Second message' 'quit' | ~/interaction-harness/harness --chat
```

`--chat` and `--interactive` explicitly select the loop. Without that flag, piped input is still one atomic request. A supplied question remains one-off even in an interactive terminal. `--chat "first question"` sends that question and then stays open. Chat uses one input line per turn; the existing one-off stdin path accepts multiline blocks.

## Keys

In a native Termux shell, source the relevant helper and enter the key at its hidden prompt:

```sh
. "$HOME/interaction-harness/export-key.sh"
. "$HOME/interaction-harness/export-anthropic-key.sh"
```

The helpers export `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in that shell and save a mode-600 key file inside the mode-700 `state` directory. Exported keys take priority. Keys are not placed in process arguments, source code, model prompts, or verification reports. Provider calls use the official OpenAI or Anthropic endpoint. A successful live call establishes model access; a subscription login is not used as an API key.

## Speech corrections

The preprocessor applies these explicit mappings before the API call:

| Dictated text | Sent text |
|---|---|
| NC | antsy |
| AIPG | AIGP |
| redmi | README |
| term units | Termux |

`NC` is case-sensitive so the `nc` command stays intact. Quoted text, code spans, fenced code, URLs, and paths stay literal. Use `--no-normalize` when the raw wording must stay exact. Raw and normalized text are both recorded. The frozen prompt also contains contextual hints such as “show mod” → `chmod`; that contextual interpretation remains a model judgment.

## Sessions

```sh
~/interaction-harness/harness --new "A fresh request."
~/interaction-harness/harness --session device-audit "Start with this log."
~/interaction-harness/harness --session device-audit "What did that error mean?"
~/interaction-harness/harness -c "Use the same device."
~/interaction-harness/harness --session device-audit --turns 3 "Continue."
```

The default and `--new` start an isolated session with no prior exchanges. After a successful turn it becomes the most recent active session, so `-c` / `--continue` can pick it up. `--session NAME` creates or reopens a named session. Names accept 1–64 letters, digits, underscores, and hyphens. The three session-selection flags are mutually exclusive.

Files live at `state/sessions/<id>.json`. By default the session keeps every exchange (up to 100,000); `--turns N` sets a smaller window (1–1,000,000). The API receives at most 2,400,000 characters of prior history on Anthropic and 650,000 on OpenAI, keeping whole exchanges; `--history-chars N` changes that cap (up to 4,000,000). The two defaults were sized to each model's window, measured in live calls on 2026-11-11. The current input limit is 1,000,000 characters. Oversized input is rejected before it can become a truncated instruction.

The exact frozen prefix and shared schema always come first. History and the new request follow them. Session writes are atomic and each session is locked during a turn, including any execution confirmation. Failed API calls are logged but do not add an assistant exchange or replace the most recent successful session.

## Output gate

The same strict wire schema is used for OpenAI Structured Outputs and Anthropic's `emit_reply` tool. Opus 5.5 uses `tool_choice: auto`; its tool instructions require one final `emit_reply` call, and the local gate rejects ordinary-text responses. Strict mode validates the tool input. The tool returns data; it never executes a shell command. All four fields are required: `intent`, `cleaned_input`, `direct_answer`, `execution_payload`. Intent is exactly `observation` or `action_request`. An observation cannot carry a command. Unsupported wire-level string-length keywords are omitted from both providers' shared schema; Pydantic enforces the lengths locally.

Only the validated direct answer and optional plain command print to stdout. A local regex scrubber removes canned opening prefixes such as “Sure,”, greetings, apologies ("Sorry," "I'm sorry,"), agreement ("You're right."), praise ("Good catch."), and fixed disclaimers while preserving factual text on the same line. An opener counts only when it stands alone before punctuation: "Certainly not.", "Sure signs of…", host names such as `www.hello.com`, and file names such as `hello.txt` stay content. The same words are rejected when they start a later sentence. It removes opening prompt echoes and handles stacked prefixes. “Probably,” “Maybe,” general qualifications, missing-data statements, and requests for logs remain valid content. This supersedes the earlier whole-line removal of no-data caveats, which could erase legitimate uncertainty. Exact prompt-echo checks use the actual request, and recall uses the recorded request. Execution payloads are never scrubbed.

Unrequested reassurance is removed the same way, anywhere in the answer: sentences such as “It does not change any files.”, “It changes nothing.”, “These checks are read-only.” and “I did not change anything.”, and trailing clauses such as “without changing them”. The rest of the answer is kept as written. The removal is skipped when the operator's own request negates or questions a change (“don't change anything”, “will it delete”), names safety or read-only, or asks that secrets stay hidden, because then the sentence is the answer. Ordinary words such as “write a command” or “change to the folder” do not switch it off. In `--loop` runs the check uses the original task, not the continuation message. An answer that is only reassurance is not displayed.

Opening-line cleanup makes no extra API call. If every answer line is removed, stdout stays empty and a short stderr error is returned, with no retry. The remaining schema/body linter still checks terminal controls, unsupported execution claims, and other pre-existing errors; its existing bounded corrective retry applies only to those separate failures. Refusals and incomplete responses remain failures. The gate is deterministic for its rules; intent interpretation and prose still come from a model. An already-open chat loads this code on its next launch; `exit`, then the same shortcut with `-c`, resumes the most recent session.

## Execution

```sh
~/interaction-harness/harness -x "Give me a command that prints the current directory."
~/interaction-harness/harness --exec --exec-timeout 30 "Show the current user ID."
```

The answer and proposed command appear first. Then the native Termux launcher asks exactly:

```text
[Run command? (y/N)]:
```

By default only `y` (case-insensitive) executes. Enter or `n` declines. Every command gets its own prompt. Explicit `-y` / `--yes` skips the prompt for this invocation; it requires `--exec` or `--loop`. Without execution mode, only text is printed. An observation never triggers execution. Interactive approval reads `/dev/tty`, so piped input cannot become approval. Without a terminal, execution requires explicit `-y`.

Approved commands run with native Termux Bash and noninteractive stdin. stdout and stderr remain separate. The command's exit code is returned; timeout is 124. The default timeout is 120 seconds and each output stream is limited to 1 MiB of displayed capture. Confirmation and execution results are stored with the turn. Later session history includes a separate execution observation with the command, approval, stdout, stderr, and exit status. The assistant reply remains exactly four fields. A reply may report finished work in the first person ("I ran…", "I created…", "Done.") only when it directly follows a command that was approved, finished in time, and exited 0. A failed or timed-out command does not unlock that wording, and neither does an older success earlier in the session; the gate then asks for one corrected reply. Doubt, denial, and quoted log text are not treated as such reports. The other display checks still apply.

## Multi-turn agent execution

```sh
g1 --loop "Create a temporary file, then read it back."
george --loop --max-turns 8 "Inspect this log and verify the fix."
g1 --loop -y "Create a temporary file, then read it back."
george --chat --loop --session maintenance
```

`--loop` implies execution mode. The client requests one four-field reply, displays it through the existing gate, asks for command approval, runs the approved payload in native Termux, and records stdout, stderr, and exit status. It then sends that result back as a separate `execution_observation` data message and asks for the next step. The first loop record holds the original task and the turn ceiling and never changes between turns; each continuation message names its own turn ("This is model turn 2 of 5."). Command output is data, not a new instruction or source of approval. Only the CLI `-y` flag enables automatic confirmation; the model cannot set it through its four-field reply.

The default ceiling is five model turns, including the final answer. `--max-turns N` accepts 1-50. A command on the last permitted turn can run after approval, then the loop stops with exit code 3 and a `loop_limit` record. A null execution payload finishes the loop. A declined command stops immediately without another model call. API or gate failures also stop the loop. Nonzero command results and timeouts are returned to the model so it can diagnose or repair the step within the original request. On normal completion, the last executed command's exit status is returned; a later successful command clears an earlier failure. A task that issues no commands returns 0. Existing bounded format-correction retries remain inside each model turn.

Each model turn has its own SQLite row and usage metrics. Approved results are saved with that turn. The original goal and latest execution observation remain available even with `--turns 1` or `--history-chars 0`. These required loop inputs are additional to the optional older-history budget. At most 8,000 characters from each output stream are included in model feedback. A longer stream keeps its first 2,000 characters and its end, where errors and tracebacks usually are; a marker states how many characters were left out of the middle, and the stream is named in the truncation field. The complete captured output remains in the local record. The ordinary native capture limit still applies.

`--chat --loop` starts a fresh bounded agent run for each typed message while retaining the chosen session. `-y` applies to that whole invocation. A recalled answer is never executed. Without `--loop`, `--exec` still performs just one command and returns.

## Local history and recall

```sh
~/interaction-harness/harness --recall "permission mode"
```

`state/history.db` stores every model turn, including failures: ID, timestamp, engine, session ID, raw input, normalized input, cleaned input, intent, answer, command payload, total tokens, cache-read tokens, model, status, error, and execution result. It also records total input tokens, output tokens, cache-creation tokens, the number of requests with cache reads, and API latency in milliseconds. Counters and latency include corrective attempts; native execution time and launcher overhead are separate. OpenAI input tokens already include cached input; Anthropic uncached input, cache reads, and cache creation are summed for the common total. Old databases migrate in place. Previously unrecorded metrics remain NULL. SQLite FTS5 searches raw input, cleaned input, answers, and commands. Recall uses no API, returns up to five matching saved replies through the display gate, and never executes a saved command. Session trimming does not delete the history database.

## Dictation

```sh
~/interaction-harness/harness --listen
~/interaction-harness/harness -l --session device-audit
~/interaction-harness/harness -l -x
```

This uses `termux-speech-to-text` and Android's speech recognizer through Termux:API. The CLI package and companion Android app are required. Speak when the Android speech dialog opens. The recognized text goes through the same normalization, schema, gate, sessions, and logging. `--listen-timeout N` sets the listening timeout (default 90 seconds, maximum 180). No-audio, missing-service, and timeout cases produce a short error with no API call. This route does not upload an audio file to Whisper.

## Frozen prefix and caching

`prefix_block.txt` is read-only and its SHA-256 digest is pinned in `harness.py`. A changed prefix stops before any API request. Version 3 retains ten examples and adds agent-loop observations and explicit auto-confirm semantics. The prefix stays byte-identical between requests until an intentional version change. OpenAI receives a stable cache key; Anthropic receives a cache breakpoint at the end of the frozen system prefix. In loop mode every request is a byte-for-byte prefix of the next: the first record carries no per-turn value, and each continuation message is stored exactly as sent. OpenAI's automatic cache can therefore reuse earlier turns as well as the prefix; the Anthropic breakpoint covers the frozen prefix only. Once the history window (`--turns`, `--history-chars`) is full it slides, and the front of the conversation changes again. The frozen V3 text still says the loop record names the current turn; the continuation message now does. Real provider usage records show cache reads and writes. `state/usage.jsonl` stores request metadata without prompt or answer text; the separately requested SQLite history stores the full turns.

## Tools page

`tools_block.txt` is the index of the operator's tools: one line per tool family, with the command that prints that family's card. The cards and the commands behind them are described under *Toolbox*. The page is sent on every call right after the frozen prefix, on both engines, and both providers cache it.

It is plain text and the operator can edit it. It is not hash-pinned. Rules: at most 8,000 characters, no control characters. An empty or missing file sends nothing and the harness works as before. The page grants no permission; every command still needs approval. Each usage record stores the page's SHA-256 as `tools_sha256`. Keep it to tools that were checked on the phone, because the model will propose what the page lists.

## Advisor

George can ask the other model for a second opinion on the work in front of him. Only George can start it.

**Start it.**

```sh
/advisor                              # typed at the > prompt of a george or g1 chat
/advisor why did that command fail?   # with his own question for the reviewer
george -c --advisor "QUESTION"        # outside a chat, for the last session
g1 --session NAME --advisor           # outside a chat, for a named session; the question is optional
```

The working model cannot start it. It is not a tool, it is on no card and on no page, and no threshold fires it. A model that writes `/advisor` in an answer gets the word printed and nothing more. A session with no exchange yet answers with one short error and makes no API call.

**The packet.** Code builds it, with no model call. It is one JSON object:

- `task`: the loop's original task when the latest exchange is a loop step; otherwise the first request of the session.
- `exchanges`: the last three exchanges (`--advisor-turns N`, 1 to 50). Each holds the input, the working model's four fields, and any command result: the command, whether it was approved, its exit code, whether it timed out, and both output streams. Each stream is clipped by `storage.clip_stream`, exactly as the working model saw it: at most 400,000 characters, start and end kept, the gap marked.
- `operator_question`: George's own question, when he gave one.
- The size cap is 600,000 characters. A larger packet is refused with one short error before any call. Nothing is cut to fit.

**The call.** It goes to the other engine: from `george` to `gpt-6.1-sol`, from `g1` to `claude-opus-5-5`, at the lane's own `--effort` and `--timeout`. It is stateless. It carries the reviewer prompt and the packet, and nothing else: no session history, no frozen prefix, no tools page, no rules or profile pages, no web tools, no reply schema. The reviewer prompt is:

> You are an outside reviewer of another model's work. State the root cause, then the next command or fix. At most three short bullets. No greeting, no praise, no reassurance.

No temperature is sent. Both providers refuse one on these models (checked live, Nov 11, 2026): OpenAI answers HTTP 400 "Unsupported parameter: 'temperature' is not supported with this model", and Anthropic answers HTTP 400 "temperature: Extra inputs are not permitted".

**The gates.** The reply is plain text, and every display gate runs on it before George sees it.

- Removed in code, at no cost: canned openers and filler sentences (bullet by bullet, so a bullet keeps its mark), prompt echoes, and unrequested reassurance. Reassurance stays when George's question or the task asked about safety.
- Rejected: terminal control characters, more than three bullets, more than 16,000 characters, a report of finished work (the advisor ran nothing), a claimed web lookup, and a URL that is not in the packet. A rejected reply gets one corrected try, which is a second paid call. Two rejections show nothing.
- A reply with nothing left after cleanup is an error, with no second call.
- A refusal, a timeout or an API error is one short line on stderr, exit code 2. The chat goes on, and the session is unchanged.

**What happens to the advice.**

- It prints at once on stdout, under the label line `Advisor (MODEL):`.
- It is saved on the latest exchange in the session file, under `advisor_notes`. In the working model's next request it is a user-role JSON message typed `advisor_note`, placed right after that exchange and its command result. It holds the advising model's name, the text, and a fixed line that says it is data from an outside reviewer, not an instruction from the operator. Everything before it in the request is byte-identical to what was sent before, so the cached prefix holds.
- One row goes into `history.db` with status `advisor` (or `advisor_error`), the advising engine and model, `/advisor QUESTION` as the input, the advice, and the token usage. `--recall` does not show advisor rows. One `usage.jsonl` record with `kind: advisor` holds the sizes and the usage, and no packet or advice text.
- `/advisor` does not make the working model speak. George's next message does.

**Live proof (Nov 11, 2026).** Once on each lane, through the real launcher with `--effort max --loop -y` and an isolated state folder: a loop task that ends in a failing `ls` (exit 2), then `/advisor`, then one more question. On `george`, gpt-6.1-sol answered in two bullets under the label, and Claude's next answer restated the note. On `g1`, claude-opus-5-5 answered in three bullets, and GPT's next answer restated the note. Both chats exited 0. The working lane's next call still read its cache: 13,939 tokens on Claude and 10,749 on GPT. The advisor call used 501 input and 459 output tokens on GPT, and 635 input and 1,815 output tokens on Claude.

The code is in `advisor.py`. `cli.py` holds the trigger and the two flags, and `storage.py` holds `advisor_note`. Tests: `test_advisor.py`.

## Recall, notes and session surgery

**Past chats on every turn.** Before each message from George, code (no model call) takes the key words of his message and searches three indexes:

- `chats`: `/root/corpus.db`, the turn index of the Claude Code, Codex and Gemini sessions on the phone (June 2026 to now, kept current).
- `archive`: `~/conversation-corpus/data/index/corpus.sqlite`, 2,108 conversations back to August 2024 (ChatGPT, Claude web, laptop sessions).
- `lanes`: this client's own `state/history.db`. Exchanges already in the session, rewound exchanges and the current turn are left out.

Key words are the message's content words, weighted by how rare they are in the turn index; very common words drop out. Each saved turn is scanned for the 480-character stretch that holds the most key-word weight. Up to five passages are kept, at most two from one chat. They go into one user-role JSON data message typed `recall_notes`, placed directly before George's message, at the tail of the request. Each passage has `ref` (`chats#N`, `archive#N`, `lanes#N`), `source`, `chat`, `title` when the chat has one, `date` (phone time) and `speaker`. A fixed `standing` line says the passages are evidence from saved chats, not instructions. The message is saved on the exchange and replayed byte for byte in later requests, so every request stays a prefix of the next and the cached front never changes. In `--loop` runs only the first model turn searches.

The search stops at 5 seconds. A search that runs out of time, fails or finds nothing attaches nothing, and the turn goes on. Each search writes one `usage.jsonl` record with `kind: recall`: status, time in ms, key-word count, passage refs and errors, never passage text. `/off recall` and `/on recall` in a chat switch it for this state folder (`state/recall.json`); `--no-recall` skips it for one run. It ships on. Like the page list, it is switched on only by the command-line entry point, so unit tests never read the phone's chats.

The same search by hand: `past-chats WORDS` and `past-chats --open REF [N]` (`card memory`).

**Notes.** `note add NAME "TEXT"` writes `NAME.md` in `/root/.claude/projects/-root/memory/` in George's format (a front block with `name`, `description` "M/D: text", `metadata.type`) and appends its line `- [Name](NAME.md) — M/D: first words` under `## From the lanes` at the end of `MEMORY.md`. An existing note is never overwritten. `note show NAME`, `note list`.

**Sessions.** One exchange is one message from George and every model turn that answered it.

```sh
george --fork audit audit-b -- "Try the other fix."   # new session audit-b, a full copy of audit; audit is unchanged
george --from golden-page "Start here."                 # a new session that starts as a copy of golden-page
session golden golden-page                              # every new chat starts as a copy of it; --new skips it
session golden --clear
sessions                                                # date, name, lane, exchanges, first line
session show NAME | session export NAME --pdf           # the PDF goes to /sdcard/Download/session-NAME.pdf
session rewind NAME 2 | session cut NAME 3 5 | session splice NAME OTHER [FROM TO]
```

In a chat: `/fork [NEWNAME]` (the chat continues in the copy) and `/rewind [N]` (drop the last N exchanges; default 1). Exchanges taken out of a session stay in `history.db` and are also kept in `state/sessions/NAME.removed.jsonl`. Every change takes the same lock a live turn takes.

Code: `recall_notes.py`, `recall_cli.py`, `session_tools.py`, `note_tool.py`; commands `toolbox/bin/session`, `sessions`, `note`, `past-chats`; card `lanes`. Tests: `test_recall_notes.py`, `test_session_tools.py`, `test_note_tool.py`.

## Toolbox

George's subscription setup can drive his phone, laptop, mail, money tools, bakery tools and other models. The API lanes could reach almost none of it, because nothing told them the commands exist. The toolbox makes each capability one command, proves it through the harness's own shell, and catalogues it.

**The pieces.**

- `tools_block.txt` — the index. One line per family, ending in `Print: card NAME`. Thirty-one families and 4,411 characters since the whole-phone pass. The first nineteen-family index measured 1,044 tokens on Claude Opus 5.5 and 739 on GPT-6.1 Sol.
- `toolbox/cards/NAME.md` — one card per family, each under 4,000 characters: what it does, the exact commands with real argument shapes, what comes back, which side it runs on, and the one known failure.
- `toolbox/bin/` — the commands the model types. `toolbox/debian/` — the Debian-side halves of four of them.
- `toolbox/install.sh` — links every file in `toolbox/bin` into `$PREFIX/bin`. Safe to run again. It never replaces a real file.
- `toolbox/hrun.py` — runs one command exactly as the harness does and prints its exit code.

**The commands.**

| Command | What it does |
|---|---|
| `cards` | Lists every card with its purpose. |
| `card NAME` | Prints one card. Exit 1 on an unknown name. |
| `deb COMMAND ARGS` | Runs one command on the Debian side, in the current folder. |
| `edit-exact FILE OLD NEW` | Replaces OLD with NEW only when OLD appears exactly once. Exit 1 and nothing written otherwise. |
| `text-pdf OUT.pdf TEXT` | Makes a PDF that holds TEXT (or the text on stdin). |
| `page-text URL` | Opens URL in the signed-in phone Chrome on its hidden screen and prints the page text. |
| `mail-unread berkeley\|gmail [N]` | Unread count of the inbox and the newest N. Marks nothing read. |
| `paypal-get PATH` | One read-only GET on the live PayPal API. |
| `bakery-stats [DAYS]` | The bakery's site, search, listing and social numbers. |
| `cloud-check NAME` | One read-only call that shows a cloud key still works. Prints no key. |
| `mcp TOOL 'JSON'` | Calls one of the 55 tools of the phone's own MCP server. `mcp tools` lists them. Exit 1 when the tool reports an error. |
| `rish -c 'COMMAND'` | Runs a command on the phone through Shizuku, at shell rights, with no adb. |
| `media-volume [PERCENT]` | Prints the media volume as a percent, or sets it. |

**Install, or re-install after a clone.** In native Termux:

```sh
sh ~/interaction-harness/toolbox/install.sh
```

**Rules for changing it.**

- A command goes on a card only after it ran through the harness's own runner and its exit code was seen: `python ~/interaction-harness/toolbox/hrun.py 'COMMAND'` in native Termux. A run from another shell proves nothing here.
- Cards state facts. A command that acts on the outside world gets one plain fact line, such as "This sends a real email at once."
- No key, token or password value goes on the index, on a card, or in a script. Say where the key lives.
- `tools_block.txt` must stay byte-identical between calls, so the caches keep hitting. Every edit to it starts the cache over once.
- `test_toolbox.py` checks the caps, that the index and the cards name the same families, control characters, key-shaped strings, the card printer, the installer and `edit-exact`.

**The whole-phone pass (Nov 11, 2026).** A scan showed the lanes knew a small part of the phone. Eleven families were added: `mcp-see`, `mcp-touch` and `mcp-apps` (all 55 tools of the phone's MCP server, with argument shapes taken from its own `tools/list`), `phone-settings`, `phone-hardware`, `shizuku`, `devices`, `agent-scripts`, `agent-box`, `programs` and `boot`. Every read-only form ran through the harness's own runner; every form that taps, sends, calls or changes a setting is listed without a run.

**Repaired on the phone that day.** These were lost when George moved from the Z Flip 7 to the Pixel 11, and their short names work again: `deb recall` (the file had a letter n where its line breaks belong), `deb mbc-stats` and the mail scripts (the Python folder `/root/.gmail/venv` was gone; gcloud's selected account was a service account), `deb phone-do`, `deb phone-ask`, `deb assistant` and `deb support-chat` (the installed copy and the errand profile were copied back from the old phone), `qr`, Modal, `playwright`, `apkinfo`, `check-model` and `yalta` (missing Python modules), the Bright Data program and `lt` (missing Node packages), `gemini` on both sides, `grok` (the program; its sign-in is still needed), and `termux-notification-list` (Termux:API had no notification access).

**Still not working when checked (Nov 11, 2026).** Each card states its own failure. In short: `grok` needs George's sign-in (`grok login --device-code`); PayPal transaction search needs a permission only George can add in the PayPal developer dashboard; the MCP server's camera and location tools lack those two app permissions; the name reader for hidden screens does not answer on Android 17, so hidden screens are driven by picture (`card screen`), and the MCP tools see the visible screen only; DroidRun's helper is not enabled; no boot keeper loop is running and Android lists no scheduled timers.

**Live proof of the whole-phone pass (Nov 11, 2026).** Six questions on each lane, real launcher, `--loop -y`, isolated state: battery level and temperature, set the media volume to its current level, the last five notifications, Wi-Fi state and network name, the Android version through Shizuku, and a node position on a hidden screen through the MCP tools. Ten of twelve passed with exit 0 and matched a direct check. The hidden-screen question did not pass on either lane: the MCP server cannot see a hidden screen, and both models said so.

**Live proof (Nov 11, 2026).** Six questions on each engine, through the real launcher with `--loop -y` and an isolated state folder: a screenshot with its path and size, the Berkeley unread count and newest subject, the bakery site's sessions for seven days, the laptop's hostname, an exact edit of a file, and a one-page PDF in Downloads. Twelve of twelve exited 0 with the right command, and each answer matched a direct check. Every run printed the family's card first, then ran the command from it. With the index in place the second call still read the cache: 13,939 tokens on Claude, 10,810 of 11,584 on GPT-6.1 Sol.

## Rules and profile pages

`george` and `g1` used to start every call knowing nothing about the operator. Each call now carries the operator's own pages, read from the files he already keeps. Git holds the mechanism only. The text of the pages never enters the repository.

**The list.** `state/pages.json` in this installation. Git ignores `state/`. Each entry has a `label`, an absolute `path`, and an optional `sections` list of exact heading lines:

```json
[
  {"label": "rules", "path": "/absolute/path/rules.md", "sections": ["## First heading", "## Second heading"]},
  {"label": "profile", "path": "/absolute/path/profile.md"}
]
```

- Without `sections` the whole file is sent. With `sections`, only those sections are sent, in the order listed. A section runs from its heading line to the next line that starts with `## `.
- The text is sent word for word. Only blank space at the two ends of a page is dropped.
- The files are read on every call. An edit to a source file reaches the model on the next call, and that page's cache entry starts over.
- Order on both engines: frozen prefix, tools page, then the listed pages in list order. Each page is its own system page.

**Limits.** Each is checked before any API call and ends the run with one short error (exit code 2). Nothing is ever cut to fit.

- A page file that is missing or unreadable.
- A named heading that is not found, or that appears more than once.
- Control characters in a page.
- A single page over 20,000 characters, or all listed pages together over 40,000 characters.
- An empty page.
- A malformed list: not a JSON list, a key other than `label`, `path`, `sections`, a bad or repeated label, a path that is not absolute.

**No list, no change.** With `state/pages.json` missing or empty, the request holds the frozen prefix and the tools page only, exactly as before this feature.

**Usage log.** Each usage record has a `pages` field: the label and SHA-256 of every page sent, in order. Page text is never written to the usage log. Page text is not stored in `history.db` or in session files either, because it is not part of a turn.

**Cache markers on Claude.** Anthropic allows four `cache_control` markers in one request. With listed pages, the system pages use two: one at the end of the tools page and one at the end of the last page sent. Without listed pages the layout is unchanged: one marker on the prefix and one on the tools page. `pages.anthropic_system()` builds this. Any code that builds the Anthropic `system` parameter must call it, so the count stays at two.

**Where the list is switched on.** `harness.PAGES_FILE` is `None` when the module is imported. Only the command-line entry point, the `__main__` block at the bottom of `harness.py`, sets it to `state/pages.json` in the installation folder, next to the saved keys. `HARNESS_STATE_DIR` does not move it. The unit tests import the module, so they never read the installation's real list. `test_pages.py` points the list at temporary folders.

**On this phone (Nov 11, 2026).** Two entries. `rules` is five sections of `/root/.claude/CLAUDE.md`. `profile` is the whole of `/root/.claude/projects/-root/memory/who-george-is.md`. Sizes from the providers' own usage numbers:

| Page | Characters | Claude Opus 5.5 tokens | GPT-6.1 Sol tokens |
|---|---|---|---|
| `rules` | 6,089 | 1,947 | 1,283 |
| `profile` | 6,130 | 2,389 | 1,619 |
| both | 12,219 | 4,336 | 2,902 |

Added cost per call for both pages, at list prices on that date: on Claude, $0.0009 when read from cache and $0.0217 on the call that writes the cache; on GPT-6.1 Sol, $0.0003 cached and $0.0058 uncached. On Claude the second call of a session read 9,772 tokens from cache: the reply tool, the prefix, the tools page and both pages. On GPT-6.1 Sol the second call read 6,173 of 6,746 input tokens from cache.

## Where context goes

Each API call carries context in four places, in this order.

1. **Frozen prefix.** `prefix_block.txt` is sent first on every call as the system prompt: the operator contract, the observation/action rules, the speech hints, and the worked examples. It is byte-identical between calls, so both providers can cache it. The usage log records the cache-read tokens each provider reports. The size of the cache discount depends on the provider and the model, and the first call pays to write the cache.
   The tools page (`tools_block.txt`) follows it as a second cached page. The operator's pages listed in `state/pages.json` follow the tools page; see *Rules and profile pages*.
2. **Reply schema.** The four-field schema travels in the request parameters: OpenAI Structured Outputs in strict mode, and the strict `emit_reply` tool on Anthropic. The schema fixes the fields and their types. It does not control the words inside `direct_answer`; a greeting or an apology is still a valid string. Removing filler is the job of the local scrubber and linter described under *Output gate*.
3. **Rolling history.** Up to six prior exchanges, capped at 24,000 characters, follow the prefix. When a command ran, its result follows that exchange as a separate JSON data message typed `execution_observation`, holding the command, exit code, stdout and stderr. It is data for the model to read, not an instruction. Older turns leave the model's view. They stay in `state/history.db`, and `--recall` is a search the operator runs by hand. The model does not retrieve old turns by itself.
4. **Current request.** The new input, after speech normalization, is the last message.

### What enforces what

- **Local code enforces:** schema validation, the observation-has-no-command rule, opening-line cleanup, the filler linter, removal of unrequested reassurance, the completed-work check (a reply may report finished work only when an approved command that exited 0 directly precedes it), the control-character check, and the y/N execution prompt.
- **The prompt only requests:** tone, answer-first order, asking one question when the input is unclear, and contextual speech corrections. The model follows these most of the time, not every time.
- **The API changes one thing:** no consumer chat app sits between the caller and the model, so the app's own system prompt is absent and the caller owns the whole request. The model's trained behavior is unchanged. It can still hedge and it can still refuse. A refusal is reported as a failure and is never displayed as an answer.
- **Claude's tool call is not forced.** `tool_choice` is `auto`, so the model can answer in plain text. The local gate rejects that reply.
- **Speed.** Both defaults run at high reasoning effort. A turn takes seconds with or without a cache hit.

## Senses

Both engines have hosted web search and page fetching enabled by default. `--no-web` disables both. `--web-max N` sets a total lookup ceiling per model turn (2-50; default 5). OpenAI uses its `web_search` tool for search, `open_page`, and `find_in_page` actions. Claude uses `web_search_20260209` and `web_fetch_20260209` with direct calling. Claude exposes separate per-tool limits, so the client reserves `ceil(N/2)` searches and `floor(N/2)` fetches: three searches and two fetches at the default. The minimum of two leaves a slot for each tool. A paused Claude turn resumes with its complete content unchanged; an invalid final tool reply is returned as a tool error within the same quota turn. OpenAI corrective calls use the remaining shared budget. Tool definitions stay byte-identical for a fixed engine and flag configuration.

```sh
g1 "Search the web for today's official Python release news."
george "Fetch https://example.com and give me its title."
g1 --no-web "What does chmod 640 mean?"
george --web-max 8 "Search for the latest announcement and read its page."
g1 --image ~/picture.png "What is shown here?"
george --file /sdcard/Download/report.pdf "Read the second chart."
```

`--image PATH` and `--file PATH` are repeatable. Images can be PNG, JPEG, WebP, or GIF; files must be PDF. The file signature determines the type, regardless of its extension. Paths beginning with `~` mean the Termux home, `/sdcard` paths work through Debian, and relative paths use the folder from which the native launcher was started. In chat, use one line such as `/image "/sdcard/Download/a b.png" What number is shown?` or `/file ~/report.pdf What does page two say?`.

Files are sent inline without client resizing, cropping, or truncation. The verified first-party limits are: OpenAI, 512 MB total request payload, PDFs individually under 50 MB and at most 50 MB combined; Claude, 10 MB base64 data per image and 128 MB total request payload including PDFs and all other content. Base64 overhead counts. Preflight rejects an over-limit file or request before making an API call. Provider processing and model-specific image/page constraints still apply; a provider rejection is a failure, not a substituted or shortened attachment.

An exchange stores each attachment's phone path, SHA-256, byte size, media type and kind. Bytes are not stored in SQLite or session files. While that exchange remains in the rolling history, the original file is checked and re-sent on later turns. A missing or changed file stops the request instead of silently substituting new content.

The client records actual hosted tool events and provider-reported counts. It deduplicates source URLs and prints at most eight, after the answer and before any command:

```text
Sources:
1. Example Domain — https://example.com
```

Only a lookup returning sources creates this block. The model must not write its own Sources section. SQLite stores `sources_json`, `lookup_counts_json`, and `attachments_json`; sessions retain the same metadata, and `--recall` displays saved sources. Counts distinguish search, fetch and find actions, preserve the provider's usage reports, and include the URLs that were supplied as request/history context.

Two checks run after the existing answer checks. A claimed search, browse, fetch or online check without a recorded lookup is rejected. Quoted text and denials are preserved. A URL in the answer must be in this turn's sources, the operator's request, or the supplied session history. Either violation gets at most one corrective reply. Hosted lookup errors, including Claude's HTTP-200 error blocks, stop the turn with an error and no answer. The four-field reply, frozen prefix and operator-owned context pages retain their existing contracts.

Verification: `python verify_senses.py --engine openai` and `python verify_senses.py --engine anthropic` run the seven live cases and save JSON reports under `state/senses-checks/`. A separate development copy can supply `--key-dir /path/to/live/state`; only the directory is passed on the command line. `--resume REPORT_DIRECTORY --case NAME` reruns a failed case while retaining prior receipts. The PNG and PDF fixtures use the standard library; no dependency was added.

Official references checked for this implementation: [OpenAI web tools](https://developers.openai.com/api/docs/guides/tools-web-search), [OpenAI images](https://developers.openai.com/api/docs/guides/images-vision), [OpenAI files](https://developers.openai.com/api/docs/guides/file-inputs), [Claude web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [Claude web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool), [Claude server tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/server-tools), [Claude images](https://platform.claude.com/docs/en/build-with-claude/vision), and [Claude PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support).

## Screen

Both engines can see a picture returned by an approved command. Inside `--loop`,
`screen snap` captures a PNG and attaches it to the next turn. `look PATH` does the
same for an existing PNG, JPEG, WebP, GIF, or PDF. Every command still asks for
`[Run command? (y/N)]` unless the operator chose `-y`. The four-field reply and all
display, execution, lookup, and source gates still run.

```sh
screen snap [--target phone|hidden:NAME|laptop|yana] [--out PATH]
screen size [--target TARGET]
screen tap X Y [--target TARGET]
screen swipe X1 Y1 X2 Y2 [MS] [--target TARGET]
screen text 'WORDS' [--target TARGET]
screen key KEYCODE [--target TARGET]
look /sdcard/Download/picture.png

g1 --loop "Take a picture of hidden screen work and tell me what app is showing."
george --loop "Use look /sdcard/Download/order.pdf and read its delivery date."
```

Install with `sh toolbox/install.sh` after choosing this version for use. The
installer links commands in `toolbox/bin`, including `screen`. This phone already
has a real system binary named `look`; the installer keeps it and reports that
the harness uses its own `look` from the toolbox. In a plain shell outside the
harness, use `~/interaction-harness/toolbox/bin/look PATH` for this version.
The native runner puts **this checkout's** toolbox first on PATH. Development
copies therefore use their own commands and cards without changing installed
links. Screen inspection uses Debian's installed Pillow; no new package is needed
on this phone.

The default target is George's visible phone. Input acts on that screen at once.
`hidden:NAME` requires an existing hidden display; a missing or zero display id
fails instead of using screen zero. `card phone` gives the lifecycle commands.
For hidden captures, the driver matches the logical display's exact virtual
`uniqueId` to SurfaceFlinger's capture id and uses `adb exec-out screencap -p -d ID`.
This avoids the older hidden `shot` reader's "no frame" failure after its pending
frames are consumed on a static screen. Ambiguous or missing mappings fail closed.
Coordinates are pixels of the captured image at full size. `size` uses a fresh
capture, so rotation is reflected in the dimensions. Android text supports
printable ASCII; unsupported characters and literal `%s` return an error.
Windows captures its primary desktop through a short-lived interactive PowerShell
task; the task and its temporary files are removed. Windows input uses user32 and
SendKeys. Its supported keys are ENTER, TAB, ESC, BACKSPACE, UP, DOWN, LEFT, RIGHT
and their matching Android keycodes. Laptop input and all Yana operations remain
**listed, not run** in this task's live proof. The driver implements them; tests
check the generated commands. Visible-phone proof is capture only.

The file-naming rule is an **inherited private receipt descriptor**. Only an
explicit local `screen snap` or `look` process writes `{"path":"..."}` to that
descriptor. The runner never scans stdout, stderr, web pages, log files, or model
text for markers. An approved arbitrary shell program can intentionally use its
inherited descriptor; the descriptor is not a sandbox against the approved shell.
Outside a harness command, the toolbox's `look` just prints a path.

After the command, the client applies the same signature, path, and provider-size
checks as `attachments.py`. It copies accepted bytes to private
`state/execution-attachments/<SHA-256>.<type>`. This prevents a later overwrite of
`--out` or the original file from changing an earlier turn. SQLite's
`attachments_json` and `execution_result` record path, SHA-256, byte size, media
type, and image/file kind; session JSON stores the same execution attachment.
The image is sent with that execution observation while its exchange remains in
the history window. The latest result also survives a zero history budget during
the current loop. An oversized or unreadable file becomes `attachment_errors` in
the next observation; the loop can recover. Snap rejects all-black frames, missing
targets, and timeouts with distinct one-line errors and nonzero exits. Output
images are published only after validation, so a failed capture cannot attach a
stale `--out` file.

The frozen prefix is unchanged. The tools index is loaded once per request and
has identical bytes for every turn of a session. Picture bytes are added at the
execution observation, after the stable cached prefix. API image formats were
checked against [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
and [Claude image inputs](https://platform.claude.com/docs/en/build-with-claude/vision).

`verify_screen.py --engine openai|anthropic --case app|search|phone|cache
--state PATH --hidden NAME` uses the real launcher with isolated state. Its
proof-only command check permits input solely on NAME; George's phone can only be
captured, and Yana and laptop commands are excluded. Start the hidden screen and
open Settings before the app/search cases; stop it after checks. Reports keep the
exact query, exit code, command results, SQLite rows, and cache counters. Image
answers must also be compared with their saved PNGs.

## API tools

`g1 --tools` and `george --tools` list every API tool, its default state, its provider, and any recorded provider refusal. There are 26 switches covering 39 provider/tool pairs. The final answer still passes through the same four-field schema and display gates. The frozen prefix is unchanged.

```sh
g1 --tools
george --tools
g1 --loop --shell "Run pwd and report the path."
george --loop --memory "Save a note that the test shelf is blue."
george --loop --memory --new "Read the saved shelf note."
g1 --loop --mcp-local "List the last five notifications on my phone."
g1 --loop --mcp-remote "List the last five notifications on my phone."
george --loop --computer --computer-target hidden:NAME "Take a screenshot."
g1 --files --file /path/to/document.pdf "Read this document."
g1 --image-generation "Make a small blue circle."
```

Every flag has a `--no-NAME` form. Inside a chat, use `/tools`, `/on NAME`, or `/off NAME`. Chat switches are saved in `state/tools.json`; flags override that file for one launch. Use hyphens in flags and chat commands; the JSON keys use underscores. `--api-advisor` controls Anthropic's hosted advisor tool. The separate `--advisor` and `/advisor` commands remain the operator's review feature.

Local actions use the existing native runner and command approval. Start with `--loop` or `--exec`; `-y` explicitly approves commands without a question. Tool requests, results, exit codes and attachment hashes are recorded in SQLite and session files. A discovery listing or approval is not a completed action. A failed latest action cannot borrow an older success. Tool-use claims require a matching receipt before display.

| Switch | Provider | Default | Why |
| --- | --- | --- | --- |
| `--web-search` | openai, anthropic | on | Keeps the existing lookup behavior. |
| `--web-fetch` | openai, anthropic | on | Keeps the existing lookup behavior. |
| `--history-cache` | anthropic | on | Cuts repeated input without changing the answer. |
| `--memory` | anthropic | off | Adds lasting notes across chats. |
| `--code-execution` | openai, anthropic | off | Uses a paid hosted runtime. |
| `--computer` | openai, anthropic | off | Can change the device. |
| `--browser` | anthropic | off | Can act on signed-in websites. |
| `--shell` | openai, anthropic | off | Can change files and devices. |
| `--hosted-shell` | openai | off | Uses a paid hosted runtime. |
| `--text-editor` | anthropic | off | Can change files. |
| `--apply-patch` | openai | off | Can change files. |
| `--mcp-local` | openai, anthropic | off | Exposes device actions to the model. |
| `--mcp-remote` | openai, anthropic | off | Sends tool requests through a remote endpoint. |
| `--files` | openai, anthropic | off | Stores files with the API provider. |
| `--file-search` | openai | off | Uses provider storage and retrieval. |
| `--skills` | openai, anthropic | off | Runs skill instructions and supporting code. |
| `--tool-search` | openai, anthropic | off | Changes how tools enter model context. |
| `--programmatic` | openai, anthropic | off | Changes tool execution and adds runtime cost. |
| `--context-editing` | anthropic | off | Removes old detail from the model input. |
| `--compaction` | openai, anthropic | off | Changes the context sent to the model. |
| `--background` | openai | off | Changes storage and request lifetime. |
| `--image-generation` | openai | off | Adds image-generation charges. |
| `--api-advisor` | anthropic | off | Calls another paid model. |
| `--functions` | openai, anthropic | off | Exposes local command execution. |
| `--custom-tools` | openai | off | Exposes local command execution. |
| `--namespaces` | openai | off | Changes tool names and discovery. |

OpenAI supplies web search and page fetch as one tool; their switches move together. Skills turn on their required hosted runtime. Programmatic calls turn on functions (and Claude's sandbox). Tool search and namespaces turn on functions. OpenAI local shell and hosted shell cannot be enabled together.

The `options` object in `state/tools.json` holds `computer_target`, `browser_endpoint`, `max_tool_steps` (24 by default), and resource IDs. File search needs `vector_store_ids`. Skills need version-pinned `openai_skills` or `anthropic_skills`; their list shapes match the providers' official APIs. Model notes live in `state/memory/`; edits are bounded to that folder. Uploaded file IDs are reused only for unchanged attachment hashes. Generated images go to `state/generated/`; downloaded provider files go to `state/downloads/`. Final replies include those local paths.

Computer use reuses the screen driver (`phone`, `hidden:NAME`, `laptop`, `yana`). The touch adapter withholds Claude's right-click, middle-click and cursor-position members. It returns an error for unsupported input. The live proof captures a hidden screen; it does not exercise every tap/key on every target. Claude's browser tool uses the existing phone CDP endpoint, default `http://127.0.0.1:9335`. Its live proof lists tabs without changing them.

### Remote phone MCP

Local MCP exposes the phone's 55 tool definitions through `agentbridge-call`. The remote route uses an authenticated Cloudflare Worker and an outbound phone bridge, active only during a remote-MCP request. The installed relay permits `android_notification_list` by default. Set `mcp_allowed_tools` deliberately to expose more tools. Keep remote MCP off until needed.

`options` holds `mcp_url`, `mcp_token_file`, `mcp_bridge_url`, `mcp_bridge_token_file`, and `mcp_allowed_tools`. Secret values live only in private token files, outside git. The two tokens serve different roles. The Worker keeps pending requests in memory, not Durable Object storage. The phone bridge closes when the request ends. Other authenticated remote MCP servers need only their URL, client token path and allowed tools.

`deploy_mcp_relay.py --account ACCOUNT --token-file PATH --state PRIVATE_DIR` deploys this relay and writes its private configuration. `api_mcp_tunnel.py` also supports a local HTTP adapter for existing tunnel services. The deployed Worker route passed on both engines; the temporary quick-tunnel route proved unreliable and is not the installed route. No existing ngrok endpoint was replaced.

### Conversation cache and proof

Claude caches the growing conversation using one automatic history marker alongside the two system-page markers. Earlier messages stay byte-identical; each loop note sits beside its own turn. A three-turn live test checks that turn three reads more cached tokens than the complete first request. Cache metrics, tool-list hashes and provider errors are saved with the existing usage events.

`verify_tools.py --engine openai --case shell --state state/api-tools/my-proof` runs one real tool case through the launcher, schema, display gate and SQLite. Use `--engine anthropic` for Claude and `--options-file FILE` for resource IDs or a relay. The script permits only its own harmless commands, fixture edits, hidden screenshot, tab listing and five-notification query. The memory case creates a note in one session and reads it in a second.

See [API_TOOLS_REPORT.md](API_TOOLS_REPORT.md) for one result per provider/tool pair, defaults, live exit codes, exact evidence paths, cache counts, and the limits of the checks. Runtime settings and full reports stay under ignored `state/`; they contain private device results.

## Second gate

The local gate filters wording with patterns in code. The second gate adds what patterns cannot do. The code is in new modules; `harness.py` and `cli.py` hold only the hooks.

### The choice check

When George's request is an instruction, the local gate rejects a reply that asks leave for the ordered work ("Do you want me to…", "Should I proceed?", "Shall I…", "Would you like me to…", "Let me know if you'd like…") or that ends by offering the work instead of doing it. The usual one corrective retry follows. A question about a missing fact is allowed: one that opens with which, what, where, when, who or how, or one that names real alternatives ("Should I use main or dev?"). The check is skipped when the request is not an instruction, and when George asked to be asked first. Code: `choice_check.py`. Tests: `test_choice_check.py`.

### Rules as data

A new filter rule no longer needs an edit to `harness.py`. The rules are a JSON list in `state/gate_rules.json` in this installation. Each entry holds:

- `name`: lower-case letters, digits and hyphens.
- `pattern`: a regular expression. It is matched one sentence at a time, without regard to case.
- `action`: `strip_sentence` cuts each sentence that matches and keeps the rest. `reject` sends the reply back for one corrected try.
- `bad`: the sentences the rule must match.
- `date` and `history_row`: the day it was added and the `history.db` row that caused it.

The gate reads the file when a run starts and again whenever the file changes, so a rule added while a chat is open applies to the next reply. The rules run after every built-in check in `validate_reply`. A reply in which every sentence is cut gets the corrective retry. A broken entry is skipped and named once on stderr; the other rules still run.

```sh
rule add NAME --row N --action strip_sentence --pattern 'REGEX' --bad 'SENTENCE' [--bad 'SENTENCE' ...]
rule list
rule drop NAME
rule test [NAME] [--text 'WORDS']
```

- `rule add` refuses a rule (exit 1, nothing written) unless it matches every one of its own bad sentences and matches nothing in `gate_known_good.txt`. It also refuses when history row N does not exist.
- `gate_known_good.txt` ships with the code: 230 sentences, built by `build_known_good.py` from the accepted answers in the saved `history.db` files and the positive cases in the existing tests. Add a line by hand when a rule cut something that must stay.
- `rule test` runs every stored rule against its own bad sentences and the known-good file again. With `--text` it shows what the gate would do to those words.
- Exit codes: 0 worked, 1 refused or a rule failed its test, 2 wrong use.

A habit that no regular expression can express is a check in code: `habit_checks.py` holds `CUT_SENTENCES` (whole sentences cut wherever they stand) and `CHECKS` (functions that return a reason for the corrective retry). The gate runs both after the data rules.

Code: `gate_rules.py`, `gate_rules_cli.py`, `habit_checks.py`, `gate_admin.py`; the command is `toolbox/bin/rule`. Tests: `test_gate_rules.py`. The unit tests never read the real rules file: it is switched on only by the command-line entry point (`second_gate.switch_on`), like the page list.

## Verification

```sh
proot-distro login debian -- sh -c 'cd /data/data/com.termux/files/home/interaction-harness && .venv/bin/python -m unittest -v test_harness test_features test_repl test_diagnostics test_loop test_reassurance test_tools_block test_pages test_senses test_toolbox test_screen_driver test_execution_images test_screen_card test_advisor test_choice_check test_chats test_api_tools test_api_relay test_recall_notes test_session_tools test_note_tool'
python ~/interaction-harness/test_native_terminal.py
python ~/interaction-harness/verify_loop.py --engine openai
python ~/interaction-harness/verify_loop.py --engine anthropic --yes
python ~/interaction-harness/verify_smoke.py --engine openai
python ~/interaction-harness/verify_smoke.py --engine anthropic
~/interaction-harness/verify-live --engine openai
~/interaction-harness/verify-live --engine anthropic
python ~/interaction-harness/verify_repl.py --engine openai
python ~/interaction-harness/verify_repl.py --engine anthropic
```

`verify_loop.py` verifies a real temporary-file create/read task through three model turns. Its confirmation-mode test approves only the two exact test commands; `--yes` tests explicit auto-confirm. It checks the file contents, captured read output, final null payload, session records, and unchanged four-field schema. Reports remain under `state/loop-checks/`.

`verify_smoke.py` runs two real one-off calls through the installed Bash alias (`g1` or `george`) using the requested echo text. It checks the exact four-field session reply, answer-only display, provider cache counters, and matching SQLite metrics. The second identical request probes cache reuse; a zero cache read is recorded as a miss, not fabricated as a hit. Reports and isolated SQLite databases are stored under `state/diagnostics/`. This layout uses `harness.py` plus `cli.py`; `python -m harness.cli` is not a supported entry point.

Each full `verify-live` engine run makes eight small queries (at most one corrective retry per query), then verifies local recall and history. The first two calls check actual cache reuse; later calls check named memory and continuation. Test history lives under the run's own private directory and does not take over the operator's active session. `verification.json` links the latest results. The live REPL checks open real terminal sessions through the Bash aliases, verify both requested models and high effort, test session memory and exit, and check one-off mode. Native execution checks are recorded separately. The spoken dictation check was explicitly skipped by the operator; the hook remains available. `requirements.lock` pins installed dependencies.

Exit codes: 0 for success, recall with no match, or a declined execution; 2 for invalid input, credentials, gate, API, bridge, or dictation failure; 3 for the agent turn ceiling; 130 for interruption. Approved command exit codes are propagated (signals use 128 + signal number; timeouts use 124).

`HARNESS_STATE_DIR` selects an isolated state directory for automation/tests; saved credentials remain in this installation's `state` directory. `state/`, `.venv/`, backups, and logs are excluded by `.gitignore`. The local Git baseline contains code, configuration, schemas, the frozen prefix, documentation, and tests. Credentials, personal history, environments, backups, and generated reports are excluded. A baseline commit does not publish the repository.

## Official references

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)
- [Anthropic schema support](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic model IDs](https://platform.claude.com/docs/en/models/overview)
