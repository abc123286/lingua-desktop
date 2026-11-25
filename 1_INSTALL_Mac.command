#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  LINGUA Desktop - one-time install (Mac)"
echo "============================================"
PY=""
for c in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys,tkinter; assert sys.version_info[:2]==(3,12) and tkinter.TkVersion>=8.6" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo
  echo "Python 3.12 from python.org is needed (Apple's built-in Python is too old)."
  echo "Install Python 3.12 from https://www.python.org/downloads/macos/ then run this again."
  read -p "Press Enter to close..."
  exit 1
fi
"$PY" -m venv .venv || { echo "Could not create .venv"; read -p "Press Enter..."; exit 1; }
echo "Installing parts (this takes a few minutes)..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt || { echo "Install failed. Check your internet."; read -p "Press Enter..."; exit 1; }
chmod +x "2_START_Mac.command"
echo
echo "Done! Now double-click 2_START_Mac.command"
echo "Also install BlackHole 2ch and 16ch (free): https://existential.audio/blackhole/"
read -p "Press Enter to close..."
