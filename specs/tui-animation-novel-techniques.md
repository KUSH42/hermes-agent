# Spec: TUI Novel Animation Techniques

**Status:** Draft  
**Priority:** P1 (techniques 1–4), P2 (techniques 5–6)  
**Depends on:** textual-migration (implemented), tool-block-browse-mode (implemented), tool-output-streamline §8 (implemented)  
**Goal:** Exploit Textual's reactive engine, CSS variable system, built-in animator, and per-cell `render_line()` API to deliver animations that are architecturally impossible in React/Ink — creating a perceptibly faster, smoother, and more premium TUI.

---

## 1. Problem

### 1.1 Ink's rendering model imposes unavoidable latency

Ink (React for the terminal) renders through a VDOM → reconciliation → string diff → terminal write pipeline. Each animation frame requires a reconciliation pass that allocates closures, diffs the component tree, and schedules a flush. On a 16ms budget this adds 2–5ms of fixed overhead before any pixels move.

Textual's rendering path: `reactive` change → watcher fires → `Widget.render()` / `render_line()` → terminal write. No VDOM, no reconciliation, no closure allocation per frame. A `set_interval(1/30)` callback flipping one boolean costs ~0.05ms.

### 1.2 The current Hermes TUI has no motion

Every state change is instant: blocks appear, the status bar updates, counters jump. A well-animated CLI tool feels orders of magnitude more responsive than a static one, even if the underlying operation takes the same time. The perception of speed is as important as actual speed.

### 1.3 Existing animation specs cover only full-screen TTE and typewriter streaming

`tui-text-effects.md` covers `App.suspend()` + TerminalTextEffects for `/effects` command. `tui-streaming-typewriter.md` covers per-character token reveal on `LiveLineWidget`. Neither covers in-situ widget animations that play continuously as the agent runs — status pulse, skeleton shimmer, counter easing, block entrances.

---

## 2. Goals

1. **`animation.py`** — shared utilities: `lerp`, `ease_out_cubic`, `ease_in_out_cubic`, `pulse_phase`, `lerp_color`, `PulseMixin`. No `context_bar_color` — `_compaction_color` lerps directly between skin-aware colors. No custom animation driver — use `widget.styles.animate()` for single-shot value transitions.
2. **`MessagePanel` fade-in** — new response panels fade opacity 0 → 1 over 250ms on mount. Uses `self.styles.animate("opacity", ...)`.
3. **Blinking cursor in `LiveLineWidget` (typewriter-off path)** — when typewriter mode is disabled, add a trailing `▌` that blinks at 1 Hz during active streaming via `set_interval(0.5)`. The existing typewriter path already shows `▌` via `_animating`. No change to the typewriter path.
4. **`ThinkingWidget` skeleton shimmer** — between prompt submission and first token, an animated shimmer placeholder inside `OutputPanel` occupies the first output line. Deactivated atomically from `_consume_output` on the event loop when the first non-None chunk arrives.
5. **`StatusBar` running-indicator pulse** — `StatusBar` inherits `PulseMixin`; when `agent_running=True`, a `●` character in `StatusBar.render()` breathes between two accent shades at ~0.5 Hz. No child widget required — `render()` reads `self._pulse_t` directly.
6. **`AnimatedCounter`** — leaf widget that smoothly eases from an old float value to a new one over 200ms. Defined as a reusable standalone pattern for future use; it is **not** mounted in `StatusBar`. The tok/s animation in `StatusBar` is done directly via `_tok_s_displayed: reactive[float]` and `self.animate("_tok_s_displayed", ...)`. `AnimatedCounter` uses `widget.animate()` on its own `_displayed` reactive.
7. **Context bar hue shift** — `StatusBar._compaction_color()` is extended to lerp between its three skin-aware band colors (normal → warn → crit) rather than snapping. Uses `lerp_color()` from `animation.py`. No timer.
8. All new tests pass; existing 341 tests continue to pass; total ≥ 383 tests after this spec.

---

## 3. Non-Goals

- TTE full-screen effects. Already covered by `tui-text-effects.md`.
- Streaming typewriter (per-character reveal). Already covered by `tui-streaming-typewriter.md`.
- `ToolBlock` height animation on collapse/expand. `height: auto` is not a numeric CSS property; `styles.animate()` requires a numeric target. Deferred — see §24.
- Particle or physics effects (falling characters, bouncing). Outside the design language — section rules, gutters, and flat typography are the identity.
- Animated scrolling (`OutputPanel` smooth-scroll on new content). Deferred — adds complexity to the existing `_user_scrolled_up` scroll-lock logic.
- Any animation that fires on the agent thread. All animation timers live on the Textual event loop.
- Changes to `LiveLineWidget`'s typewriter path. `_animating` + `_tw_cursor` already handles cursor during typewriter mode. This spec adds a separate blink path for the non-typewriter case only.

---

## 4. Competitive Context: What Textual Does That Ink Cannot

| Capability | Textual | Ink / React |
|---|---|---|
| `widget.styles.animate("opacity", value, easing=...)` | Built-in, event-loop-accurate | Requires manual `setTimeout` chains; JS timers have ≥4ms floor |
| CSS `transition` on color/opacity | Native, same frame budget as CSS | JS-interpolated; must clear/set timers per prop |
| `render_line()` per-cell control | Direct `Strip` construction; sub-cell styling | React reconciles string nodes; no per-cell API |
| `get_css_variables()` override | Swap entire palette at runtime with `refresh_css()` in <1ms | Requires re-render of every component that references the variable |
| `set_interval` timer precision | CPython event loop; ~0.3ms jitter | Node.js `setInterval`; ~4ms minimum; GC pauses during V8 major collections |
| No GC pauses | Python's reference-counting GC is incremental | V8 stop-the-world major GC can pause for 10–50ms — visible frame drop |

---

## 5. Shared Utilities: `hermes_cli/tui/animation.py`

A small, dependency-free utilities module. All public functions are pure (no side effects, no Textual imports). `PulseMixin` is the exception — it requires Textual's `set_interval` and `refresh` via duck-typing. Import from here in widgets — do not re-implement in individual files.

