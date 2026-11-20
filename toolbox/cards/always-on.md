# always-on — the lane service that runs with no window open: jobs, doors, the page, talk

Runs on: the Termux side. The service is agentd. It takes a task, runs it as a g2 or g1 job in the
background, and tells George the result. Checked 2026-11-19: service and keeper running, after a phone restart too.

Jobs
  job list                          one row per job: ID STATE LANE DOOR TIME TASK
  job show 6                        the task, the full answer and every command it ran (--full: each step)
  job wait 6                        waits, then prints the answer
  job stop 6                        stops it
  job add "Check the battery and the Wi-Fi name."            -> "job 7 queued on g2 (session job-7-1a2b)"
  job add --lane g1 --session audit "Continue the audit."
      job add starts a real lane run with --loop -y. It is a paid API call and it acts without asking.
  Type `job list`, not `jobs`: in this shell `jobs` is bash's own word and prints nothing.

The service
  agentd status                     service, keeper, page addresses, job counts, each door's state
      Its "password:" line is the page password. Do not repeat that line.
  agentd url                        the page addresses: http://127.0.0.1:8377/ and the Tailscale one
  agentd log 30                     the last 30 log lines
  agentd start | stop               stop writes a STOPPED mark; the keeper then leaves it down until start
  After `agentd restart` over ssh the service stayed down once (2026-11-19). Use `agentd start`, then `agentd status`.

The doors a task can come in by (settings: ~/interaction-harness/state/doors.json)
  folder     a text file dropped in ~/interaction-harness/state/inbox; the answer lands in state/outbox
  text       a text to this phone that starts with the keyword, from George's own number
  telegram   the Telegram bridge on the always-on box hands /g1 and /g2 tasks here
  voice      the voice line's lane_job tool, through its own Cloudflare tunnel (`card calls`)
  clock      state/schedule.json (0 entries today)      events   state/triggers.json (0 rules today)
  page       port 8377; it asks for the password once

A public address for the page (each line opens the page to the internet until Ctrl-C)
  agentd tunnel            a Cloudflare quick tunnel      agentd tunnel ngrok      through George's ngrok account
  Listed, not run.

Talk
  talk --clip /sdcard/Download/question.m4a --no-speak      a recorded clip goes to the lane; prints the answer
  talk                     records from the microphone and speaks the answer out loud. Listed, not run.
  talk --lane g1 --seconds 30

When a job ends George gets a phone notification: "LANE job ID STATE", and the answer is spoken when
spoken answers are on (`card voice`).

Known failure
  "job: the service is not running": agentd start. A job whose runner died shows "interrupted"; it is not run again.
