---
name: tui-development
description: >
  Architecture, patterns, and API gotchas for the hermes-agent Textual TUI
  (hermes_cli/tui/). Covers widget development, thread→app communication,
  overlay state protocol, testing with Pilot, CSS theming, and known Textual
  8.x pitfalls.
  TRIGGER when: writing or modifying TUI widgets, adding new overlays or
  status bars, debugging Textual rendering, writing tests in tests/tui/,
  touching _cprint or _hermes_app, or working with hermes_cli/tui/*.
  DO NOT TRIGGER when: modifying agent logic, tools, config, or non-TUI CLI
  commands (hermes_cli/commands.py, hermes_cli/config.py, etc.).
compatibility: "Python 3.11+, Textual >=1.0,<9 (pinned), Rich >=14"
metadata:
  author: xush
  version: "1.2"
  target: code_agent
---

## Module Map

```
hermes_cli/tui/
├── __init__.py             # Package exports: HermesApp, state dataclasses
├── app.py                  # HermesApp(App) — reactive state, queue consumer, watchers, theme
├── widgets.py              # All widgets + CountdownMixin + _safe_widget_call helper
├── state.py                # OverlayState, ChoiceOverlayState, SecretOverlayState
├── input_widget.py         # HermesInput — history, autocomplete, masking, trigger dispatch
├── hermes.tcss             # Visual CSS (colours, margins); structural CSS in DEFAULT_CSS
├── skin_loader.py          # JSON/YAML → Textual CSS variable dict (semantic fan-out)
├── path_search.py          # PathSearchProvider — threaded walker, Candidate/PathCandidate/SlashCandidate
├── fuzzy.py                # fuzzy_rank — subsequence scorer with match-span highlighting
├── completion_list.py      # VirtualCompletionList — O(viewport) ScrollView, 10k+ items at 60fps
├── completion_context.py   # detect_context — regex trigger dispatcher (/, @, NATURAL)
├── completion_overlay.py   # CompletionOverlay — VirtualCompletionList + PreviewPanel container
├── tool_blocks.py          # ToolBlock+ToolHeader+ToolBodyContainer — collapsible tool output; StreamingToolBlock (IDLE→STREAMING→COMPLETED, 60fps flush, 200-line cap, 2kB/line cap); ToolTail scroll-lock badge
├── history_suggester.py    # HistorySuggester — Fish-style ghost text via native Suggester API
├── preview_panel.py        # PreviewPanel — syntax-highlighted file preview, binary sniff
└── context_menu.py         # ContextMenu (layer:overlay, position:absolute) + MenuItem dataclass + _ContextItem + _ContextSep

tests/tui/
├── test_output_panel.py        # Queue routing, sentinel flush, backpressure
├── test_reasoning_panel.py     # Open/close lifecycle, _safe_widget_call, wrap=True
├── test_status_widgets.py      # Spinner, hint, status, voice, image bars
├── test_overlays.py            # All 4 overlays: visibility, timeout, key nav, queue
├── test_hermes_input.py        # History, autocomplete, masking, insert, trigger dispatch
├── test_theme.py               # CSS var injection, bad skin resilience
├── test_integration.py         # Full lifecycle, stress, concurrent transitions
├── test_interrupt.py           # ctrl+c/escape agent interrupt, overlay cancel, double-exit
├── test_state.py               # Dataclass properties, queue communication
├── test_skin_loader.py         # JSON/YAML load, semantic fan-out, SkinError
├── test_path_search.py         # Walker batching, cancellation, SlashCandidate list
├── test_fuzzy.py               # Scoring, ranking, empty query, tiebreak
├── test_virtual_completion.py  # render_line, scroll, keyboard navigation
├── test_completion_context.py  # detect_context regex cases (/, @, NATURAL, edge cases)
├── test_history_suggester.py   # Ghost text, no match, case sensitivity
├── test_completion_overlay.py  # Visibility, --slash-only mode, preview routing
├── test_preview_panel.py       # File load, binary sniff, OSError, cancellation, clear
└── test_autocomplete_perf.py   # @pytest.mark.slow perf microbench (fuzzy + virtual list)

├── test_streaming_tool_block.py  # StreamingToolBlock lifecycle, byte cap, visible cap, app API (11 tests)
├── test_tool_blocks.py           # ToolBlock collapse/expand, browse mode, toggle no-op
└── test_context_menu.py          # ContextMenu show/hide/clamp; _flash_hint; paste hint; _build_context_items dispatch; copy actions (21 tests)

tests/cli/
└── test_reasoning_tui_bridge.py  # cli.py → TUI reasoning bridge (20 tests)

tests/environments/
└── test_execute_streaming.py     # execute_streaming() fallback+local, ContextVar callback API (11 tests)
```

---

## Architecture Overview

```
HermesApp(textual.App)
│
├── OutputPanel (ScrollableContainer, _user_scrolled_up flag suppresses auto-scroll during streaming)
│     ├── MessagePanel (per-turn)
│     │     ├── TitledRule (response header, hidden → .visible on first content)
│     │     ├── ReasoningPanel (display:none → .visible, ▌ gutter lines)
│     │     ├── ToolBlock / StreamingToolBlock — collapsible tool output (see tool_blocks.py)
│     │     │     ├── ToolHeader (label, chevron/spinner, line count/duration, collapsed state)
│     │     │     └── ToolBodyContainer → CopyableRichLog (markup=False)
│     │     └── RichLog (response text, markup=False, wrap=True)
│     └── LiveLineWidget (in-progress streaming chunk)
├── CompletionOverlay (Horizontal, display:none → .--visible)
│     ├── VirtualCompletionList (ScrollView, O(viewport), render_line)
│     └── PreviewPanel (RichLog, syntax-highlighted, binary sniff)
├── PathSearchProvider (Widget, display:none — threaded walker)
├── OverlayLayer (Vertical)
│     ├── ClarifyWidget  ┐
│     ├── ApprovalWidget │ all use CountdownMixin + typed OverlayState
│     ├── SudoWidget     │
│     └── SecretWidget   ┘
├── HintBar (Static, reactive hint)
├── ImageBar (Static, display:none)
├── TitledRule (input separator, "⚕ Hermes")
├── HermesInput (custom: history, HistorySuggester ghost text, trigger dispatch, mask, ❯ chevron)
├── PlainRule (dim rule below input)
├── VoiceStatusBar (display:none → .active)
├── StatusBar (dock:bottom, background matches app, reads app reactives)
└── ContextMenu (layer:overlay, position:absolute — mounted last so it paints above all)
```

**Layer system:** `HermesApp.LAYERS = ("default", "overlay")` declares two layers. `ContextMenu` uses `layer: overlay;` in its `DEFAULT_CSS`, placing it above all default-layer widgets. Mounting order within a layer follows DOM order — ContextMenu is last in `compose()`.

**Context menu dispatch (right-click → `HermesApp.on_click`):**
- `event.button != 3` → return (left/middle click ignored)
- `_build_context_items(event)` walks up `event.widget`'s parent chain. Priority:
  1. `ToolBlock` or `ToolHeader` → Copy tool output / Expand-Collapse / Copy all output
  2. `MessagePanel` → Copy selected (if selection) / Copy full response
  3. `HermesInput` or `#input-row` → Paste hint / Clear input
  4. Fallback → Copy selected (only if selection active)
- `screen_x`/`screen_y` fallback to `event.x`/`event.y` before passing to `show()`
- `_flash_hint(text, duration)` — temporarily sets `HintBar.hint` then restores via `set_timer`
- Copy flash: `⎘ N chars copied` (1.5 s) — in ctrl+c selected-text branch of `on_key`
- Paste flash: `📋 N chars` (1.2 s) — `HermesInput.on_paste` handler

**Autocomplete trigger dispatch (HermesInput → CompletionOverlay):**
- `/` at start → `SlashCandidate` list from `PathSearchProvider._slash_candidates`; overlay in `--slash-only` mode (no preview)
- `@` (preceded by space or SOL) → `PathSearchProvider` starts threaded walk; batches arrive via `PathSearchProvider.Batch` message; `fuzzy_rank` applied per batch; overlay shows preview
- Any other context → overlay dismissed
- `Tab` accepts: slash replaces full value; `@path` splices fragment, trailing space added only at EOL
- `Enter` NEVER auto-accepts — always submits as typed

**Autocomplete escape priority:**
- `HermesApp.on_key` adds Priority 0 escape check before all other handling: if `CompletionOverlay` has class `--visible`, remove it and `event.prevent_default()` — stops browse-mode enter or agent interrupt from firing on the same keypress

**Thread → App communication (from agent/background threads):**
- **Scalar state:** `app.call_from_thread(setattr, app, "reactive_name", value)`
- **Streaming output:** `app.write_output(text)` / `app.flush_output()` (preferred API; handles CPython fast path internally). Legacy: `_cprint(text)` shim in cli.py.
- **Widget methods:** `app.call_from_thread(_safe_widget_call, app, WidgetType, "method", *args)`
- **Reasoning:** `app.call_from_thread(app.open_reasoning, "title")` / `app.call_from_thread(app.append_reasoning, delta)` / `app.call_from_thread(app.close_reasoning)`
- **Streaming tool blocks:** `app.call_from_thread(app.open_streaming_tool_block, tool_call_id, label)` / `app.call_from_thread(app.append_streaming_line, tool_call_id, line)` / `app.call_from_thread(app.close_streaming_tool_block, tool_call_id, duration_str)`. Uses `_active_streaming_blocks: dict[str, StreamingToolBlock]` on `HermesApp`. Inject line callback via `set_streaming_callback(cb)` ContextVar in `terminal_tool.py`; reset with `reset_streaming_callback(token)` after the call.

**CRITICAL:** `open_reasoning()`, `append_reasoning()`, `close_reasoning()` access the DOM — they are **NOT thread-safe when called directly**. Always wrap in `call_from_thread` from background threads. Calling them directly on the event loop (e.g. from a watcher or `set_interval` callback) is fine.

**Module-level bridge:** `_hermes_app: HermesApp | None = None` in cli.py — set in `run()`, cleared in `finally`. Replaces all `hasattr(self, "_app")` guards.

**Reasoning bridge (cli.py → TUI):**
- `_stream_reasoning_delta()`: on first token, calls `tui.call_from_thread(tui.open_reasoning, "Reasoning")`; every delta sent immediately via `tui.call_from_thread(tui.append_reasoning, text)`
- `_close_reasoning_box()`: calls `tui.call_from_thread(tui.close_reasoning)`
- `_on_reasoning()` (non-streaming): opens panel on first call, appends text
- `_reset_stream_state()`: closes non-streaming TUI panel if opened
- Pattern: always check `tui = _hermes_app` for None before any `call_from_thread`

**Interrupt handling (app.py `on_key`):**
- Priority order: overlay cancellation → agent interrupt → idle input
- ctrl+c on overlay: sends "deny" (choice) or "" (secret), clears state
- escape on overlay: sends None (choice) or "" (secret), clears state
- ctrl+c/escape during `agent_running`: calls `self.cli.agent.interrupt()`, shows "⚡ Interrupting..."
- Double ctrl+c within 2s: `self.exit()` force exit
- Idle ctrl+c: clears input content, or exits if already empty
- `input_widget.py`: disabled input bubbles ctrl+c and escape to app (no longer swallowed)

---

## Visual Design System

**Section separation** uses horizontal rules, not box borders. No rounded corners (`╭╮╰╯`) or square box-drawing (`┌┐└┘`) anywhere.

| Section | Top separator | Content style | Bottom separator |
|---|---|---|---|
| Response | TitledRule ("⚕ Hermes", accent+dim two-tone) | Normal text | None (next turn's rule separates) |
| Reasoning | None | `▌` gutter prefix, dim italic text | None (collapses when done) |
| Input area | TitledRule ("⚕ Hermes") | `❯` chevron prompt | PlainRule (dim) |

**Reasoning panel** uses a left `▌` gutter marker (dim) instead of a border. This provides visual containment without consuming horizontal rules. Reasoning collapses (hides) after streaming completes.

**Response rule** (TitledRule inside MessagePanel) is hidden by default and shown via `.visible` CSS class when the first content token arrives. There is no bottom rule — the next message turn's top rule implicitly closes the section.

**StatusBar** uses `background: $background` (matches app background) rather than a contrasting bar color.

**PT mode** mirrors TUI: response open = `──{label}──` (two-tone), reasoning uses `▌` gutter prefix via `_dim_lines()`, no bottom borders for either.

---

## Widget Development Patterns

### Creating a new widget

Textual widgets use **either** `compose()` (yields children) **or** `render()` (returns
a renderable) — **never both**. If `compose()` yields children, `render()` is never called.

**Pattern A — composite widget (children do the rendering):**

```python
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

class MyWidget(Widget):
    DEFAULT_CSS = """
    MyWidget {
        height: auto;      /* structural → DEFAULT_CSS */
        display: none;     /* structural → DEFAULT_CSS */
    }
    MyWidget.visible { display: block; }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="my-content")

    def set_content(self, text: str) -> None:
        # Static.update() DOES parse Rich markup — unlike Widget.render()
        try:
            self.query_one("#my-content", Static).update(f"[dim]{text}[/dim]")
        except NoMatches:
            pass
