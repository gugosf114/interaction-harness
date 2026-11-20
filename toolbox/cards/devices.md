# devices — every device George's phone can reach

See them
  adb devices -l                 the adb list
  tailscale-devices              every device on George's private network: name, online or offline, system, address

The adb list (checked 2026-11-19; it changes through the day)
  127.0.0.1:5555       this phone, the Pixel 11. Android 17. Always there.
  100.81.55.57:5555    the Z Flip 7 (SM-F766U), George's old phone. Listed at 7:05 pm. At 4:35 pm it was
                       offline and adb answered "device '100.81.55.57:5555' not found".
  100.68.147.84:5555   Yana's Galaxy S25+ over Tailscale: `card yana-phone`.
  192.168.1.216:5555   Yana's phone again, by its home Wi-Fi address, when both phones are home.
  A device that is missing: adb connect ADDRESS:5555 puts it back when it is reachable.
  emulator-5554 (this phone listed twice) no longer shows.

The Z Flip 7
  adb -s 100.81.55.57:5555 shell getprop ro.product.model                         -> SM-F766U
  deb ssh -i /root/.ssh/termux -p 8022 100.81.55.57 'COMMAND'                    a shell in its Termux
  deb scp -i /root/.ssh/termux -P 8022 100.81.55.57:PATH /sdcard/Download/       copy a file from it
  It still holds the files from before the move to the Pixel: an older copy of the chat archive, its own
  Debian install at $PREFIX/var/lib/proot-distro/containers/debian/rootfs, and the sign-ins that were on it.
  flip-red                                       opens the Flip's "rednotice" Claude window in this terminal.
                                                 It is a live chat, not a one-shot. Listed, not run.
  adb -s 100.81.55.57:5555 shell input tap X Y          This taps the Flip's screen at once.
  adb -s 100.81.55.57:5555 exec-out screencap -p > ~/tmp/flip.png      a picture of its screen; with the screen
                                                                       off the file is not a picture

The other machines on the private network
  DESKTOP-760722E (100.109.240.20)           George's Windows laptop: `card laptop`
  DESKTOP-K15HEJT (100.113.104.54)           a second Windows desktop; no command reaches it yet
  agent-bridge-conductor (100.123.176.12)    the always-on Linux box: `card agent-box`
  YANA's S25+ (100.68.147.84)                `card yana-phone`
  Pixel 11 (100.72.227.33)                   this phone

Tailscale, the private network (always on since 2026-11-19, on this phone and the Flip)
  ping -c 1 -W 3 100.100.100.100                 answers only while Tailscale is on
  sh ~/bin/tailscale_keeper.sh once              turns it on when it is off. A loop does this every 60 s;
                                                 boot file 17-tailscale-keeper and timer 7736 keep the loop alive.
  Log: ~/.agent-bridge/tailscale-keeper.log. Android's own always-on VPN setting names Tailscale too.
  tailscale-devices reads the list from the laptop, so it needs the laptop on.

Which adb target to use
  deb bash /root/agent-bridge/scripts/transport.sh ensure      prints the live target for this phone and heals
                                                               the connection when it has dropped
  A plain `adb shell` with no -s fails here: "adb: more than one device/emulator". Always name the device.

Known failure
  "device offline", "not found" or "Connection timed out" for a 100.x address: that device is asleep or off
  the private network, or Tailscale on this phone is off (the ping line above tells which).
  deb ts-fix was written for the Flip and still names the Flip's address. On the Pixel use the keeper line.
  adb-connect-existing scans for the Wireless debugging port to reopen adb. Listed, not run.
