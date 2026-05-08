#!/usr/bin/env bash
# TAKE 6 — streaming token effects (decrypt, nier, zalgo)
source "$(dirname "$0")/_lib.sh"

echo "=== TAKE 6: streaming token effects ==="
echo "Focus kitty window. Press Enter when ready."
read -r

clear
cd /home/xush/.hermes
countdown 3 "starting recording"
obs_toggle

"$PYTHON" demo_stream_effects_v3.py decrypt nier zalgo --delay 0.04 --pause 0.5
cd "$REPO"

hold 1 "settling"
obs_toggle

sleep 1
rename_latest "take6.mkv"
