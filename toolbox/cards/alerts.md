# alerts — put a notification on George's phone

Runs on: the Termux side (Termux:API).

Show a notification
  termux-notification --title 'TITLE' --content 'TEXT'
  This shows on the phone at once.
  --id 4101                 give it a number, so a later call with the same number replaces it
  --priority max            max | high | default | low | min
  --sound                   play the notification sound
  --ongoing                 pin it until it is removed
  --button1 'Open' --button1-action 'termux-open-url https://example.com'
  termux-notification --help lists every option.

Remove one
  termux-notification-remove 4101

A short pop-up on the screen
  termux-toast 'TEXT'

Other phone signals
  termux-vibrate -d 400                     vibrate for 400 ms
  termux-clipboard-set 'TEXT'               put text on the clipboard
  termux-clipboard-get                      read the clipboard
  termux-open-url 'https://example.com'     open a page on George's visible screen
  termux-battery-status                     JSON: percentage, status; changes nothing

Known failure
  termux-notification-list does not answer on this phone (no reply in 40 seconds, checked 2026-11-11).
  Do not use it to read notifications.
