# calls — the voice line into a Claude session, and the AI that phones a place for George

The voice line: George dials the line and talks to a Claude session that runs in tmux (Vapi is the wire).
  deb bash /root/.vapi/bridge/phone.sh status       active room, server, tunnel; changes nothing
  deb voice-list                                    the rooms; a star marks where the phone rings
  deb bash /root/.vapi/bridge/phone.sh on           starts the server and a public tunnel, and points the number at it
  deb bash /root/.vapi/bridge/phone.sh off          stops the server and the tunnel
  deb voice-use ROOM                                rings into another open room
  Keys: /root/.gmail/aicalls.env. How it works: deb cat /root/.vapi/bridge/README.md
  Checked 2026-11-11: server down, tunnel down, room "brain" gone.

The caller (Bland): an AI voice phones a business
  P=/data/data/com.termux/files/home/phone-errands     (write the full path in each command)
  deb /data/data/com.termux/files/home/phone-errands/phone-ask --balance      -> "$9.97 left on Bland"
  deb /data/data/com.termux/files/home/phone-errands/phone-ask --last         last call: answers and transcript
  deb /data/data/com.termux/files/home/phone-errands/phone-do --last          last errand: result and transcript
  deb /data/data/com.termux/files/home/phone-errands/phone-ask "+14155551234" "Ace Hardware on Mission" "Are you open Sunday?" "Do you sell propane?"
      This places a real phone call at once and spends Bland credit, about $0.14 a minute.
  deb /data/data/com.termux/files/home/phone-errands/phone-do CARD.txt
      Runs an errand from a card file (who, number, goal, facts). This places a real phone call at once.
  deb /data/data/com.termux/files/home/phone-errands/phone-do --dry CARD.txt  shows the call plan, places no call
  deb /data/data/com.termux/files/home/phone-errands/phone-do --help          the card format
  Key: /root/.bland/key.

Known failure
  phone-ask stops with "ValueError: The shared profile needs the handoff phone number." (checked
  2026-11-11 with --dry). The folder phone-errands/config holds profile.example.json and no filled-in profile.
  `deb phone-do` and `deb phone-ask` answer "command not found": use the full paths above.
