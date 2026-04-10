# Spec: Typewriter Character-Animation for Streaming Output

## Overview

Replace the current word-boundary flush (every ~12 chars) with a character-by-character
typewriter effect — each character of a streaming response appears individually with a
configurable minimum inter-character delay. Completed lines stay permanently printed;
only the current in-progress line is animated. Multiple lines are independent: line N+1
cannot start animating until line N is fully committed.

---

## Architectural Context (from codebase analysis)

Before speccing the solution, the following facts about the runtime environment are
load-bearing:

| Fact | Detail |
|---|---|
| App lifecycle | `app.run()` is active throughout streaming; the TUI is never hidden |
| Streaming thread | Agent runs in `threading.Thread` (cli.py:7077); `_stream_delta` is called from that thread |
| Output mechanism | `_cprint` → `print_formatted_text(ANSI(...))` — thread-safe via `patch_stdout`'s `StdoutProxy` |
| Buffering | StdoutProxy **buffers** output; it is flushed to the terminal at the next renderer cycle |
| Render cadence | `app.invalidate()` fires ~every 0.15–0.25 s from the spinner thread (cli.py:7729) |
| `run_in_terminal` | Used internally by prompt_toolkit when flushing StdoutProxy — NOT called directly by streaming code |
| Prompt visibility | TextArea (input prompt) stays visible at the bottom at all times; never hidden |
| `app` reference | Stored at `self._app` (initialized to `None` in `__init__`; set at cli.py:8665 when TUI starts) |

**The critical buffering problem for typewriter output:**
StdoutProxy batches writes and flushes them together on the next render cycle. If the pump
writes chars A, B, C in rapid succession and only one render cycle fires, all three appear
simultaneously — defeating the effect. The pump must therefore:

1. Write one character to the display buffer.
2. Call `self._app.invalidate()` immediately (schedules a render on the event loop via
   `call_soon_threadsafe`).
3. Sleep for `char_delay_ms` milliseconds — this pause gives the event loop time to actually
   execute the scheduled render before the next character is written.

The sleep IS the synchronisation mechanism. No explicit render-complete acknowledgement is
needed; the event loop will process the invalidation during the sleep window.

---

## Approach Decision

Two approaches were considered:

### Option A — Append-only `print_formatted_text(char, end="")` per character

Each character is emitted via `print_formatted_text(ANSI(char), end="")` with a sleep +
`app.invalidate()` between calls. The cursor stays after the last character; subsequent
writes append to the same terminal line. The pump emits **only the new character** on each
call (not the accumulated buffer), so the cursor never needs to rewind during animation.
When a line is committed, a `\r` + clear sequence overwrites the partial line with the
fully-rendered version.

**Pros**: No layout changes; minimal diff; re-uses existing `_cprint` infrastructure.  
**Cons**: Depends on prompt_toolkit maintaining partial-line cursor state correctly across
`run_in_terminal` cycles. This is not explicitly guaranteed by the public API.

### Option B — `FormattedTextControl` live row in the TUI layout

Add a `Window(content=FormattedTextControl(lambda: ...), height=1)` to the app layout.
The in-progress line lives in the layout; the pump updates it and calls `app.invalidate()`.
When a `\n` is hit, the line is promoted via `_cprint` (permanent) and the live row clears.

**Pros**: Cursor behaviour is 100% reliable — the line is rendered by the app's own renderer,
no partial-line cursor fighting.  
**Cons**: Requires layout surgery (height=1 row conditionally visible); the live row sits
*above* the prompt but *below* already-committed lines, which means committed lines scroll
normally and the live row is always at the bottom of the output area.

**Decision: implement Option A first; fall back to Option B if cursor-state issues are
observed in testing.**

Option A is the minimal viable implementation. If `print_formatted_text(end="")` correctly
appends to the partial line across render cycles (which prompt_toolkit's cursor-tracking
suggests it should), it is sufficient. Option B is specced in full in the Appendix for use
if Option A proves unreliable.

---

## Design: Option A (Primary)

### Components

```
Token stream
    │
    ▼
_emit_stream_text()          ← existing; modified
    │ feeds chars one-by-one
    ▼
_TypewriterQueue             ← new: thread-safe deque
    │
    ▼
_TypewriterPump (daemon thread) ← new: sleeps between chars, drives display
    │                │
    │ one char at    │ completed line (\n boundary)
    │ a time         │
    ▼                ▼
_write_char()      _commit_line()  ← routes through _stream_block_buf/_stream_code_hl
(end="", single    then _cprint() for permanent commit
 new char only)
```

### Module structure

`_TypewriterQueue` and `_TypewriterPump` live in a new **`cli_typewriter.py`** module to
keep `cli.py` from growing further. The module imports the following symbols from `cli.py`
(they are already defined there — no new definitions needed):

| Symbol | Purpose |
|---|---|
| `_pt_print` | alias for `print_formatted_text` |
| `_PT_ANSI` | alias for `prompt_toolkit.formatted_text.ANSI` |
| `_normalize_ansi_c1` | strips C1 control codes before wrapping in ANSI |
| `_RST` | reset escape sequence `"\x1b[0m"` |
| `_DIM` | dim escape sequence |
| `_RICH_RESPONSE` | module-level flag controlling markdown rendering |
| `_vlen` | visible column-width of a string (strips ANSI codes) |
| `_apply_block_line` | block-level markdown renderer |
| `_apply_inline_md` | inline markdown renderer |
| `_cprint` | permanent-line printer (routes through `patch_stdout`) |
| `_dim_lines` | wraps text in dim ANSI codes |

