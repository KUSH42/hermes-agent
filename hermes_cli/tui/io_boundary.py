"""I/O Boundary enforcement module for the Hermes TUI.

All synchronous subprocess and file I/O in hermes_cli/tui/ must be routed through
this module. Callers pass ``self`` (a Widget or the App) as the first positional
argument; ``_resolve_app`` resolves it to the App for worker dispatch.

Callback contract
-----------------
- Callbacks dispatched from worker threads fire **on the event loop** via
  ``app.call_from_thread``.
- Inside a callback body, call widget methods directly.  Do NOT wrap in another
  ``call_from_thread`` — that raises ``RuntimeError``.
- Worker-dispatched callbacks should guard with ``if not self.is_mounted: return``.
- Synchronous validation-failure callbacks fire directly on the calling thread
  (the event loop) before the helper returns — no ``await`` or ``pilot.pause``
  needed in tests.

Boundary opt-out
----------------
Use ``# allow-sync-io: <reason>`` (reason >= 3 chars) on the call line or within
two lines above/below it to exempt a specific site from T-BOUND-01a/02 scanner.

Scanner limitations
-------------------
- Aliased imports (``import subprocess as _sp; _sp.run(...)``) are NOT caught.
- ``path_variable.open(...)`` where ``path_variable`` is a pre-existing variable
  is NOT caught (only inline-constructed ``Path(...).open(...)`` patterns are).
- ``Path(...).parent.open(...)`` chained through intermediate attribute access is
  NOT caught — the intermediate ``.parent`` breaks the inline-constructed pattern.
- ``from pathlib import Path as P; P(...).open(...)`` aliased Path imports are NOT
  caught — scanner only checks ``ast.Name(id="Path")`` and ``ast.Name(id="pathlib")``.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from textual.worker import get_current_worker

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget
    from textual.worker import Worker

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FORBIDDEN_PATH_CHARS: set[str] = {';', '|', '&', '$', '`', '\n', '\r', '\x00'}

_GUI_EDITORS: set[str] = {"code", "subl", "atom", "gedit", "kate", "mousepad", "xed", "pluma"}

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class IOBoundaryError(Exception):
    """Base class for all io_boundary errors.  Carries a ``reason`` string."""
    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        super().__init__(reason)


class ValidationError(IOBoundaryError):
    """URL or path rejected by the validator."""


class SuspendBusyError(IOBoundaryError):
    """Suspend requested but another suspend (TTE/editor) is already active."""


class FileTooLargeError(IOBoundaryError):
    """File exceeds the ``max_bytes`` limit."""


class SpawnError(IOBoundaryError):
    """Reserved for Phase C+.  Dead code — never instantiated in Phase A/B."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https", "file", "mailto"}
_BLOCKED_SCHEMES = {"javascript", "data", "vbscript", "about", "chrome", "view-source"}
_MAILTO_RE = re.compile(r'^mailto:[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(\?.*)?$')


def _validate_url(url: str, *, sandbox_root: "Path | None" = None) -> str:
    """Validate and canonicalize a URL.

    Returns the canonicalized URL string on success.
    Raises ValidationError on rejection.
    """
    url = url.strip()
    if not url:
        raise ValidationError("empty URL")

    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()

    if not scheme:
        raise ValidationError("missing scheme")
    if scheme in _BLOCKED_SCHEMES:
        raise ValidationError(f"scheme not allowed: {scheme}")
    if scheme not in _ALLOWED_SCHEMES:
        raise ValidationError(f"scheme not allowed: {scheme}")

    if scheme == "mailto":
        if not _MAILTO_RE.match(url):
            raise ValidationError("invalid mailto URL")
        return urllib.parse.urlunparse(parsed)

    if scheme == "file":
        # Check the raw URL string for forbidden chars before urlparse normalizes them away
        # (urlparse strips \n, \r, \x00 from paths silently)
        raw_path = url[len("file://"):] if url.lower().startswith("file://") else url
        for ch in _FORBIDDEN_PATH_CHARS:
            if ch in raw_path:
                raise ValidationError(f"forbidden character in file path: {repr(ch)}")
        path_part = parsed.path
        # Resolve path (normalizes ..)
        resolved = Path(path_part).resolve(strict=False)
        if sandbox_root is not None:
            try:
                resolved.relative_to(sandbox_root)
            except ValueError:
                raise ValidationError("file path outside sandbox root")
        new_parsed = parsed._replace(path=str(resolved))
        return urllib.parse.urlunparse(new_parsed)

    # http / https — no forbidden-char check on path (RFC 3986 ; is valid)
    return urllib.parse.urlunparse(parsed)


