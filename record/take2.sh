#!/usr/bin/env bash
# TAKE 2 — TTE montage (5 effects in one take)
source "$(dirname "$0")/_lib.sh"

echo "=== TAKE 2: TTE montage (5 effects) ==="
echo "Will play: beams, burn, waves, laseretch, vhstape"
echo
echo "Focus kitty window. Press Enter when ready."
read -r

countdown 3 "starting recording"
obs_toggle

clear
python /home/xush/.hermes/demo_tte.py beams burn waves laseretch vhstape --pause 0.4 --fps 60

hold 1 "settling"
obs_toggle
echo "    stopped recording"

sleep 1
rename_latest "take2.mkv"