`cli.py` imports the two classes back:
```python
from cli_typewriter import _TypewriterQueue, _TypewriterPump
```

All other code changes (integration into `_emit_stream_text`, `_flush_stream`, etc.) remain
in `cli.py`.

### `_vlen` helper

`_vlen(s: str) -> int` returns the visible terminal column-width of `s` by stripping all
ANSI escape sequences before measuring `len()`. It is already defined in `cli.py` and used
by the box-drawing code. The pump uses it in `_commit_line` to clear the exact number of
columns occupied by the animated partial line.

### `_TypewriterQueue`

```python
import collections
import threading
from typing import Any, List

class _TypewriterQueue:
    """Thread-safe character queue for the typewriter pump."""

    FLUSH_SENTINEL = object()   # signals: flush in-progress line immediately
    STOP_SENTINEL  = object()   # signals: pump thread should exit

    def __init__(self):
        self._q   = collections.deque()
        self._ev  = threading.Event()   # set when items are available

    def push(self, item: Any) -> None:          # called from agent thread
        self._q.append(item)
        self._ev.set()

    def push_text(self, text: str) -> None:
        for ch in text:
            self._q.append(ch)
        self._ev.set()

    def is_empty(self) -> bool:
        return not self._q

    def drain(self, max_items: int = 64) -> List[Any]:
        """Return up to max_items items without blocking.

        The event is cleared BEFORE dequeuing so that any push() arriving
        during or after the drain will re-set the event and be picked up on
        the next wait() call.  Clearing after dequeuing would create a race
        where a push between the dequeue and the clear is silently lost until
        the 0.5 s timeout fires.

        If the deque still has items after draining max_items, the event is
        re-set so the pump's next wait() returns immediately rather than
        blocking for up to 0.5 s.  Without this, every 64-char batch would
        be followed by a 500 ms stall when the queue piles up under fast
        token streams (E2).
        """
        self._ev.clear()          # clear first, then drain
        out = []
        for _ in range(max_items):
            if not self._q:
                break
            out.append(self._q.popleft())
        if self._q:               # items remain; wake pump immediately next cycle
            self._ev.set()
        return out

    def wait(self, timeout: float = 0.5) -> None:
        self._ev.wait(timeout)
```

### `_TypewriterPump` (daemon thread)

Runs for the lifetime of the streaming session. Started when the first token arrives;
stopped when `_flush_stream()` (response) or `_close_reasoning_box()` (reasoning) is called.

The pump is parameterised so the same class serves both the response stream and the
reasoning stream. All stream-specific behavior (which ANSI color to use, which state
machines to route through, how to wrap committed lines) is injected via constructor
arguments.

