# sessions — reach the other AI sessions that are open on this phone

Live Codex sessions (Termux side)
  ~/.local/bin/session-message --list
  One line per session: "pid=12599 tty=/dev/pts/2". It prints nothing when no Codex session is open.
  ~/bin/codex-session-message --list           the same list; "No live raw-Termux Codex sessions found."
  ~/bin/codex-session-message pts/2 'MESSAGE'  sends the message and prints that session's reply
  ~/.local/bin/session-message --tty 2 'ONE LINE OF TEXT'
  This types the line into that Codex session and submits it, as if George had typed it.

The post office: po (Debian side)
  deb po list                                  the newest search digests in ~/postoffice
  deb po send TITLE 'MESSAGE'                  send to the session with that title
  deb po send pts/3 'MESSAGE'                  send to the session on that terminal
  deb po send pid:12599 'MESSAGE'              send to that process
  deb po blast 'MESSAGE'                       send to every registered tmux pane
  Each send types the message into another live session at once.
  deb po find 'WORDS'                          search every saved chat; see `card memory`

Hand one tool call to the on-phone bridge (Termux side)
  ~/.local/bin/agentbridge-call TOOL_NAME '{"key":"value"}'
  Example: ~/.local/bin/agentbridge-call android_get_screen_state '{}'

Windows George opens himself (each is a live chat, not a one-shot; listed, not run)
  brain [NAME]              his Claude "brain" session in tmux; the voice line talks to the one named brain
  tmux -L vapi-line ls      the voice line's tmux rooms: brain, control, vsrv, vtun
  deb fork                  a new Claude Code session that starts as a copy of his golden chat
  fork-mcfly                reopens the pruned copy of the long chat
  launch ; inception status the multi-model cockpit. inception status failed 2026-11-19: Codex's app-server is not running.
  ~/.shortcuts              home-screen buttons: "Voice Summon" and Launch_God_Mode.sh (a Gemini session)
  reasoning-trace           a Codex hook that makes Codex show its reasoning; a switch file turns it off

A long job for Claude on the laptop: see `card laptop`. A lane job in the background: `card always-on`.
The voice line into a Claude session: see `card calls`.

Known failure
  `po blast` reaches only sessions that run inside tmux and were registered with `po register`.
  A plain Termux window cannot take typed-in keys from po. session-message reaches Codex sessions only.
