# calls — the voice line into a Claude session, and the AI that phones a place for George

The voice line: George dials the line and talks to a Claude session that runs in tmux (Vapi is the wire).
  deb bash /root/.vapi/bridge/phone.sh status       active room, server, tunnel; changes nothing
  deb voice-list                                    the rooms; a star marks where the phone rings
  deb bash /root/.vapi/bridge/phone.sh on           starts the server and a public tunnel, and points the number at it
  deb bash /root/.vapi/bridge/phone.sh off          stops the server and the tunnel
  deb voice-use ROOM                                rings into another open room
  Keys: /root/.gmail/aicalls.env. How it works: deb cat /root/.vapi/bridge/README.md
  Checked 2026-11-19: active room brain (up), server up, tunnel up. The number is 650-252-3543.
  deb voice-session NAME                            opens a new Claude room and points the phone at it at once.
      It has no help form: any first word, even --help, becomes a room name. Listed, not run.

The caller (Bland): an AI voice phones a business
  deb phone-ask --balance                     -> "$9.97 left on Bland"
  deb phone-ask --last                        last call: answers and transcript
  deb phone-do --last                         last errand: result and transcript
  deb phone-ask --dry "+14155551234" "Ace Hardware on Mission" "Are you open Sunday?"
                                              prints the request it would send; places no call
  deb phone-ask "+14155551234" "Ace Hardware on Mission" "Are you open Sunday?" "Do you sell propane?"
      This places a real phone call at once and spends Bland credit, about $0.14 a minute.
  deb phone-do CARD.txt
      Runs an errand from a card file (who, number, goal, facts). This places a real phone call at once.
  deb phone-do --dry CARD.txt                 shows the call plan, places no call
  deb phone-do --help                         the card format
  When a live person answers, the call is handed to George's own number from the errand profile.
  Key: /root/.bland/key. Profile: /root/.local/state/phone-errands/profile.json.

The same brain from a terminal: deb assistant submit 'JOB' | jobs | status; deb support-chat CARD.txt (`card programs`).
A call-out by a Vapi assistant: deb python3 /root/.vapi/place_call.py --assistant ID --to +1XXXXXXXXXX --task 'WORDS'
  This places a real phone call at once. Listed, not run.

Known failure
  The installed tool in /root/.local/share/phone-errands is older than the code in ~/phone-errands.
  `python3 scripts/install.py` in that folder installs the newer revision and restarts the line.
