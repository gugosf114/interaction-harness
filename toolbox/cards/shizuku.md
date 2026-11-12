# shizuku — the second door into the phone, for when adb's port has dropped

What it is
  Shizuku is an app that keeps a helper running at shell rights (uid 2000), the same rights adb has.
  It needs no adb connection and no network port. When 127.0.0.1:5555 is dead, this door is still open.

Run a command through it (Termux side)
  rish -c 'getprop ro.build.version.release'         -> 17
  rish -c 'id'                                       -> uid=2000(shell) ...
  rish -c 'input tap 540 1200'                       This taps George's visible screen at once.
  rish -c 'settings get global airplane_mode_on'
  Everything the command prints comes out on stdout. The exit code is the command's own.
  The files behind it are ~/rish and ~/rish_shizuku.dex. The rish on the path wraps them and
  passes each answer through the folder /sdcard/.rish.

George's helper script (Debian side)
  deb bash /root/agent-bridge/scripts/shizuku.sh status        "backend : LIVE (uid 2000)"
  deb bash /root/agent-bridge/scripts/shizuku.sh available     exit 0 when the door works
  deb bash /root/agent-bridge/scripts/shizuku.sh shell 'getprop ro.build.version.release'
  deb bash /root/agent-bridge/scripts/shizuku.sh tap 540 1200          taps the visible screen
  deb bash /root/agent-bridge/scripts/shizuku.sh text 'words'          types into the focused field
  deb bash /root/agent-bridge/scripts/shizuku.sh key 66                sends a key code (66 is Enter, 4 is Back)
  deb bash /root/agent-bridge/scripts/shizuku.sh dump                  writes the screen's node tree to a file on the phone
  deb bash /root/agent-bridge/scripts/shizuku.sh pull /sdcard/file.txt ~/file.txt        copies a phone file out

Is the helper alive
  adb -s 127.0.0.1:5555 shell pidof shizuku_server             a number means it runs
  Everything that reads or sets phone settings through it is on `card phone-settings`.

Bring it back
  sh ~/bin/shizuku_keeper.sh once                    one look: starts the helper again when adb is up
  sh ~/.termux/boot/heal-adb-shizuku                 the full boot heal: reopens adb 5555, then starts Shizuku
  Log: ~/.agent-bridge/heal.log

Known failure
  "Server is not running": the first call after a quiet spell can say this while the helper is alive,
  so rish tries three times by itself. When it still says so, the helper died. It dies whenever
  Android restarts adb's own service. Run the keeper line above, wait a few seconds, and try again.
