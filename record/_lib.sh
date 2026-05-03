#!/usr/bin/env bash
# Shared helpers for take recording. Source this from each take script.

set -uo pipefail

REPO="/home/xush/.hermes/hermes-agent"
RAW="$REPO/raw_takes"
mkdir -p "$RAW"

# ── audio cue (uses sine wave via ffmpeg → paplay) ───────────────────────────
beep_high() { ffmpeg -nostdin -loglevel error -f lavfi -i "sine=frequency=880:duration=0.15" -f wav - 2>/dev/null | paplay 2>/dev/null & }
beep_low()  { ffmpeg -nostdin -loglevel error -f lavfi -i "sine=frequency=440:duration=0.20" -f wav - 2>/dev/null | paplay 2>/dev/null & }

# ── countdown (visible + audible) ────────────────────────────────────────────
countdown() {
    local secs=$1 msg=${2:-""}
    echo
    [ -n "$msg" ] && echo ">>> $msg"
    for ((i=secs; i>0; i--)); do
        printf "    %d... " "$i"
        beep_low
        sleep 1
    done
    printf "GO!\n"
    beep_high
}

# ── timed hold ───────────────────────────────────────────────────────────────
hold() {
    local secs=$1 msg=${2:-"holding"}
    echo
    echo ">>> $msg ($secs s)"
    for ((i=secs; i>0; i--)); do
        printf "    %d.. " "$i"
        sleep 1
    done
    echo
}

# ── OBS hotkey (assumes F10 set as global hotkey for start/stop) ─────────────
obs_toggle() {
    xdotool key F10
    sleep 0.3
}

# ── slow-type a string into focused window, char by char ─────────────────────
type_slow() {
    local text="$1" delay_ms=${2:-80}
    xdotool type --delay "$delay_ms" -- "$text"
}

# ── press a single key into focused window ───────────────────────────────────
press() { xdotool key "$1"; sleep 0.2; }

# ── rename the latest mkv in raw_takes/ ──────────────────────────────────────
rename_latest() {
    local target="$1"
    local latest
    latest=$(ls -t "$RAW"/*.mkv 2>/dev/null | head -1)
    if [ -z "$latest" ]; then
        echo "ERROR: no mkv found in $RAW" >&2
        return 1
    fi
    mv "$latest" "$RAW/$target"
    echo "    saved: $RAW/$target ($(du -h "$RAW/$target" | cut -f1))"
}

# ── verify a file exists and is non-trivial ──────────────────────────────────
check_file() {
    local f="$RAW/$1"
    if [ ! -f "$f" ]; then echo "MISSING: $1"; return 1; fi
    local size
    size=$(stat -c%s "$f")
    if [ "$size" -lt 100000 ]; then echo "TOO SMALL: $1 ($size bytes)"; return 1; fi
    echo "OK: $1"
}
