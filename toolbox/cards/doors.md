# doors — every port and listener: what answers on it, how to knock, what to do when it is shut

Checked 2026-11-19 at 7:10 pm, after a phone restart at 4:54 pm. "up" means the knock below answered then.

On this phone (127.0.0.1)
  5555   adb, the phone talking to itself. up.      adb -s 127.0.0.1:5555 shell true ; echo $?        `card phone`
  5037   the adb server. up.                        adb devices
  8022   sshd, the Termux shell. up.                pgrep -x sshd
  8080   the phone's MCP server (55 tools). up.     deb phone-link  -> "phone link UP (http 405)"     `card mcp-see`
  8377   the lane service's page. up.               curl -s -m 4 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8377/
                                                    -> 401 without the password                       `card always-on`
  8790   the voice line's server. up.               curl -s -m 4 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8790/
                                                    -> 200                                            `card calls`
  9335   Chrome Beta on the hidden screen "web". up.   deb curl -s -m 4 127.0.0.1:9335/json/version   `card phone-browser`
  9336   George's own Chrome. Not forwarded (000). It is opened on demand: `card browsers`.
  9222   the Linux hidden browser. down (000); its boot start failed twice that day: `card browsers`.
  8765   open only while google-signin waits for a tap: `card mail`.
  9225   the LinkedIn helper's own port. down: `card bridge`.
  Shizuku has no port. Knock: rish -c id      `card shizuku`
  Which ports listen right now:
  adb -s 127.0.0.1:5555 shell 'ss -ltnH' | awk '{print $4}' | sort -u
  Port 9080 and a few high random ports also listen. Nothing here names their owner.

Public tunnels out of this phone (both were up)
  ngrok, fixed address  -> 8790, the voice line.    deb bash /root/.vapi/bridge/phone.sh status
  cloudflared, quick    -> 8377, the voice line's lane_job tool.     agentd status
  A new one: `card programs` (ngrok, cloudflared, lt) or `agentd tunnel`.

On the laptop (reached with: deb ssh wimlaptop ...)
  22     ssh. up.                                   deb ssh wimlaptop hostname                        `card laptop`
  9222   the headed Chrome for forms and jobs (task GeorgeJobApplicationsChrome). up.
  9224   the headless Chrome for Google's consoles (task GeorgeGoogleConsoleHeadless). up.
         deb bash -c 'ssh wimlaptop "curl -s -m 5 http://127.0.0.1:9224/json/version"'                `card browsers`
  9226   the browser runner's own port. down.       9227   the Play Console runner's port. Not checked.
  8081   the grounding model server. Not checked.   Tunnels from here use 19222 and 19224.

On the always-on box (100.123.176.12)
  8787   the conductor. up.                         curl -s -m 8 http://100.123.176.12:8787/health -> ok   `card agent-box`
  18080  the box's tunnel to this phone's 8080. down ("tunnel": false in /dash/health).

Other devices (adb 5555 and Termux ssh 8022 on each)
  100.81.55.57    the Z Flip 7. up at 7:05 pm, offline at 4:35 pm.          `card devices`
  100.68.147.84   Yana's phone; on the home Wi-Fi it also lists as 192.168.1.216.     `card yana-phone`
  192.168.1.215   the Chromecast.   192.168.1.66   the LG TV. Home Wi-Fi only.        `card tv`

The private network itself
  tailscale-devices                                 every device: name, online or offline, address
  ping -c 1 -W 3 100.100.100.100                    answers only while Tailscale is on
  sh ~/bin/tailscale_keeper.sh once                 turns Tailscale back on when it is off; a loop does this every 60 s

Known failure
  A 100.x address that times out while the device is on: Tailscale on this phone is off. It stayed off
  after the 4:54 pm restart until it was switched on by hand. The keeper line above fixes it.
