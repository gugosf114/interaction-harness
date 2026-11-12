# Interaction harness

A native Termux command with OpenAI and Anthropic backends, a shared four-field reply schema, a local display gate, six-exchange sessions, SQLite recall, confirmed shell execution, and Android dictation.

## Quick use

```sh
~/interaction-harness/harness "Explain chmod 640."
~/interaction-harness/harness --engine anthropic "Explain chmod 640."
python ~/interaction-harness/harness.py "Read this observation."
printf '%s\n' 'Explain this permission mode.' | ~/interaction-harness/harness
```

The default is OpenAI (`gpt-6.1-sol`). Anthropic defaults to the latest Opus tier verified during setup, `claude-opus-5-5`. `--model MODEL` selects a model on the chosen engine. Both require support for their strict-output and cache parameters. Both engines default to `high` effort. OpenAI receives `reasoning.effort`; Anthropic receives adaptive thinking plus `output_config.effort`. `--effort low|medium|high|xhigh|max` overrides the level. The output budget is 8,192 tokens, including thinking, so high effort has room to finish.

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

Files live at `state/sessions/<id>.json`. Only the latest six complete user/assistant exchanges remain by default; `--turns N` changes that window (1–50). The API receives at most 24,000 characters of prior history, keeping whole exchanges; `--history-chars N` changes that cap. The current input limit is 50,000 characters. Oversized input is rejected before it can become a truncated instruction.

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

`tools_block.txt` tells the model what this phone has: `gh` signed in, `git`, `rg`, `jq`, `curl`, `python`, the bridge to the Debian side, the read-only mail reader, and the Termux phone commands. It is sent on every call right after the frozen prefix, on both engines, and both providers cache it.

It is plain text and the operator can edit it. It is not hash-pinned. Rules: at most 8,000 characters, no control characters. An empty or missing file sends nothing and the harness works as before. The page grants no permission; every command still needs approval. Each usage record stores the page's SHA-256 as `tools_sha256`. Keep it to tools that were checked on the phone, because the model will propose what the page lists.

## Where context goes

Each API call carries context in four places, in this order.

1. **Frozen prefix.** `prefix_block.txt` is sent first on every call as the system prompt: the operator contract, the observation/action rules, the speech hints, and the worked examples. It is byte-identical between calls, so both providers can cache it. The usage log records the cache-read tokens each provider reports. The size of the cache discount depends on the provider and the model, and the first call pays to write the cache.
   The tools page (`tools_block.txt`) follows it as a second cached page.
2. **Reply schema.** The four-field schema travels in the request parameters: OpenAI Structured Outputs in strict mode, and the strict `emit_reply` tool on Anthropic. The schema fixes the fields and their types. It does not control the words inside `direct_answer`; a greeting or an apology is still a valid string. Removing filler is the job of the local scrubber and linter described under *Output gate*.
3. **Rolling history.** Up to six prior exchanges, capped at 24,000 characters, follow the prefix. When a command ran, its result follows that exchange as a separate JSON data message typed `execution_observation`, holding the command, exit code, stdout and stderr. It is data for the model to read, not an instruction. Older turns leave the model's view. They stay in `state/history.db`, and `--recall` is a search the operator runs by hand. The model does not retrieve old turns by itself.
4. **Current request.** The new input, after speech normalization, is the last message.

### What enforces what

- **Local code enforces:** schema validation, the observation-has-no-command rule, opening-line cleanup, the filler linter, removal of unrequested reassurance, the completed-work check (a reply may report finished work only when an approved command that exited 0 directly precedes it), the control-character check, and the y/N execution prompt.
- **The prompt only requests:** tone, answer-first order, asking one question when the input is unclear, and contextual speech corrections. The model follows these most of the time, not every time.
- **The API changes one thing:** no consumer chat app sits between the caller and the model, so the app's own system prompt is absent and the caller owns the whole request. The model's trained behavior is unchanged. It can still hedge and it can still refuse. A refusal is reported as a failure and is never displayed as an answer.
- **Claude's tool call is not forced.** `tool_choice` is `auto`, so the model can answer in plain text. The local gate rejects that reply.
- **Speed.** Both defaults run at high reasoning effort. A turn takes seconds with or without a cache hit.

## Verification

```sh
proot-distro login debian -- sh -c 'cd /data/data/com.termux/files/home/interaction-harness && .venv/bin/python -m unittest -v test_harness test_features test_repl test_diagnostics test_loop test_reassurance test_tools_block'
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
