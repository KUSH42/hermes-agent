#!/usr/bin/env bash
# TAKE 1 — Skin startup montage (6 skins, single continuous recording)
# Each skin's own startup TTE plays back-to-back. Edit cuts later.
source "$(dirname "$0")/_lib.sh"

# Order chosen for visual contrast: bold first, then warm/cool/neutral mix.
SKINS=(matrix charizard poseidon ares hermes tokyo-night)

# Per-skin hold (seconds): ~2s hermes boot + ~4s TTE (240 frames @ 60fps) + 3s settled banner dwell.
HOLD_S=12.5

# Gap between skins (seconds). Long enough to make cut points obvious.
GAP_S=1

echo "=== TAKE 1: skin startup montage (${#SKINS[@]} skins) ==="
echo "    skins: ${SKINS[*]}"
echo "    per-skin hold: ${HOLD_S}s · gap: ${GAP_S}s"
echo "    total raw: ~$(( (HOLD_S + GAP_S) * ${#SKINS[@]} ))s"
echo
echo "Focus kitty window. Press Enter when ready."
read -r

countdown 3 "starting recording"
obs_toggle

for skin in "${SKINS[@]}"; do
    # blank the terminal silently — no text before hermes alt-screen kicks in
    printf '\033[2J\033[H' >/dev/tty
    HERMES_SKIN="$skin" hermes </dev/tty >/dev/tty 2>/dev/tty &
    HPID=$!
    sleep "$HOLD_S"
    # quit cleanly so terminal state stays sane for next skin
    xdotool key ctrl+q
    sleep 0.4
    kill "$HPID" 2>/dev/null
    wait "$HPID" 2>/dev/null
    # restore terminal: full reset flushes any buffered TTE frames
    printf '\033c\033[?1049l\033[?25h' >/dev/tty
    stty sane 2>/dev/null
    sleep "$GAP_S"
done

hold 1 "letting last frame settle"
obs_toggle
echo "    stopped recording"

sleep 1
rename_latest "take1.mkv"
