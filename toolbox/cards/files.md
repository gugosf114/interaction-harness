# files — read, search, write and edit files on this phone

Runs on: the Termux side. Both sides see /data/data/com.termux/files/home/... and /sdcard/... at the same paths.
Debian's own home is /root. Reach it with `deb`, or from the Termux side at
/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs/root/...

Read a slice
  sed -n '40,80p' FILE            lines 40 to 80
  head -c 2000 FILE               first 2,000 characters
  tail -n 50 FILE ; wc -l FILE    the end ; the line count
  deb sed -n '1,60p' /root/FILE   a file in Debian's home

Search
  rg -n 'PATTERN' FOLDER_OR_FILE  matching lines with file name and line number
  rg -l 'PATTERN' FOLDER          only the names of files that match
  rg --files FOLDER | rg 'NAME'   find a file by its name
  deb rg -n 'PATTERN' /root/FOLDER

Write a new file
  set -C; cat > FILE <<'END'
  first line
  second line
  END
  Prints nothing when it works. `set -C` makes the shell refuse to replace a file that exists:
  "cannot overwrite existing file", exit 1.

Edit: exact replace
  edit-exact FILE 'OLD TEXT' 'NEW TEXT'
  Replaces OLD with NEW only when OLD appears exactly once in FILE.
  Works:    "Replaced 1 occurrence in FILE, at line N."  exit 0
  Refuses:  "OLD was not found in FILE. Nothing was written."  exit 1
            "OLD appears 3 times in FILE. It must appear exactly once. Nothing was written."  exit 1
  OLD and NEW may span lines. The file keeps its permissions. The write is all or nothing.

Known failure
  A `cd` in one command does not carry to the next: each command gets its own shell. Use full paths.
  The model sees at most 8,000 characters of each output stream; the middle of longer output is cut.
  Read long files in slices.