```python
# hermes_cli/tui/animation.py
"""
Shared animation utilities for the Hermes TUI.

Pure functions have no side effects and no Textual imports.
PulseMixin uses duck-typed Textual APIs (set_interval, refresh).
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Pure numeric helpers
# ---------------------------------------------------------------------------

def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b at position t ∈ [0, 1]."""
    return a + (b - a) * t


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: fast start, gentle deceleration. t ∈ [0, 1]."""
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    """Symmetric S-curve. t ∈ [0, 1]."""
    if t < 0.5:
        return 4.0 * t ** 3
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def pulse_phase(tick: int, period: int = 30) -> float:
    """
    Sine-based oscillation: returns a value in [0, 1] that cycles smoothly
    over `period` ticks. Tick 0 → 0.0; tick period/4 → 1.0; tick period/2 → 0.0.

    At 15fps with period=30: one full breath = 2 seconds.
    """
    return (math.sin(2.0 * math.pi * tick / period) + 1.0) / 2.0


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def lerp_color(hex1: str, hex2: str, t: float) -> str:
    """
    Linearly interpolate between two hex colors.

    Args:
        hex1: Start color, e.g. "#4caf50" or "4caf50".
        hex2: End color.
        t:    Blend factor ∈ [0, 1]. 0 → hex1, 1 → hex2.

    Returns:
        Interpolated hex color string, e.g. "#7abc60".

    Interpolation is in linear RGB. Gamma error is negligible (<1 step per
    channel) for terminal truecolor output.
    """
    def _parse(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    r1, g1, b1 = _parse(hex1)
    r2, g2, b2 = _parse(hex2)
    r = round(lerp(r1, r2, t))
    g = round(lerp(g1, g2, t))
    b = round(lerp(b1, b2, t))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# PulseMixin
# ---------------------------------------------------------------------------

class PulseMixin:
    """
    Mixin that drives a sinusoidal pulse at 15fps using Textual's set_interval.

    Subclass must appear before Widget in the MRO:
        class MyWidget(PulseMixin, Widget): ...

    PulseMixin has no __init__ to avoid MRO conflicts. It uses duck-typing
    for Textual APIs (set_interval, refresh) — these are resolved at call
    time via self, which is always a Widget subclass in practice.

    Usage:
        def on_mount(self) -> None:
            ...

        def watch_some_reactive(self, value: bool) -> None:
            if value:
                self._pulse_start()
            else:
                self._pulse_stop()

        def render(self) -> RenderResult:
            color = lerp_color("#888888", "#ffbf00", self._pulse_t)
            return Text("●", style=f"bold {color}")
    """

    _pulse_t: float = 0.0
    _pulse_tick: int = 0
    _pulse_timer: object | None = None

    def _pulse_start(self) -> None:
        """Start the pulse. Safe to call multiple times (idempotent)."""
        if self._pulse_timer is None:
            self._pulse_tick = 0
            # set_interval callback MUST be def (not async def) when no await used.
            self._pulse_timer = self.set_interval(  # type: ignore[attr-defined]
                1 / 15, self._pulse_step
            )

    def _pulse_stop(self) -> None:
        """Stop the pulse and reset to neutral."""
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        self._pulse_t = 0.0
        self.refresh()  # type: ignore[attr-defined]

    def _pulse_step(self) -> None:
        """15Hz timer callback — must be plain def."""
        self._pulse_tick += 1
        # pulse_phase is defined in this same module — no import needed here.
        self._pulse_t = pulse_phase(self._pulse_tick, period=30)
        self.refresh()  # type: ignore[attr-defined]
```

---

## 6. Technique 1: `MessagePanel` Fade-In

### 6.1 What it does

When a new `MessagePanel` is mounted into `OutputPanel`, it starts at 0% opacity and fades to 100% over 250ms. The result: new response blocks appear to materialize rather than snap into existence.

### 6.2 Correct Textual API

`StylesBase.animate(attribute, value, ...)` is the correct method. `Widget.animate()` animates an attribute on the widget instance itself (via `getattr`) and cannot traverse dotted attribute paths — `widget.animate("styles.opacity", ...)` would raise `AttributeError` because Python's `getattr` does not support dotted names. The correct call is:

```python
self.styles.animate("opacity", 1.0, duration=0.25, easing="out_cubic")
```

`StylesBase.animate` is defined at `textual/css/styles.py:1408`. It accepts the same parameters as `Widget.animate()` and targets the styles object's own attributes. `opacity` is a `FractionalProperty` on `StylesBase` — a float in [0, 1].

### 6.3 Implementation

**In `widgets.py`, `MessagePanel.on_mount()`:**

```python
def on_mount(self) -> None:
    # Fade in from transparent. Set opacity before animate so the widget
    # starts invisible. on_mount() fires after DOM insertion — safe to
    # call styles.animate() here.
    self.styles.opacity = 0.0
    self.styles.animate("opacity", 1.0, duration=0.25, easing="out_cubic")
```

No CSS rule required. The assignment `self.styles.opacity = 0.0` is programmatic. Setting it in `__init__` is unsafe because Textual applies CSS rules during the mount phase, which runs between `__init__` and `on_mount()` — CSS processing would override any programmatic style assigned in `__init__`. By placing the assignment in `on_mount()`, we ensure it runs after CSS is applied and the widget is fully attached to the DOM.

### 6.4 Constraints

- `styles.animate()` is safe to call from `on_mount()` — the app is running and the widget is in the DOM.
- `duration=0.25` (seconds). `easing="out_cubic"` is a Textual built-in easing name.
- During tests: `await asyncio.sleep(0.3)` + `await pilot.pause()` confirms the animation completed and `styles.opacity == 1.0`.

---

## 7. Technique 2: Blinking Cursor in `LiveLineWidget` (Typewriter-Off Path)

### 7.1 What it does and what it does NOT change

`LiveLineWidget` already has a blinking cursor when typewriter mode is enabled: `_animating` reactive drives `▌` in `render()` via the `_tw_cursor` flag. This spec does **not** touch that path.

When typewriter is **disabled** (`_tw_enabled = False`), `feed()` falls through to `append()` and `_animating` stays `False` — so no cursor is shown. This technique adds a `set_interval(0.5)` blink that only activates in that case.

### 7.2 Implementation

Add to `LiveLineWidget` in `widgets.py` — two new instance attributes (not class-level reactives, to avoid the shared-state problem) initialized in `on_mount()`, and mutations to `feed()` and `flush()`:

```python
class LiveLineWidget(Widget):
    # Existing class attributes unchanged: _buf, _animating

    def on_mount(self) -> None:
        # Existing typewriter setup (unchanged):
        self._tw_enabled: bool = _typewriter_enabled()
        self._tw_delay: float = _typewriter_delay_s()
        self._tw_burst: int = _typewriter_burst_threshold()
        self._tw_cursor: bool = _typewriter_cursor_enabled()
        if self._tw_enabled:
            self._char_queue: asyncio.Queue[str] = asyncio.Queue()
            self._drain_chars()
        # New: blink state for typewriter-off path
        self._blink_visible: bool = True
        self._blink_timer: object | None = None

    def on_unmount(self) -> None:
        # Existing:
        self._animating = False
        # New: cancel blink timer
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None

    def feed(self, chunk: str) -> None:
        """Existing docstring unchanged."""
        if not getattr(self, "_tw_enabled", False):
            # Non-typewriter path: start blink timer on first chunk (if config allows).
            # _cursor_blink_enabled() is defined in §13 / widgets.py (module-level config accessor).
            if getattr(self, "_blink_timer", None) is None and _cursor_blink_enabled():
                self._blink_timer = self.set_interval(0.5, self._toggle_blink)
            self.append(chunk)
            return
        # ... existing typewriter path unchanged ...

    def _toggle_blink(self) -> None:
        """Blink timer callback — must be plain def."""
        self._blink_visible = not self._blink_visible
        self.refresh()

    def flush(self) -> None:
        """Extended flush — stops blink timer in addition to existing logic."""
        # Stop non-typewriter blink
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        self._blink_visible = True  # reset to visible for next turn
        # ... existing flush logic unchanged ...

    def render(self) -> RenderResult:
        if not self._buf and not self._animating:
            return Text("")
        t = Text.from_ansi(self._buf) if self._buf else Text("")
        # Typewriter cursor (existing path — unchanged):
        if self._animating and getattr(self, "_tw_cursor", True):
            t.append("▌", style="blink")
        # Non-typewriter blink (new path — only when typewriter is off):
        elif (
            not getattr(self, "_tw_enabled", False)
            and getattr(self, "_blink_timer", None) is not None
            and getattr(self, "_blink_visible", True)
        ):
            t.append("▌", style="dim")
        return t
```

