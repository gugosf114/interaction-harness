# apps — install, update, remove, switch off and on, open, permissions and default apps on the Pixel 11

Runs on: the Termux side. Each command goes through adb (127.0.0.1:5555), or through Shizuku when adb does
not answer. Add --via adb or --via shizuku to pick the door. Each command family was checked both ways on 2026-11-11. Default-link writes used the scratch app; the browser role was set to its existing holder.

Look
  app list                      the apps George installed: package  version  (code)
  app list chrome               only names that hold "chrome"; --all adds the system apps
  app info PACKAGE              version, target SDK, on or off, installer, install and update times, path
  app perms PACKAGE             every permission it asks for: name, kind (install, runtime, special), granted yes/no
  app front                     the app in front on George's visible screen and on each hidden screen
  app default browser           the app that holds a role: browser, dialer, sms, home, assistant
  app default example.com       the apps that can open that domain's links, and whether each opens them itself

Change (each acts on the phone at once)
  app install FILE.apk          or a link: app install https://f-droid.org/repo/NAME_CODE.apk
      Prints "installed PACKAGE VERSION (CODE)". Replaces an older copy and keeps its data.
  app update FILE_OR_LINK       the same, only for an app already installed: "updated PACKAGE: OLD -> NEW"
  app uninstall PACKAGE         removes the app and its data
  app disable PACKAGE           switches the app off (its icon goes away); app enable PACKAGE switches it on
  app stop PACKAGE              force-stops it
  app clear PACKAGE             deletes all of the app's data and sign-ins
  app open PACKAGE              opens it on George's visible screen
  app open PACKAGE --hidden NAME   opens it on a hidden screen (card phone starts one); --display ID by number
  app grant PACKAGE CAMERA      grants a permission; app revoke PACKAGE CAMERA takes it away
      A short name means android.permission.NAME. Prints "granted=true" or "granted=false".
  app default browser PACKAGE   makes PACKAGE the browser (also dialer, sms, home, assistant)
  app default example.com PACKAGE      PACKAGE opens example.com links; add "off" at the end to stop that

Facts
  Exit 0 when it worked, 1 when the phone refused (the phone's own words follow), 2 for wrong arguments.
  Through Shizuku the command's output is read from files: Android refuses a pipe or a /sdcard file as the
  output of pm and the other cmd services ("Failed transaction"), so app writes to /data/local/tmp first.
  Downloads and copies of APKs wait in /sdcard/Download/.app-install and are removed after the install.
  Reading an APK's package name uses apkinfo on the Debian side.

Known failure
  "app: Shizuku answers Server is not running": see card shizuku. --via adb still works.
