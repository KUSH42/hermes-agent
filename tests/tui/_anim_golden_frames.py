"""Golden frames for animation safety tests (SPEC-ANM ANM-2).

These are pre-recorded reference outputs for apply_external_trail used in
test_apply_external_trail_correctness_unchanged.

How generated:
- Input: BrailleCanvas with single dot at pixel (0,0) → '⠁' (U+2801, bitmask=0x01)
- Params: width=2, height=4 (1 terminal col × 1 terminal row)
- cfg.trail_decay=0.85
- After one call: TrailCanvas pixel (0,0) gets intensity 1.0, then decay_all()
  gives 0.85 which is ≥ threshold 0.3, so dot survives one round.
"""

# Frame from a single-dot input run through apply_external_trail once.
# The dot at braille pixel (0,0) maps to bit_idx=0 (dy=0, dx=0), so px=0, py=0.
# TrailCanvas intensity=1.0, after decay_all → 0.85 ≥ threshold=0.3 → dot preserved.
APPLY_EXTERNAL_TRAIL_SINGLE_DOT_FRAME_1 = "⠁"  # ⠁
