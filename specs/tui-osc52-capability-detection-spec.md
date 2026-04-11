# TUI OSC 52 Clipboard Capability Detection — Feature Specification

**Status:** IMPLEMENTED 2026-04-11  
**Impact:** Low  
**Key:** SPEC-E  

---

## 1. Problem Statement

`HermesApp` uses Textual's `App.copy_to_clipboard(text)` for all clipboard operations. Textual's implementation sends an OSC 52 escape sequence to the terminal. OSC 52 is widely supported (kitty, WezTerm, iTerm2, tmux ≥ 3.2) but silently fails in terminals that do not support it (gnome-terminal, xterm without a special patch, many SSH sessions).

When clipboard copy fails silently, the user sees `"⎘  N chars copied"` but the clipboard is empty — misleading feedback that is worse than no feedback.

This spec defines:
1. A **capability probe** that detects OSC 52 support before TUI startup
2. Conditional UI feedback: success vs. failure distinction in copy hints
3. A **graceful no-op** with informative message when OSC 52 is unavailable

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| OSC 52 probe at pre-startup (separate event loop) | pyperclip / xclip / pbcopy fallback |
| `_clipboard_available: bool` on `HermesApp` | SSH forwarding of OSC 52 |
| Conditional copy hint ("⎘ copied" vs "⚠ clipboard unavailable") | Re-probing on reconnect |
| `HERMES_CLIPBOARD=0|1` env var override | Detecting set-only vs. get+set capability separately |
| Probe timeout: 500 ms | Persisting result across sessions |
| Platform guard: skip probe on Windows | |

---

## 3. OSC 52 Probe Mechanism

### 3.1 How OSC 52 read-back works

OSC 52 supports both *set* (write clipboard) and *get* (read clipboard) operations. A terminal that supports OSC 52 *get* responds to the probe with a DCS sequence:

Probe sequence (BEL terminator):
```
ESC ] 52 ; c ; ? BEL
```

Valid response patterns:
```
ESC ] 52 ; c ; <base64-content> BEL   (clipboard content, possibly empty base64)
ESC ] 52 ; c ; BEL                    (empty clipboard)
ESC \ (ST — string terminator)        (some terminals: acknowledgement without content)
```

If unsupported: no response (timeout), or echoed escape bytes (response parse rejects them).

### 3.2 Probe implementation

File: `hermes_cli/tui/osc52_probe.py` (new file)

```python
"""OSC 52 clipboard capability probe.

Must be called BEFORE App.run() — uses a separate event loop to avoid
racing with Textual's terminal ownership.
"""

from __future__ import annotations

import asyncio
import os
import sys

_OSC52_PROBE = "\033]52;c;?\a"   # BEL terminator
_PROBE_TIMEOUT = 0.5             # seconds to wait for terminal response


async def probe_osc52() -> bool:
    """Return True if the terminal responds to an OSC 52 read-back probe.

    False is returned (not raised) for ALL failure conditions:
    - Not a TTY
    - Not Linux/macOS (Windows: termios unavailable)
    - Timeout (terminal supports set-only or no OSC 52)
    - Exception in terminal raw-mode handling

    Callers should treat False conservatively (clipboard unavailable).
    The HERMES_CLIPBOARD env var overrides this result entirely.
    """
    # Platform guard: termios is POSIX-only
    if sys.platform == "win32":
        return False

    import termios  # import inside function: avoids ImportError on Windows
    import tty
    import select

    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return False

    old_settings = None  # initialize before try so finally block can safely check
    try:
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)

        # Send the probe
        os.write(sys.stdout.fileno(), _OSC52_PROBE.encode())

        # Wait for initial response data
        loop = asyncio.get_event_loop()
        ready = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: select.select([fd], [], [], _PROBE_TIMEOUT)),
            timeout=_PROBE_TIMEOUT + 0.1,  # outer timeout slightly longer than inner
        )
        if not ready[0]:
            return False  # timeout — not supported

        # Drain all available response bytes (50 ms timeout per read)
        response = b""
        while True:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                break
            chunk = os.read(fd, 256)
            if not chunk:
                break
            response += chunk

        # Validate: response must contain OSC 52 header, NOT be the echoed probe itself
        # A terminal that doesn't support OSC 52 may echo the probe bytes literally.
        # Valid responses contain ESC]52 followed by a semicolon-separated payload.
        if b"\033]52;c;" in response or b"\x9d52;c;" in response:
            # Ensure it's a genuine response, not the echoed probe
            # The echoed probe would match exactly _OSC52_PROBE bytes
            if response.strip() != _OSC52_PROBE.encode().strip():
                return True

        return False

    except Exception:
        return False

    finally:
        # `termios` was imported earlier in this function (after the win32 guard).
        # On any code path that reaches `finally` with `old_settings is not None`,
        # the `import termios` line above has already executed successfully — so
        # `termios` is available in this scope without re-importing.
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass  # best-effort restore


def check_clipboard_env() -> bool | None:
    """Return True/False if HERMES_CLIPBOARD env var is set, else None (run probe)."""
    val = os.environ.get("HERMES_CLIPBOARD", "").strip()
    if val == "1":
        return True
    if val == "0":
        return False
    return None
```

