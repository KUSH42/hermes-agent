---
name: R3 Overlay Consolidation spec
description: R3 — 21 pre-mounted overlays → 5; ConfigOverlay + InterruptOverlay + ReferenceModal; Phases A/B/C/E merged; D pending R7
type: project
originSessionId: 659a7e30-f871-4fdd-b581-fc99edb03e80
---
**DONE** Phases A/B/C/E merged feat/textual-migration 2026-04-22. Phase D (session strip) deferred pending R7.

**Why:** 21 pre-mounted overlays, each with own show/hide/escape/test scaffolding. Consolidate to 2 canonical + 3 standalones + 4 migrated.

**How to apply:** All old class names still importable via alias layer. `query_one(VerbosePickerOverlay)` returns `ConfigOverlay`; `isinstance(ov, ClarifyWidget)` returns True when `ov.current_kind == CLARIFY`.

**Key facts:**
- `overlays/` package (was `overlays.py`); `_legacy.py` holds remaining old content; `__init__.py` re-exports all
- `overlays/config.py`: `ConfigOverlay(Widget)` — 7 tabs (Model/Skin/Syntax/Options/Reasoning/Verbose/YOLO); `1`–`7` + Tab/Shift+Tab cycle
- `overlays/interrupt.py`: `InterruptOverlay(Widget)` — 7 kinds; `present(payload, replace=False)` FIFO queue (no longer inherits CountdownMixin — deleted in E)
- `overlays/reference.py`: `ReferenceModal(Widget)` base; 4 subclasses (Help/Usage/Commands/Workspace) still pre-mounted (§7.4 fallback — no PaneManager yet)
- `overlays/_aliases.py`: alias classes with `_AliasMeta.__instancecheck__`; alias names injected into canonical `_css_type_names` frozensets for `query_one` CSS resolution
- `_dismiss_all_info_overlays` updated to iterate `{ConfigOverlay, InterruptOverlay, HistorySearch, Keymap, ToolPanelHelp}`
- `ConfigOverlay` added to escape dispatch tuple at `_app_key_handler.py:~180`; `InterruptOverlay` NOT added (handles Escape via BINDINGS)
- Standalones unchanged: `HistorySearchOverlay`, `KeymapOverlay`, `ToolPanelHelpOverlay`
- ModalScreen overlays (AnimConfig/AnimGallery/ToolsScreen) out of scope
- F1 opens `KeymapOverlay` NOT `HelpOverlay` (spec error caught in Phase C)
- `FIXTURE_CODE` kept in `_legacy.py` (used by `config.py` Syntax tab preview); `_dismiss_overlay_and_focus_input` kept (used by session/help overlays)

**Phase E (done 2026-04-22):** deleted `CountdownMixin` from `widgets/overlays.py` (~140 lines + dead state imports); deleted ~860 lines of dead picker bodies from `_legacy.py` (`PickerOverlay` base + 5 subclasses + `SkinPickerOverlay = TabbedSkinOverlay` alias); updated `overlays/__init__.py` and `widgets/__init__.py`; cleaned 3 test files (−8 tests); −1198 lines net.

**Test counts:** Phase A +30/−85 · Phase B +35/−58 · Phase C +28/−75 · Phase E −8 = net −132 tests

**Pending:** Phase D (SessionOverlay → session strip, needs R7)
