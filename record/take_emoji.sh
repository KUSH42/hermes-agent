#!/usr/bin/env bash
# TAKE EMOJI — custom emoji registry, inline TGP rendering.
#
# What this proves:
#   ~460 named images at $HERMES_HOME/emojis/, resolved by :name: substitution
#   at render time, drawn via the custom Kitty Graphics Protocol impl. Inline
#   in agent output and the composer. No other agent TUI does this.
#
# Note: animated GIF playback is on the roadmap. Today the first frame of any
# .gif renders (still beats unicode-fallback). Pick static .webp files for the
# shot to avoid implying motion the project doesn't yet support.
#
# Recording strategy:
#   Keep kitty at the regular recording size (font_size=22, 1920×1080) so it
#   matches the rest of the cuts. At 1080p source, an emoji cell is ~26-30px —
#   small but readable. If you want a hero close-up, do a modest 1.5× crop in
#   post on the relevant region.
source "$(dirname "$0")/_lib.sh"

# Static .webp emojis only (avoid GIFs until playback ships).
COMPOSER_LINE=':pepeclown: render some ascii art of a clown :5Head: and react with :smartboi: when youre done :based:'

echo "=== TAKE EMOJI: custom registry + inline TGP rendering ==="
echo "    composer line: $COMPOSER_LINE"
echo
echo "Make sure kitty (regular recording config: font_size=22, 1920×1080) is"
echo "focused with hermes already running. Press Enter when ready."
read -r

countdown 2 "starting recording — type begins immediately after"
obs_toggle

type_slow "$COMPOSER_LINE" 50

hold 2 "holding on composer with emojis swapped in"

press "Return"

hold 6 "holding on agent response with rendered emoji images"

obs_toggle
echo "    stopped recording"

sleep 1
rename_latest "take_emoji.mkv"
