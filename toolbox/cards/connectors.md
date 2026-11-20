# connectors — what George's Claude Code sessions have that this lane lacks, and the phone-side tool that does the same

George's Claude Code sessions carry claude.ai connectors. This lane has none of them. For each one, this is
the command here that does the same job, or the plain fact that nothing does. Checked 2026-11-19.

Has an equal here
  Gmail connector            google-mail NAME ..., mail-unread            `card mail`
                             The connector makes drafts. google-mail sends at once; it has no draft step.
                             A bakery draft: deb /root/.gmail/idraft.py MSG_ID TO /FULL/PATH/body.txt (listed, not run).
  Google Calendar connector  google-calendar NAME ...                     `card calendar`
                             No update, delete or reply-to-invite here. Read and create only.
  Google Drive connector     google-drive NAME list | read | create       `card drive`
                             No share, move, trash or permission change here.
  PayPal connector           paypal-get PATH (read); draft and send by curl      `card money`
                             No payment links and no dispute list here.
  Web search, page fetch     built into this client. A blocked page: deb bdata scrape URL (`card browsers`).
  A browser with hands       page-open, page-click, page-type             `card web-hands`
  PDF read and make          read-doc, make-pdf, text-pdf                 `card office`
  Pictures and video         make-image, make-video                       `card pictures`
  Skills                     skill find WORDS, skill show NAME            `card skills`
  Subagents, background runs job add "TASK"                               `card always-on`
  Memory notes               note add, deb cat .../memory/NAME.md         `card memory`
  Scheduled runs             state/schedule.json of the lane service      `card always-on`; scripts: `card timers`

Nothing here does it
  Canva                      no command. The skill text for it names tools this lane lacks.
  Figma                      no command.
  Adobe (Express, Acrobat, Firefly, fonts)     no command. PDF work: `card office`. Pictures: `card pictures`.
  Claude Docs, Artifacts     no command. A public page instead: publish FILE (`card publish`).
  Microsoft 365, Slack, Notion, Linear, Atlassian, Intercom      not signed in anywhere on this phone.
  For any of these, say that the lane has no tool for it. George's Claude Code session has it:
  a line into that session is on `card sessions`.

Only this lane has
  The four-field reply and the gates, /wrong lessons and rules (`card lessons`), the usage meter
  (`card usage`), the second-model judge.

Known failure
  A skill printed with `skill show` may tell you to call a connector tool. The lane notes at its top name
  each missing one. There is no stand-in command beyond the lines above.
