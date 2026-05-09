#!/usr/bin/env bash
# TAKE NAMEPLATE — assistant nameplate idle-beat anims (PULSE/SHIMMER/DECRYPT).
#
# Default nameplate idle beats fire at random 30-60s intervals — too slow for
# a take. This script overrides via HERMES_NP_IDLE_MIN_S / HERMES_NP_IDLE_MAX_S
# (wired in app.py at AssistantNameplate construction) so beats fire every
# 2-4s. Hold for 30s to capture ~10-15 beats covering all three idle effect
# types.
source "$(dirname "$0")/_lib.sh"

SKIN="${HERMES_SKIN:-hermes}"
HOLD_S="${HOLD_S:-30}"
NP_MIN="${NP_MIN:-2}"
NP_MAX="${NP_MAX:-4}"

echo "=== TAKE NAMEPLATE: idle beats on $SKIN ==="
echo "    idle beat interval: ${NP_MIN}-${NP_MAX}s · hold: ${HOLD_S}s"
echo
echo "Focus kitty window. Press Enter when ready."
read -r

# Blank terminal silently before alt-screen
printf '\033[2J\033[H' >/dev/tty

countdown 3 "starting"
obs_toggle

HERMES_SKIN="$SKIN" \
HERMES_NP_IDLE_MIN_S="$NP_MIN" \
HERMES_NP_IDLE_MAX_S="$NP_MAX" \
    hermes </dev/tty >/dev/tty 2>/dev/tty &
HPID=$!

# Wait through hermes startup TTE (~8s) plus the requested hold for beats.
sleep $(( 10 + HOLD_S ))

obs_toggle
sleep 0.5

# PID-only teardown — never xdotool ctrl+q (could hit OBS)
kill -TERM "$HPID" 2>/dev/null
sleep 0.5
kill -KILL "$HPID" 2>/dev/null
wait "$HPID" 2>/dev/null

# Restore terminal
printf '\033c\033[?1049l\033[?25h' >/dev/tty
stty sane 2>/dev/null

sleep 1
rename_latest "take_nameplate.mkv"