```python
import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


class _TypewriterPump(threading.Thread):
    """
    Consumes characters from a _TypewriterQueue one at a time, sleeping
    char_delay_ms between each, and writing them to the terminal via
    print_formatted_text(end="").

    CRITICAL — emit only the new character per call, not the full buffer:
    _write_char() prints a single character with end="" so the cursor lands
    immediately after it.  The accumulated _line_buf is used only for the
    commit-and-clear sequence in _commit_line().  Printing the full buffer
    without a preceding \\r on each call would produce duplicated characters
    on screen (e.g. "h" then "he" from col-1 → "hhe").

    Newline characters promote the in-progress line to a committed _cprint
    line via the same _stream_block_buf / _stream_code_hl state machine path
    used by _emit_stream_text.
    """

    def __init__(
        self,
        queue: _TypewriterQueue,
        cli_instance,
        char_delay_ms: int = 18,
        ansi_attr: str = "_stream_text_ansi",
        block_buf_attr: str = "_stream_block_buf",
        code_hl_attr: str = "_stream_code_hl",
        line_wrapper: Callable[[str], str] = lambda l: l,
        thread_name: str = "typewriter-pump",
    ):
        """
        Parameters
        ----------
        queue           : _TypewriterQueue feeding this pump.
        cli_instance    : The CLI object; attributes are read via getattr.
        char_delay_ms   : Inter-character sleep in milliseconds.
        ansi_attr       : Name of the ANSI color string on cli_instance.
                          Response pump: "_stream_text_ansi".
                          Reasoning pump: "_reasoning_text_ansi" (set to _DIM).
        block_buf_attr  : Name of the _BlockBuf state machine on cli_instance.
                          Response pump: "_stream_block_buf".
                          Reasoning pump: "_reasoning_block_buf".
        code_hl_attr    : Name of the _CodeBlockHL state machine on cli_instance.
                          Response pump: "_stream_code_hl".
                          Reasoning pump: "_reasoning_code_hl".
        line_wrapper    : Callable applied to committed lines before _cprint.
                          Response pump: identity (lambda l: l).
                          Reasoning pump: lambda l: _dim_lines(l)[0].
        thread_name     : Thread name visible in tracebacks and enumerate().
                          Use distinct names for response vs. reasoning pumps
                          so concurrent threads are identifiable in debug output.
        """
        super().__init__(daemon=True, name=thread_name)
        self._q               = queue
        self._cli             = cli_instance
        self._delay           = char_delay_ms / 1000.0
        self._ansi_attr       = ansi_attr
        self._block_buf_attr  = block_buf_attr
        self._code_hl_attr    = code_hl_attr
        self._line_wrapper    = line_wrapper
        self._line_buf        = ""       # raw chars for the current in-progress line
        self._stopped         = threading.Event()

    # ------------------------------------------------------------------
    # Control interface (called from agent / main thread)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the pump to drain remaining items and exit.

        Sets _stopped (used only for the safety exit) then pushes
        STOP_SENTINEL so the run() loop exits cleanly after draining.
        The two operations are sequential; flush_now() should be called
        first to ensure _line_buf is empty before STOP_SENTINEL arrives.
        """
        self._stopped.set()
        self._q.push(_TypewriterQueue.STOP_SENTINEL)

    def flush_now(self) -> None:
        """Force-commit whatever is buffered (used at turn boundary / stream end)."""
        self._q.push(_TypewriterQueue.FLUSH_SENTINEL)

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Loop until STOP_SENTINEL is encountered.

        The loop does NOT exit on _stopped alone.  stop() always pushes
        STOP_SENTINEL so the pump drains all pending characters before
        exiting.  Exiting on the flag alone would silently drop characters
        queued between the last drain() and the stop() call.

        A safety exit is included for the edge case where stop() sets
        _stopped but STOP_SENTINEL has not yet been pushed (a transient
        window of ~1 µs).  In that window _line_buf is guaranteed empty
        because flush_now() is always called before stop() in _flush_stream
        and _close_reasoning_box, so _commit_line() here is a no-op.
        """
        while True:
            self._q.wait(timeout=0.5)
            items = self._q.drain()
            for item in items:
                if item is _TypewriterQueue.STOP_SENTINEL:
                    self._commit_line()   # commit any remaining partial line
                    return
                if item is _TypewriterQueue.FLUSH_SENTINEL:
                    self._commit_line()
                    continue
                if item == "\n":
                    self._commit_line()
                    continue
                # Regular character: emit only this new char, then sleep
                self._line_buf += item
                self._write_char(item)
                if self._cli._app is not None:   # skip sleep in non-TUI / test mode
                    time.sleep(self._delay)
            # Safety exit: if _stopped is set and queue is genuinely empty,
            # return rather than blocking forever on the next wait().
            # _line_buf is empty here (flush_now precedes stop), so
            # _commit_line() is a no-op but is called for correctness.
            if self._stopped.is_set() and self._q.is_empty():
                self._commit_line()
                return

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _write_char(self, ch: str) -> None:
        """Emit a single new character via print_formatted_text(end="").

        Only the new character `ch` is emitted — NOT the full _line_buf.
        The character is wrapped in the stream's color ANSI prefix/suffix
        (read from cli_instance via self._ansi_attr) so color is applied
        character-by-character.  This is safe because _line_buf contains
        only raw text with no unclosed ANSI spans.
        """
        cli  = self._cli
        ansi = getattr(cli, self._ansi_attr, "")
        text = f"{ansi}{ch}{_RST}" if ansi else ch
        _pt_print(_PT_ANSI(_normalize_ansi_c1(text)), end="")
        if cli._app is not None:
            cli._app.invalidate()

    def _commit_line(self) -> None:
        """Commit the in-progress partial line permanently via _cprint.

        Steps:
        1. Guard: no-op if _line_buf is empty.
        2. Snapshot and clear _line_buf.
        3. Erase the animated partial from the terminal with \\r + spaces + \\r.
           Width = _vlen(_line_buf) — the visual width of the raw text painted
           character-by-character.  ANSI color codes from _write_char do not
           contribute terminal column width, so _vlen on the raw buffer is correct.
        4. Route the complete line through the stateful block_buf and code_hl
           pipeline (same path as _emit_stream_text) so code fences, tables, and
           setext headings render correctly.
        5. Apply line_wrapper and emit via _cprint (permanent, with trailing \\n).
        """
        if not self._line_buf:
            return
        cli  = self._cli
        _tc  = getattr(cli, self._ansi_attr, "")
        line = self._line_buf
        self._line_buf = ""

        # Erase animated partial (raw chars, no markdown applied yet)
        _pt_print(_PT_ANSI("\r" + " " * _vlen(line) + "\r"), end="")

        if _RICH_RESPONSE:
            out = getattr(cli, self._block_buf_attr).process_line(line)
            if out is None:
                # Line buffered inside table / setext heading; partial cleared,
                # cursor at col 0 of same row.  Next animated chars start there.
                return
            out2 = getattr(cli, self._code_hl_attr).process_line(out)
            if out2 is None:
                # Line buffered inside fenced code block.
                return
            if out2 is out:
                # Plain prose: apply full block + inline markdown
                out = _apply_inline_md(
                    _apply_block_line(out, reset_suffix=_tc), reset_suffix=_tc
                )
                _cprint(self._line_wrapper(f"{_tc}{out}{_RST}" if _tc else out))
            else:
                # Syntax-highlighted code: out2 contains highlighted lines.
                # No _tc color wrapper — the syntax highlighter already applies
                # its own ANSI colors; adding _tc would corrupt them.
                for hl_line in out2.splitlines():
                    _cprint(self._line_wrapper(f"  {hl_line}"))
        else:
            _cprint(self._line_wrapper(f"{_tc}{line}{_RST}" if _tc else line))
```

### `__init__` additions

Add alongside the existing `self._stream_buf = ""` initialization:

```python
# Typewriter pump state (one pump per stream type)
self._tw_queue           = _TypewriterQueue()
self._tw_reasoning_queue = _TypewriterQueue()
self._tw_pump            = None   # _TypewriterPump; created on first response token
self._tw_reasoning_pump  = None   # _TypewriterPump; created on first reasoning token
self._reasoning_text_ansi = ""    # set to _DIM when reasoning box opens
```

> **Note on `_reasoning_block_buf` and `_reasoning_code_hl`:** These attributes mirror
> `_stream_block_buf` and `_stream_code_hl` and are assumed to be **already initialized**
> in the existing `__init__` body (same pattern as the response stream state machines).
> They are referenced by the reasoning pump via `getattr` and are not new attributes
> introduced by this spec — do not add them here.

### `_reset_stream_state` additions

Add at the end of the existing `_reset_stream_state` body (after the `_stream_block_buf` /
`_stream_code_hl` reset block):

```python
# Replace queues with fresh instances so orphan sentinels from the previous
# turn cannot be consumed by the next turn's pump.
self._tw_queue           = _TypewriterQueue()
self._tw_reasoning_queue = _TypewriterQueue()
# Pumps are already None from _flush_stream / _close_reasoning_box, but
# null them explicitly here as a safety net for test paths that bypass
# those methods.
self._tw_pump            = None
self._tw_reasoning_pump  = None
self._reasoning_text_ansi = ""    # reset so next turn starts colorless until box-open
```

### Integration into `_emit_stream_text`

The existing word-boundary flush and `while "\n"` loop are replaced by a queue push when
typewriter mode is active. The `_TYPEWRITER_ENABLED` flag provides a fallback to the
current word-boundary behavior.

Note: `_tc = getattr(self, "_stream_text_ansi", "")` is assigned in the unchanged
box-open preamble and is available in the fallback path below.

```python
def _emit_stream_text(self, text: str) -> None:
    # ... box-open / deferred-content / color-setup preamble unchanged ...
    # _tc = getattr(self, "_stream_text_ansi", "")  ← set in preamble; used in fallback

    if _TYPEWRITER_ENABLED:
        # Start pump on first token of this turn
        if self._tw_pump is None:
            self._tw_pump = _TypewriterPump(
                self._tw_queue,
                self,
                _TYPEWRITER_CHAR_DELAY_MS,
                # ansi_attr, block_buf_attr, code_hl_attr, line_wrapper all use defaults
            )
            self._tw_pump.start()
        self._tw_queue.push_text(text)
        # _stream_buf is not used for display in typewriter mode;
        # keep it empty so the _flush_stream compatibility guard is a no-op.
        return

    # --- Fallback: original word-boundary flush path ---
    # _tc is available from the preamble above.
    self._stream_buf += text
    while "\n" in self._stream_buf:
        line, self._stream_buf = self._stream_buf.split("\n", 1)
        if _RICH_RESPONSE:
            out = self._stream_block_buf.process_line(line)
            if out is None:
                continue
            out2 = self._stream_code_hl.process_line(out)
            if out2 is None:
                continue
            if out2 is out:
                out = _apply_inline_md(
                    _apply_block_line(out, reset_suffix=_tc), reset_suffix=_tc
                )
                _cprint(f"{_tc}{out}{_RST}" if _tc else out)
            else:
                for hl_line in out2.splitlines():
                    _cprint(f"  {hl_line}")
        else:
            _cprint(f"{_tc}{line}{_RST}" if _tc else line)

    if (
        len(self._stream_buf) >= _PARTIAL_FLUSH_CHARS
        and self._stream_buf[0] not in ("#", ">", "|", "`", " ", "\t", "-", "*", "+")
    ):
        cut = self._stream_buf.rfind(" ")
        if cut > 5:
            chunk = self._stream_buf[:cut + 1]
            self._stream_buf = self._stream_buf[cut + 1:]
            _cprint(f"{_tc}{chunk}{_RST}" if _tc else chunk)
```

### `_flush_stream` changes

When typewriter mode is active, `_flush_stream` joins the pump before running the
state-machine flush and drawing the box border. `self._tw_pump` is nulled out after the
join so a second call to `_flush_stream` (e.g., from interrupt handling) is a no-op
for the pump block rather than re-entering it with a dead thread.

```python
def _flush_stream(self) -> None:
    """Emit any remaining partial line and close the box."""
    self._close_reasoning_box()

    if _TYPEWRITER_ENABLED and self._tw_pump is not None:
        # 1. Enqueue flush sentinel so the pump commits any in-progress partial.
        self._tw_pump.flush_now()
        # 2. Signal stop; STOP_SENTINEL is pushed into the queue by stop().
        self._tw_pump.stop()
        # 3. Wait for the pump to drain and exit.
        self._tw_pump.join(timeout=2)
        if self._tw_pump.is_alive():
            log.warning(
                "typewriter pump did not stop within 2 s; "
                "partial output may be incomplete"
            )
        self._tw_pump = None   # prevent double-stop on a second _flush_stream call

    _tc = getattr(self, "_stream_text_ansi", "")

    # _stream_buf is empty in typewriter mode (kept so by _emit_stream_text);
    # this block is a no-op in that case.
    if self._stream_buf:
        if _RICH_RESPONSE:
            block_out = self._stream_block_buf.process_line(self._stream_buf)
            if block_out is not None:
                out2 = self._stream_code_hl.process_line(block_out)
                if out2 is not None:
                    if out2 is block_out:
                        out2 = _apply_inline_md(
                            _apply_block_line(out2, reset_suffix=_tc), reset_suffix=_tc
                        )
                        _cprint(f"{_tc}{out2}{_RST}" if _tc else out2)
                    else:
                        for hl_line in out2.splitlines():
                            _cprint(hl_line)
        else:
            _cprint(f"{_tc}{self._stream_buf}{_RST}" if _tc else self._stream_buf)
        self._stream_buf = ""

    if _RICH_RESPONSE:
        # Flush buffered block-level state (runs even if _stream_buf was empty).
        buf_tail = self._stream_block_buf.flush()
        if buf_tail is not None:
            for hl_line in buf_tail.splitlines():
                if "\x1b" not in hl_line:
                    hl_line = _apply_inline_md(
                        _apply_block_line(hl_line, reset_suffix=_tc), reset_suffix=_tc
                    )
                _cprint(f"{_tc}{hl_line}{_RST}" if _tc else hl_line)
        tail = self._stream_code_hl.flush()
        if tail:
            for hl_line in tail.splitlines():
                _cprint(f"  {hl_line}")
            _cprint(_RST)

    if self._stream_box_opened:
        w = shutil.get_terminal_size().columns
        _cprint(f"{_resp_border_ansi()}╰{'─' * (w - 2)}╯{_RST}")
