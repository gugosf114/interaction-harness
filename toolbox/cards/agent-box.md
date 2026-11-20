# agent-box — the always-on box, the laptop's helpers, and the scripts that talk to them

The box: a Linux machine on George's private network, agent-bridge-conductor, 100.123.176.12.
conductor.py runs on it as a server on port 8787. It is the "brain" that takes jobs while the phone sleeps.

Ask the box (reads)
  curl -s -m 8 http://100.123.176.12:8787/health                 -> ok
  curl -s -m 8 http://100.123.176.12:8787/dash/health            brain, tunnel and watcher status as JSON
  curl -s -m 8 http://100.123.176.12:8787/dash/data              the task board as JSON
  curl -s -m 8 http://100.123.176.12:8787/dash/budget            today's brain spend against its daily cap
  curl -s -m 8 http://100.123.176.12:8787/dash/pending           a plan that waits for George's approval, or {}
  Also reads: /dash/missions (the one-tap jobs), /dash/outbox (results; reading one takes it out).
  Checked 2026-11-19: health ok, brain true, tunnel false, spend 0 of a 10 dollar daily cap.

Give the box work (each of these makes the brain act)
  curl -s -m 8 -X POST -H 'Content-Type: application/json' -d '{"text":"THE JOB IN WORDS"}' http://100.123.176.12:8787/pad
  curl -s -m 8 -X POST -H 'Content-Type: application/json' -d '{"kind":"note"}' http://100.123.176.12:8787/signal
      /pad queues a job. /signal with kind "note" wakes the brain to read it; kind "summon" means come now.
  curl -s -m 8 -X POST http://100.123.176.12:8787/dash/approve   approves the waiting plan (/dash/reject drops it)
  POST /dash/laptop/job {"id","verb","args"} runs one thing on the laptop through the box when ssh is down
  (verbs: run, read_file, write_file, screenshot, desktop, browse, get_active); the answer is at /dash/laptop/result.
  POST /dash/cmd {"name"} runs one named, fixed command. POST /dash/watch and /dash/memory write a watch or a fact.
  All of these act. Listed, not run.

What else runs on the box (code in /root/agent-bridge/scripts, read it with `deb sed -n '1,40p' FILE`)
  conductor.py         the server above
  box_scheduler.py     fires timed jobs from ~/.agent-bridge/schedules.json on the box, once a minute
  telegram_bridge.py   a private Telegram bot: George's messages become jobs, the brain's answers come back.
                       Its token and chat id live in /etc/conductor-brain.env on the box.

The laptop's helpers
  laptop_agent.py      runs on the laptop and gives the brain a second body there: run a command, open a URL,
                       take a screenshot, drive Windows controls, read a file
  windows_desktop.ps1  the Windows control script behind it: list controls, click, type, key, scroll, open
  mcp.sh               laptop-side client for the phone's MCP server over an ssh tunnel:
                       mcp.sh up | down | status | call TOOL 'JSON'
  orch.sh              on the laptop's WSL: named tmux sessions for parallel AI sessions
  orch                 the phone-side command for it (Termux side, on the path):
                       orch ls                                   live sessions on the laptop -> "(no sessions)"
                       orch new sonnet research                  start named sessions
                       orch send sonnet "claude.exe -p 'PROMPT'"     types a line into that session at once
                       orch read sonnet                          what that session shows
                       orch kill sonnet

From the phone's home screen
  voice_summon.sh      the "Voice Summon" shortcut: George speaks, the words go to the box as a job
  The phone's status light and beacons that talked to the box are stopped: `card agent-scripts`.
  ~/.shortcuts         holds it, next to Launch_God_Mode.sh

Plain shell on the laptop and long jobs for Claude there: `card laptop`.

Known failure
  curl prints nothing and exits 28: the box is asleep or off the private network. `tailscale-devices` shows it.
