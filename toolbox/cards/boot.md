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
  17-tailscale-keeper      keeper loop that turns Tailscale back on within 60 s (~/bin/tailscale_keeper.sh tick)
      check:  ping -c 1 -W 3 100.100.100.100      one look:  sh ~/bin/tailscale_keeper.sh once
  20-agentd                the lane service and its keeper (`card always-on`)
      check:  agentd status
  heal-adb-shizuku         reopens adb 5555 through Wireless debugging, then restarts Shizuku
      check:  tail -5 ~/.agent-bridge/heal.log
  hidden-chrome            starts the Linux hidden browser inside Debian (/root/hchrome/start.sh, debug port 9222)
      check:  deb curl -s -m 5 127.0.0.1:9222/json/version
  start-hidden-operator    starts the keeper that holds the hidden screens up (hidden_supervisor.sh boot)
      check:  bash ~/hidden-operator/scripts/hidden_supervisor.sh status
  start-sshd               keeps Termux awake and starts sshd
      check:  pgrep -x sshd

Which keeper loops are alive right now
  ps -eo args | grep -E '[s]hizuku_keeper|[m]cp_door_keeper|[w]ifi_debug_keeper|[1]6-voice-line|[h]idden_supervisor|[t]ailscale_keeper|[k]eeper.sh watch'
  One line per live loop. No lines means none is running.

Facts (checked 2026-11-19, 7:10 pm; the phone restarted by itself at 4:54 pm when the battery ran out)
  After that restart these came back with no hand: sshd, adb on 5555, Shizuku, the MCP door, the two hidden
  screens, the voice line, the lane service, and seven keeper loops. The Tailscale keeper was added that
  evening and makes eight.
  Tailscale did not come back by itself. It is now the phone's always-on VPN and has the keeper above.
  The Linux hidden browser on 9222 did not start: "hidden chrome did NOT come up" (~/.agent-bridge/hidden-chrome.log).
  Termux:Boot runs every file in the folder, whatever its name. A file named start-agent-bridge.off ran at
  that restart and started signal.sh --watch, brain_beacon.sh and timer 7919, which George had stopped that
  day. They were stopped again and the file now sits in ~/.termux/boot-off. To switch a boot file off,
  move it out of ~/.termux/boot.

Known failure
  After a phone restart nothing here runs until the Termux:Boot app has been opened once since it was installed.
  A restart with no Wi-Fi leaves adb and Shizuku down until the phone is back on the home Wi-Fi.