```

### Lifecycle management

| Event | Action |
|---|---|
| First response token (`_emit_stream_text` in typewriter mode) | Create and start `_TypewriterPump` with default attrs; store as `self._tw_pump` |
| Turn boundary (`_stream_delta(None)`) | Calls `_flush_stream()` (unchanged call site) |
| `_flush_stream()` | `pump.flush_now()` → `pump.stop()` → `pump.join(timeout=2)` → log warning if alive → `self._tw_pump = None` |
| `_reset_stream_state()` | See `_reset_stream_state` additions section — replaces both queues with fresh instances and explicitly nulls both pump refs. |
| First reasoning token (`_stream_reasoning_delta` in typewriter mode) | Create and start reasoning `_TypewriterPump`; store as `self._tw_reasoning_pump` |
| `_close_reasoning_box()` | (see below) |

### Structural-prefix lines (headings, code fences, lists, tables)

The pump always animates character-by-character regardless of structural prefix. The raw
`**`, `#`, `>` etc. characters are visible during animation and snap to the fully-rendered
form when `_commit_line` fires. This snap is masked by the `\r`-clear-and-replace step, so
the visual artefact is minimal for most prefixes.

**Decision**: passthrough mode for structural-prefix lines is **deferred** to a follow-up
iteration. The snap artefact is acceptable for the initial implementation. If it proves
visually disruptive in testing, add a prefix check at the top of the `for item in items`
loop that switches to a "batch" mode: accumulate without `_write_char` calls until `\n`,
then commit directly.

### Reasoning stream

`_stream_reasoning_delta` receives the same treatment as `_emit_stream_text`. A second
`_TypewriterPump` instance drives reasoning output using `_DIM` as the ANSI color and
`_reasoning_block_buf` / `_reasoning_code_hl` as the state machines. The `line_wrapper`
argument applies `_dim_lines` so committed reasoning lines are rendered dim.

#### Modified `_stream_reasoning_delta` (typewriter path)

```python
def _stream_reasoning_delta(self, text: str) -> None:
    if not text:
        return
    self._reasoning_stream_started = True
    self._reasoning_shown_this_turn = True
    if getattr(self, "_stream_box_opened", False):
        return

    # Open reasoning box on first reasoning token (unchanged)
    if not getattr(self, "_reasoning_box_opened", False):
        self._reasoning_box_opened = True
        self._reasoning_text_ansi  = _DIM   # used by reasoning pump via ansi_attr
        w = shutil.get_terminal_size().columns
        r_label = " Reasoning "
        r_fill = w - 2 - len(r_label)
        _cprint(f"\n{_DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{_RST}")

    if _TYPEWRITER_ENABLED:
        if self._tw_reasoning_pump is None:
            self._tw_reasoning_pump = _TypewriterPump(
                self._tw_reasoning_queue,
                self,
                _TYPEWRITER_CHAR_DELAY_MS,
                ansi_attr="_reasoning_text_ansi",
                block_buf_attr="_reasoning_block_buf",
                code_hl_attr="_reasoning_code_hl",
                line_wrapper=lambda line: _dim_lines(line)[0],
                thread_name="typewriter-pump-reasoning",
            )
            self._tw_reasoning_pump.start()
        self._tw_reasoning_queue.push_text(text)
        return

    # --- Fallback: original word-boundary flush path (unchanged, including
    #     the word-boundary flush block that follows the while loop) ---
    self._reasoning_buf = getattr(self, "_reasoning_buf", "") + text
    while "\n" in self._reasoning_buf:
        line, self._reasoning_buf = self._reasoning_buf.split("\n", 1)
        # ... (existing per-line rendering code unchanged) ...
    # ... (existing word-boundary flush block unchanged) ...
```

#### Modified `_close_reasoning_box`

The required operation order is strict: the reasoning pump must be fully drained before
the box border is drawn, and the box border must be drawn before deferred response content
is pushed to `_emit_stream_text` (which starts the response pump). Interleaving any of
these steps would corrupt terminal output.

