# hidden-screens — screens only the agent sees: make one, open an app on it, look, tap, type, keep it alive

Runs on: the Debian side. The code is /root/hidden-operator (also at ~/hidden-operator on the Termux side).
Use these paths. The older copies in /root/agent-bridge/scripts fail here ("adb: more than one device").
George's real screen does not change. Checked 2026-11-19: screens "apps" (id 3) and "web" (id 4) are UP.

One door for all of it
  deb bash /root/hidden-operator/bin/op                  prints the verbs: screen drive map teach sms keeper web learn browse
  deb bash /root/hidden-operator/bin/op screen list      name, id, UP or DOWN
  deb bash /root/hidden-operator/bin/op keeper status    each screen, and "watch: ALIVE" when the keeper loop runs

The screen itself (H = deb bash /root/hidden-operator/scripts/hidden_display.sh ; write it out in full)
  H list | H status -n NAME | H id -n NAME               every screen | one screen | its display number
  H start -n NAME phone                                  make one (1080x2400). Also: tablet, or W H DPI
  H start -n tall 1080 6000 420                          a tall screen: an app lays out six screens of rows at once
  H launch -n NAME PACKAGE/ACTIVITY                      open an app on it
  H shot -n NAME /sdcard/Download/hidden.png             one picture
  H grid -n NAME 200 /sdcard/Download/grid.png           the picture with a numbered grid; the numbers are tap points
  H zoom -n NAME 160 1580 130 4                          a close look around one point; run grid first, or it says "no frame"
  H tap -n NAME X Y | H swipe -n NAME X1 Y1 X2 Y2 | H text -n NAME 'words' | H key -n NAME 66
  H ensure -n NAME                                       bring a dead screen back with its app
  H stop -n NAME | H stopall                             close one | close every hidden screen
  H reap                                                 frees a phone whose screen readers are stuck
  The `screen` command does the same looks and taps and shows the picture to the model: `card screen`.

By button name (the name reader)
  deb bash /root/hidden-operator/scripts/hidden_drive.sh open NAME PACKAGE/ACTIVITY
  ... hidden_drive.sh do NAME 'Button text' | seq NAME 7 plus 8 | type NAME 'words' | key NAME 66 | read NAME
  bash ~/hidden-operator/scripts/read_all.sh -n NAME 3 --buttons      scroll and read a whole list (Termux side only)
  deb python3 /root/hidden-operator/scripts/app_map.py show NAME      the saved map of an app's screens
      also: snap NAME | tap NAME 'Button' | explore NAME 20 | goto NAME 'words'. Maps: /root/.hidden-maps (3 saved).
  deb bash /root/hidden-operator/scripts/teach_skill.sh list          taught picture skills -> "(no skills)"
      also: new NAME | tap NAME X Y | steps NAME | replay NAME | drop NAME

Texts and login codes (reads only)
  deb bash /root/hidden-operator/scripts/read_sms_code.sh latest 5    time, sender, first words
  deb bash /root/hidden-operator/scripts/read_sms_code.sh code        the newest login code
  deb bash /root/hidden-operator/scripts/read_sms_code.sh wait 120    waits for a new text that brings a code

The keeper
  bash ~/hidden-operator/scripts/hidden_supervisor.sh status          screens and the watch loop
  bash ~/hidden-operator/scripts/hidden_supervisor.sh boot | stop     start the loop | stop it. Timer 7733 restarts it.

The browser on the screen "web": `card phone-browser` and `card web-hands`.

Known failure (checked 2026-11-19, Pixel 11, Android 17)
  The name reader does not answer: `hidden_drive.sh read web` prints nothing and read_all.sh reads 0 rows.
  Drive by picture: grid, zoom, tap. Two `hidden_display.sh ensure` calls sat stuck for hours that day
  trying to restart the reader.
