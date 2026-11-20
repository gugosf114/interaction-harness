# programs — other programs on this phone that no other card names

Debian side (put `deb` in front)
  deb ngrok version                           -> ngrok version 3.39.11
  deb ngrok http 8080                         opens a public web address that reaches port 8080 on this phone
  deb cloudflared --version
  deb cloudflared tunnel --url http://localhost:8080      a public address through Cloudflare; it changes each run
  deb lt --version  ;  deb lt --port 8080     localtunnel: the same idea, a third provider
  deb edge-tts --list-voices                  every neural voice
  deb edge-tts --voice en-US-AvaNeural --text 'WORDS' --write-media /sdcard/Download/words.mp3      makes an MP3
  deb edge-playback --text 'WORDS'            speaks the words out loud at once
  deb playwright --version                    -> Version 1.65.1. The Python library for driving a browser.
  deb playwright install chromium             downloads its own browser; none is installed yet, and the
                                              headless tools on `card bridge` fail for lack of it
  deb apkinfo /FULL/PATH/app.apk              package name, version and permissions of an APK file
  deb check-model /FULL/PATH/model.onnx       checks that an ONNX model file is valid
  deb harvest SESSION_ID 8                    prints the eight best exchanges of one Claude Code session
  deb google-console --help                   the command list of George's Google-consoles client, as JSON.
                                              The client drives pages on the laptop.
  deb assistant profile                       the fields saved in the errand profile
  deb assistant jobs  ;  deb assistant status jobs and state of the personal brain behind the voice line
  deb assistant submit 'THE JOB'              hands a job to that brain
  deb support-chat --dry CARD.txt             shows the plan for a support-chat errand; without --dry it runs it
  deb line status                             the WiM Line (a phone-call voice for George): what is up
  deb line  ;  deb line stop                  start it; stop it
  deb yalta --help                            a history game George plays against Claude brains
  deb fork                                    opens a new Claude Code session that starts as a copy of George's
                                              "golden" chat. It is a full chat window, not a one-shot.
  deb v                                       buzzes, listens for 30 seconds, prints what was said
  deb uv --version ; deb uvx TOOL             the Python tool runner (0.13.7)
  deb bdata budget                            Bright Data: `card browsers`

Termux side
  nmap -sn 192.168.1.66                       is that address up
  nmap -sn 192.168.1.0/24                     which devices answer on the home network
  tailscale-devices                           every device on George's private network
  transcripts --help                          the tool that analyses George's saved chat archive
  inception status                            the multi-model cockpit: status | resume | fork | server | pair | cockpit

Known failure (checked 2026-11-19)
  deb assistant jobs and deb assistant status answered that day. When they answer "<urlopen error [Errno 111]
  Connection refused>" the voice line is down: `card calls`.
  deb line status shows every part DOWN until `deb line` starts it.
  inception status: "codex app-server daemon version failed". firebase: "Cannot find module 'semver'".
