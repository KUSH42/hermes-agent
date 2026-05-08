#!/usr/bin/env bash
# TAKE 1 — Skin startup montage. One MKV per skin.
# Each skin's own startup TTE plays, recorded to its own file.
source "$(dirname "$0")/_lib.sh"

# Order chosen for visual contrast: bold first, then warm/cool/neutral mix.
SKINS=(matrix charizard poseidon ares hermes tokyo-night)

# Per-skin hold (seconds): ~2s hermes boot + ~6s TTE (360 frames @ 60fps) + 3s settled banner dwell.
HOLD_S=15

# Gap between recordings (seconds).
GAP_S=2

echo "=== TAKE 1: skin startup montage (${#SKINS[@]} skins, one MKV each) ==="
echo "    skins: ${SKINS[*]}"
echo "    per-skin hold: ${HOLD_S}s · gap: ${GAP_S}s"
echo
echo "Focus kitty window. Press Enter when ready."
read -r

countdown 3 "starting"

for skin in "${SKINS[@]}"; do
    echo
    echo ">>> recording skin: $skin"
    # blank the terminal silently — no text before hermes alt-screen kicks in
    printf '\033[2J\033[H' >/dev/tty

    obs_toggle  # START recording for this skin

    HERMES_SKIN="$skin" hermes </dev/tty >/dev/tty 2>/dev/tty &
    HPID=$!
    sleep "$HOLD_S"

    obs_toggle  # STOP recording before killing hermes (avoids capturing teardown)
    sleep 0.5

    # Terminate hermes by PID — never xdotool ctrl+q (could hit OBS instead)
    kill -TERM "$HPID" 2>/dev/null
    sleep 0.5
    kill -KILL "$HPID" 2>/dev/null
    wait "$HPID" 2>/dev/null

    # restore terminal: full reset flushes any buffered TTE frames
    printf '\033c\033[?1049l\033[?25h' >/dev/tty
    stty sane 2>/dev/null

    sleep 1
    rename_latest "take1_${skin}.mkv"

    # Wipe viewport so any stray glyphs (prompt, prior frame) don't get
    # captured at the head of the next scene's recording.
    printf '\033[2J\033[H' >/dev/tty

    sleep "$GAP_S"
done

echo
echo "=== TAKE 1 done. Files:"
ls -lh "$RAW"/take1_*.mkv 2>/dev/null