**No double-cursor:** The `elif` ensures the non-typewriter blink only fires when `_animating` is `False`. When typewriter is active, `_animating=True` takes the first branch exclusively. When typewriter is inactive, `_animating` stays `False` and the non-typewriter branch activates when `_blink_timer` is set.

### 7.3 Constraints

- `_blink_timer` and `_blink_visible` are initialized in `on_mount()` (not `__init__`), avoiding event-loop dependency issues on Python ≤3.9.
- `_toggle_blink` is a plain `def` — no `await`, so `async def` is prohibited.
- `getattr(..., None)` guards protect against `on_unmount()` being called before `on_mount()` (rare during test teardown).

---

## 8. Technique 3: `ThinkingWidget` Skeleton Shimmer

### 8.1 What it does

Between the moment the user presses `Enter` and the moment the first response token arrives, the output area shows a single-line shimmering placeholder:

```
  ░░▒▒▓▓▒▒░░░░▒▒▓▓▒▒░░  ← cycles left across terminal width at 8fps
```

This eliminates the blank, motionless window between submission and first token — the period that makes a TUI feel "stuck."

### 8.2 Mounting location

`ThinkingWidget` is mounted inside **`OutputPanel.compose()`**, between `ToolPendingLine` and `LiveLineWidget`. This places it in the scrollable output stream where streaming content appears.

```python
# OutputPanel.compose() — modified
def compose(self) -> ComposeResult:
    yield ToolPendingLine(id="tool-pending")
    yield ThinkingWidget(id="thinking")   # NEW
    yield LiveLineWidget(id="live-line")
```

Mounting at the `HermesApp` level would render it outside the scrollable output area — wrong.

### 8.3 First-token detection (event-loop safe)

`_consume_output` runs as an `async` coroutine worker on the Textual event loop. It is safe to call widget methods directly from there:

```python
# HermesApp._consume_output — modified excerpt
async def _consume_output(self) -> None:
    _first_chunk_in_turn: bool = True   # local flag, reset on None sentinel
    while True:
        chunk = await self._output_queue.get()
        if chunk is None:
            # Sentinel: flush live line; reset first-chunk flag for next turn
            _first_chunk_in_turn = True
            try:
                self.query_one(OutputPanel).flush_live()
            except NoMatches:
                pass
            continue
        # Deactivate shimmer on first content chunk of each turn
        if _first_chunk_in_turn:
            _first_chunk_in_turn = False
            try:
                self.query_one(ThinkingWidget).deactivate()
            except NoMatches:
                pass
        try:
            panel = self.query_one(OutputPanel)
            panel.live_line.feed(chunk)
            if not panel._user_scrolled_up:
                self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass
        await asyncio.sleep(0)
```

**Thread safety:** `deactivate()` is called from the event loop (inside `_consume_output`), not from the agent thread. No `call_from_thread` needed.

**Import in `app.py`:** `ThinkingWidget` is defined in `hermes_cli/tui/widgets.py` (new class, added in Step 4). Add `ThinkingWidget` to the existing `from hermes_cli.tui.widgets import (...)` import block in `app.py`. The `query_one(ThinkingWidget)` calls in `_consume_output` and `on_hermes_input_submitted` require this import to resolve.

**Activation** is called from `on_hermes_input_submitted`, which fires on the event loop when the user presses `Enter`. Direct call is safe:

```python
# HermesApp.on_hermes_input_submitted — add at top:
try:
    self.query_one(ThinkingWidget).activate()
except NoMatches:
    pass
```

**Flush guard:** `flush_output()` is called from the agent thread. It enqueues a `None` sentinel. The `None` path in `_consume_output` resets `_first_chunk_in_turn = True`. If the agent sends zero content (empty response), the next `flush_live()` hides `ThinkingWidget` via the `flush_output()` path — but `ThinkingWidget` may still be active. Add a guard in `flush_live()`:

```python
# OutputPanel.flush_live() — add deactivate call:
def flush_live(self) -> None:
    try:
        self.query_one(ThinkingWidget).deactivate()
    except NoMatches:
        pass
    # ... existing flush_live logic unchanged ...
```

`flush_live()` runs on the event loop (called from `_consume_output`) — direct widget call is safe.

### 8.4 Widget implementation

```python
# hermes_cli/tui/widgets.py — new imports needed at top:
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from hermes_cli.tui.animation import lerp_color, pulse_phase

# Shimmer character table: ascending density from space to ▓ and back
_SHIMMER_CHARS = " ░▒▓▒░"
_SHIMMER_LEN   = len(_SHIMMER_CHARS)


class ThinkingWidget(Widget):
    """
    Animated skeleton placeholder shown while the agent is thinking
    (after prompt submission, before first response token arrives).
    """

    DEFAULT_CSS = "ThinkingWidget { height: 1; display: none; }"

    _phase: reactive[int] = reactive(0, repaint=True)
    _shimmer_timer: object | None = None

    def activate(self) -> None:
        """Show shimmer and start animation. Call from event loop only."""
        self.styles.display = "block"
        if self._shimmer_timer is None:
            self._shimmer_timer = self.set_interval(1 / 8, self._advance_phase)

    def deactivate(self) -> None:
        """Hide shimmer and stop animation. Idempotent. Call from event loop only."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self.styles.display = "none"
        self._phase = 0

    def _advance_phase(self) -> None:
        """Timer callback — plain def required (no await)."""
        self._phase = (self._phase + 1) % (_SHIMMER_LEN * 4)

    def render_line(self, y: int) -> Strip:
        # height: 1 → Textual only calls render_line(0), but guard defensively.
        width = self.size.width or 40
        if y != 0:
            return Strip.blank(width)
        phase = self._phase
        segments: list[Segment] = []
        for x in range(width):
            idx = (x + phase) % _SHIMMER_LEN
            char = _SHIMMER_CHARS[idx]
            brightness = idx / max(_SHIMMER_LEN - 1, 1)
            color = lerp_color("#1a1a1a", "#4a4a4a", brightness)
            segments.append(Segment(char, Style(color=color)))
        return Strip(segments).crop(0, width)
```

**Why `render_line()` not `render()`:** `render_line()` provides per-cell control and builds `Strip` directly — no string allocation per line, no `Text` object. For a 120-column shimmer at 8fps: 8 × 120 = 960 segment constructions/second. Textual draws only cells in the viewport — cost is O(visible_columns), not O(terminal_width).

**Style import note:** `from rich.style import Style` — not `textual.css.styles`. These are entirely different types.

### 8.5 Constraints

- `activate()` and `deactivate()` are event-loop-only. Never call from the agent thread. The `call_from_thread` mechanism is not needed here because all call sites (`on_hermes_input_submitted`, `_consume_output`, `flush_live`) run on the event loop.
- `_shimmer_timer` is `None` initially (no event loop resource in `__init__`). `set_interval` only creates the timer when `activate()` is called after `on_mount`.
- Use `add_class("visible")` / `remove_class("visible")` — CSS class names use plain names, not `--visible`. The `styles.display = "none"` / `"block"` approach is used here for clarity (not a CSS class), consistent with the existing overlay implementation.

