#!/usr/bin/env bash
# TAKE 7 — drawbraille animation engines
source "$(dirname "$0")/_lib.sh"

echo "=== TAKE 7: drawbraille engines ==="
echo "Focus kitty window. Press Enter when ready."
read -r

clear
cd "$REPO"
countdown 3 "starting recording"
obs_toggle

"$PYTHON" scripts/demo_anim.py \
    --engines aurora_ribbon,plasma,matrix_rain \
    --gradient \
    --color "#ff0050" --color2 "#00ffcc" \
    --duration 7 --fps 30

hold 1 "settling"
obs_toggle

sleep 1
rename_latest "take7.mkv"
