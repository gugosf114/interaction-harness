# chats — read what the other AI sessions on this phone are saying and doing

George runs several AI sessions at once: Claude Code sessions and Codex sessions. Each one saves every
message to a file the moment it happens. These two commands read those files. They change nothing.

List the sessions, newest first
  chat-list            the 15 newest
  chat-list 40         the 40 newest
  One line each: last write time, kind (claude or codex), the first 8 characters of its id, size,
  and George's first words in it.

Read the end of one session
  chat-tail ID         the last 20 messages
  chat-tail ID 60      the last 60
  ID is any part of a session id from chat-list. Each line: time, who spoke (George, Claude, Codex),
  what they said, and "[ran ...]" for each command or tool the model used. Hidden thinking is skipped.
  Times in the files are UTC.

Where the files live
  Claude Code: /data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs/root/.claude/projects/-root/ID.jsonl
               (the same folder is /root/.claude/projects/-root/ on the Debian side)
  Codex:       ~/.codex/sessions/YEAR/MONTH/DAY/rollout-...-ID.jsonl
  This client: ~/interaction-harness/state/sessions/NAME.json and state/history.db (search it: harness --recall "WORDS")

Search inside every past chat: see `card memory`.
Send a line into a live session: see `card sessions`.

Known failure
  "no session matches": the id was mistyped. Run chat-list and copy the 8 characters.
