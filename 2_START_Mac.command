#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Please run 1_INSTALL_Mac.command first."
  read -p "Press Enter to close..."
  exit 1
fi
.venv/bin/python -m lingua
