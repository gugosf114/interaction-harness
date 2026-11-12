# lanes — this client's own saved sessions: list, read, fork, rewind, cut, splice, golden, PDF

One exchange is one message from George and everything the lane did for it (in --loop runs: every
model turn that followed it). Sessions live in ~/interaction-harness/state/sessions/NAME.json.
Nothing here deletes a row from state/history.db. Exchanges taken out of a session are kept in
state/sessions/NAME.removed.jsonl. All commands run in native Termux.

List and read
  sessions                          every session, newest first: date, name, lane, exchanges, first line.
                                    "*" marks the golden session, ">" the one -c continues.
  session show NAME                 the whole session as plain text, exchanges numbered [1], [2], ...
  session export NAME --pdf         writes /sdcard/Download/session-NAME.pdf and prints its path and size
  session export NAME --out PATH    plain text to PATH (a PATH ending in .pdf makes a PDF)

Change
  session fork SOURCE [NEWNAME]     a new session that is a full copy of SOURCE. SOURCE is not written.
                                    Default name SOURCE-fork, then SOURCE-fork-2, ...
  session rewind NAME [N]           drop the last N exchanges (default 1)
  session cut NAME FROM TO          drop exchanges FROM to TO, numbered as in `session show`
  session splice NAME OTHER [FROM TO]   append OTHER's exchanges (or FROM to TO of them) to NAME
  session golden NAME               every new chat starts as a copy of NAME (george, g1, harness)
  session golden --clear            new chats start empty again
  session golden                    print the golden session

At George's prompt (he types these, in a george or g1 chat)
  /fork [NEWNAME]    the chat goes on in a copy; the original stays as it was
  /rewind [N]        drop the last N exchanges of this chat
  /off recall, /on recall   the past-chat search before each message
Flags: --fork SESSION [NEWNAME], --from NAME (a new session starts as a copy of NAME), --new (empty, no golden copy).

Known failure
  "No session named NAME": run sessions and copy the name. A PDF needs weasyprint on the Debian side.
