#!/usr/bin/env bash
# TAKE 13 — same composer state across multiple skins (flicker montage)
# Usage: ./take13_skin.sh <skin>
# Run once per skin: matrix, charizard, poseidon, ares, tokyo-night, solarized-dark
source "$(dirname "$0")/_lib.sh"

SKIN="${1:?Usage: $0 <skin>}"
PROMPT="build a generative p5.js sketch where particles trace a"

echo "=== TAKE 13 [$SKIN]: composer flicker shot ==="
echo "Will launch hermes with skin=$SKIN, type prompt, hold 3s, quit."
echo "Focus kitty window. Press Enter when ready."
read -r

# Launch hermes in this terminal
HERMES_SKIN="$SKIN" hermes &
HPID=$!

echo "    waiting 6s for TTE + startup..."
sleep 6

countdown 2 "starting recording — type begins immediately"
obs_toggle

# Type the prompt slowly into the focused composer
type_slow "$PROMPT" 60

hold 3 "holding cursor blink on prompt"

obs_toggle
echo "    stopped recording"

# Quit hermes
press "ctrl+q"
sleep 1
kill "$HPID" 2>/dev/null
wait "$HPID" 2>/dev/null

rename_latest "take13_${SKIN}.mkv"
