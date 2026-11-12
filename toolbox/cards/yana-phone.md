# yana-phone — Yana's Galaxy S25+ over Tailscale (100.68.147.84)

What is reachable (checked 2026-11-11: both doors answered, model SM-S936U)
  Her Termux shell over ssh, and adb over the network. Commands here run on Yana's phone.

Run a command in her Termux
  deb ssh -i /root/.ssh/yana/yana_key -p 8022 u0_a657@100.68.147.84 'COMMAND'
  Example: deb ssh -i /root/.ssh/yana/yana_key -p 8022 u0_a657@100.68.147.84 'getprop ro.product.model'

adb
  deb adb connect 100.68.147.84:5555
  deb adb -s 100.68.147.84:5555 shell getprop ro.product.model
  deb bash -c 'adb -s 100.68.147.84:5555 exec-out screencap -p > /sdcard/Download/yana-screen.png'
  The last line saves a picture of what is on her screen.

What her phone holds, from the notes
  Termux, Termux:API, a Debian install with Claude Code on George's account, the PayPal live key file,
  the bakery website deploy key, SMS and contacts through Termux:API, and `say` with a Russian voice.
  Yana types plain English to her Claude. She does not type commands.

The notes
  deb cat /root/.claude/projects/-root/memory/yana-phone.md
  deb cat /root/.claude/projects/-root/memory/yana-texts-work-queue.md

Known failure
  "Connection timed out": her phone is asleep or off Tailscale. Tailscale on her phone must be on.
