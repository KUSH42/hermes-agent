#!/usr/bin/env bash
# TAKE 8 — syntax highlighting
source "$(dirname "$0")/_lib.sh"

echo "=== TAKE 8: syntax highlighting ==="
echo "Focus kitty window. Press Enter when ready."
read -r

countdown 3 "starting recording"
obs_toggle

clear
cd /home/xush/.hermes
python demo_syntax.py
cd "$REPO"

hold 4 "letting it sit on screen"
obs_toggle

sleep 1
rename_latest "take8.mkv"
