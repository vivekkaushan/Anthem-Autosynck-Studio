#!/bin/bash
# Double-click to launch AutoSync Studio on macOS. First run creates a private Python environment.
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.autosync-venv"
# PySide6 needs a released Python (3.12 - 3.13). Prefer those over a brand-new system Python.
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
[ -z "$PY" ] && { echo "Python 3.12+ not found. Run: brew install python@3.13"; read -r -p "Press Return"; exit 1; }
if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating environment with $PY ..."
  "$PY" -m venv "$VENV" || { read -r -p "venv failed. Press Return"; exit 1; }
fi
if ! "$VENV/bin/python" -c "import PySide6, numpy, scipy, soundfile" >/dev/null 2>&1; then
  echo "Installing requirements (first run only) ..."
  "$VENV/bin/pip" install -q -r requirements.txt || { read -r -p "pip failed. Press Return"; exit 1; }
fi
command -v ffmpeg >/dev/null 2>&1 || echo "Note: FFmpeg not found on PATH (brew install ffmpeg)"
exec "$VENV/bin/python" main.py
