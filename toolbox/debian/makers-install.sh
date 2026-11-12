#!/bin/bash
# makers-install.sh : install the pinned Python libraries behind make-docx, make-xlsx, make-pptx, make-pdf and read-doc.
# Run it on the Debian side:  deb bash ~/interaction-harness/toolbox/debian/makers-install.sh
# Safe to run again: with every pin in place it downloads nothing and changes nothing.
# Everything goes into one private folder. Debian's own Python packages are read, never changed.
set -eu
venv=${HARNESS_MAKERS_VENV:-/root/.local/share/harness-makers/venv}
here=$(dirname "$(readlink -f "$0")")
pins=$(cat "$here/../makers-requirements.lock")
if [ "${1:-}" = --pins ]; then printf '%s' "$pins" | sed '/^$/d'; exit 0; fi
if [ ! -x "$venv/bin/python" ]; then
  mkdir -p "$(dirname "$venv")"
  # A private environment keeps the SDK and office dependencies separate.
  python3 -m venv "$venv"
  echo "made $venv"
fi
if python3 "$here/makers_common.py" >/dev/null 2>&1; then
  echo "every pin is in place: nothing to install"
else
  # shellcheck disable=SC2086
  "$venv/bin/python" -m pip install --disable-pip-version-check --no-input --ignore-installed $pins
fi
python3 "$here/makers_common.py"