def _validate_path(
    path: "str | Path",
    *,
    for_write: bool = False,
    sandbox_root: "Path | None" = None,
    mkdir_parents: bool = False,
) -> Path:
    """Validate and resolve a file path.

    Returns the resolved Path on success.
    Raises ValidationError on rejection.
    """
    # Check forbidden chars in the raw path string BEFORE resolve() (null byte causes ValueError)
    raw = str(path)
    for ch in _FORBIDDEN_PATH_CHARS:
        if ch in raw:
            raise ValidationError(f"forbidden character in path: {repr(ch)}")

    resolved = Path(raw).expanduser().resolve(strict=False)

    # Also check resolved path components for any chars that might survive expansion
    for part in resolved.parts:
        for ch in _FORBIDDEN_PATH_CHARS:
            if ch in part:
                raise ValidationError(f"forbidden character in path component: {repr(ch)}")

    # sandbox_root check
    if sandbox_root is not None:
        try:
            resolved.relative_to(sandbox_root)
        except ValueError:
            raise ValidationError("path outside sandbox root")

    if for_write and not mkdir_parents:
        # Check parent exists and is writable
        parent = resolved.parent
        if parent.exists() and not os.access(parent, os.W_OK):
            raise ValidationError(f"parent directory not writable: {parent}")
        # Reject symlink targets outside sandbox_root
        if sandbox_root is not None and resolved.is_symlink():
            real = resolved.resolve(strict=False)
            try:
                real.relative_to(sandbox_root)
            except ValueError:
                raise ValidationError("symlink target outside sandbox root")

    return resolved


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_app(caller: "App | Widget") -> "App":
    """Return the App instance from caller (App or Widget)."""
    from textual.app import App
    from textual.widget import Widget as _Widget
    if isinstance(caller, App):
        return caller
    if isinstance(caller, _Widget):
        return caller.app
    raise TypeError(f"caller must be App or Widget, got {type(caller)!r}")


def _dispatch_worker(app: "App", fn: "Callable") -> "Worker":
    """Dispatch fn as a thread worker registered under the 'io_boundary' group."""
    return app.run_worker(fn, thread=True, exclusive=False, group="io_boundary")


def _safe_callback(app: "App", cb: "Callable | None", *args: object) -> None:
    """Schedule cb(*args) on the event loop from a worker thread.

    Must only be called from inside a worker thread.
    Swallows non-RuntimeError exceptions (broken callback logic).
    Re-raises RuntimeError (programming bug: called from event loop).
    """
    if cb is None:
        return
    try:
        app.call_from_thread(cb, *args)
    except RuntimeError:
        raise  # called from event loop — programming bug
    except Exception:
        pass  # swallow broken callback logic


