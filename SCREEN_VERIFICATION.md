# Screen verification — 2026-11-11

I did all three deliverables on `feature/universal-vision-driver` in the separate
`~/interaction-harness-screen` copy. The base is `503a86b`. The branch is for review;
this task does not merge to main or update the live installation.

- I did the `screen` driver: six verbs, four targets, distinct missing-screen,
  black-image, and timeout errors. Phone and laptop captures ran; all input proof
  used the newly created hidden screen `astra-screen-proof`.
- I did the automatic image handoff and `look`: private descriptor, normal
  attachment checks, fixed copies, SQLite/session records, and recovery feedback.
- I did the card, one index line, installer handling, README Screen section,
  help text, and tests. `run_chat` and the advisor are unchanged.

## Test results

236 unit tests passed (the existing 210 plus 26 new tests), exit 0.
All four native PTY tests passed, exit 0. Installation checks used a temporary
prefix, including the real-system-`look` name collision. The system binary stays
in place; the harness resolves its own toolbox first on PATH.

All final live cases passed through the real Termux launcher and command runner.
Each engine had isolated state. The proof runner allowed input only on its named
hidden screen and capture only on George's visible screen.

| Engine | Case | Exit | Seconds | Cache-read tokens across this case |
|---|---|---:|---:|---:|
| openai | app | 0 | 41.06 | 20042 |
| openai | search | 0 | 96.67 | 44784 |
| openai | phone | 0 | 42.12 | 20056 |
| openai | cache | 0 | 12.93 | 6344 |
| anthropic | app | 0 | 77.02 | 30228 |
| anthropic | search | 0 | 180.51 | 40304 |
| anthropic | phone | 0 | 68.08 | 30228 |
| anthropic | cache | 0 | 27.74 | 10076 |

The separate cache case is the second invocation of its app session. Both engines
reported positive cache-read tokens. Cache counters are provider receipts, not
estimated cost savings.

The pictures were opened and compared with the answers. OpenAI identified Settings
on its home page. Claude identified Settings on its search page and named its four
visible recent results. Both search cases captured first, tapped, typed `wifi`,
captured again, and read **Use Wi-Fi** under **Network & internet > Internet**.
Both final phone captures showed **7:02** and both answers said **7:02**.

Nine accepted image records were rehashed and matched their saved byte sizes.
Both SQLite files passed `PRAGMA integrity_check`. Every saved assistant reply had
exactly the original four fields. All events in each final run used one unchanged
tools-index hash and one unchanged prefix hash. The frozen prefix matches the base
commit byte for byte. The unit tests compare the actual first request bytes with
the next request for both fake provider clients.

## Target receipts

| Target | Status | What ran |
|---|---|---|
| `phone` | run | `screen snap --target phone`; `screen size --target phone` → 1080 2424 |
| `hidden:astra-screen-proof` | run | snap, size, tap, swipe, text, key; 1080 2400; app/search proof on both engines |
| `laptop` | run | `screen snap --target laptop`; `screen size --target laptop` → 2560 1440 |
| `yana` | listed, not run | all six verbs; the task forbids capturing or driving this phone |

Laptop input is **listed, not run**. It is implemented with Windows user32 and
SendKeys in an interactive scheduled task, but no live input was sent. The
PowerShell capture is proved. Its hidden launcher avoids photographing a console
window created by the screenshot command. Its task and temporary files are removed;
a read-only query found no remaining `harness-screen-*` scheduled tasks.

George's visible-screen input is **listed, not run**. All taps, swipes, text, and
keys in this task targeted `hidden:astra-screen-proof`.

These are the exact unrun examples, each **listed, not run**, not claims of live success:

```sh
screen tap 10 20 --target phone
screen swipe 10 20 30 40 300 --target phone
screen text 'WORDS' --target phone
screen key KEYCODE_ENTER --target phone
screen tap 10 20 --target laptop
screen swipe 10 20 30 40 300 --target laptop
screen text 'WORDS' --target laptop
screen key KEYCODE_ENTER --target laptop
screen snap --target yana
screen size --target yana
screen tap 10 20 --target yana
screen swipe 10 20 30 40 300 --target yana
screen text 'WORDS' --target yana
screen key KEYCODE_ENTER --target yana
```

No final tested target remains broken. Missing targets, black captures and timeouts
were checked offline; Yana reachability and laptop input remain unverified.

## Failures found and repaired

- The old hidden `shot` command exhausted ImageReader frames on an unchanged
  screen. Exact error: `[hidden] no frame`; the early OpenAI search check exited 2
  after capture exited 1. The new driver resolves the named virtual screen's exact
  uniqueId to its SurfaceFlinger capture id, then captures that display directly.
  Three repeated static captures worked. A regression test checks repeated fresh
  screencap calls and rejects absent, duplicate, or physical-display mappings.
- The first Windows encoded command exceeded cmd.exe's limit. Exact error:
  `The command line is too long.` Gzip packing reduced the command size; all verb
  templates now fit the command limit in unit checks. A hidden WScript launcher
  prevents the helper console from covering the actual desktop image.
- The first Claude app proof exited 2 because the proof-only allowlist did not
  accept two read-only card commands separated by a newline. It now parses newline
  separators and still blocks visible input, Yana, other hidden screens and shell
  redirection. Both engines were rerun with final receipts retained separately.
- Hidden-screen creation returned exit 1 with
  `[hidden] display exists but shared reader failed; see /data/local/tmp/vd/ud.log`.
  Its virtual display existed and worked. The driver needs that display and adb,
  not the shared accessibility reader. No shared reader or existing web display
  code was edited. The task's own hidden screen was stopped after the live checks.

## Local proof and API references

Raw proof stays private in `~/interaction-harness-screen/state/screen-proof/`:
`verified.json`, `openai-v2/*-report.json`, `anthropic-v3/*-report.json`,
`full-suite-final.log`, `native-final.log`, `commands.json`, `laptop-final.txt`,
`laptop-final.png`, `laptop-cleanup-check.json`, `hidden-stop.json`, and screenshots.
Old failed-run logs remain beside the final logs. No key, state database, chat
history, or screenshot is part of the commit.

Image request formats were checked against the official provider pages and then
proved with real image calls on both lanes:

- https://developers.openai.com/api/docs/guides/images-vision
- https://platform.claude.com/docs/en/build-with-claude/vision