```python
def _close_reasoning_box(self) -> None:
    if not getattr(self, "_reasoning_box_opened", False):
        return

    # Step 1: drain and join the reasoning pump so all animated chars are
    # committed before the border is drawn.
    if _TYPEWRITER_ENABLED and self._tw_reasoning_pump is not None:
        self._tw_reasoning_pump.flush_now()
        self._tw_reasoning_pump.stop()
        self._tw_reasoning_pump.join(timeout=2)
        if self._tw_reasoning_pump.is_alive():
            log.warning(
                "reasoning pump did not stop within 2 s; "
                "partial reasoning output may be incomplete"
            )
        self._tw_reasoning_pump = None

    # Step 2: flush word-boundary buffer (non-typewriter path or leftover).
    if getattr(self, "_reasoning_buf", ""):
        _cprint(_dim_lines(self._reasoning_buf)[0])
        self._reasoning_buf = ""

    # Step 3: draw the closing border.
    w = shutil.get_terminal_size().columns
    _cprint(f"{_DIM}└{'─' * (w - 2)}┘{_RST}")
    self._reasoning_box_opened = False

    # Step 4: push deferred response content AFTER the border.
    # In typewriter mode this calls the modified _emit_stream_text which
    # creates the response pump and pushes chars to its queue.
    deferred = getattr(self, "_deferred_content", "")
    if deferred:
        self._deferred_content = ""
        self._emit_stream_text(deferred)
```

#### Reasoning pump lifecycle

| Event | Action |
|---|---|
| First reasoning token | Create `_TypewriterPump` (reasoning params); start; store as `self._tw_reasoning_pump` |
| `_close_reasoning_box()` called | `pump.flush_now()` → `pump.stop()` → `pump.join(timeout=2)` → log warning if alive → `self._tw_reasoning_pump = None` → draw border → push deferred content |
| `_reset_stream_state()` | Same as above — handled in the shared `_reset_stream_state` additions block (replaces both queues, nulls both pump refs). |

---

## Configuration

```python
# cli.py module-level constants (user-adjustable via CLI_CONFIG):
_TYPEWRITER_CHAR_DELAY_MS = 18    # milliseconds between characters (~56 CPS visual)
_TYPEWRITER_ENABLED       = True  # set False to fall back to word-boundary flush
```

Exposed in `CLI_CONFIG["display"]`:
```yaml
display:
  typewriter: true
  typewriter_delay_ms: 18
```

Speed reference (CPS = characters per second):

| delay_ms | CPS  | Character feel |
|---|---|---|
| 0 | ∞ | Instant per-char (equivalent to word-boundary flush) |
| 10 | ~100 | Fast, barely perceptible animation |
| 18 | ~56 | Default — fast, natural for technical content |
| 30 | ~33 | Visible beat; comfortable for prose |
| 50 | ~20 | Deliberate, readable |
| 80+ | ≤12 | Slow classic typewriter feel |

---

## Edge Cases

### E1 — Stream ends mid-line (no trailing `\n`)
`_flush_stream()` calls `pump.flush_now()` then `pump.stop()`. The pump processes
`FLUSH_SENTINEL` (commits partial) then `STOP_SENTINEL` (commits again — no-op since
buffer is now empty — then returns).

### E2 — Very fast tokens (buffer piles up)
The pump processes one character per `char_delay_ms`. If the model streams 50 tokens/s and
`char_delay_ms = 18`, the queue grows faster than it is consumed. This is intentional — the
pump is the rate limiter, and the queue acts as a jitter buffer. The visual output lags
behind the model, which is correct for a typewriter effect. The queue is unbounded (deque);
no backpressure is applied to the token stream.

### E3 — Stream interrupted (Ctrl+C)
The existing interrupt path calls `_flush_stream()` which joins the pump. The pump commits
the partial line and exits. No orphan threads since the pump is a daemon thread. A second
Ctrl+C during the 2 s join window is handled by the daemon flag — the thread is abandoned
but reaped on process exit.

### E4 — Multi-line tokens (token contains `\n`)
`push_text(text)` iterates character by character; `\n` chars are pushed individually.
When the pump pops a `\n`, it calls `_commit_line()`. Multiple newlines in a single token
result in multiple sequential `_commit_line()` calls — correct.

### E5 — Reasoning box open, content token arrives
`_emit_stream_text` defers content while the reasoning box is open (existing logic,
`self._deferred_content`). When `_close_reasoning_box()` is called:
1. The reasoning pump is joined (all reasoning chars committed).
2. The reasoning box border is drawn.
3. Deferred content is passed to `_emit_stream_text`, which creates the response pump.

This ordering is explicit in `_close_reasoning_box` above. The response pump never starts
before the reasoning pump finishes.

### E6 — Rich response with code block
A fenced code block spans multiple lines. The pump animates each code line character by
character (raw chars including indentation), and `_commit_line` sends each line through
`_stream_block_buf.process_line()` and `_stream_code_hl.process_line()`. The state machines
are stateful — they must be fed lines in order, which is guaranteed since the pump
serializes all output.

### E7 — `app.invalidate()` called from pump thread
`app.invalidate()` is thread-safe in prompt_toolkit (uses `call_soon_threadsafe` internally).
No lock needed around the call from the pump thread.

### E8 — `_app` is `None` (non-TUI mode / tests)
`_write_char` guards with `if cli._app is not None`. In non-TUI mode, `_pt_print` still
works (prints directly to stdout), and the missing `invalidate()` call is harmless.
`_app` is always initialized to `None` in `__init__`, so no `hasattr` check is needed.

### E9 — `_commit_line` called when `_line_buf` is empty
Guard: `if not self._line_buf: return` at top of `_commit_line`. Covers double-commit
from `flush_now()` immediately followed by `stop()`.

