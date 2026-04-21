---
name: tui-development
description: >
  Textual 8.x TUI development for the hermes-agent project. Covers widget patterns,
  thread safety, testing with run_test/pilot, CSS theming, reactive state, and all
  known Textual 8.x gotchas. TRIGGER when: building, fixing, or auditing hermes TUI
  components; adding new widgets, overlays, animations, or bindings.
version: "1.1"
author: Hermes Agent
metadata:
  hermes:
    tags: [tui, textual, ui, widgets, css, testing, reactive]
    related_skills: [systematic-debugging, test-driven-development]
---

# TUI Development — Hermes Agent

---

## Codebase structure

### HermesApp mixin map

`app.py` (1701L) delegates all method groups to focused mixin files:

| File | Class | Key methods |
|---|---|---|
| `_app_utils.py` | (module-level) | `_CPYTHON_FAST_PATH`, `_log_lag`, `_run_effect_sync` |
| `_app_io.py` | `_AppIOMixin` | `_consume_output`, `_commit_lines`, `flush_output` |
| `_app_spinner.py` | `_SpinnerMixin` | `_tick_spinner`, `_set_hint_phase`, `_compute_hint_phase` |
| `_app_tool_rendering.py` | `_ToolRenderingMixin` | `mount_tool_block`, `open/close_streaming_tool_block` |
| `_app_browse.py` | `_BrowseMixin` | `watch_browse_mode`, `_rebuild_browse_anchors`, `_jump_anchor` |
| `_app_context_menu.py` | `_ContextMenuMixin` | `on_click`, `_show_context_menu_at`, `_build_context_items` |
| `_app_sessions.py` | `_SessionsMixin` | `_init_sessions`, `_switch_to_session`, `_create_new_session` |
| `_app_theme.py` | `_ThemeMixin` | `get_css_variables`, `apply_skin`, `_flash_hint`, `_copy_text_with_hint` |
| `_app_commands.py` | `_CommandsMixin` | `_handle_tui_command`, `_initiate_undo`, `_run_rollback_sequence` |
| `_app_overlay_watchers.py` | `_OverlayWatchersMixin` | `watch_clarify/approval/sudo/secret/undo/status_error_state` |
| `_app_watchers.py` | `_WatchersMixin` | `watch_size/compaction/voice/attached_images`, file-drop helpers |
| `_app_key_handler.py` | `_KeyHandlerMixin` | `on_key` (full dispatcher), `on_hermes_input_submitted` |
| `_browse_types.py` | (shared types) | `BrowseAnchorType`, `BrowseAnchor`, `_is_in_reasoning` |

Class declaration order (all mixins must precede `App`):
```python
class HermesApp(
    _AppIOMixin, _SpinnerMixin, _ToolRenderingMixin,
    _BrowseMixin, _ContextMenuMixin, _SessionsMixin,
    _ThemeMixin, _CommandsMixin,
    _OverlayWatchersMixin, _WatchersMixin, _KeyHandlerMixin,
    App
):
```

### Module split map

| Original file | Split into |
|---|---|
| `app.py` (2911L) | 12 `_app_*.py` mixins + 1701L core |
| `drawille_overlay.py` | `anim_engines.py` (engines) + core |
| `tool_blocks.py` | `tool_blocks/` subpackage: `_shared.py`, `_header.py`, `_block.py`, `_streaming.py` |
| `widgets/renderers.py` | `code_blocks.py`, `inline_media.py`, `prose.py` (renderers.py kept as re-export shim) |
| `input_widget.py` (908L) | `input/` subpackage: `_constants.py`, `_history.py`, `_path_completion.py`, `_autocomplete.py`, `widget.py` |

`input_widget.py` kept as a 5-line backward-compat shim — all old importers unchanged.

### Parallel sessions architecture