```

**Pattern B — leaf widget (self-rendering, no children):**

```python
from textual.app import RenderResult
from textual.reactive import reactive
from textual.widget import Widget
from rich.text import Text

class MyLeafWidget(Widget):
    DEFAULT_CSS = "MyLeafWidget { height: 1; }"

    my_value: reactive[str] = reactive("", repaint=True)

    def render(self) -> RenderResult:
        # NEVER return plain str — it renders as LITERAL text (no markup).
        # Always return Text() / Text.from_markup() / Text.from_ansi().
        return Text.from_markup(f"[dim]{self.my_value}[/dim]")
```

### Rules

1. **`Widget.render()` return type:** Plain `str` = literal text (no markup parsing). Use `Text()` / `Text.from_markup()` / `Text.from_ansi()` for styled output. **Exception:** `Static.update(str)` DOES parse Rich markup — this only applies to `render()`.
2. **`compose()` vs `render()` — pick one:** If `compose()` yields children, `render()` is never called. Use `compose()` for composite widgets, `render()` for leaf widgets.
3. **`RichLog.write()`** has NO `markup` kwarg. Set `markup=` at construction time. For mixed content: `markup=False` + pass `Text.from_markup(...)` objects.
4. **`Text.from_ansi()`** for `_cprint` output — raw ANSI strings render escape bytes literally in `markup=False` RichLog.
5. **`self.size.width`** is `0` during `compose()` — don't use for layout math. Use Textual `Rule` for horizontal separators.
6. **`query_one`** is THE access pattern — no `self.output_panel` attributes on HermesApp. Always `app.query_one(WidgetClass)` or `app.query_one("#id")`.
7. **`query_one` raises `NoMatches`** if widget not found. Wrap in try/except during teardown, or use `_safe_widget_call`.
8. **CSS placement:** Structural properties (`height`, `overflow`, `display`, `dock`) in `DEFAULT_CSS`. Visual properties (`color`, `margin`, `padding`) in `hermes.tcss`.
9. **Reactive mutable defaults:** Use `reactive(list)` not `reactive([])` — factory form avoids shared state.

---

## Overlay State Protocol

ALL overlay state uses typed `@dataclass` hierarchy — never raw dicts:

```python
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState

