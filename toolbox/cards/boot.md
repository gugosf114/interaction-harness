# boot — what starts by itself when the phone boots, and how to check and restart each piece

The files are in ~/.termux/boot. The Termux:Boot app runs every file there once after a restart.
Restart any one by hand:  sh ~/.termux/boot/NAME

  10-brain-up              keeps Termux awake, starts sshd, connects adb to 127.0.0.1:5555, starts Shizuku
      check:  pgrep -x sshd ; adb devices ; rish -c id
  11-droidrun.sh           turns the DroidRun helper's accessibility service back on
      check:  deb bash /root/agent-bridge/scripts/droidrun.sh status
  12-timers                waits 90 s, then re-hangs every timer in the table (timers-ensure boot)
      check:  termux-job-scheduler --pending          (`card timers`)
  13-wifi-debug            keeper loop that holds Wireless debugging on at home (~/bin/wifi_debug_keeper.sh tick)
      check:  ps -eo args | grep '[w]ifi_debug_keeper'
  14-mcp-door              keeper loop that holds the phone MCP server's door open (~/bin/mcp_door_keeper.sh tick)
      check:  deb phone-link          restart one look:  sh ~/bin/mcp_door_keeper.sh once
  15-shizuku-keeper        keeper loop that brings Shizuku back within 30 s (~/bin/shizuku_keeper.sh tick)
      check:  rish -c id              restart one look:  sh ~/bin/shizuku_keeper.sh once
  16-voice-line            keeper loop for the voice line: every 60 s it runs /root/.vapi/bridge/phone.sh ensure
      check:  deb bash /root/.vapi/bridge/phone.sh status     log: ~/.agent-bridge/voice-line.log
  heal-adb-shizuku         reopens adb 5555 through Wireless debugging, then restarts Shizuku
      check:  tail -5 ~/.agent-bridge/heal.log
  hidden-chrome            starts the Linux hidden browser inside Debian (/root/hchrome/start.sh, debug port 9222)
      check:  deb curl -s -m 5 127.0.0.1:9222/json/version
  start-hidden-operator    starts the keeper that holds the hidden screens up (hidden_supervisor.sh boot)
      check:  bash ~/hidden-operator/scripts/hidden_supervisor.sh status
  start-sshd               keeps Termux awake and starts sshd
      check:  pgrep -x sshd
  start-agent-bridge.off   switched off; it used to start the old phone supervisor

Which keeper loops are alive right now
  ps -eo args | grep -E '[s]hizuku_keeper|[m]cp_door_keeper|[w]ifi_debug_keeper|[1]6-voice-line|[h]idden_supervisor'
  One line per live loop. No lines means none is running.

Facts (checked 2026-11-11)
  sshd, adb on 5555, Shizuku and the MCP door are up.
  No keeper loop is running, the hidden-screen keeper says "watch: DEAD", the Linux hidden browser on 9222
  does not answer, the voice line is down, and Android lists no scheduled timers.
  Starting a file by hand starts its loop again. The loops stop at the next restart of Termux unless
  Termux:Boot runs them.

Known failure
  After a phone restart nothing here runs until the Termux:Boot app has been opened once since it was installed.
