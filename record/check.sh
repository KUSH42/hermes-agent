#!/usr/bin/env bash
# Verify all expected raw takes exist + are non-trivial
source "$(dirname "$0")/_lib.sh"

echo "=== Take inventory ==="
echo

# Per-skin take1 files (must match SKINS array in take1.sh)
TAKE1_SKINS=(matrix charizard poseidon ares hermes tokyo-night)

REQUIRED=(
    take2.mkv            # TTE montage
    take6.mkv            # streaming token effects
    take7.mkv            # drawbraille engines (short)
    take8.mkv            # syntax highlighting
    take_drawbraille.mkv # 192×52 engine showcase
    take_emoji.mkv       # custom emoji registry
    take_nameplate.mkv   # nameplate idle-beat anims
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

echo "TAKE 1 (per-skin startup montage):"
for skin in "${TAKE1_SKINS[@]}"; do
    check_file "take1_${skin}.mkv" || missing=$((missing+1))
done

echo
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
    echo "✓ All required takes present. Optional: $opt_present/${#OPTIONAL[@]}"
    echo "Tell me 'takes ready' to proceed to edit."
else
    echo "✗ $missing required takes missing. Re-record those before proceeding."
    exit 1
fi