# Choice overlays (clarify, approval):
state = ChoiceOverlayState(
    deadline=time.monotonic() + timeout,
    response_queue=queue.Queue(),
    question="Allow?",
    choices=["once", "deny"],
    selected=0,
)
app.call_from_thread(setattr, app, "approval_state", state)
answer = state.response_queue.get()  # blocks agent thread

# Secret overlays (sudo, secret):
state = SecretOverlayState(
    deadline=time.monotonic() + timeout,
    response_queue=queue.Queue(),
    prompt="Enter password:",
)
```

**CountdownMixin** — all 4 overlays inherit this. To add a new timed overlay:

```python
class NewOverlay(CountdownMixin, Widget):
    _state_attr = "new_state"          # HermesApp reactive name
    _timeout_response = None           # value on expiry
    _countdown_prefix = "new"          # → #new-countdown widget ID

    def compose(self) -> ComposeResult:
        yield Static("", id="new-content")
        yield Static("", id="new-countdown")  # required by CountdownMixin

    def on_mount(self) -> None:
        self._start_countdown()        # starts 1s tick timer
```

---

## Output API

**Preferred (new code):** `HermesApp.write_output(text)` and `HermesApp.flush_output()`. Both are thread-safe. `write_output` handles the CPython fast-path (`put_nowait` directly) vs safe-path (`call_soon_threadsafe`) internally.

**Legacy shim:** `_cprint(text)` — module-level function in cli.py (~206 call sites). Routes to either:
- **Textual queue** when `_hermes_app` is set (TUI active) — always uses `call_soon_threadsafe`
- **prompt_toolkit renderer** when `_hermes_app is None` (single-query / no-TUI)

The bounded `asyncio.Queue(maxsize=4096)` provides backpressure. `QueueFull` → drop (recoverable). `None` sentinel flushes the live line buffer and the consumer stays alive for the next turn.

---

## Thread Safety

| Pattern | Use case | Safe? |
|---|---|---|
| `app.call_from_thread(fn, *args)` | Scalar reactive mutation from agent thread | Yes |
| `loop.call_soon_threadsafe(queue.put_nowait, chunk)` | Streaming output from agent thread | Yes (all runtimes) |
| `queue.put_nowait(chunk)` directly | Streaming output (CPython only) | Yes (GIL-atomic) |
| `self.post_message(Msg(...))` from `@work(thread=True)` | Delivering result from worker to own widget | Yes — preferred over `call_from_thread` for workers |
| `setattr(self.app, attr, val)` from `set_interval` callback | Timer updating reactive | Yes (on event loop) |
| `call_from_thread` from the app's own thread | Bug — raises RuntimeError | NO |
| `call_from_thread` before app running | Falls through to stdout in `_cprint` | Handled |
| `call_from_thread` when parent widget has `display: none` | From `@work` worker to hidden widget | Fails silently — use `post_message` instead |

---

## Testing Patterns

All TUI tests use Textual's built-in `Pilot` fixture:

```python
import pytest
from unittest.mock import MagicMock
from hermes_cli.tui.app import HermesApp

