# phone — see and drive George's Pixel 11, the phone this runs on

Screenshot of the real screen
  deb shot /sdcard/Download/screen.png
  Prints the path. The file is a PNG. Always give a path: the built-in default path no longer exists.

Read texts (SMS)
  termux-sms-list -l 20
  JSON list, one object per message: number, received, body, type. `termux-sms-list -h` lists the filters.

Read the screen as words (the on-phone bridge, port 8080)
  ~/.local/bin/agentbridge-call android_get_screen_state '{}'
  deb phone-link                 says "phone link UP" or reopens the bridge

adb (device 127.0.0.1:5555 is this phone)
  adb -s 127.0.0.1:5555 shell getprop ro.product.model        -> Pixel 11
  adb devices                                                 also lists the Z Flip 7 and Yana's phone
  adb -s 127.0.0.1:5555 shell input tap X Y                   This taps George's visible screen at once.
  adb -s 127.0.0.1:5555 shell am start -n PACKAGE/ACTIVITY    This opens an app on George's visible screen.

Hidden screens: a screen only the agent sees. George's real screen does not change.
  H=/root/hidden-operator/scripts/hidden_display.sh   (write the full path in each command)
  deb bash /root/hidden-operator/scripts/hidden_display.sh list                    name, id, UP or DOWN
  deb bash /root/hidden-operator/scripts/hidden_display.sh start -n NAME phone     make one (or: tablet)
  deb bash /root/hidden-operator/scripts/hidden_display.sh launch -n NAME PACKAGE/ACTIVITY
  deb bash /root/hidden-operator/scripts/hidden_display.sh shot -n NAME /sdcard/Download/hidden.png
  deb bash /root/hidden-operator/scripts/hidden_display.sh tap -n NAME X Y
  deb bash /root/hidden-operator/scripts/hidden_display.sh text -n NAME 'words'
  deb bash /root/hidden-operator/scripts/hidden_display.sh stop -n NAME
  The screen named "web" holds the signed-in Chrome: see `card phone-browser`.

The AI that phones a place for George (phone-do, phone-ask): see `card calls`.
Full how-to: deb cat /root/.claude/device-control.md

Known failure
  `deb phone-do` and `deb phone-ask` answer "command not found": their links in /usr/local/bin point
  at a folder that is gone. The full paths in `card calls` work.