- Each session = git worktree + branch + process. Active: `HermesApp` (full TUI). Background: `HeadlessSession` (no Textual import).
- Session data in `session_dir/sessions.json` (fcntl.flock on writes); each session has `state.json`, `notify.sock`, `output.jsonl`.
- **Session switch** via `self.exit(callback=lambda: os.execvp(...))` — never call `execvp` from the event loop. Flush to `output.jsonl` before exec.
- **Headless output hook**: module-level `_output_hook: Optional[Callable] = None` in `cli.py`; `_cprint` calls it if set; `HeadlessSession.__init__` sets it; `_on_complete` clears it.
- **Cross-process notify**: background sends newline-delimited JSON to active session's `notify.sock`; `_NotifyListener` daemon calls `app.call_from_thread(...)` on receipt.
- **Socket path limit**: ~104 chars (macOS) / ~108 chars (Linux) — validate on create. Startup-race notifications silently dropped — acceptable.
- **Dock stacking**: multiple `dock: bottom` widgets stack bottom-to-top in compose order. `_SessionNotification` uses `layer: overlay` + `dock: bottom` to float above without disturbing others.
- **Orphan detection**: `os.kill(pid, 0)` + `/proc/<pid>/cmdline` check for `--worktree-session-id <id>` guards against PID reuse.
- **Branch pre-validation**: run `git show-ref --verify --quiet refs/heads/<branch>` before `git worktree add` for cleaner error without partial state.
- **2s polling**: `SessionIndex.read()` in event loop is fine at 2s (tiny JSON, ~0.1ms). Move to worker only on slow filesystems.

---

## Recent changes

### 2026-04-21 — Module splits (drawille / tool_blocks / renderers / input)

**Track B — drawille**: `anim_engines.py` holds `AnimParams`, `AnimEngine`, `TrailCanvas`, `_BaseEngine`, 20 engine subclasses, `CompositeEngine`, `CrossfadeEngine`. Deleted duplicate `_GalleryPreview(Widget)` + `AnimGalleryOverlay(Widget)` that were shadowing `ModalScreen` versions (pre-existing test failure fixed).

**Track C — tool_blocks subpackage**: `OmissionBar` placed in `_shared.py` not `_streaming.py` to break circular import: `_block.py` needs `OmissionBar`; `_streaming.py` needs `ToolBlock` from `_block.py`. After splitting, `renderers.py` re-exports all public symbols so existing importers compile unchanged.

**Track D — renderers split**: Fixed `rich.strip.Strip` → `textual.strip.Strip` (Rich has no `strip` module).

**input/ subpackage**: `HermesInput` MRO must be `(_HistoryMixin, _AutocompleteMixin, _PathCompletionMixin, TextArea, ...)` — TextArea defines `update_suggestion`, which shadows the mixin's version if TextArea comes first.

**After any module split — two required steps**:
1. Add re-export lines to the original file (or `__init__.py`) so old importers still work.
2. Check for module-level names (e.g. `random`, `re`) that the old file imported but the new module does not.

### 2026-04-21 — app.py 4-phase mixin extraction

Unique gotchas from this work (patterns are in Framework sections below):

- **Shared types in `_browse_types.py`**: `_app_browse.py` needs `BrowseAnchorType`/`BrowseAnchor` but can't import from `app.py`. Extracted shared types to `_browse_types.py`; both files import from there.
- **Duplicate constants across mixin boundary**: `_KNOWN_SLASH_COMMANDS` exists in both `app.py` and `_app_key_handler.py`. Keep in sync manually.
- **Edit tool fails after Python-script modification**: Use `python3 - <<'PYEOF' ... PYEOF` string-replace scripts throughout. Edit tool raises "file modified since read" after the first script touch — stick to scripts for the whole session.
- **Duplicate method bug (pre-existing)**: `app.py` had a second session block (appended during branch merges) that re-defined cached methods with inferior disk-reading versions — actively wrong behavior. Always `grep -n "def method_name"` across a file before assuming a method definition is unique.

### 2026-04-21 — UX audits (Pass 9 + Full UX Audit, ~45 fixes)

Key behavioral specs implemented (structural patterns are in Framework):

