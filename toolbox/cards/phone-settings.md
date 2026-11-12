# phone-settings — volume, brightness, Wi-Fi, Bluetooth, airplane mode, do-not-disturb, battery, screen timeout, permissions

Each `rish -c '...'` line goes through Shizuku. The adb twin is: adb -s 127.0.0.1:5555 shell '...'
rish prints some answers on stderr: add 2>&1 when you read one.

Volume
  media-volume               -> "media volume: 40% (10 of 25)"
  media-volume 55            sets the media volume to 55 percent at once
  termux-volume              every stream as JSON: call, system, ring, music, alarm, notification
  termux-volume ring 5       sets one stream to a level (not a percent)

Brightness
  rish -c 'settings get system screen_brightness'        0 to 255
  termux-brightness 120      sets it at once (0 to 255, or: auto)

Wi-Fi
  rish -c 'cmd wifi status' 2>&1 | head -4               "Wifi is enabled" and: Wifi is connected to "NAME"
  termux-wifi-connectioninfo                             ip, link speed, signal; the name shows as unknown here
  termux-wifi-scaninfo                                   networks in range
  rish -c 'svc wifi enable'  ;  rish -c 'svc wifi disable'       turns Wi-Fi on or off at once

Bluetooth
  rish -c 'settings get global bluetooth_on'             1 is on
  rish -c 'dumpsys bluetooth_manager' 2>&1 | grep -A12 'Bonded devices'      the paired devices
  rish -c 'cmd bluetooth_manager enable'  ;  rish -c 'cmd bluetooth_manager disable'      on or off at once
  Connect a paired device: Android has no shell command for it. Open the device list on a hidden screen
  and tap the device's name there (`card screen` taps by picture):
  deb bash /root/hidden-operator/scripts/hidden_display.sh start -n bt phone
  deb bash /root/hidden-operator/scripts/hidden_display.sh launch -n bt 'com.android.settings/.Settings$ConnectedDeviceDashboardActivity'

Airplane mode
  rish -c 'cmd connectivity airplane-mode'               enabled or disabled
  rish -c 'cmd connectivity airplane-mode enable'        cuts every radio at once (disable turns it off)

Do-not-disturb
  rish -c 'settings get global zen_mode'                 0 off, 1 priority only, 2 total silence, 3 alarms only
  rish -c 'cmd notification set_dnd priority'            on | priority | alarms | off

Battery
  termux-battery-status                                  percentage, temperature in C, status, plugged, health
  rish -c 'dumpsys battery' 2>&1 | grep -E 'level|temperature'       temperature in tenths of a degree
  rish -c 'dumpsys batterystats --charged' 2>&1 | sed -n '/Estimated power use/,/^$/p' | head -40
      mAh since the last full charge; one "UID u0a344: 446 ..." line per app
  rish -c 'pm list packages -U' 2>&1 | grep 10344        the app behind UID u0a344 (10000 + 344)

Screen timeout
  rish -c 'settings get system screen_off_timeout'       milliseconds
  rish -c 'settings put system screen_off_timeout 600000'      sets it to 10 minutes

App permissions
  rish -c 'dumpsys package PACKAGE' 2>&1 | grep -A30 'runtime permissions'
  rish -c 'pm grant PACKAGE android.permission.CAMERA'   grants it at once
  rish -c 'pm revoke PACKAGE android.permission.CAMERA'  takes it away at once

Known failure
  rish answers "Server is not running" when Shizuku is down: see `card shizuku`. The adb twin still works.
