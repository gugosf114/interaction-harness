#!/data/data/com.termux/files/usr/bin/sh
# toolbox/install.sh : put the toolbox commands on the Termux path. Safe to run again.
# Each command becomes a link in $PREFIX/bin that points back into this folder, so a git pull updates it.
set -eu
here=$(dirname "$(readlink -f "$0")")
bin=${PREFIX:-/data/data/com.termux/files/usr}/bin
status=0
for f in "$here"/bin/*; do
  name=$(basename "$f")
  chmod +x "$f"
  if [ -e "$bin/$name" ] && [ ! -L "$bin/$name" ]; then
    echo "SKIPPED $name: $bin/$name exists and is not a link." >&2; status=1; continue
  fi
  ln -sfn "$f" "$bin/$name"
  echo "linked $name -> $f"
done
exit $status