- `CodeBlockFooter.flash_copy()`: flashes "✓ Copied" for 1.5 s via `_copy_flash_timer`; `--flash-copy { color: $success; }` in DEFAULT_CSS.
- `ToolPanel.action_rerun()`: calls `self._header_bar.flash_rerun()` → pulses glyph to "streaming" for 600 ms then restores `_last_state`.
- `CountdownMixin._countdown_start_time: float = 0.0`; `_build_countdown_strip()` uses `lerp_color("#5f87d7", "#ef5350", t)` for smooth color. Urgency prefix `"⚠ "` at ≤3 s, `"⚠⚠ "` at ≤1 s; suppressed when `HERMES_NO_UNICODE` or `HERMES_ACCESSIBLE`.
- StatusBar browse badge format: `BROWSE ▸N/M · L{level}`; `browse_detail_level: reactive[int]` on `HermesApp`; `_apply_browse_focus()` sets it from focused `ToolPanel.detail_level`.
- `VirtualCompletionList.empty_reason: reactive[str]`; `_EMPTY_REASON_TEXT` dict; `watch_items` resets to `""` when items arrive.
- `FooterPane._narrow_diff_glyph` (Static "±") shown in compact mode when diff present.
- `CompletionOverlay.on_resize` caps `max_height = max(4, h-8)`; DEFAULT_CSS `min-height: 4`.
- `HelpOverlay.show_overlay()` clears search input and repopulates full command list on every open.
- `SessionOverlay._update_selection()` calls `scroll_to_widget` to keep selected row visible.
- `WorkspaceOverlay.show_overlay()` focuses `#ws-tab-git` button on open.
- Error-aware placeholder: when agent stops with `status_error` set, `HermesInput.placeholder` shows `Error: <snippet>… (Esc to clear)`.
- `Chip.remediation` strings from all chips joined with ` · ` into `FooterPane._remediation_row`. Not inline in chip row.
- `generic_result_v4` single-line threshold: `primary = f"✓ {n} lines" if n > 1 else "✓"` — single-line gives bare `"✓"`.
- `set_result_summary_v4` merged into `set_result_summary` — single method handles accent state, mini-mode, hero chip, promoted chips, error banner, age timer, auto-collapse, footer render. `ResultSummary` (old dataclass) still exists for v2 parsers but is no longer accepted. App callers always pass `ResultSummaryV4`.

### 2026-04-21 — API renames to track

| Old (removed) | New |
|---|---|
| `action_prev_turn` | `action_jump_turn_prev` |
| `action_next_turn` | `action_jump_turn_next` |
| scroll-based turn nav (`scroll_visible()`) | `app._jump_anchor(direction, anchor_type)` on `_browse_anchors` |
| `set_result_summary_v4` | `set_result_summary` (merged) |

---

## Framework: Textual 8.2.3

### Import paths

```python
from textual.app import App, ComposeResult
from textual.widgets import Static, Button, Input, RichLog, Label
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual import events, work
from textual.worker import get_current_worker
from textual.reactive import reactive
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message  # needed for inner Message subclasses
```

### Reactive state

```python
class MyApp(App):
    my_value: reactive[str] = reactive("")

    def watch_my_value(self, old: str, new: str) -> None:
        ...
```

Watchers run synchronously on the event loop. Never do blocking I/O in a watcher.

**Manually calling `watch_*` does NOT update the reactive value**: `widget.watch_has_focus(False)` invokes the callback but `widget.has_focus` stays unchanged. Track display state in a plain bool attribute the watcher writes to; read that, not the reactive, in other methods:

```python
def __init__(self):
    self._hint_visible: bool = False

def watch_has_focus(self, value: bool) -> None:
    self._hint_visible = value
    ...

def on_resize(self, event) -> None:
    if self._hint_visible:  # NOT self.has_focus
        self._set_hint(...)
```

**`int()` casts in watchers**: Tests that call `widget.watch_collapsed(False)` with a mock `_block` will trigger `len(mock._all_plain)` → MagicMock → TypeError. Wrap restore/expand blocks in `try/except` and cast explicitly:

```python
try:
    saved = int(self._saved_visible_start)
    total = int(len(self._block._all_plain))
except Exception:
    pass
```

### Worker pattern

```python
@work(thread=True)   # CPU or blocking I/O
def _load_file(self) -> None:
    data = open(...).read()
    self.call_from_thread(self._display, data)

@work            # async — runs in event loop
async def _do_search(self, query: str) -> None: ...

# Cancel previous before starting new:
def _search(self, query: str) -> None:
    self._search_worker = self.run_worker(self._do_search(query), exclusive=True)
```

### Thread safety

- `call_from_thread(fn, *args)` — schedule callback on event loop from worker thread
- Never call `self.query_one()` or widget setters from a `@work(thread=True)` worker
- `get_current_worker().is_cancelled` — check cancellation in long loops

### MRO rules (mixins + Textual)

**Always list mixins BEFORE the Textual base class.** Textual bases (TextArea, Widget, App) define many methods — placing them first causes them to shadow your mixin's overrides:

```python
# WRONG — TextArea.update_suggestion shadows _HistoryMixin.update_suggestion
class HermesInput(TextArea, _HistoryMixin, can_focus=True): ...

# CORRECT — mixin found first in MRO
class HermesInput(_HistoryMixin, TextArea, can_focus=True): ...
```

This applies to `App` subclasses with multiple mixins too — see HermesApp declaration above.

**`PulseMixin`**: `PulseMixin.__init_subclass__` warns at class-definition time if `Widget` appears before `PulseMixin` in MRO. Use `class Foo(PulseMixin, Widget): ...`.

**Mixin self-references**: Mixins access attributes defined on the host class. Use `# type: ignore[attr-defined]` on all such accesses — at runtime `self` is always the concrete class:
```python
class _WatchersMixin:
    def watch_size(self, size: Any) -> None:
        self.query_one(HintBar)  # type: ignore[attr-defined]
        self._flash_hint("...", 2.0)  # type: ignore[attr-defined]
```

### BINDINGS

```python
BINDINGS = [
    Binding("ctrl+shift+a", "select_all", "Select all", show=False),
    Binding("f2", "show_usage", "Usage", show=True),
    Binding("escape", "dismiss", "Close", show=False),
]
```

**`ctrl+a` conflicts** with terminal select-all in many terminals — use `ctrl+shift+a`.

### compose() vs __init__ for widget attributes

Attributes assigned in `compose()` (e.g. `self._foo = Static(...)`) are only set after mounting. `hasattr(widget, "_foo")` fails on a freshly constructed (unmounted) widget. Declare in `__init__` as `self._foo: Static | None = None`; assign in `compose()`.

**Widgets dropped from `compose()` leave broken state references**: If a widget is no longer yielded in `compose()`, any `self._widget` reference becomes `None` and `self._widget.state = ...` silently fails or crashes. After a refactor, grep every `self._attr =` in `__init__`/`compose()` and confirm the widget is still yielded.

**Default placeholder must reach `TextArea.__init__`**: Assigning `self._idle_placeholder` after `super().__init__()` does NOT update the displayed placeholder:
```python
def __init__(self, *, placeholder: str = "", ...) -> None:
    _default = "Type a message  @file  /  commands"
    _effective = placeholder if placeholder else _default
    super().__init__(..., placeholder=_effective, ...)
    self._idle_placeholder: str = _effective  # keep in sync
```

### Overlay show/hide pattern

All overlays in this codebase use **pre-mount + `--visible` toggle**. Dynamically mounting/removing overlays breaks `_hide_all_overlays()` and requires `try/except NoMatches` everywhere.

```python
# In App.compose():
yield MyOverlay(id="my-overlay")  # always in DOM, display:none by default

# Show:
def show_overlay(self) -> None:
    self.add_class("--visible")
    try:
        self.query_one("#search-input", Input).value = ""  # reset stale state
    except NoMatches:
        pass
    self.call_after_refresh(self._focus_default)

# Hide:
def hide_overlay(self) -> None:
    self.remove_class("--visible")  # NOT self.remove()
```

Tests check `overlay.has_class("--visible")`, not DOM presence. `_hide_all_overlays()` iterates overlay classes and calls `remove_class("--visible")` — works because they're always in DOM.

**`query_one()` vs `query()` when the same class is pre-mounted**: If `App.compose()` mounts `ToolPanelHelpOverlay(id="tool-panel-help-overlay")` and a test mounts another instance, `query_one(ToolPanelHelpOverlay)` returns the pre-mounted one. Use `query()` whenever multiple instances can exist:

```python
# WRONG — finds pre-mounted widget, ignores test's instance
self.query_one(ToolPanelHelpOverlay).remove_class("--visible")

# CORRECT
for w in self.query(ToolPanelHelpOverlay):
    w.remove_class("--visible")
```

### CSS / TCSS

```css
/* Custom CSS variables MUST be declared in .tcss, not just get_css_variables() */
$spinner-shimmer-dim: #555555;
$spinner-shimmer-peak: #d8d8d8;

HelpOverlay > #help-content {
    scrollbar-size-vertical: 1;
    scrollbar-color: $text-muted 30%;
}
```

New `$var-name` refs must be declared in the `.tcss` file at parse time — `get_css_variables()` alone is insufficient.