@pytest.mark.asyncio
async def test_example():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()                    # flush reactive updates
        widget = app.query_one("#some-widget")
        assert widget.display
        await pilot.press("enter")             # simulate keypress
        await pilot.pause()
```

### Test runner config

- **Override xdist:** `pytest -o "addopts=" tests/tui/` — Textual tests need serial execution; the project's `addopts = "-n auto"` forces parallel xdist which breaks `app.run_test()`.
- **All tests must be `async def`** with `@pytest.mark.asyncio`.
- **`RichLog` line count:** Use `len(log.lines)`, not `log.line_count` (doesn't exist).
- **Timing tests:** Use `await asyncio.sleep(duration)` + `await pilot.pause()` for countdown/timer tests.

### Testing overlay timeouts

To test an already-expired overlay (countdown auto-resolve), set `deadline` in the past and wait for the 1s tick:

```python
state = ChoiceOverlayState(
    deadline=time.monotonic() - 1,   # already expired
    response_queue=rq,
    question="Q?", choices=["a"],
)
app.approval_state = state
await pilot.pause()
await asyncio.sleep(1.2)            # wait for countdown tick (1s interval)
await pilot.pause()
result = rq.get(timeout=2)
assert result == "deny"              # ApprovalWidget._timeout_response
```

---

## CSS Theming

Runtime skin application uses `get_css_variables()` override:

```python
# In HermesApp:
def get_css_variables(self) -> dict[str, str]:
    base = super().get_css_variables()
    skin = getattr(self, "_skin_vars", {})  # defensive: called during super().__init__
    return {**base, **skin}

