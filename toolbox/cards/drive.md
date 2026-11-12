# drive — Google Drive for each account: list and search files, read one, upload one

NAME is an account name from `google-accounts` (see `card mail`).
Type each command as written, with no deb in front.

List and search
  google-drive NAME list                 the 10 files changed most recently:
                                         "  FILE_ID | 2026-11-10 14:22 | document | 1024 | File name"
  google-drive NAME list 30              30 files
  google-drive NAME list 10 'tax return' files whose name or text holds those words
      The type is document, spreadsheet, presentation, folder, pdf, or the file's own kind. Size is in bytes.

Read one
  google-drive NAME read FILE_ID         prints the text. A Google document or slide deck comes as plain text,
                                         a spreadsheet as CSV (its first sheet).
  google-drive NAME read FILE_ID /FULL/PATH/out
                                         saves the file's bytes there. Use this for a PDF or a picture.

Upload one
  google-drive NAME create /FULL/PATH/file 'TITLE'
      This puts a real new file in that account's Drive at once. Without TITLE it keeps the file's own name.
      Prints: created: FILE_ID | name | link

  A path under /data/data/com.termux/files/home or /sdcard is the same file on the Termux and Debian sides.

Where the keys live
  /root/.gmail/accounts/NAME.json, written by google-signin.

Known failure
  "drive is not allowed yet": that account has no drive sign-in. google-signin NAME opens Google's page on
  George's screen, and George taps Allow.
  "is not text": the file is a PDF, a picture or another binary kind. Give a path to save it.
  "is a folder": list or search for the files inside it.