### 3.3 Probe timing

The probe runs in `cli.py` *before* `HermesApp.run()`:

```python
# In cli.py run() (before app.run()):
from hermes_cli.tui.osc52_probe import probe_osc52, check_clipboard_env

_clipboard_override = check_clipboard_env()
if _clipboard_override is not None:
    _clipboard_ok = _clipboard_override
else:
    _clipboard_ok = asyncio.run(probe_osc52())   # separate event loop, pre-Textual

app = HermesApp(cli, clipboard_available=_clipboard_ok)
app.run()
```

**Why pre-startup:** Textual's `App.run()` acquires exclusive terminal raw mode. Sending raw escape sequences and reading responses inside an active Textual session would race with Textual's own terminal reader. Using `asyncio.run()` (a completely separate event loop) before `app.run()` avoids this race entirely.

---

## 4. HermesApp Changes

### 4.1 Constructor

```python
def __init__(
    self,
    cli: Any,
    startup_fn=None,
    clipboard_available: bool = True,
    **kwargs: Any,
) -> None:
    super().__init__(**kwargs)
    # ... existing init unchanged ...
    self._clipboard_available: bool = clipboard_available
```

### 4.2 `_copy_text_with_hint()` method

Extract and consolidate the existing `copy_to_clipboard` + `_flash_hint` pattern into a single method. All existing copy call sites are updated to use it:

```python
def _copy_text_with_hint(self, text: str) -> None:
    """Copy text to clipboard with capability guard and hint flash."""
    if not self._clipboard_available:
        self._flash_hint("⚠  Clipboard unavailable (terminal has no OSC 52 support)", 2.5)
        return
    self.copy_to_clipboard(text)
    self._flash_hint(f"⎘  {len(text)} chars copied", 1.5)
```

**Existing call sites to migrate:**

Replace all occurrences of the pattern:
```python
self.copy_to_clipboard(content)
self._flash_hint(f"⎘  {len(content)} chars copied", 1.5)
```
with:
```python
self._copy_text_with_hint(content)
```

The following locations in `app.py` contain this pattern:
- `_copy_tool_output()`
- `_copy_all_output()`
- `_copy_panel()`
- `_copy_text()` (existing method, if present)
- Browse-mode `c` key handler in `on_key()`
- `ctrl+c` selected-text copy branch in `on_key()`

---

## 5. StatusBar Indicator (Optional)

If `_clipboard_available` is `False`, a persistent `⚠ no clipboard` indicator appears in the StatusBar (rightmost, dim). This is informational — the session is fully functional, only copy is affected.

```css
/* hermes.tcss */
#status-clipboard-warning {
    color: $warning;
    display: none;
    margin-left: 1;
}
#status-clipboard-warning.--active {
    display: block;
}
```

In `HermesApp.on_mount()`:
```python
if not self._clipboard_available:
    try:
        self.query_one("#status-clipboard-warning").add_class("--active")
    except NoMatches:
        pass
```

