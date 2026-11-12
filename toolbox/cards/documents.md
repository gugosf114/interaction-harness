# documents — make a PDF, make a QR code, download a video, put a file in Downloads

PDF from text (Termux command; the page is drawn by weasyprint on the Debian side)
  text-pdf /sdcard/Download/NAME.pdf 'THE TEXT'
  printf 'line one\nline two\n' | text-pdf /sdcard/Download/NAME.pdf
  Prints the path and the size: "/sdcard/Download/NAME.pdf  3224 bytes". Letter page, one-inch margins.
  The output path must be under the Termux home folder or under /sdcard.

PDF from an HTML file (your own layout)
  deb weasyprint /FULL/PATH/in.html /FULL/PATH/out.pdf

Read the text of a PDF
  deb pdftotext /FULL/PATH/file.pdf -

QR code
  deb bash -c 'qr "TEXT OR URL" > /sdcard/Download/code.png'
  Not working on this phone (checked 2026-11-11):
  "ModuleNotFoundError: No module named 'qrcode'". The Python module qrcode is missing on the Debian side.

Download a video (yt-dlp 2026.10.26, Debian side)
  deb yt-dlp -F 'URL'                                            list the formats, download nothing
  deb yt-dlp -o '/sdcard/Download/%(title)s.%(ext)s' 'URL'       download into Downloads
  Prints progress lines, then the saved file name.

Put a file in Downloads
  cp /FULL/PATH/FILE /sdcard/Download/
  ls -lt /sdcard/Download | head
  /sdcard/Download is the Downloads folder George opens on the phone. Both sides can read and write it.

Known failure
  text-pdf prints the weasyprint error and exits non-zero when the output folder does not exist.
  Make the folder first, or write to /sdcard/Download.
