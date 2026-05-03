#!/usr/bin/env bash
# Verify all expected raw takes exist + are non-trivial
source "$(dirname "$0")/_lib.sh"

echo "=== Take inventory ==="
echo

REQUIRED=(
    take1.mkv      # matrix cold open
    take2.mkv      # TTE montage
    take3.mkv      # composer + skill picker
    take4.mkv      # HERO Kimi run
    take5_browser.mkv  # art.html in browser
    take6.mkv      # streaming effects
    take7.mkv      # drawbraille engines
    take8.mkv      # syntax highlighting
    take9.mkv      # live skin switch
    take10.mkv     # /model picker
    take11.mkv     # navigation overlays
    take12.mkv     # static final hold
)

OPTIONAL=(
    take13_matrix.mkv
    take13_charizard.mkv
    take13_poseidon.mkv
    take13_ares.mkv
    take13_tokyo-night.mkv
    take13_solarized-dark.mkv
)

missing=0
echo "REQUIRED:"
for f in "${REQUIRED[@]}"; do
    check_file "$f" || missing=$((missing+1))
done

echo
echo "OPTIONAL (take 13 flicker):"
opt_present=0
for f in "${OPTIONAL[@]}"; do
    if [ -f "$RAW/$f" ]; then
        check_file "$f" && opt_present=$((opt_present+1))
    else
        echo "skipped: $f"
    fi
done

echo
if [ $missing -eq 0 ]; then
    echo "✓ All required takes present. Optional: $opt_present/6"
    echo "Tell me 'takes ready' to proceed to edit."
else
    echo "✗ $missing required takes missing. Re-record those before proceeding."
    exit 1
fi