**CSS class operations require `_classes`** (set by `DOMNode.__init__`): Calling `add_class`/`remove_class` on `object.__new__(SomeWidget)` raises `AttributeError`. In production methods exercised by unit tests, wrap CSS mutations:
```python
try:
    self.remove_class(f"-l{old}")
    self.add_class(f"-l{new}")
except AttributeError:
    pass
```

### HintBar / flash system

```python
# Timed flash (expires after duration seconds):
self._flash_hint("Message", 2.0)

# Respect timed flash before clearing — don't overwrite an active flash:
if _time.monotonic() >= self._flash_hint_expires:
    self.query_one(HintBar).hint = ""
```

Widget-level flash variants:
- `CodeBlockFooter.flash_copy()` — flashes "✓ Copied" for 1.5 s, CSS class `--flash-copy`
- `ToolHeader.flash_rerun()` — pulses glyph to "streaming" for 600 ms then restores `_last_state`

### CompletionOverlay

`THRESHOLD_COMP_NARROW = 80` — overlay gets `--narrow` CSS class when terminal width < 80. First-call guard: always apply narrow class when `_last_applied_w == 0`.

Add `--no-preview` class to hide `PreviewPanel` and expand `VirtualCompletionList`:
```css
CompletionOverlay.--no-preview PreviewPanel { display: none; }
CompletionOverlay.--no-preview VirtualCompletionList { width: 1fr; }
```

`watch_highlighted_candidate()` adds `--no-preview` to `CompletionOverlay` when candidate is `None`.

### AnimationClock

`AnimationClock.subscribe(divisor, cb)` clamps `divisor = max(1, int(divisor))` and logs a warning if clamped. Always pass integer divisors.

### Desktop notify gate

```python
# In __init__:
self._last_keypress_time: float = 0.0

# In on_key:
self._last_keypress_time = _time.monotonic()

# In _maybe_notify:
since_key = _time.monotonic() - self._last_keypress_time
if since_key < 5.0:
    return  # user is watching, skip notify
```

### Scroll

```python
# scroll_y setter — fine for reactive watchers, avoids double-repaint:
self.scroll_y = new_y
# Imperative scroll:
scroll_widget.scroll_to_widget(target_widget, animate=False)
```

### Local import shadowing module-level alias

```python
import time as _time  # module level

def watch_agent_running(self, value: bool) -> None:
    if value:
        import time as _time  # BUG: treats _time as local throughout the function
        self._turn_start_time = _time.monotonic()
    # Later in same function, value=False branch:
    if _time.monotonic() >= self._flash_hint_expires:  # UnboundLocalError!
```

Python sees any `import X as Y` assignment anywhere in a function scope and treats `Y` as local throughout. Never re-import inside a conditional branch.

### accessibility_mode()

```python
from hermes_cli.tui.constants import accessibility_mode
if accessibility_mode():
    # Use ASCII fallbacks instead of Unicode box-drawing chars
    ...
```

Reads `HERMES_NO_UNICODE` and `HERMES_ACCESSIBLE` env vars at call time — not cached at import.

### browse_mode watcher self-reset guard

`watch_browse_mode` immediately resets `self.browse_mode = False` if no ToolHeaders exist in DOM. Tests that set `app.browse_mode = True` directly will see it reset to False. Mount real ToolHeaders first, or test the render logic structurally via `inspect.getsource`.

---

## Testing patterns

### Running tests

**NEVER run `python -m pytest tests/tui/`** — full suite always times out (2900+ tests). Run only targeted files:

```bash
# Module-specific:
python -m pytest tests/tui/test_tool_blocks.py tests/tui/test_tool_panel.py -x -q --override-ini="addopts="

# Import check only for app.py:
python3 -c "from hermes_cli.tui.app import HermesApp; print('OK')"
```

Use `--override-ini="addopts="` to suppress rtk output suppression.

**After splits, run only files for the touched modules.** Do not run suites for unrelated modules.

### Basic async test structure

```python
@pytest.mark.asyncio
async def test_my_widget() -> None:
    from unittest.mock import MagicMock
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(MyWidget)
        widget.some_attr = "value"
        await pilot.pause()
        assert widget.rendered_text == "expected"
```

- `await pilot.pause()` — let event loop tick (needed after reactive changes)
- `await pilot.pause(delay=0.3)` — wait for workers (file preview, etc.)
- `pilot.press("key")` may be consumed by the focused widget — call `app.on_key(mock_event)` directly to test app-level handlers
- Use `asyncio.get_running_loop()` not `asyncio.get_event_loop()` in sync pytest fixtures (Python 3.10+ deprecation)