`StatusBar` must yield `Static("⚠ no clipboard", id="status-clipboard-warning")` in its `compose()` method, positioned as the rightmost element (after all existing indicators).

This section is **optional** — implementers may omit the persistent indicator and rely solely on per-copy hint flashes.

---

## 6. Environment Override

| `HERMES_CLIPBOARD` value | Behaviour |
|---|---|
| `1` | Skip probe; `_clipboard_available = True` (force OSC 52 on) |
| `0` | Skip probe; `_clipboard_available = False` (force clipboard off) |
| unset or any other value | Run probe (default behaviour) |

`check_clipboard_env()` (in `osc52_probe.py`) handles this before `probe_osc52()` is called (see §3.3).

---

## 7. Probe Failure Mode Reference

| Failure mode | Detection | Result |
|---|---|---|
| Not a TTY (pipe, CI) | `os.isatty(fd) == False` | `False` immediately |
| Windows | `sys.platform == "win32"` | `False` immediately |
| Terminal supports OSC 52 set-only | Timeout (0.5 s) | `False` (use `HERMES_CLIPBOARD=1` override) |
| SSH without OSC 52 passthrough | Timeout | `False` |
| tmux < 3.2 | Timeout | `False` |
| tmux ≥ 3.2 with `set-clipboard on` | Valid response | `True` |
| Terminal echoes probe literally | Response rejected by validation | `False` |
| `termios.tcgetattr` fails | Exception; `old_settings=None` | `False`; `finally` skips `tcsetattr` safely |
| `tty.setraw` fails | Exception | `False`; `finally` restores `old_settings` if set |

**Known false-negative:** Terminals that support OSC 52 *set* (write) but not *get* (read-back) will probe as `False`. Alacritty is the primary example. These users should set `HERMES_CLIPBOARD=1`.

---

## 8. Tests

File: `tests/tui/test_osc52_capability.py`

| # | Test | Assertion |
|---|---|---|
| 1 | `probe_osc52()` with mocked `select.select` returning fd ready + response `b"\033]52;c;dGVzdA==\a"` → True | Returns True |
| 2 | `probe_osc52()` with mocked `select.select` timeout → False | Returns False (within ≤ 0.7 s) |
| 3 | `probe_osc52()` when `os.isatty` returns False → False | Returns False immediately |
| 4 | `probe_osc52()` with `sys.platform == "win32"` → False | Returns False without importing `termios` |
| 5 | `probe_osc52()` with `termios.tcgetattr` raising `OSError` → False, does not raise | Returns False; terminal state unchanged |
| 6 | `probe_osc52()` response is the echoed probe bytes → False (not a valid response) | Returns False |
| 7 | `HermesApp(_clipboard_available=False)` + `_copy_text_with_hint("x")` → warning flash | HintBar contains "Clipboard unavailable" |
| 8 | `HermesApp(_clipboard_available=False)` + `_copy_text_with_hint()` → `copy_to_clipboard` NOT called | Mock not called |
| 9 | `HermesApp(_clipboard_available=True)` + `_copy_text_with_hint("hello")` → "5 chars copied" | HintBar contains "5 chars" |
| 10 | `HermesApp(_clipboard_available=True)` + `_copy_text_with_hint()` → `copy_to_clipboard` called | Mock called once |
| 11 | `HERMES_CLIPBOARD=1` → `check_clipboard_env()` returns True | No probe call needed |
| 12 | `HERMES_CLIPBOARD=0` → `check_clipboard_env()` returns False | No probe call needed |
| 13 | `HERMES_CLIPBOARD` unset → `check_clipboard_env()` returns None | Probe should be run |
| 14 | Browse-mode `c` with clipboard unavailable → warning hint | HintBar text correct |
| 15 | Context menu "Copy tool output" with clipboard unavailable → warning hint | HintBar text correct |

---

## 9. Non-Goals

- pyperclip / xclip / pbcopy fallback
- Re-probing on terminal resize or reconnect
- Detecting set-only vs. get+set OSC 52 capability independently
