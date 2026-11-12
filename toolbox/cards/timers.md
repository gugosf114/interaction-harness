# timers — run a script later, or again and again

Runs on: the Termux side. Android's job scheduler runs a script file on a period. The shortest period
Android allows is 900000 ms (15 minutes). A period of 0 runs the script once.

See what Android has scheduled
  termux-job-scheduler --pending
  One "Pending Job ID: SCRIPT ..." line per job, or "No jobs found".

The table of George's timers
  cat ~/.local/share/timers.tsv
  One line per timer: id, period in ms, script path. One id holds one script.

Hang a new repeating timer
  ~/.local/bin/timer-add ID PERIOD_MS /FULL/PATH/script.sh
  Example: ~/.local/bin/timer-add 7801 3600000 ~/bin/my-check.sh
  It refuses an id that is taken and a script that is not a runnable file. It adds the line to the table.
  With no arguments it prints: "usage: timer-add <id> <period-ms> <script>".

Put every timer in the table back on its hook
  ~/.local/bin/timers-ensure
  Re-schedules each table line that Android no longer lists. It logs to ~/.local/state/timers-ensure.log
  and shows a phone notification for each timer it puts back.

Run a script once, soon
  termux-job-scheduler --job-id 7802 --script /FULL/PATH/once.sh --period-ms 0 --persisted false

Cancel one
  termux-job-scheduler --cancel --job-id 7802

Facts
  The script must be a file with a shebang line and the run permission (chmod +x).
  Checked 2026-11-11: the table holds seven timers and Android answers "No jobs found".

Known failure
  A timer drops off its hook after a reboot or an app update. `timers-ensure` puts it back.