---

## 9. Technique 4: Context Bar Hue Shift

### 9.1 What it does

`StatusBar._compaction_color(progress)` currently snaps between three fixed colors at the 0.80 and 0.95 thresholds. This technique makes it **smoothly interpolate** between those skin-aware colors within each band using `lerp_color`, eliminating the hard jump.

### 9.2 Existing `_compaction_color` logic

The current implementation (verified from source):

```python
@staticmethod
def _compaction_color(progress: float) -> str:
    try:
        from hermes_cli.skin_engine import get_active_skin
        skin = get_active_skin()
    except Exception:
        skin = None

    if progress >= 0.95:
        return skin.get_ui_ext("context_bar_crit", "#ef5350") if skin else "#ef5350"
    if progress >= 0.80:
        return skin.get_ui_ext("context_bar_warn", "#ffa726") if skin else "#ffa726"
    return skin.get_ui_ext("context_bar_normal", "#5f87d7") if skin else "#5f87d7"
```

This snaps at 0.80 and 0.95 — visually jarring. The fix adds lerp within each band.

### 9.3 Implementation

**Prerequisite:** `hermes_cli/tui/animation.py` (with `lerp_color`) is a **new file created by this spec in Step 0**. This change is applied in Step 1 after `animation.py` exists.

Replace `_compaction_color` with a version that lerps between band boundary colors:

```python
@staticmethod
def _compaction_color(progress: float) -> str:
    from hermes_cli.tui.animation import lerp_color
    try:
        from hermes_cli.skin_engine import get_active_skin
        skin = get_active_skin()
    except Exception:
        skin = None

    color_normal = skin.get_ui_ext("context_bar_normal", "#5f87d7") if skin else "#5f87d7"
    color_warn   = skin.get_ui_ext("context_bar_warn",   "#ffa726") if skin else "#ffa726"
    color_crit   = skin.get_ui_ext("context_bar_crit",   "#ef5350") if skin else "#ef5350"

    if progress >= 0.95:
        return color_crit
    if progress >= 0.80:
        # Lerp from warn → crit across the 0.80–0.95 band
        t = (progress - 0.80) / 0.15
        return lerp_color(color_warn, color_crit, t)
    if progress >= 0.50:
        # Lerp from normal → warn across the 0.50–0.80 band
        t = (progress - 0.50) / 0.30
        return lerp_color(color_normal, color_warn, t)
    return color_normal
```

`lerp_color` is imported inside the method. No top-level import needed since `animation.py` has no Textual imports and will not cause circular import issues, but the lazy import avoids any load-order sensitivity.

The rest of `StatusBar.render()` is unchanged: `_BAR_WIDTH`, `_BAR_FILLED`, `_BAR_EMPTY`, `status_compaction_progress`, and `status_compaction_enabled` all retain their existing names and roles.

### 9.4 Color thresholds (aligned with existing skin system)

| Fill % | Transition | Rationale |
|---|---|---|
| 0–50% | `color_normal` (skin `context_bar_normal`) | Well within limits — solid baseline |
| 50–80% | Normal → warn lerp | Gradual approach to warning zone |
| 80–95% | Warn → crit lerp | Approaching context limit |
| 95–100% | `color_crit` (skin `context_bar_crit`) | At or near limit — full alert |

Thresholds align with the existing 0.80/0.95 snap points. The lerp adds smoothness without changing the thresholds that operators may rely on for visual cues.

### 9.5 Existing test updates required

Two tests in `tests/tui/test_status_widgets.py` use exact-equality assertions at `progress=0.85`. After this change, `0.85` is in the warn→crit lerp band and returns an interpolated color, not the pure warn color. These tests **must** be updated as part of Step 1:

```python
# test_compaction_bar_color_thresholds (line ~93):
# OLD:  assert color(0.85) in ("#ffa726",)
# NEW:
from hermes_cli.tui.animation import lerp_color
expected_085 = lerp_color("#ffa726", "#ef5350", (0.85 - 0.80) / 0.15)
assert color(0.85) == expected_085

# test_compaction_bar_color_from_skin (lines ~212-231):
# OLD:  assert StatusBar._compaction_color(0.85) == "#ffa726"
# NEW:
expected = lerp_color("#ffa726", "#ef5350", (0.85 - 0.80) / 0.15)
assert StatusBar._compaction_color(0.85) == expected

# When a skin is active with color_warn="#ddeeff" and color_crit="#112233":
# OLD:  assert StatusBar._compaction_color(0.85) == "#ddeeff"
# NEW:
expected_skin = lerp_color("#ddeeff", "#112233", (0.85 - 0.80) / 0.15)
assert StatusBar._compaction_color(0.85) == expected_skin

# Assertions at 0.5 and 0.99 are unaffected:
# 0.5: t=0 → lerp(normal, warn, 0) == normal → exact equality still holds
# 0.99: >= 0.95 → returns color_crit directly → exact equality still holds
```

**New band audit required (Step 1):** The new `0.50–0.80` lerp band changes what was previously pure `color_normal` for any `progress` in `[0.50, 0.80)`. When implementing Step 1, search `test_status_widgets.py` for any existing assertions at a `progress` value in `[0.50, 0.80)` (e.g., `color(0.60)`, `color(0.75)`) — these will now fail because they previously returned `color_normal` and will now return a blended value. Update them to use `lerp_color(color_normal, color_warn, (progress - 0.50) / 0.30)` using the same pattern as the `0.85` updates above.

The 12 test count in Step 0 is for `animation.py` pure-function tests only. The `_compaction_color` test updates are part of Step 1 (not new tests; test count for Step 1 stays at 3 new assertions, with the 2 existing ones updated in-place).

---

## 10. Technique 5: `StatusBar` Running-Indicator Pulse

### 10.1 Architecture choice

`StatusBar` currently renders entirely via a single `render()` method — it has no `compose()` and no child widgets. Adding a `RunningIndicator` child would require converting `StatusBar` from a leaf render widget to a composite widget, breaking the existing flat render architecture.

The simpler approach: **`StatusBar` inherits `PulseMixin`**. The `●` character in `StatusBar.render()` reads `self._pulse_t` to interpolate its color. `_pulse_start()` and `_pulse_stop()` are called from an existing watcher. No child widget, no architecture change.

### 10.2 Implementation

**Important:** `watch_<attr>()` on a Widget is only auto-invoked by Textual for reactives defined on that same Widget instance. `agent_running` is defined on `HermesApp`, not `StatusBar`. Defining `watch_agent_running()` on `StatusBar` would be dead code. The correct pattern is to register a custom callback in `on_mount()` using `self.watch(app, attr, callback)`.

The existing `StatusBar.on_mount()` registers all app attributes to `_on_status_change` (which calls `self.refresh()`). Replace the `agent_running` registration with a dedicated `_on_agent_running_change` callback:

```python
from hermes_cli.tui.animation import PulseMixin, lerp_color

class StatusBar(PulseMixin, Widget):
    """Bottom status bar — inherits PulseMixin for running-indicator pulse."""
    DEFAULT_CSS = "StatusBar { dock: bottom; height: 1; }"

    def on_mount(self) -> None:
        app = self.app
        # Register existing attributes to _on_status_change.
        # IMPORTANT: "agent_running" and "status_tok_s" are omitted from this loop —
        # they are registered to dedicated callbacks below. Including them here would
        # double-register them (two independent callbacks), causing duplicate refreshes
        # and conflicting animation + refresh calls.
        for attr in (
            "status_tokens", "status_model", "status_duration",
            "status_compaction_progress", "status_compaction_enabled",
            "command_running",
            "browse_mode", "browse_index", "_browse_total",
            "status_output_dropped",
        ):
            self.watch(app, attr, self._on_status_change)
        # agent_running: dedicated callback to start/stop pulse + refresh:
        self.watch(app, "agent_running", self._on_agent_running_change)
        # status_tok_s: dedicated callback to start animation + (implicitly) refresh
        # via repaint=True on _tok_s_displayed:
        self.watch(app, "status_tok_s", self._on_tok_s_change)

    def _on_agent_running_change(self, running: bool = False) -> None:
        """Start or stop the pulse animation when agent_running changes."""
        # _pulse_enabled() is defined in §13 / widgets.py (module-level config accessor).
        if running and _pulse_enabled():
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def render(self) -> RenderResult:
        # ... existing render logic ...
        # Replace static `Text(" running", style="#ffa726")` with:
        if running:
            if self._pulse_timer is not None:
                # Use timer-running check, NOT _pulse_t > 0 — pulse_phase() returns
                # exactly 0.0 at the bottom of each sine cycle, which would snap the
                # color back to #ffa726 for one frame every 2 seconds.
                pulse_color = lerp_color("#ffa726", "#ffbf00", self._pulse_t)
            else:
                pulse_color = "#ffa726"
            state_t = Text(" ● running", style=f"bold {pulse_color}")
        # ... rest of render unchanged ...
```

**MRO:** `class StatusBar(PulseMixin, Widget)` places `PulseMixin` before `Widget`. `PulseMixin` has no `__init__`, so MRO chaining is trivially safe.

**`_pulse_step` and `refresh`:** `PulseMixin._pulse_step()` calls `self.refresh()`, triggering `StatusBar.render()`. The 15fps pulse drives 15 StatusBar repaints/second while the agent is running. `StatusBar.render()` is O(1) — negligible cost.

**Existing `" running"` text:** The current render uses `Text(" running", style="#ffa726")`. Replace with `Text(" ● running", style=f"bold {pulse_color}")` where `pulse_color` oscillates between `#ffa726` and `#ffbf00` when `_pulse_timer is not None` (pulse running), and stays `#ffa726` when idle (agent just finished, pulse stopped). Do **not** guard on `_pulse_t > 0` — `pulse_phase()` returns exactly `0.0` at the bottom of each sine cycle (tick 0, 30, 60…), which would cause a one-frame color snap every 2 seconds.

### 10.3 Constraints

- `PulseMixin._pulse_step` is a plain `def` — no `await`, so `async def` is prohibited.
- `_pulse_t`, `_pulse_tick`, `_pulse_timer` are class attributes on `PulseMixin` with value `0.0`, `0`, and `None` — safe defaults before `_pulse_start()` is called.
- `lerp_color` must be imported at `widgets.py` module level (not inside `render()`) to avoid per-repaint import cost.

---

## 11. Technique 6: Animated tok/s Counter in `StatusBar`

### 11.1 Architecture constraint

**Textual widgets use either `compose()` (yields children) or `render()` (returns a renderable) — never both.** Once `compose()` mounts children, `render()` is never called. `StatusBar` is a pure `render()` leaf widget with no children. Adding a `compose()` method to host an `AnimatedCounter` child would suppress `render()`, breaking the entire status bar.

Therefore, the animated tok/s counter is implemented **directly on `StatusBar`** using a reactive attribute `_tok_s_displayed` and `Widget.animate()`. No child widget is needed.

`AnimatedCounter` is defined as a standalone reusable widget for future use (not inside `StatusBar`).

### 11.2 Inline implementation on `StatusBar`

```python
class StatusBar(PulseMixin, Widget):
    # New: animated tok/s backing reactive
    _tok_s_displayed: reactive[float] = reactive(0.0, repaint=True)

    def on_mount(self) -> None:
        app = self.app
        # ... existing registrations (for all attributes except status_tok_s) ...
        # status_tok_s gets its own callback for animation:
        self.watch(app, "status_tok_s", self._on_tok_s_change)
        # agent_running gets its own callback for pulse:
        self.watch(app, "agent_running", self._on_agent_running_change)

    def _on_tok_s_change(self, tok_s: float = 0.0) -> None:
        """Animate _tok_s_displayed to new tok/s value."""
        if _animate_counters_enabled():
            self.animate("_tok_s_displayed", float(tok_s), duration=0.2, easing="out_cubic")
        else:
            self._tok_s_displayed = float(tok_s)

    def render(self) -> RenderResult:
        # ... existing render logic ...
        # Replace: tok_s = getattr(app, "status_tok_s", 0.0)
        # With:    tok_s = self._tok_s_displayed
        tok_s = self._tok_s_displayed
        # ... rest of render unchanged: `f"{tok_s:.0f} tok/s"` ...
```

**`widget.animate("_tok_s_displayed", ...)` is correct:** `Widget.animate()` resolves the attribute via `getattr(self, "_tok_s_displayed")`. Since `_tok_s_displayed` is a reactive defined on `StatusBar` (not a dotted path), `getattr` succeeds. The animator interpolates from the current reactive value to the new target, triggering `repaint=True` on every step.

**`_on_tok_s_change` registration:** Registered in `on_mount()` via `self.watch(app, "status_tok_s", self._on_tok_s_change)` — replacing the generic `_on_status_change` registration for that attribute. This is the same pattern used for `agent_running`.

### 11.3 Standalone `AnimatedCounter` widget (for future use)

`AnimatedCounter` is defined in `widgets.py` as a standalone reusable widget. It is **not** mounted inside `StatusBar`. It serves as the documented pattern for animated numeric display in future widgets:

```python
class AnimatedCounter(Widget):
    """
    Reusable leaf widget: smoothly eases a numeric value when updated.
    Use set_target() from the event loop or via call_from_thread.
    """

    DEFAULT_CSS = "AnimatedCounter { height: 1; width: auto; }"

    _displayed: reactive[float] = reactive(0.0, repaint=True)
    _unit: str = ""

    def set_target(self, value: float, unit: str = "") -> None:
        """Animate to value over 200ms. Safe to call from event loop."""
        self._unit = unit
        self.animate("_displayed", float(value), duration=0.2, easing="out_cubic")

    def render(self) -> RenderResult:
        t = Text(str(round(self._displayed)))
        if self._unit:
            t.append(f" {self._unit}", style="dim")
        return t
```

### 11.4 Constraints