### E10 — Partial line contains ANSI codes (color applied mid-animation)
`_write_char` wraps each character with the stream color prefix + `_RST` suffix. Since
each character is a fully closed ANSI sequence, there are no unclosed spans in the terminal
state at any point during animation.

### E11 — `pump.join(timeout=2)` times out
The pump thread is a daemon so it will be reaped when the process exits. A
`log.warning` is emitted so the condition is visible in debug logs. The session continues
normally; the state-machine flush and box border are drawn immediately after.

### E12 — `_flush_stream` called twice (e.g., interrupt + normal teardown)
After the first call, `self._tw_pump` is set to `None`. The second call skips the pump
block entirely (`if _TYPEWRITER_ENABLED and self._tw_pump is not None` is False). The
orphan `FLUSH_SENTINEL` / `STOP_SENTINEL` pushed by the first call sit in `_tw_queue`
until `_reset_stream_state` replaces the queue with a fresh instance — harmless.

---

## What Does NOT Change

- `_flush_stream` call sites — signature unchanged; pump join is added inside the body
- `_close_reasoning_box` call sites — signature unchanged; reasoning pump stop is added inside the body
- `_stream_block_buf`, `_stream_code_hl`, `_reasoning_block_buf`, `_reasoning_code_hl`
  state machines — called from `_commit_line` (same pipeline, different call site)
- The non-streaming Panel path (post-response reasoning display) — unchanged
- All existing tests for line-buffered behaviour — updated to reflect pump architecture

---

## Test Plan

### Unit tests (`tests/cli/test_typewriter_pump.py`)

| Test | Assertion |
|---|---|
| `test_write_char_emits_single_char_not_full_buf` | `_write_char('e')` with `_line_buf = "he"` → `_pt_print` receives only `"e"` (not `"he"`) |
| `test_write_char_uses_ansi_attr` | Pump constructed with `ansi_attr="_reasoning_text_ansi"` reads color from that attr, not `_stream_text_ansi` |
| `test_newline_commits_line` | `\n` in queue → `_commit_line` called; `_cprint` receives full line; `_line_buf` empty |
| `test_flush_sentinel_commits` | `FLUSH_SENTINEL` → `_commit_line`; remaining chars committed |
| `test_stop_sentinel_commits_and_exits` | `STOP_SENTINEL` → `_commit_line` then thread exits |
| `test_stop_after_chars_commits_partial` | Push `h`, `e`, `l`, `STOP_SENTINEL`; pump commits `"hel"` before exiting (no silent drop) |
| `test_empty_commit_is_noop` | `_commit_line` with empty `_line_buf` does not call `_cprint` |
| `test_multiline_token` | Text with two `\n` → two `_commit_line` calls in order |
| `test_invalidate_called_per_char` | `app.invalidate()` called once per non-newline character |
| `test_no_invalidate_when_app_none` | `_app = None` → no AttributeError; pump continues |
| `test_char_delay_observed` | With `char_delay_ms=50`, two chars take ≥ 90 ms (assert via `time.monotonic`) |
| `test_commit_line_feeds_block_buf_state_machine` | `_stream_block_buf.process_line()` and `_stream_code_hl.process_line()` called in order per committed line |
| `test_commit_line_feeds_reasoning_state_machines` | Pump with `block_buf_attr="_reasoning_block_buf"` calls that attr's `process_line()`, not `_stream_block_buf` |
| `test_commit_line_applies_line_wrapper` | Reasoning pump (with `line_wrapper=_dim_lines[0]`) passes committed line through wrapper before `_cprint` |
| `test_commit_line_clears_partial_width` | `_pt_print` receives `\r + spaces(_vlen(line)) + \r` before the committed line |
| `test_drain_clears_event_before_dequeue` | Push one item; call `drain()`; push another item concurrently; verify second item retrievable on next `drain()` without waiting for timeout |
| `test_join_timeout_logs_warning` | Stall pump artificially; verify `log.warning` is called if join exceeds 2 s |
| `test_is_empty_reflects_queue_state` | `is_empty()` returns `True` when deque is empty, `False` after `push()` |
| `test_drain_re_sets_event_when_items_remain` | Push 100 items; `drain(max_items=64)` returns 64; event is set afterwards (36 remaining) |
| `test_drain_clears_event_when_queue_empty` | Push 10 items; `drain(max_items=64)` returns 10; event is cleared (queue empty) |
| `test_pump_processes_large_queue_without_stall` | Push 200 chars with `char_delay_ms=0`; all committed within 200 ms (no 500 ms inter-batch stalls) |
| `test_pump_thread_names_distinct` | Response pump `name == "typewriter-pump"`; reasoning pump `name == "typewriter-pump-reasoning"` |
| `test_write_char_skips_sleep_when_app_none` | Pump with `char_delay_ms=100` and `_app=None` processes 10 chars in < 100 ms (sleep is skipped) |
| `test_init_reasoning_text_ansi_is_empty_string` | After `__init__`, `_reasoning_text_ansi` attribute exists and equals `""` |

### Integration tests (`tests/cli/test_typewriter_integration.py`)

