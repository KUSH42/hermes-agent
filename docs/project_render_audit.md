---
name: Renderer audit specs (2026-04-24)
description: Five body-renderer specs addressing rendereraudit.md (39 issues across 10 renderers + cross-cutting)
type: project
originSessionId: c01e097c-c112-4bf2-b104-1e502ad19138
---
Body renderer subsystem audit (`/home/xush/.hermes/rendereraudit.md`) split into 5 DRAFT specs in `/home/xush/.hermes/`:

1. **2026-04-24-render-visual-grammar-spec.md** — **APPROVED** — R-G1/G2/G3/G4 + color-discipline portions of D2/C1/L1. Foundation: `_grammar.py` module (glyphs, `SkinColors`, `build_path_header`, `build_gutter_line_num`, `build_rule`, `BodyFooter`). 23 tests.
2. **2026-04-24-render-diff-overhaul-spec.md** — **APPROVED 2026-04-24** — R-D1/D2/D3/D4/D5. Expand affordance for collapsed hunks, skin bg tints, word-diff fidelity, `+A -B` per-file header, 2-col fixed gutter. 26 tests.
3. **2026-04-24-render-search-overhaul-spec.md** — **IMPLEMENTED 2026-04-24** — R-Sr1/Sr2/Sr3/Sr4/Sr5. Hit vs context, grammar header, pre-highlighted ANSI for VirtualSearchList, full nav+Enter+footer+scrollbar, sticky group header. 32 tests. Commit c1454a88 on feat/render-search-overhaul.
4a. **2026-04-24-render-code-json-table-log-spec.md** — **IMPLEMENTED 2026-04-24** — R-C1/C2/C3/C4, R-J1/J2/J3. CodeRenderer + JsonRenderer only. Skin-driven Syntax theme, conditional line numbers, regex-anchored fence (negative-lookahead body), lang+origin header, Syntax(json.dumps) swap + parse-fail hint + large-object collapse (_JsonCollapseWidget). 23 tests. Commit 1cabe40f on feat/textual-migration.
4b. **2026-04-24-render-table-log-spec.md** — **IMPLEMENTED 2026-04-24** — R-T1/T2/T3, R-L1/L2/L3. TableRenderer + LogRenderer. Table shape sanity (_looks_like_table) + no fake headers + proportional numeric, level→skin vars + full timestamp modes + continuation gutter (glyph(GLYPH_GUTTER) inline). 20 tests. Commit 12858046 on feat/textual-migration.
5. **2026-04-24-render-shell-selection-streaming-spec.md** — **IMPLEMENTED 2026-04-24** — R-S1/S2, R-F1, R-E1/E2, R-X1/X2/X3, R-P1/P2/P3, R-G5. CWD rule + exit/stderr body, fallback footer, empty-state diagnostic, streaming→final swap notice, streaming search path headers, streaming diff gutter, drop SHELL unconditional override, low-conf disclosure, registry reorder, universal truncation footer. 35 tests. Commit b6fa7c5b on feat/render-shell-selection-streaming; merged to feat/textual-migration.

**Why:** Single rendereraudit.md listed 39 issues across 10 renderers + cross-cutting — too large for one spec (`/home/xush/.hermes/CLAUDE.md` rule: split when >2 subsystems OR >35 tests).

**How to apply:** Spec 1 is the foundation — land it first. Specs 2–5 depend on it. Within each spec, the implementation-order section enumerates intra-spec ordering. All five are DRAFT; no implementation yet.

**New skin vars introduced (3-edit requirement):** `$diff-add-bg`, `$diff-del-bg`, `$info`, `$syntax-theme` — must land in `COMPONENT_VAR_DEFAULTS` + `hermes.tcss` + all 4 bundled skins per existing enforcement in `test_css_var_single_source.py`.
