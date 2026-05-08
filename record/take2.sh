#!/usr/bin/env bash
# TAKE 2 — 4 streaming token effects animating in parallel.
# Side-by-side panels via demo_stream_quad.py — distinct from take6's
# sequential decrypt/nier/zalgo run.
source "$(dirname "$0")/_lib.sh"

EFFECTS=(shimmer glitch_morph cosmic gradient_tail)

echo "=== TAKE 2: streaming effects (4-up parallel) ==="
echo "    effects: ${EFFECTS[*]}"
echo
echo "Focus kitty window. Press Enter when ready."
read -r

clear
cd /home/xush/.hermes
countdown 3 "starting recording"
obs_toggle

"$PYTHON" demo_stream_quad.py "${EFFECTS[@]}" --delay 0.07 --settle 1.2 --cycles 2
cd "$REPO"

hold 1 "settling"
obs_toggle
echo "    stopped recording"

sleep 1
rename_latest "take2.mkv"