| Test | Assertion |
|---|---|
| `test_emit_stream_text_feeds_queue` | `_emit_stream_text("hello")` → queue contains `h`, `e`, `l`, `l`, `o` |
| `test_emit_stream_text_fallback_when_disabled` | `_TYPEWRITER_ENABLED = False` → `_stream_buf` accumulates chars; queue not used |
| `test_flush_stream_stops_pump` | After `_flush_stream()`, pump thread is not alive |
| `test_flush_stream_nulls_pump_ref` | After `_flush_stream()`, `self._tw_pump is None` |
| `test_flush_stream_state_machine_flush_after_pump` | `_stream_block_buf.flush()` and `_stream_code_hl.flush()` are called after pump joins |
| `test_flush_stream_idempotent` | Second call to `_flush_stream()` after pump is None does not raise and does not re-enter pump block |
| `test_reset_creates_fresh_queue` | After `_reset_stream_state()`, `_tw_queue` is a new `_TypewriterQueue` instance |
| `test_reasoning_pump_independent` | Reasoning and response pumps are separate instances; each stops independently |
| `test_close_reasoning_box_joins_before_border` | `_close_reasoning_box()` joins reasoning pump before `_cprint` receives border characters |
| `test_close_reasoning_box_deferred_content_after_border` | Deferred content is pushed to response pump only after the box border `_cprint` call |
| `test_init_creates_queues_not_none` | After `__init__`, `_tw_queue` and `_tw_reasoning_queue` are `_TypewriterQueue` instances (not `None`) |
| `test_init_pumps_are_none` | After `__init__`, `_tw_pump` and `_tw_reasoning_pump` are `None` |
| `test_reset_replaces_both_queues` | `_reset_stream_state()` replaces both `_tw_queue` and `_tw_reasoning_queue` with new instances |
| `test_reset_nulls_pumps_without_prior_flush` | `_reset_stream_state()` without preceding `_flush_stream()` still leaves both pump refs `None` |
| `test_reset_resets_reasoning_text_ansi` | After `_close_reasoning_box()` sets `_reasoning_text_ansi` to `_DIM`, `_reset_stream_state()` resets it back to `""` |

### Regression tests

Existing `tests/cli/test_cli_stream_per_token.py` requires updates:
- `TestEmitStreamTextLineBuf`: `test_token_accumulates_in_buf` and
  `test_multi_token_accumulation` must be updated since chars now go to the queue,
  not `_stream_buf`, when `_TYPEWRITER_ENABLED = True`
- `TestWordBoundaryFlush`: tests must set `_TYPEWRITER_ENABLED = False` to exercise the
  fallback path, or be replaced by `test_emit_stream_text_feeds_queue`
- All `_pt_print(end="")` absence assertions remain valid (pump uses `_pt_print(end="")`
  only inside `_write_char`, which is tested separately)

---

## Appendix: Option B — FormattedTextControl Live Row

If Option A proves unreliable (cursor-state issues across `run_in_terminal` cycles), the
layout-based approach is as follows:

### Layout addition

```python
# In the layout definition (cli.py ~line 7524):
from prompt_toolkit.layout import FormattedTextControl, Window
from prompt_toolkit.filters import Condition

typewriter_row = Window(
    content=FormattedTextControl(lambda: self._tw_live_line or []),
    height=1,
    dont_extend_height=True,
    style="class:typewriter",
)
typewriter_visible = Condition(lambda: bool(self._tw_live_line))

# Insert ConditionalContainer(typewriter_row, typewriter_visible)
# into the layout HSplit, between the scrollable output area and the input rule.
```

### Live line state

```python
# Add to __init__:
self._tw_live_line: list = []   # FormattedText fragment list, updated by pump
```

### Pump changes for Option B

`_write_char` becomes:
```python
def _write_char(self, ch: str) -> None:
    ansi = getattr(self._cli, self._ansi_attr, "")
    text = f"{ansi}{self._line_buf}{_RST}" if ansi else self._line_buf
    self._cli._tw_live_line = [("", text)]  # whole buffer; layout re-renders
    self._cli._app.invalidate()
```

`_commit_line` clears `_tw_live_line` (sets it to `[]`) then calls `_cprint` as before.
The committed line is permanently above the live row in the scrollback.

This approach has zero cursor-position dependencies and is guaranteed to work correctly.
The trade-off is layout complexity and the visual position (live row is always at the bottom
of the output area, above the input prompt — this is actually the more natural placement for
streaming output anyway).

---

## Implementation Order

1. Add `_TypewriterQueue` and `_TypewriterPump` classes in a new `cli_typewriter.py`
   module (keeps `cli.py` from growing further); import into `cli.py`
2. Add `__init__` attributes (`_tw_queue`, `_tw_reasoning_queue`, `_tw_pump`,
   `_tw_reasoning_pump`)
3. Modify `_emit_stream_text` to feed the queue (with `_TYPEWRITER_ENABLED` guard)
4. Modify `_flush_stream` to join pump + null ref
5. Modify `_close_reasoning_box` with the four-step sequence (join → flush buf → border → deferred)
6. Modify `_stream_reasoning_delta` to feed the reasoning queue
7. Set `_reasoning_text_ansi = _DIM` at reasoning-box-open time (step in `_stream_reasoning_delta`)
8. Update `_reset_stream_state` to replace queues with fresh instances
9. Add config knobs (`_TYPEWRITER_CHAR_DELAY_MS`, `_TYPEWRITER_ENABLED`) and
   `CLI_CONFIG["display"]` keys
10. Write unit tests (`test_typewriter_pump.py`)
11. Write integration tests (`test_typewriter_integration.py`)
12. Update / replace word-boundary flush regression tests
13. Manual smoke test; if Option A cursor issues observed, implement Option B layout
