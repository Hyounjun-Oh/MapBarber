#!/usr/bin/env bash
# Opens MapBarber. The first run creates a private virtual environment next to this
# script and installs the dependencies; later runs start immediately.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
VENV="$HERE/.venv"
PYTHON="${PYTHON:-python3}"
STAMP="$VENV/.requirements"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "mapbarber: $PYTHON was not found; install Python 3.9 or newer" >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "mapbarber: first run, creating $VENV ..."
  if ! "$PYTHON" -m venv "$VENV"; then
    echo "mapbarber: could not create a virtual environment (on Debian/Ubuntu: sudo apt install python3-venv)" >&2
    rm -rf "$VENV"
    exit 1
  fi
fi

if ! cmp -s "$HERE/requirements.txt" "$STAMP" 2>/dev/null; then
  echo "mapbarber: installing dependencies ..."
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r "$HERE/requirements.txt"
  cp "$HERE/requirements.txt" "$STAMP"
fi

# VTK's Qt widget needs an X11 surface; under Wayland, run through XWayland.
if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi

export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m mapbarber "$@"
