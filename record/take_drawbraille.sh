#!/usr/bin/env bash
# TAKE DRAWBRAILLE — animation engine showcase at 192×52 cells.
#
# Spawns a fresh kitty sized to ~192×52 cells (1920×1080 at font_size=10),
# runs demo_anim.py through a curated engine sequence with a 4-stop chroma
# gradient and hue-shift drift. ~40s of footage; cut whichever beats hit.
#
# Engines, in order (visual arc: bold → motion → math → atmospheric → close):
#   matrix_rain, rotating, dna, triple_helix, torus_3d, wireframe_cube,
#   lissajous_weave, aurora_ribbon, plasma, fluid_field, neural_pulse,
#   mandala_bloom, kaleidoscope, strange_attractor
#
# Override knobs (env vars):
#   FONT_SIZE       kitty font size (default 10; lower = more cells)
#   PER_ENGINE_S    seconds per engine (default 3)
#   FPS             frame rate (default 30; bump to 60 for the take)
#   PALETTE         4-stop hex CSV (default cool→hot→cyan→violet)
#   HUE_SHIFT       drift speed (default 1.0)
source "$(dirname "$0")/_lib.sh"

FONT_SIZE="${FONT_SIZE:-10}"
PER_ENGINE_S="${PER_ENGINE_S:-3}"
FPS="${FPS:-60}"
PALETTE="${PALETTE:-#ff0080,#ffaa00,#00ffcc,#8800ff}"
HUE_SHIFT="${HUE_SHIFT:-1.0}"

# demo_anim.py --width/--height take CELLS (it multiplies ×2/×4 internally for braille pixels).
CELLS_W=192
CELLS_H=52

ENGINES="matrix_rain,rotating,dna,triple_helix,torus_3d,wireframe_cube,lissajous_weave,aurora_ribbon,plasma,fluid_field,neural_pulse,mandala_bloom,kaleidoscope,strange_attractor"

echo "=== TAKE DRAWBRAILLE: 192×52 engine showcase ==="
echo "    font_size=$FONT_SIZE  per_engine=${PER_ENGINE_S}s  fps=$FPS"
echo "    canvas: ${CELLS_W}×${CELLS_H} cells"
echo "    palette: $PALETTE  hue-shift: $HUE_SHIFT"
echo "    engines: $ENGINES"
echo
echo "Press Enter to spawn the recording kitty. (Recording terminal stays separate.)"
read -r

# Spawn dedicated kitty sized for 192×52 cells. --hold keeps window open after exit.
kitty --override font_size="$FONT_SIZE" \
      --override window_padding_width=0 \
      --override hide_window_decorations=yes \
      --override remember_window_size=no \
      --override initial_window_width=1920 \
      --override initial_window_height=1080 \
      --hold bash -lc "cd /home/xush/.hermes/hermes-agent && venv/bin/python scripts/demo_anim.py \
          --engines '$ENGINES' \
          --duration $PER_ENGINE_S \
          --fps $FPS \
          --multi-color '$PALETTE' \
          --hue-shift $HUE_SHIFT \
          --width $CELLS_W \
          --height $CELLS_H" &
KPID=$!

echo "    waiting 2s for kitty to render first frame..."
sleep 2

countdown 3 "starting recording — focus the kitty window NOW"
obs_toggle

# Total runtime ≈ engines × per_engine + small slack
N_ENGINES=$(echo "$ENGINES" | tr ',' '\n' | wc -l)
TOTAL_S=$(( N_ENGINES * PER_ENGINE_S + 2 ))
echo "    holding for ${TOTAL_S}s while showcase plays..."
sleep "$TOTAL_S"

obs_toggle
echo "    stopped recording"

# Close the demo kitty
kill "$KPID" 2>/dev/null
wait "$KPID" 2>/dev/null

sleep 1
rename_latest "take_drawbraille.mkv"
