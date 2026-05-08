#!/usr/bin/env bash
# Shared helpers for take recording. Source this from each take script.

set -uo pipefail

REPO="/home/xush/.hermes/hermes-agent"
RAW="$REPO/raw_takes"
PYTHON="$REPO/venv/bin/python"
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

# ── OBS hotkey — sends F10 directly to the OBS window (bypasses focus) ───────
obs_toggle() {
    local obs_wid
    obs_wid=$(xdotool search --classname obs 2>/dev/null | head -1)
    if [ -n "$obs_wid" ]; then
        xdotool key --window "$obs_wid" F10
    else
        echo "[obs_toggle] WARNING: OBS window not found, sending F10 to focused window" >&2
        xdotool key F10
    fi
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
# Output goes to $RAW/rename.log, never to tty — visible echoes between scenes
# get captured by OBS on the next recording start as a stray row of glyphs.
rename_latest() {
    local target="$1"
    local log="$RAW/rename.log"
    local latest
    # Only pick up FRESH mkvs (mtime within the last 60s) — avoids re-renaming
    # a previous scene's already-renamed mkv when this scene failed to record.
    latest=$(find "$RAW" -maxdepth 1 -name '*.mkv' -mmin -1 -printf '%T@ %p\n' 2>/dev/null \
             | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -z "$latest" ] || [ "$(basename "$latest")" = "$target" ]; then
        echo "[$(date +%H:%M:%S)] ERROR: no fresh mkv for $target" >>"$log"
        return 1
    fi
    mv "$latest" "$RAW/$target"
    echo "[$(date +%H:%M:%S)] saved: $target ($(du -h "$RAW/$target" | cut -f1))" >>"$log"
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