def _is_gui_editor(cmd_argv: "list[str]") -> bool:
    """Return True if cmd_argv[0] names a known GUI editor binary."""
    binary = os.path.basename(cmd_argv[0])
    return binary in _GUI_EDITORS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def safe_run(
    caller: "App | Widget",
    cmd: "list[str]",
    *,
    timeout: "float | int",
    on_success: "Callable | None" = None,
    on_error: "Callable | None" = None,
    on_timeout: "Callable | None" = None,
    env: "dict | None" = None,
    cwd: "str | Path | None" = None,
    input_bytes: "bytes | None" = None,
    capture: bool = True,
) -> "Worker | None":
    """Dispatch a subprocess command to a thread worker.

    Validates cmd synchronously; dispatches the actual subprocess.run call
    to a worker thread.  Callbacks fire on the event loop.

    Returns the Worker on success, or None if synchronous validation failed
    (in which case on_error has already been called before returning).

    Must be called from the event loop (action handlers, on_mount, etc.).
    """
    # Synchronous validation
    if not cmd:
        exc = ValidationError("cmd must be a non-empty list")
        if on_error:
            on_error(exc, "")
        return None
    for elem in cmd:
        if elem is None or not isinstance(elem, str):
            exc = ValidationError(f"all cmd elements must be str, got {type(elem)!r}")
            if on_error:
                on_error(exc, "")
            return None

    app = _resolve_app(caller)

    def _worker_body() -> None:
        w = get_current_worker()
        # Check cancellation before spawning
        if w.is_cancelled:
            return
        try:
            if input_bytes is not None and not capture:
                result = subprocess.run(
                    cmd,
                    input=input_bytes,
                    check=True,
                    timeout=timeout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                result = subprocess.run(
                    cmd,
                    timeout=timeout,
                    capture_output=capture,
                    env=env,
                    cwd=cwd,
                    input=input_bytes,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc_te:
            elapsed = float(timeout)
            if on_timeout is not None:
                _safe_callback(app, on_timeout, elapsed)
            return
        except (OSError, subprocess.SubprocessError) as exc_os:
            _safe_callback(app, on_error, exc_os, "")
            return

        # Check cancellation after subprocess returns
        if w.is_cancelled:
            return

        decoded_stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        decoded_stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""

        if result.returncode != 0:
            synthetic_exc = subprocess.CalledProcessError(
                result.returncode, cmd, stderr=decoded_stderr.encode('utf-8', errors='replace')
            )
            _safe_callback(app, on_error, synthetic_exc, decoded_stderr)
        else:
            _safe_callback(app, on_success, decoded_stdout, decoded_stderr, result.returncode)

    return _dispatch_worker(app, _worker_body)


def safe_open_url(
    caller: "App | Widget",
    url: str,
    *,
    on_error: "Callable | None" = None,
) -> None:
    """Open a URL in the system browser/handler.

    Validates the URL synchronously; dispatches xdg-open/open/start to a worker.
    on_error is one-arg: on_error(exc: Exception).
    """
    try:
        url = _validate_url(url)
    except ValidationError as exc:
        if on_error:
            on_error(exc)
        return

    # Resolve platform opener
    if sys.platform == "darwin":
        opener = ["open"]
    elif sys.platform == "win32":
        opener = ["cmd.exe", "/c", "start", ""]
    else:
        opener = ["xdg-open"]

    # Adapt on_error: safe_run calls on_error(exc, stderr) but safe_open_url is 1-arg
    _err = (lambda exc, _: on_error(exc)) if on_error else None

    safe_run(caller, [*opener, url], timeout=10, on_error=_err)


def safe_edit_cmd(
    caller: "App | Widget",
    cmd_argv: "list[str] | None",
    path: "str | Path",
    *,
    line: "int | None" = None,
    on_exit: "Callable | None" = None,
    on_error: "Callable | None" = None,
) -> None:
    """Launch a terminal editor with full-terminal ownership via App.suspend().

    Execution order (authoritative):
      1. Resolve cmd_argv (fallback to $EDITOR / $VISUAL).
      2. Validate path via _validate_path.
      3. If empty cmd_argv or GUI editor: delegate to safe_open_url.
      4. If app._suspend_busy: call on_error(SuspendBusyError).
      5. Structured try/except/finally: set _suspend_busy, suspend, run, on_exit.

    on_error is one-arg: on_error(exc: Exception).
    on_exit is zero-arg: on_exit() called after suspend exits.
    """
    app = _resolve_app(caller)

    # Step 1: resolve cmd_argv
    cmd_argv = cmd_argv or shlex.split(
        os.environ.get("EDITOR") or os.environ.get("VISUAL") or ""
    )

    # Step 2: validate path
    try:
        resolved_path = _validate_path(path)
    except ValidationError as exc:
        if on_error:
            on_error(exc)
        return

    # Step 3: empty cmd_argv or GUI editor → delegate to safe_open_url
    if not cmd_argv or _is_gui_editor(cmd_argv):
        safe_open_url(caller, resolved_path.as_uri(), on_error=on_error)
        return

    # Step 4: check suspend busy flag
    if app._suspend_busy:
        if on_error:
            on_error(SuspendBusyError("another suspend (TTE/editor) is already active"))
        return

    # Step 5: suspend and run
    try:
        app._suspend_busy = True  # first line inside try
        argv = [*cmd_argv] + ([f"+{line}"] if line is not None else []) + [str(resolved_path)]
        with app.suspend():
            subprocess.run(argv)  # allow-sync-io: safe_edit_cmd is intentionally blocking via App.suspend()
        if on_exit:
            on_exit()
    except (OSError, subprocess.SubprocessError) as exc:
        if on_error:
            on_error(exc)
    finally:
        app._suspend_busy = False


def safe_read_file(
    caller: "App | Widget",
    path: "str | Path",
    *,
    encoding: "str | None" = "utf-8",
    max_bytes: int = 1_048_576,
    on_done: "Callable",
    on_error: "Callable | None" = None,
    sandbox_root: "Path | None" = None,
) -> None:
    """Read a file in a worker thread and dispatch on_done with the content.

    on_done(content: str | bytes) — str when encoding is set, bytes when encoding=None.
    on_error(exc: Exception) — one arg.
    """
    try:
        resolved = _validate_path(path, sandbox_root=sandbox_root)
    except ValidationError as exc:
        if on_error:
            on_error(exc)
        return

    app = _resolve_app(caller)

    def _worker_body() -> None:
        try:
            size = resolved.stat().st_size
            if size > max_bytes:
                _safe_callback(
                    app, on_error,
                    FileTooLargeError(f"file exceeds max_bytes={max_bytes}: {size} bytes")
                )
                return
            if encoding is None:
                content: "str | bytes" = resolved.read_bytes()
            else:
                content = resolved.read_text(encoding=encoding)
            _safe_callback(app, on_done, content)
        except Exception as exc:
            _safe_callback(app, on_error, exc)

    _dispatch_worker(app, _worker_body)


def safe_write_file(
    caller: "App | Widget",
    path: "str | Path",
    data: "str | bytes",
    *,
    encoding: "str | None" = "utf-8",
    mode: str = "w",
    on_done: "Callable | None" = None,
    on_error: "Callable | None" = None,
    mkdir_parents: bool = False,
    sandbox_root: "Path | None" = None,
) -> None:
    """Write data to a file in a worker thread.

    on_done(bytes_written: int) — optional, fire-and-forget if None.
    on_error(exc: Exception) — one arg.
    """
    try:
        resolved = _validate_path(
            path,
            for_write=True,
            sandbox_root=sandbox_root,
            mkdir_parents=mkdir_parents,
        )
    except ValidationError as exc:
        if on_error:
            on_error(exc)
        return

    app = _resolve_app(caller)

    def _worker_body() -> None:
        try:
            if mkdir_parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            if encoding is None:
                with open(resolved, mode + "b" if "b" not in mode else mode) as f:  # allow-sync-io: inside worker thread, off event loop
                    written = f.write(data)
            else:
                with open(resolved, mode, encoding=encoding) as f:  # allow-sync-io: inside worker thread, off event loop
                    written = f.write(data)
            _safe_callback(app, on_done, written)
        except Exception as exc:
            _safe_callback(app, on_error, exc)

    _dispatch_worker(app, _worker_body)


def cancel_all(app: "App") -> None:
    """Cancel all pending io_boundary workers for this app instance."""
    app.workers.cancel_group(app, "io_boundary")


# ---------------------------------------------------------------------------
# Boundary scanner (used by T-BOUND-01a/01b)
# ---------------------------------------------------------------------------

def scan_sync_io(paths: "Iterable[Path]") -> "list[tuple[Path, int, str]]":
    """Scan Python source files for unexempted synchronous I/O call sites.

    Returns a list of (file_path, lineno, call_name) tuples for each call site
    that is not exempted by an ``# allow-sync-io: <reason>`` comment within two
    lines above or below the call.

    Rules:
    - Matches: subprocess.run/Popen/call/check_output/check_call,
               os.system/popen/exec*, open() builtin, io.open(),
               Path(...).open(), pathlib.Path(...).open().
    - Aliased subprocess imports (``import subprocess as _sp``) are NOT caught.
    - ``path_variable.open()`` (pre-existing variable) is NOT caught.
    - ``Path(...).parent.open()`` chained through attribute access is NOT caught.
    - ``from pathlib import Path as P; P(...).open()`` aliased imports are NOT caught.
    - Reason must be >= 3 chars after stripping or the exemption is invalid.
    """
    violations: list[tuple[Path, int, str]] = []

    _SUBPROCESS_ATTRS = {
        "run", "Popen", "call", "check_output", "check_call"
    }
    _OS_ATTRS_BLOCKED = {
        "system", "popen",
        "execl", "execle", "execlp", "execlpe",
        "execv", "execve", "execvp", "execvpe",
    }
    _OS_ATTRS_ALLOWED = {"execvp"}  # session-switch contract

    def _lines_of(p: Path) -> list[str]:
        try:
            return p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []

    def _is_exempted(lines: list[str], lineno: int) -> bool:
        # lineno is 1-based (from ast)
        lo = max(0, lineno - 3)   # lineno-2 inclusive (0-based: lineno-1-2 = lineno-3)
        hi = min(len(lines), lineno + 2)  # lineno+2 inclusive (0-based: lineno-1+2+1 = lineno+2)
        window = lines[lo:hi]
        for raw_line in window:
            idx = raw_line.find("# allow-sync-io:")
            if idx == -1:
                continue
            reason_part = raw_line[idx + len("# allow-sync-io:"):].strip()
            if len(reason_part) >= 3:
                return True
        return False

    def _check_call_node(node: ast.Call, lines: list[str], filepath: Path) -> "str | None":
        """Return the call name if this node is a blocked sync-io call, else None."""
        func = node.func

        # subprocess.X(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _SUBPROCESS_ATTRS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            return f"subprocess.{func.attr}"

        # os.system / os.popen / os.exec* (except execvp)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            attr = func.attr
            if attr in _OS_ATTRS_BLOCKED and attr not in _OS_ATTRS_ALLOWED:
                return f"os.{attr}"
            # os.exec* pattern (catch all execXXX except execvp)
            if attr.startswith("exec") and attr not in _OS_ATTRS_ALLOWED:
                return f"os.{attr}"

        # open(...) builtin — ast.Name(id="open")
        if isinstance(func, ast.Name) and func.id == "open":
            return "open"

        # io.open(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "open"
            and isinstance(func.value, ast.Name)
            and func.value.id == "io"
        ):
            return "io.open"

        # Path(...).open(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "open"
            and isinstance(func.value, ast.Call)
        ):
            inner = func.value
            # Path(...).open(...)
            if isinstance(inner.func, ast.Name) and inner.func.id == "Path":
                return "Path(...).open"
            # pathlib.Path(...).open(...)
            if (
                isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "Path"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id == "pathlib"
            ):
                return "pathlib.Path(...).open"

        return None

    for filepath in paths:
        filepath = Path(filepath)
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(filepath))
        except Exception:
            continue

        lines = source.splitlines()

        for node in ast.walk(tree):
            call_node: "ast.Call | None" = None

            if isinstance(node, ast.Call):
                call_node = node
            elif isinstance(node, ast.With):
                # with open(...) as f — check context items
                for item in node.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        call_node = ctx
                        break

            if call_node is None:
                continue

            call_name = _check_call_node(call_node, lines, filepath)
            if call_name is None:
                continue

            lineno = call_node.lineno
            if not _is_exempted(lines, lineno):
                violations.append((filepath, lineno, call_name))

    return violations