def apply_skin(self, skin_vars: dict[str, str]) -> None:
    self._skin_vars = skin_vars
    self.refresh_css()
```

**`get_css_variables()` is confirmed stable** from Textual 1.0 through 8.x — no rename, no deprecation.

Skin keys must be valid Textual CSS variable names (`"primary"`, `"background"`, `"error"`, etc.).

---

## Known Textual 8.x Gotchas

| Gotcha | Detail |
|---|---|
| `work` import path | `from textual import work`, NOT `from textual.work import work` |
| `RichLog.line_count` | Does not exist. Use `len(log.lines)` |
| `get_css_variables()` during `__init__` | Called by `super().__init__()` before instance attrs exist. Use `getattr(self, "_attr", default)` |
| `@work(thread=True)` required | `@work` alone = async coroutine. Must pass `thread=True` for threaded workers |
| `set_interval` callback type | Must be `def`, not `async def`, unless containing `await` |
| `RenderResult` import | `from textual.app import RenderResult` — not `textual.widget` |
| `scrollbar-gutter: stable` | Unsupported Textual CSS property — don't copy from web CSS |
| Default quit key in Textual ≥1.0 | `ctrl+q` (changed from `ctrl+c` in pre-1.0) |
| `post_message` from `@work` threads | Use `self.post_message(Msg(...))` — NOT `call_from_thread`. `call_from_thread` fails silently when the widget's parent has `display: none`. Message class names must NOT start with `_` (produces double-underscore in handler name, breaking discovery). |
| `display: none` suppresses child workers | When a parent container has `display: none`, Textual doesn't deliver `@work` callbacks to child widgets in tests. Add `.add_class("--visible")` to the parent overlay before testing any thread-backed child. |
| `scroll_offset` is read-only | `ScrollView.scroll_offset` is a read-only `Offset`. Use `scroll_to(y=..., animate=False)` or set the `highlighted` reactive (triggers `scroll_to_region`). Scroll is a no-op when widget is hidden. |
| Reactive watcher fires on value change only | `None → None` does NOT fire `watch_*`. In tests, set a non-None value first, wait, then set to None to test the clear path. |
| `Style(bgcolor=...)` in `render_line` | When building `Strip`s in `render_line`, use `Style(bgcolor="blue")` not the Rich shorthand `"on_blue"`. |
| `VirtualCompletionList` `virtual_size` | Set `self.virtual_size = Size(self.size.width, len(self._items))` in `render_line` / `watch_items`. Call `extend_cell_length` → `crop` → `apply_style` in that order. |
| `Suggester.get_suggestion` returns full value | Return the FULL replacement value (or `None`), not just the tail. Textual diffs the suggestion against current input to render the ghost suffix. |
| `asyncio.Queue` in `__init__` | `asyncio.Queue()` requires a running event loop (Python ≤3.9) and binds to the running loop (3.10+). Never initialise in `__init__` — always in `on_mount()`. |
| `asyncio.wait_for` + `CancelledError` | Catch only `asyncio.TimeoutError` inside the loop; let `CancelledError` propagate to the outer `finally` so Textual's worker cancellation reaches cleanup. Do NOT add a bare `except TimeoutError` branch (shadows `CancelledError` on Python < 3.11). |
| Long-running `@work` drainer pattern | Start once in `on_mount()`; use `asyncio.wait_for(queue.get(), timeout=0.5)` + `while self.is_mounted` for clean unmount. Never poll with `get_nowait()` in a loop — it exits on empty queue instead of waiting. |

---

## Streaming Typewriter Animation

`LiveLineWidget.feed(chunk)` is the typewriter entry point (opt-in, default off). See full spec:
`/home/xush/.hermes/tui-streaming-typewriter.md`

Key patterns:
- **`_ANSI_SEQ_RE`** in `feed()` splits chunks into atomic items: single visible chars OR complete escape sequences (CSI/OSC/Fe). Prevents partial escape codes in `_buf` between frames.
- **Burst compensation** in `_drain_chars()`: when `queue.qsize() >= burst_threshold`, sync-drain a batch and yield once (`asyncio.sleep(0)`) instead of sleeping per-char. Prevents O(N) yields for fast model output.
- **Config cached on `on_mount()`** — never call `get_config()` from `render()` or any hot path.
- **`flush()`** is synchronous (no awaits) — safe on event loop; drainer's sleeping `asyncio.sleep` cannot race with it.

---

## Adding a New Widget Checklist

1. Define widget class in `hermes_cli/tui/widgets.py`
2. Add structural CSS in `DEFAULT_CSS`, visual CSS in `hermes.tcss`
3. Yield it from `HermesApp.compose()` in `app.py`
4. If reactive: add reactive field to `HermesApp`, add `watch_*` method
5. If thread-updated: use `call_from_thread` or `_safe_widget_call`
6. If timed overlay: inherit `CountdownMixin`, define `_state_attr`, `_timeout_response`, `_countdown_prefix`
7. If choice overlay: add state_attr + widget_type to the `on_key()` loop in `HermesApp` (app.py) for Up/Down/Enter/Escape dispatch
8. Write async tests in `tests/tui/test_*.py` using `app.run_test()`
9. Run: `pytest -o "addopts=" tests/tui/ -v`
