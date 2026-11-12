# phone-hardware — sensors, location, camera, microphone, torch, texts, calls, contacts and dialogs (Termux:API)

Runs on: the Termux side. Each command talks to the Termux:API app on the phone.

Read
  termux-sensor -l                                  the 37 sensors by name
  termux-sensor -s 'Light' -n 1                     one reading from the sensors whose name holds "Light"
  termux-location -p network -r last                latitude, longitude, accuracy (-p gps -r once asks for a fresh fix)
  termux-camera-info                                camera 0 is the back one, camera 1 the front one
  termux-audio-info                                 sample rates; whether a headset or Bluetooth audio is connected
  termux-contact-list                               every contact as JSON: name, number
  termux-call-log -l 10                             the last ten calls
  termux-telephony-deviceinfo                       carrier and SIM state (every field is null on this phone)
  termux-microphone-record -i                       is a recording running
  termux-media-player info                          the track that is playing
  termux-usb -l                                     attached USB devices
  termux-keystore list                              keys in the Android keystore
  termux-tts-engines                                the phone's own voices
  termux-infrared-frequencies                       empty here: this phone has no infrared sender
  termux-saf-dirs                                   folders George has opened to Termux (none so far)

Act
  termux-torch on  ;  termux-torch off              the flashlight, at once
  termux-camera-photo -c 0 /sdcard/Download/photo.jpg       takes a photo with the back camera
  termux-microphone-record -f /sdcard/Download/note.m4a -l 10       records 10 seconds of sound (-q stops early)
  termux-media-player play /sdcard/Download/song.mp3        plays out loud (pause | stop)
  termux-sms-send -n +14155551234 'TEXT'            This sends a real text message at once.
  termux-telephony-call +14155551234                This places a real phone call at once.
  termux-dialog confirm -t 'TITLE' -i 'QUESTION'    shows a box on George's screen and prints his answer as JSON
  termux-dialog text -t 'TITLE'                     asks him to type; other kinds: checkbox, radio, date, time, sheet
  termux-toast 'TEXT'                               a short pop-up on his screen
  termux-share /sdcard/Download/file.pdf            opens Android's share sheet on his screen
  termux-download -t 'TITLE' 'https://example.com/file.zip'       hands a download to Android's download manager
  termux-wallpaper -f /sdcard/Download/picture.jpg  sets the home screen wallpaper (-l for the lock screen)
  termux-fingerprint                                asks George to touch the fingerprint sensor; prints the result
  termux-nfc -r short                               reads an NFC tag held to the phone
  termux-saf-managedir                              asks George to pick a folder to open to Termux
  termux-speech-to-text                             listens once and prints what was said
  termux-wifi-enable true                           Wi-Fi on (false for off); see `card phone-settings`

More
  Volume, brightness, Wi-Fi, Bluetooth, battery: `card phone-settings`. Notifications and vibration: `card alerts`.
  Reading texts: `card phone`. Speaking out loud: `card voice`. Every command prints its options with -h.

Known failure
  A command that hangs with no output means the Termux:API app lacks that permission.
  `rish -c 'dumpsys package com.termux.api' | grep -A30 'runtime permissions'` shows what is granted.
