#!/usr/bin/env bash
# TAKE 1 — Skin startup montage (6 skins, single continuous recording)
# Each skin's own startup TTE plays back-to-back. Edit cuts later.
source "$(dirname "$0")/_lib.sh"

# Order chosen for visual contrast: bold first, then warm/cool/neutral mix.
SKINS=(matrix charizard poseidon ares hermes tokyo-night)

# Per-skin hold (seconds). Each skin's TTE wall ranges 1.5-3s; 6s leaves room
# for slow effects (vhstape, burn) plus a beat of the settled banner.
HOLD_S=6

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
    clear
    echo ">>> skin=$skin"
    HERMES_SKIN="$skin" hermes </dev/tty >/dev/tty 2>/dev/tty &
    HPID=$!
    sleep "$HOLD_S"
    # quit cleanly so terminal state stays sane for next skin
    xdotool key ctrl+q
    sleep 0.4
    kill "$HPID" 2>/dev/null
    wait "$HPID" 2>/dev/null
    # restore terminal: exit alt-screen, reset attributes, sane mode
    printf '\033[?1049l\033[0m\033[?25h'
    stty sane 2>/dev/null
    sleep "$GAP_S"
done

hold 1 "letting last frame settle"
obs_toggle
echo "    stopped recording"

sleep 1
rename_latest "take1.mkv"
