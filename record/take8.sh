#!/usr/bin/env bash
# TAKE 8 — syntax highlighting montage across all bundled schemes
source "$(dirname "$0")/_lib.sh"

SCHEMES=(hermes monokai dracula one-dark github-dark nord catppuccin tokyo-night gruvbox solarized-dark)
HOLD_PER_SCHEME="${HOLD_PER_SCHEME:-3}"

echo "=== TAKE 8: syntax highlighting (${#SCHEMES[@]} schemes) ==="
echo "Focus kitty window. Press Enter when ready."
read -r

clear
cd /home/xush/.hermes
countdown 3 "starting recording"
obs_toggle

for scheme in "${SCHEMES[@]}"; do
    clear
    printf '\033[1m── scheme: %s ──\033[0m\n\n' "$scheme"
    "$PYTHON" demo_syntax.py "$scheme"
    sleep "$HOLD_PER_SCHEME"
done

cd "$REPO"
hold 2 "settling"
obs_toggle

sleep 1
rename_latest "take8.mkv"