- `animate("_tok_s_displayed", ...)` on `StatusBar` cancels any in-progress animation when a new value arrives. Rapid successive changes are safe — the last one wins.
- `_tok_s_displayed` starts at `0.0`. The first `_on_tok_s_change` call animates from 0 → actual, which is correct (tok/s is 0 at session start).
- `_on_tok_s_change` receives the new value as its argument (Textual passes the watched reactive's new value to the callback). Use `tok_s: float = 0.0` default to handle the initial call.
- `_animate_counters_enabled()` is read in `_on_tok_s_change()` — not in `render()`. Checking config once per value change (not per frame) is correct.

---

## 12. Design Decisions

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| `self.styles.animate("opacity", ...)` for fade-in | Yes | `widget.animate("styles.opacity", ...)` | `getattr(widget, "styles.opacity")` fails — Python `getattr` does not traverse dotted paths. `StylesBase.animate()` exists at `styles.py:1408` and correctly resolves `"opacity"` on the `StylesBase` object. |
| `PulseMixin` inherited by `StatusBar` (not a child `RunningIndicator`) | Yes | `RunningIndicator(PulseMixin, Widget)` as a child widget | `StatusBar` is a leaf render widget. Adding a child via `compose()` suppresses `render()` entirely — Textual never calls `render()` on a widget with children. `PulseMixin` inheritance adds the timing infrastructure without touching the architecture. |
| `_on_agent_running_change` callback registered in `on_mount()` | Yes | `watch_agent_running()` method on `StatusBar` | Textual's `watch_<attr>()` auto-invocation only fires for reactives defined on the same object. `agent_running` is defined on `HermesApp`, not `StatusBar`. Must use `self.watch(app, "agent_running", self._on_agent_running_change)`. |
| `_tok_s_displayed` reactive on `StatusBar` + `widget.animate()` | Yes | `AnimatedCounter` child widget inside `StatusBar` | `StatusBar` uses `render()` and cannot simultaneously use `compose()`. A child widget would suppress `render()`. Inline animation via `self.animate("_tok_s_displayed", ...)` achieves the same effect within the leaf render architecture. |
| `_on_tok_s_change` callback replaces `_on_status_change` for `status_tok_s` | Yes | Read `status_tok_s` directly from app in `render()` | Direct read in `render()` would always display the instantaneous value with no animation. The dedicated callback intercepts each value change and starts a `widget.animate()` transition. |
| `ThinkingWidget` inside `OutputPanel.compose()` | Yes | Inside `HermesApp.compose()` | The shimmer must appear in the scrollable output area where streaming content appears. `HermesApp.compose()` contains only the app-level frame (status bar, input, overlays). |
| First-token detection via `_first_chunk_in_turn` local in `_consume_output` | Yes | HermesApp boolean reactive | Local variable inside the existing async consumer avoids polluting `HermesApp` state. Resets automatically on `None` sentinel — zero risk of stale state. |
| `_compaction_color` lerps within skin color bands | Yes | Full replacement with `context_bar_color()` | The existing skin system provides `context_bar_normal/warn/crit` with user-configurable overrides. Replacing it wholesale would ignore skin colors. Lerping *between* the skin colors preserves customization while adding smoothness. |
| Non-typewriter cursor blink as `set_interval(0.5)` + `_blink_timer` | Yes | Always-on blink via second reactive | Only activates when streaming is active (`_blink_timer` is non-None). Zero cost when idle. Preserves the existing typewriter cursor path unchanged. |
| `widget.animate("_tok_s_displayed", ...)` and `widget.animate("_displayed", ...)` | Yes | Custom `set_interval` loop | `Widget.animate()` resolves the attribute via `getattr(self, attr_name)`. Plain attribute names (no dots) work correctly. The built-in animator handles easing, cancellation, and frame scheduling. |
| `lerp_color` in linear RGB | Yes | sRGB gamma-corrected lerp | Gamma correction adds two `** 2.2` calls per channel per frame. For terminal truecolor, visual difference is below human perception threshold. |
| `pulse_phase` period = 30 ticks at 1/15s = 2s cycle | Yes | 1s or 4s | 2-second breathing cycle matches natural human breathing rate — feels organic. |

---

## 13. Configuration

No new config keys for techniques 1, 3, 4 (fade-in, shimmer, context hue). These are unconditional polish.

Techniques 2, 5, 6 (cursor blink, pulse, animated counter) expose opt-out config:

```yaml
# ~/.hermes/config.yaml
display:
  cursor_blink: true            # Non-typewriter cursor blink (default: true)
  running_indicator_pulse: true # PulseMixin on StatusBar running indicator (default: true)
  animate_counters: true        # AnimatedCounter smooth easing (default: true)
```

Config accessor functions added to `widgets.py` (analogous to `_typewriter_enabled()`):

```python
def _cursor_blink_enabled() -> bool:
    try:
        return bool(get_config().get("display", {}).get("cursor_blink", True))
    except Exception:
        return True

def _pulse_enabled() -> bool:
    try:
        return bool(get_config().get("display", {}).get("running_indicator_pulse", True))
    except Exception:
        return True

def _animate_counters_enabled() -> bool:
    try:
        return bool(get_config().get("display", {}).get("animate_counters", True))
    except Exception:
        return True
```

Config accessors (`_cursor_blink_enabled()`, `_pulse_enabled()`, `_animate_counters_enabled()`) are called inside reactive watcher callbacks (`feed()`, `_on_agent_running_change()`, `_on_tok_s_change()`). This is acceptable — watchers fire once per state change, not per frame. Never read config from `render()` or timer callbacks, which fire at high frequency (8–15×/s).

---

## 14. Files Changed

### New files

| File | Purpose |
|---|---|
| `hermes_cli/tui/animation.py` | `lerp`, `ease_out_cubic`, `ease_in_out_cubic`, `pulse_phase`, `lerp_color`, `PulseMixin` |
| `tests/tui/test_animation.py` | Unit tests for all animation utilities + `PulseMixin` |

### Modified files

| File | Changes |
|---|---|
| `hermes_cli/tui/widgets.py` | New top-level imports: `from rich.segment import Segment`; `from rich.style import Style`; `from textual.strip import Strip`; `from hermes_cli.tui.animation import PulseMixin, lerp_color, pulse_phase` (one import line for all three animation names). `MessagePanel.on_mount()`: opacity fade-in via `self.styles.animate("opacity", ...)`. `LiveLineWidget`: `_blink_visible`, `_blink_timer` in `on_mount`; `_toggle_blink()`; update `feed()`, `on_unmount()`, `render()` for non-typewriter cursor. `ThinkingWidget`: new class with `render_line()`, `activate()`, `deactivate()`. `OutputPanel.compose()`: yield `ThinkingWidget(id="thinking")` between `ToolPendingLine` and `LiveLineWidget`. `OutputPanel.flush_live()`: add `ThinkingWidget.deactivate()` call. `StatusBar`: inherit `PulseMixin`; change `on_mount()` to register `agent_running → _on_agent_running_change` and `status_tok_s → _on_tok_s_change` (replacing generic `_on_status_change` for those two attributes); add `_tok_s_displayed: reactive[float]`; add `_on_agent_running_change()`; add `_on_tok_s_change()`; update `_compaction_color()` with lerp; update `render()` for pulsing `● running` text and `_tok_s_displayed`. Add config accessors: `_cursor_blink_enabled()`, `_pulse_enabled()`, `_animate_counters_enabled()`. `AnimatedCounter`: new standalone class (not mounted in `StatusBar`). |
| `hermes_cli/tui/app.py` | `_consume_output()`: add `_first_chunk_in_turn` local flag; call `ThinkingWidget.deactivate()` on first non-None chunk per turn. `on_hermes_input_submitted()`: add `ThinkingWidget.activate()` call at top (event-loop safe). `on_key()` ctrl+c interrupt path: add `OutputPanel.flush_live()` call so the blink timer is stopped when the agent is interrupted mid-stream. |
| `tests/tui/test_output_panel.py` | Add: `ThinkingWidget` activates on submit; deactivates on first chunk; deactivates on `flush_live`. |
| `tests/tui/test_status_widgets.py` | Add: `_compaction_color(0.3)` returns normal color; `_compaction_color(0.7)` is between normal and warn; `_compaction_color(0.9)` is between warn and crit; `_on_agent_running_change(True)` starts pulse; `_on_agent_running_change(False)` stops pulse; `_on_tok_s_change(150)` animates `_tok_s_displayed`; `AnimatedCounter.set_target()` works standalone. |
| `tests/tui/test_typewriter.py` | Add: non-typewriter `feed()` starts blink timer; `flush()` stops timer; no double cursor when `_animating=True` and blink timer set. |

---

## 15. Implementation Plan

**Step 0 — `animation.py` module + pure tests (no Textual)**  
Create `hermes_cli/tui/animation.py` with all pure functions and `PulseMixin`.  
Tests: `lerp` at t=0/0.5/1; `ease_out_cubic` at endpoints; `ease_in_out_cubic` symmetry; `pulse_phase` period; `lerp_color` known values; `lerp_color` clamps to valid hex; `PulseMixin._pulse_step` advances `_pulse_t`; `_pulse_stop` resets `_pulse_t=0`.  
**Target: 12 tests. Accumulated: 12**

**Step 1 — Context bar hue shift (zero new widgets)**  
Replace `StatusBar._compaction_color()` body with the lerp-between-skin-colors implementation.  
Add `from hermes_cli.tui.animation import lerp_color` to `widgets.py` top-level imports.  
Update 2 existing test assertions in `test_status_widgets.py` (lines ~99, ~217, ~230) from exact-equality at `progress=0.85` to `lerp_color(warn, crit, t)` expected values — per §9.5.  
3 new assertions: `_compaction_color(0.3)` returns `color_normal`; `_compaction_color(0.7)` is between normal and warn; `_compaction_color(0.9)` is between warn and crit.  
**Target: 3 new + 2 updated assertions. Accumulated: 15 new tests (+ 2 existing assertions updated in place)**

**Step 2 — `MessagePanel` fade-in**  
Add `on_mount()` to `MessagePanel` with `self.styles.opacity = 0.0` + `self.styles.animate("opacity", 1.0, ...)`.  
Tests: after mount + `await pilot.pause()`, opacity is not yet 1.0 (animation in progress); after `await asyncio.sleep(0.3)` + `await pilot.pause()`, `styles.opacity == 1.0`.  
**Target: 2 tests. Accumulated: 17**

**Step 3 — Non-typewriter cursor blink in `LiveLineWidget`**  
Add `_blink_visible`, `_blink_timer` to `on_mount`; add `_toggle_blink()`; update `feed()`, `on_unmount()`, `render()`. Also update `HermesApp.on_key()` ctrl+c interrupt path to call `OutputPanel.flush_live()`, ensuring the blink timer is stopped when the user interrupts a mid-stream response.  
Tests: no blink before `feed()`; blink timer starts after first `feed()` with typewriter disabled; `flush()` stops timer; `_blink_visible=True` after `flush()`; no `▌` in render when typewriter active and `_animating=True` (no double cursor); `▌` appears in render when blink active and `_blink_visible=True`.  
**Target: 6 tests. Accumulated: 23**

**Step 4 — `ThinkingWidget` skeleton shimmer**  
Implement `ThinkingWidget` class. Update `OutputPanel.compose()`. Update `OutputPanel.flush_live()`. Update `HermesApp._consume_output()`. Update `HermesApp.on_hermes_input_submitted()`.  
Tests: hidden (`display:none`) before submit; visible (`display:block`) after `activate()`; hidden after `deactivate()`; `render_line(0)` returns strip of correct width; `render_line(1)` returns blank strip; phase advances after timer tick; `deactivate()` idempotent (second call is a no-op).  
**Target: 7 tests. Accumulated: 30**

**Step 5 — `StatusBar` running-indicator pulse**  
Change `StatusBar` base to `StatusBar(PulseMixin, Widget)`. Add `_pulse_enabled()` config accessor. Wire `_pulse_start/stop` to the `agent_running` watcher in `StatusBar.on_mount()`. Update `StatusBar.render()` to use `lerp_color(...)` + `self._pulse_t` for the `●` indicator. Guard pulse activation with `_pulse_enabled()`.  
Tests: `_pulse_t` advances after timer ticks with agent_running=True; `_pulse_stop()` resets `_pulse_t` to 0; render includes `●` when running; `●` color changes when `_pulse_timer is not None` and `_pulse_t` is non-zero (mid-cycle).  
**Target: 4 tests. Accumulated: 34**

**Step 6 — `AnimatedCounter` + `StatusBar` inline tok/s animation**  
Implement standalone `AnimatedCounter` widget (not mounted in `StatusBar`). Add `_tok_s_displayed: reactive[float]` to `StatusBar`. Add `_on_tok_s_change()` calling `self.animate("_tok_s_displayed", ...)`. Register `status_tok_s → _on_tok_s_change` in `StatusBar.on_mount()`. Update `StatusBar.render()` to read `self._tok_s_displayed` for tok/s display. Add `_animate_counters_enabled()` config accessor.  
Tests: `StatusBar._tok_s_displayed` reaches animation target after `_on_tok_s_change()` + delay; second `_on_tok_s_change()` before first completes → final value is second target; `StatusBar.render()` reads `_tok_s_displayed` (not raw `status_tok_s`); `AnimatedCounter.set_target()` animates `_displayed` standalone; `AnimatedCounter.render()` shows rounded value with unit.  
**Target: 5 tests. Accumulated: 39**

**Step 7 — Integration**  
End-to-end: submit prompt → `ThinkingWidget` active → first chunk arrives → `ThinkingWidget` hidden; agent running → pulse starts; agent done → pulse stops; context update → bar color changes.  
**Target: 3 tests. Accumulated: 42**

---

## 16. State Changes

| Field | Type | Where | Read by |
|---|---|---|---|
| `LiveLineWidget._blink_visible` | `bool` (instance) | `LiveLineWidget.on_mount()` | `render()`, `_toggle_blink()` |
| `LiveLineWidget._blink_timer` | `object \| None` (instance) | `LiveLineWidget.on_mount()` | `feed()`, `flush()`, `on_unmount()` |
| `ThinkingWidget._phase` | `reactive[int]` | `ThinkingWidget` | `render_line()` |
| `ThinkingWidget._shimmer_timer` | `object \| None` (instance) | `ThinkingWidget` | `activate()`, `deactivate()` |
| `PulseMixin._pulse_t` | `float` (class attr, shadowed per-instance on first write) | mixin | `StatusBar.render()` |
| `PulseMixin._pulse_tick` | `int` (class attr, shadowed per-instance on first write) | mixin | `_pulse_step()` |
| `PulseMixin._pulse_timer` | `object \| None` (class attr, shadowed per-instance on first write) | mixin | `_pulse_start()`, `_pulse_stop()` |
| `AnimatedCounter._displayed` | `reactive[float]` | `AnimatedCounter` | `render()`, `animate()` target |
| `AnimatedCounter._unit` | `str` (instance) | `AnimatedCounter` | `render()` |
| `_first_chunk_in_turn` | `bool` (local in `_consume_output`) | coroutine local | First-chunk detection |

No `OrchestratorState` fields modified. All state is display-layer only.

---

## 17. Capabilities Required

None. All animation is display-layer. No LLM calls, no tool execution, no filesystem access.

---

## 18. Cost Impact

Zero. No API calls, no tokens, no I/O.

---

## 19. Error Conditions

| Condition | Handling |
|---|---|
| `styles.animate()` called before widget is mounted | Textual silently ignores — animate is a no-op if app not running. No crash. |
| `_shimmer_timer.stop()` / `_blink_timer.stop()` called after widget unmounted | Textual auto-cancels `set_interval` timers on unmount; calling `.stop()` on an already-cancelled timer is a no-op. |
| `ThinkingWidget.deactivate()` called when already inactive | `_shimmer_timer is None` guard prevents double-stop; `styles.display = "none"` is idempotent. |
| `lerp_color` receives malformed hex (missing `#`, wrong length) | `int(h[0:2], 16)` raises `ValueError`. All call sites pass string literals or `skin.get_ui_ext()` output (which returns validated hex strings). Not a runtime path for user input. |
| `self.size.width == 0` in `ThinkingWidget.render_line()` | `or 40` fallback produces a 40-cell shimmer strip — acceptable for the pre-layout render. |
| `_pulse_step` fires after `agent_running` set to False but before `_pulse_stop()` watcher fires | `_pulse_t` advances one extra step — harmless. The watcher fires on the same event loop iteration as the reactive change. |
| `_toggle_blink` fires after `flush()` but before timer is fully stopped | Textual cancels `set_interval` timers synchronously in `.stop()`. The callback cannot fire after `.stop()` returns. Not reachable. |
| Config read raises exception in `_pulse_enabled()` | `except Exception: return True` default — animation enabled by default. |

---

## 20. Determinism Impact

None. All animation drives cosmetic state only. The agent loop, tool execution, and response generation are unaffected.

---

## 21. Backward Compatibility

- `LiveLineWidget.feed()` and `flush()` signatures are preserved. New state (`_blink_*`) is initialized in `on_mount()` and guarded with `getattr(..., None)` in all access sites.
- `MessagePanel.on_mount()` is new (previously absent). No existing code calls it.
- `OutputPanel.compose()` gains `ThinkingWidget`. It starts `display: none` — no visual regression.
- `OutputPanel.flush_live()` gains a `deactivate()` call. The call is `try/except NoMatches` guarded — harmless if `ThinkingWidget` is absent.
- `StatusBar` base class change (`PulseMixin, Widget`) adds no attributes that conflict with existing `StatusBar` state.
- `StatusBar` gains `_tok_s_displayed: reactive[float]` and `_on_tok_s_change()` method. It remains a pure `render()` leaf widget — no `compose()` is added, no child widgets are mounted.
- No config YAML migration required. New keys default to `true`, matching current implicit behavior.

---

## 22. Test Plan

| Step | Tests | Focus |
|---|---|---|
| 0 — `animation.py` | 12 | `lerp` / `ease_out_cubic` / `pulse_phase` / `lerp_color` correctness; `PulseMixin` tick + stop |
| 1 — Context hue | 3 new + 2 updated | New: normal at 30%, blend at 70%, blend at 90%; Updated: exact-equality at 0.85 → lerp-expected (§9.5) |
| 2 — Fade-in | 2 | Opacity 0 after mount; opacity 1.0 after 300ms |
| 3 — Cursor blink | 6 | No blink pre-feed; starts post-feed; flush stops; visible reset after flush; no double cursor; `▌` when blink active |
| 4 — ThinkingWidget | 7 | Hidden pre-submit; visible post-activate; hidden post-deactivate; render_line width; y≠0 guard; phase advance; idempotent deactivate |
| 5 — Pulse | 4 | `_pulse_t` advances; stop resets; render `●` when running; color changes with pulse |
| 6 — AnimatedCounter | 5 | `_tok_s_displayed` reaches target; second wins; `render()` reads `_tok_s_displayed`; `AnimatedCounter.set_target()` animates standalone; `AnimatedCounter.render()` shows value + unit |
| 7 — Integration | 3 | Submit→shimmer→token; running→pulse→stopped; context update→color |
| **Total** | **42 new + 2 updated** | |

**Baseline:** 341 tests. **Target:** ≥ 383 (341 + 42 new).

---

## 23. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `styles.animate("opacity", ...)` not supported in Textual 8.2.3 | Low | Medium | `StylesBase.animate` confirmed at `styles.py:1408`. Fallback: set `opacity=1.0` immediately in `on_mount()` — degrades to no animation, not a crash. |
| `ThinkingWidget.render_line()` called with `size.width=0` during test | Medium | Low | `or 40` fallback + test asserts `len(strip) == 40` when width not set. |
| `PulseMixin` MRO conflict with future `Widget` subclass changes | Low | Medium | `PulseMixin` has no `__init__`, no `super()` calls, no `Widget` attribute overlap. MRO is trivially safe. |
| `AnimatedCounter.animate("_displayed", ...)` interrupted by rapid `set_target()` | Medium | Low | Textual animator cancels in-progress animation when a new one starts for the same attribute. Final value is always the latest call. |
| `_blink_timer` not stopped if agent interrupted mid-stream | Medium | Medium | Add `flush()` call to the interrupt path in `HermesApp.on_key()` (ctrl+c during streaming). `flush()` already handles the empty-blink-timer guard via `getattr(..., None)`. |
| `ThinkingWidget` shimmer visible if agent sends empty response | Low | Low | `flush_live()` calls `deactivate()` as final guard, covering empty-response case. |
| `PulseMixin._pulse_step` fires one extra time after `_pulse_stop()` | Low | Low | `_pulse_stop()` calls `.stop()` on the timer handle synchronously. No further callbacks after that point. |

---

## 24. Deferred

### ToolBlock height animation

`ToolBlock.toggle()` currently swaps `display: none/block` instantly. An animated height transition would require:
1. Measuring `ToolBodyContainer`'s natural height before collapse.
2. Calling `styles.animate("height", target_px, duration=0.15)`.
3. Restoring `height: auto` after expand animation completes (via `on_complete` callback).

The complexity (measuring natural height before a `display: none` transition) is disproportionate to the payoff. Deferred.

### Entrance animation for `ToolBlock`

Opacity fade-in on mount (as with `MessagePanel`) is feasible but adds visual noise for short tool outputs (≤3 lines). Deferred pending user feedback on whether tool block entrance animation adds value.
