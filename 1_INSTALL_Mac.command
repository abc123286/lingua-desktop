#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  LINGUA Desktop - one-time install (Mac)"
echo "============================================"
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo
  echo "Python 3 (with Tkinter) is needed."
  echo "Install Python 3.12 from https://www.python.org/downloads/macos/ then run this again."
  read -p "Press Enter to close..."
  exit 1
fi
python3 -m venv .venv || { echo "Could not create .venv"; read -p "Press Enter..."; exit 1; }
echo "Installing parts (this takes a few minutes)..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt || { echo "Install failed. Check your internet."; read -p "Press Enter..."; exit 1; }
chmod +x "2_START_Mac.command"
echo
echo "Done! Now double-click 2_START_Mac.command"
echo "Also install BlackHole 2ch and 16ch (free): https://existential.audio/blackhole/"
read -p "Press Enter to close..."
