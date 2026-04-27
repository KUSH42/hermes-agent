---
name: Load-bearing TUI facts for hermes-agent (Textual migration era)
description: Critical facts about cli.py TUI internals — Textual ≥1.0 API (8.2.3 stable), typed overlay state, bounded queue, error boundaries
type: reference
originSessionId: 64f4bdbd-2039-4f0a-95ed-1597e155b10e
updatedDate: 2026-04-10
---
Canonical copy at `/home/xush/.hermes/reference_tui_facts.md`. This memory is a summary — read the canonical file for full details.

**Textual version:** Pin `textual>=1.0,<9.0`. Current stable: 8.2.3 (2026-04-05). Core APIs (`get_css_variables`, `call_from_thread`, `reactive`, `@work`, `set_interval`) confirmed stable from 1.0 through 8.x.

**Key facts (non-obvious):**
- `@work` requires explicit `thread=True` for threaded workers (all Textual ≥1.0)
- `RenderResult` import from `textual.app`, NOT `textual.widget`
- `Widget.render()` plain str = LITERAL text (no markup parsing) — use `Text` objects
- `RichLog.write()` has no `markup` kwarg — set at construction
- `query_one()` raises `NoMatches` — use `_safe_widget_call` error boundary during teardown
- Bounded `asyncio.Queue(maxsize=4096)` — `_cprint` catches `QueueFull`
- Overlay state: typed `@dataclass` hierarchy (`OverlayState` → `ChoiceOverlayState` / `SecretOverlayState`)
- `get_css_variables()` confirmed stable, no rename through 8.x
- `self.size.width` is `0` during `compose()` — don't use for layout
- `Pilot.resize_terminal(w, h)` is ASYNC — must `await` it (verified Textual 8.2.3)
- `current_message` is a property on `OutputPanel`, NOT `HermesApp`
- `VerticalScroll` imports from `textual.containers`, NOT `textual.widgets`
- `RichLog.DEFAULT_CSS` sets `background: $surface` — subclasses inherit it; hermes.tcss overrides with `$app-bg` for uniform app background
- `$app-bg` component var (default `#1E1E1E`) is the single knob for whole-app background tone; registered in `COMPONENT_VAR_DEFAULTS` + declared in `hermes.tcss`
- **Screen vs HermesApp background:** transparent widgets inherit from `Screen`, not `HermesApp` — must set `Screen { background: $app-bg }` AND `HermesApp { background: $app-bg }` in hermes.tcss
- `rule-bg-color` (gradient fade endpoint) falls back to `app-bg` in `_live_colors()` — always matches app background; `PlainRule.render()` reads CSS vars live per paint (fixed 2026-04-12)
- **`content_size.width` vs `size.width`:** `size.width` = full outer width including padding. `content_size.width` = inner width after padding subtracted. Use `content_size.width` for any "how many chars fit" calculation (e.g. width-responsive hint string selection in HintBar). Using `size.width` with `padding: 0 1` causes 2-char overflow at 80-col terminals.
- **`CopyableRichLog.can_focus=True` + `scroll_visible()` no-op:** `can_focus=False` prevented Textual selection tracking from activating on mouse-down. Fix: `can_focus=True` (enables selection) + override `scroll_visible()` as a no-op (suppresses focus-triggered scroll-to-top delegation to OutputPanel). `app.on_click(button=1)` already has the OutputPanel guard that prevents refocusing the input on output-zone clicks.
