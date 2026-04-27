---
name: Render table-log spec
description: IMPLEMENTED TableRenderer + LogRenderer polish (R-T1..R-T3, R-L1..R-L3); 20 tests; commit 12858046
type: project
originSessionId: 7db9349c-75c5-47cf-9c64-abf274883b64
---
R-T1..R-T3 TableRenderer and R-L1..R-L3 LogRenderer polish.

**Why:** rendereraudit.md spec 4b — shape-sanity gate for tables, no fake headers, proportional numeric alignment, log level colours from skin, full timestamp modes, continuation-line gutter.

**How to apply:** All 20 tests in `tests/tui/test_render_table_log.py`. Merged as commit 12858046 onto feat/textual-migration.

Key implementation decisions:
- `body_renderers/table.py`: `_looks_like_table(lines, delim)` — Counter modal column count ≥2, ≥70% coverage; falls back to `FallbackRenderer` on reject. `show_header=False` with bare `add_column()` (no `"ColN"` fake headers). `_column_numeric_stats(rows, j)` — proportional 0.8 threshold; outlier cells in numeric columns get `Style(color=colors.muted)`.
- `body_renderers/log.py`: `_LEVEL_STYLES` and `_LEVEL_COLORS` deleted entirely; replaced with per-call `style_map` built from `self.colors` (SkinColors). `_TS_RE` captures full sub-second + TZ (`(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?`). `_timestamp_mode: str = "full"` replaces `_timestamps_visible: bool`; modes: `"full"` (emit whole captured group, dim), `"relative"` (first-parseable-ts epoch reference, `+N.NNNs` format), `"none"` (omit). Continuation-line detection: `_CONTINUATION_RE = re.compile(r"^(?:\t| {2,})")` + `prev_had_signal` flag; gutter via `glyph(GLYPH_GUTTER) + " "` in `Style(color=c.muted)`.