### MagicMock gotchas

**`isinstance(MagicMock(spec=Cls), Cls)` is always False** — even with `spec=`. Use duck-typing:
```python
# WRONG — always False for MagicMock
if not isinstance(block, StreamingToolBlock):
    return

# CORRECT
if not hasattr(block, '_follow_tail'):
    return
```

**`getattr(mock, "_attr", False)` is truthy** — unset attrs on `MagicMock(spec=...)` return a `MagicMock()` object (truthy). Use identity check:
```python
# WRONG — fires for any unset attr (MagicMock() is truthy)
if getattr(block, "_completed", False):
    return

# CORRECT
if getattr(block, "_completed", False) is True:
    return
```

### `__new__`-created objects

Tests sometimes use `Cls.__new__(Cls)` to bypass Textual's Widget constructor. Every `self._attr` set in `__init__` is absent on such objects.

**In production code**, any method exercised by `__new__`-based tests MUST use `getattr(self, '_attr', default)`:
```python
# WRONG — AttributeError on __new__-constructed object
if self._detected_cwd:
    ...

# CORRECT
if getattr(self, '_detected_cwd', None):
    ...
```

**Prefer `Widget.__init__` over `__new__`**: `Widget.__init__` doesn't mount or compose — it's safe to call without a running app. `__new__` forces the test to maintain a parallel list of all instance attrs and breaks silently when `__init__` adds a new one. Only use `__new__` when `__init__` has custom logic that genuinely requires a running app.

### Patch targets after module splits

Patch at the module where the name is **defined**, not where it is used:

```python
# WRONG after split — spec_for now lives in tool_category.py
patch("hermes_cli.tui.tool_blocks.spec_for")

# CORRECT
patch("hermes_cli.tui.tool_category.spec_for")
```

After `input/` subpackage split, `input_widget.py` is a shim — it re-exports but doesn't re-import into its own namespace. Tests patching `hermes_cli.tui.input_widget.some_fn` must update to `hermes_cli.tui.input.widget.some_fn`.

### Overlay test fixtures

Tests using a minimal `_App` class must yield overlay widgets in `compose()`. Without them, actions that use `query_one(SomeOverlay)` silently no-op (caught `NoMatches`) and visibility assertions never fire:

```python
class _App(App):
    def compose(self):
        yield ToolPanelHelpOverlay()  # required
        yield MyWidget()

# Assert visibility state, not DOM presence:
assert not overlay.has_class("--visible")  # CORRECT
assert len(pilot.app.query(MyOverlay)) == 0  # WRONG — pre-mounted, always present
```

### Contradictory test pairs after refactors

A test written for old behavior (e.g. `assert "scroll_relative" in src`) conflicts with a new test (e.g. `assert mock.scroll_down.call_count >= 5`). When both exist and the old one passes while the new one fails, the old test codifies superseded design. Update the old test to match the new implementation.

### Unstaged modifications cause mysterious failures

Pre-session `M` files in `git status` may contain broken/reverted code that conflicts with the committed state. Run `git diff HEAD -- <file>` before assuming a test failure is in your changes.

### Ghost method calls

Always `grep -rn "def method_name"` before calling a method that was added in a recent refactor. Ghost calls (`_notify_group_header()` called but defined nowhere) silently no-op on real objects and crash on `__new__`-constructed ones.

### `__init__.py` re-exports after subpackage splits

After splitting `renderers.py` into `code_blocks.py`, `inline_media.py`, `prose.py`, the `widgets/__init__.py` re-export block still imported from `.renderers`. A single `ImportError` in `__init__.py` blocks ALL test files that import `hermes_cli.tui.app` from collecting (~100+ tests). Fix: import each class from its actual home module:

```python
# BROKEN after split
from .renderers import (CodeBlockFooter, StreamingCodeBlock, InlineImage, ...)

# CORRECT after split
from .renderers import (CopyableBlock, CopyableRichLog, LiveLineWidget, ...)
from .code_blocks import (CodeBlockFooter, StreamingCodeBlock)
from .inline_media import (InlineImage, InlineImageBar, InlineThumbnail)
from .prose import (InlineProseLog, MathBlockWidget)
```
