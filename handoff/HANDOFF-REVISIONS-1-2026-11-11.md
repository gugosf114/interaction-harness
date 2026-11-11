# INTERACTION HARNESS — HANDOFF, REVISIONS 1

Written Nov 11, 2026 by Claude (Fable 5.2), the session that ran the live checks. For the next model that picks this up.

These are corrections and additions to the handoff text titled "Complete Project Handoff: LLM Safety, Voice Interaction & Tool-Call Governance." Every line here was checked against the code, a live run, or GitHub on Nov 11, 2026. Lines I did not run are marked "not run."

## 1. Corrections

1. Bakers Agent (`gugosf114/bakers-agent`) and WiM (`abrahamyants/wim-android`) did not fail as products. Bakers Agent runs in production. WiM is in Google Play closed testing and is the operator's daily dictation tool. What failed was the build sessions: models reported work as done without proof.
2. Tests passing against fakes was Bakers Agent, March 2026. The WiM version was "the build passed" reported as "it works."
3. `george` is a shell command that starts Claude. George is the operator.
4. Commands. Without `-x` or `--loop` the command is only printed. With `-x` each command asks y/N. With `-y` commands run without asking, for that one run. Only the operator can set `-y`. The model cannot.
5. Filler. Filler at the start of an answer is cut locally at no cost. Filler later in the answer fails the gate. The harness asks once for a corrected reply, which is a second paid call. If that fails too, nothing is shown (exit 2).
6. Completed-work check. A reply may say "I ran..." or "Done." only when the command directly before it was approved, finished in time and exited 0. A failed or timed-out command does not unlock it. An older success earlier in the session does not either.
7. Claude's `emit_reply` tool is not forced (`tool_choice` is "auto"). A plain-text reply is rejected by the local gate.
8. "~2,170 tokens" for the prefix is not confirmed. The measured cached sizes are 2,490 tokens on OpenAI and 4,367 on Claude.
9. "Up to 90% cost reduction" applies to the cached input tokens only, not to the whole bill.
10. The source files named "README.pdf" and "README (1).pdf" are the Bakers Agent README and the WiM README.
11. Local code enforces the shape of a reply. Tone, answer-first order and asking when unclear are only requested by the prompt.

## 2. Verified state

Run on Nov 11, 2026, from 8:58 to 9:08 am Pacific, on commit `30abe26`. Later commits changed documentation only. The unit tests were run again on `585b16d`: 125 of 125.

| Check | Result |
|---|---|
| Python unit tests | 125 of 125, exit 0 |
| Native Termux tests | 4 of 4, exit 0 |
| Live smoke, g1 | pass; the second call read 2,502 of 2,505 input tokens from cache |
| Live smoke, george | pass; the second call read 4,367 of 4,456 from cache |
| Eight questions, g1 | 8 of 8; recall, SQLite and speech fixes pass |
| Eight questions, george | 8 of 8; recall, SQLite and speech fixes pass |
| Live chat mode, g1 | 10 of 10 checks |
| Live chat mode, george | 10 of 10 checks |
| Live agent loop, g1 | 11 of 11 checks, three model turns |
| Live agent loop, george | 11 of 11 checks, three model turns |

Cache across the three loop turns: OpenAI read 2,490, then 2,836, then 3,166 tokens. The read grows each turn, so the cache change in `30abe26` works. Claude read 4,367 on every turn; its cache covers the frozen prefix only.

The reports are under `state/` on the phone. They are not in Git.

## 3. Layout and use

- Two floors. The command starts in native Termux (`harness`, then `launch.py`). The Python client runs inside Debian (`proot-distro login debian`, `.venv`, Python 3.13.5). Approved commands and speech capture run in native Termux over a socket bridge.
- Engines: `claude-opus-5-5` and `gpt-6.1-sol`, both at high effort. Billing is per call on API keys, separate from any subscription.
- Agent loop: `--loop` runs up to 5 model turns (`--max-turns` 1 to 50) and feeds each command result back. Exit code 3 means the turn limit was reached.
- Sessions: each one-off call starts fresh. `-c` continues the last session. `--session NAME` names one. Chat mode keeps one session.
- Speech fixes applied before sending: NC to antsy, AIPG to AIGP, redmi to README, term units to Termux. `--no-normalize` turns them off.
- Reply budget: 8,192 output tokens, thinking included. A reply that runs out is reported as incomplete and is not shown.
- Exit codes: 0 ok; 2 failure (input, key, gate, API, bridge); 3 loop limit; 130 interrupted.
- How to answer the operator: answer first, short plain sentences, no greetings, apologies, reassurance or unasked caveats. Ask one short question when the meaning is unclear.

## 4. Rebuild from zero (not run)

Written from the repo's files. Not yet run end to end.

GitHub holds the code, tests, `prefix_block.txt`, the schemas, `requirements.lock` and the README. The phone alone holds both API keys (`state/api-key`, `state/anthropic-api-key`), `state/history.db`, the sessions, the check reports, `backups/`, `.venv`, and the two shortcut lines in `~/.bashrc`.

Step 1, in Termux:

```
git clone https://github.com/gugosf114/interaction-harness ~/interaction-harness
```

Step 2, build the environment in Debian:

```
proot-distro login debian -- sh -c 'cd /data/data/com.termux/files/home/interaction-harness && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock'
```

Step 3, keys, in a Termux shell:

```
. ~/interaction-harness/export-key.sh
. ~/interaction-harness/export-anthropic-key.sh
```

Step 4, add these two lines to `~/.bashrc` (each alias is one line):

```
alias george='/data/data/com.termux/files/home/interaction-harness/harness --engine anthropic --model claude-opus-5-5 --effort high'
alias g1='/data/data/com.termux/files/home/interaction-harness/harness --engine openai --model gpt-6.1-sol --effort high'
```

Step 5, run every command under "Verification" in the README.

## 5. Running the checks from a Claude Code session

- The unit tests run inside Debian directly.
- The native tests and every live check must run in native Termux. From a session inside Debian, go through the Termux door with a ten-minute command limit:

```
ssh -i ~/.ssh/termux -p 8022 127.0.0.1 'cd ~/interaction-harness && python verify_repl.py --engine anthropic; echo "EXIT=$?"'
```

- An earlier run was cut off by a tool error at the Claude chat-mode check. Run this way, no check was cut.
- Print the exit code as shown. Piping a test command into `tail` hides it.

## 6. Still open

- `--listen` (Android dictation) was never tested live. The operator skipped it.
- Local branch `fix/audit-refinements` is still on the phone. It is merged into main and is not on GitHub.
- The rebuild steps in section 4 have never been run end to end.
- No hands-on test by the operator yet. Every check so far is a script.
- Prefix change, when one is due: `prefix_block.txt` is read-only on the phone; update `PREFIX_SHA256` in `harness.py`; the OpenAI cache key is built from that hash, so the cache starts cold; a new version label breaks `test_harness.py` line 60, which looks for "FROZEN PREFIX V3"; rerun every live check. New sentence for line 19: "A client_mode agent_loop record identifies the original task and maximum turns. Each continuation message states the current model turn."
