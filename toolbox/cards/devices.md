# devices — every device George's phone can reach

See them
  adb devices -l                 the adb list
  tailscale-devices              every device on George's private network: name, online or offline, system, address

The adb list (checked 2026-11-11)
  127.0.0.1:5555       this phone, the Pixel 11. Android 17.
  emulator-5554        the same Pixel 11, listed a second time. adb scans local port 5555 for emulators
                       and finds the phone's own adb there. It is not a second device.
  100.81.55.57:5555    the Z Flip 7 (SM-F766U), George's old phone. Still on, still on the private network.
  100.68.147.84:5555   Yana's Galaxy S25+: see `card yana-phone`.

The Z Flip 7
  adb -s 100.81.55.57:5555 shell getprop ro.product.model                         -> SM-F766U
  deb ssh -i /root/.ssh/termux -p 8022 100.81.55.57 'COMMAND'                    a shell in its Termux
  deb scp -i /root/.ssh/termux -P 8022 100.81.55.57:PATH /sdcard/Download/       copy a file from it
  It still holds the files from before the move to the Pixel: an older copy of the chat archive, its own
  Debian install at $PREFIX/var/lib/proot-distro/containers/debian/rootfs, and the sign-ins that were on it.
  adb -s 100.81.55.57:5555 shell input tap X Y          This taps the Flip's screen at once.
  adb -s 100.81.55.57:5555 exec-out screencap -p > ~/tmp/flip.png      a picture of its screen; with the screen
                                                                       off the file is not a picture

The other machines on the private network
  DESKTOP-760722E (100.109.240.20)           George's Windows laptop: `card laptop`
  DESKTOP-K15HEJT (100.113.104.54)           a second Windows desktop; no command reaches it yet
  agent-bridge-conductor (100.123.176.12)    the always-on Linux box: `card agent-box`
  YANA's S25+ (100.68.147.84)                `card yana-phone`
  Pixel 11 (100.72.227.33)                   this phone

Which adb target to use
  deb bash /root/agent-bridge/scripts/transport.sh ensure      prints the live target for this phone and heals
                                                               the connection when it has dropped
  A plain `adb shell` with no -s fails here: "adb: more than one device/emulator". Always name the device.

Known failure
  "device offline" or "Connection refused" for a 100.x address: that device is asleep or off the private
  network. `tailscale-devices` shows which ones are online.
