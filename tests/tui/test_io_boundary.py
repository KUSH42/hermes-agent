"""Tests for hermes_cli/tui/io_boundary.py — Phase A.

Test IDs: T-URL-01..05, T-PATH-01..03, T-RUN-01..07, T-OPEN-URL-01..04,
T-READ-01..03, T-WRITE-01..03, T-EDIT-01..06,
T-BOUND-01a, T-BOUND-01b, T-BOUND-02..06, T-INT-01..02.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

import hermes_cli.tui.io_boundary as _mod
from hermes_cli.tui.io_boundary import (
    IOBoundaryError,
    ValidationError,
    SuspendBusyError,
    FileTooLargeError,
    SpawnError,
    _validate_url,
    _validate_path,
    _resolve_app,
    _dispatch_worker,
    _safe_callback,
    _is_gui_editor,
    safe_run,
    safe_open_url,
    safe_edit_cmd,
    safe_read_file,
    safe_write_file,
    cancel_all,
    scan_sync_io,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kw):
    """Build a minimal mock App-like object for non-Textual unit tests."""
    app = MagicMock()
    app._suspend_busy = kw.get("_suspend_busy", False)
    return app


def _make_widget(app=None):
    from textual.widget import Widget as _Widget
    w = MagicMock(spec=_Widget)
    w.app = app or _make_app()
    return w


# ---------------------------------------------------------------------------
# T-URL-01  accepts https / http / file:// / mailto:
# ---------------------------------------------------------------------------

class TestTURL01:
    def test_https(self):
        url = _validate_url("https://example.com")
        assert url.startswith("https://")

    def test_http_with_path_query(self):
        url = _validate_url("http://example.com/path?q=1")
        assert "example.com" in url

    def test_file(self):
        url = _validate_url("file:///home/x/foo.txt")
        assert url.startswith("file:///")

    def test_mailto(self):
        url = _validate_url("mailto:a@b.co")
        assert url == "mailto:a@b.co"


# ---------------------------------------------------------------------------
# T-URL-02  rejects blocked schemes
# ---------------------------------------------------------------------------

class TestTURL02:
    @pytest.mark.parametrize("bad_url", [
        "javascript:alert(1)",
        "data:text/html,<script>",
        "vbscript:msgbox(1)",
        "about:blank",
        "",
    ])
    def test_rejects(self, bad_url):
        with pytest.raises(ValidationError):
            _validate_url(bad_url)


# ---------------------------------------------------------------------------
# T-URL-03  normalizes file:// paths containing .. ; rejects control chars
# ---------------------------------------------------------------------------

class TestTURL03:
    def test_normalizes_dotdot(self):
        url = _validate_url("file:///etc/../etc/passwd")
        assert "/etc/passwd" in url
        assert ".." not in url

    def test_rejects_control_char_in_file_path(self):
        with pytest.raises(ValidationError):
            _validate_url("file:///tmp/foo\nbar")

    def test_rejects_semicolon_in_file_path(self):
        with pytest.raises(ValidationError):
            _validate_url("file:///tmp/foo;bar")


# ---------------------------------------------------------------------------
# T-URL-04  strips whitespace / canonicalizes
# ---------------------------------------------------------------------------

class TestTURL04:
    def test_strips_whitespace(self):
        url = _validate_url("  https://foo.com  ")
        assert url == "https://foo.com"

    def test_canonicalizes_returns_string(self):
        url = _validate_url("https://example.com/path?q=1")
        assert isinstance(url, str)

    def test_semicolon_in_https_path_accepted(self):
        """https: ; in path is valid per RFC 3986; forbidden-char checks only apply to file://."""
        url = _validate_url("https://example.com; rm -rf /")
        assert "example.com" in url

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError):
            _validate_url("ftp://foo")

    def test_no_scheme_rejected(self):
        with pytest.raises(ValidationError):
            _validate_url("/tmp/foo.txt")


# ---------------------------------------------------------------------------
# T-URL-05  mailto regex
# ---------------------------------------------------------------------------

class TestTURL05:
    @pytest.mark.parametrize("good", [
        "mailto:user@example.com",
        "mailto:user.name+tag@domain.org",
        "mailto:a@b.co?subject=hi",
    ])
    def test_accepts(self, good):
        url = _validate_url(good)
        assert url.startswith("mailto:")

    def test_rejects_invalid_mailto(self):
        with pytest.raises(ValidationError):
            _validate_url("mailto:not-an-email")


# ---------------------------------------------------------------------------
# T-PATH-01  rejects shell metachars, newlines, null bytes
# ---------------------------------------------------------------------------

class TestTPATH01:
    @pytest.mark.parametrize("bad_path", [
        "/tmp/foo; rm -rf /",
        "/tmp/foo\nbar",
        "/tmp/foo\x00bar",
        "/tmp/foo|bar",
        "/tmp/foo$HOME",
    ])
    def test_rejects(self, bad_path):
        with pytest.raises(ValidationError):
            _validate_path(bad_path)


# ---------------------------------------------------------------------------
# T-PATH-02  sandbox_root rejects traversal
# ---------------------------------------------------------------------------

class TestTPATH02:
    def test_rejects_traversal(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        with pytest.raises(ValidationError):
            _validate_path("../../../etc/passwd", sandbox_root=sandbox)

    def test_accepts_inside_sandbox(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        target = sandbox / "notes.md"
        resolved = _validate_path(str(target), sandbox_root=sandbox)
        assert resolved.is_relative_to(sandbox)


# ---------------------------------------------------------------------------
# T-PATH-03  expanduser + resolve round-trip
# ---------------------------------------------------------------------------

class TestTPATH03:
    def test_expanduser(self):
        resolved = _validate_path("~/notes.md")
        assert not str(resolved).startswith("~")
        assert resolved.is_absolute()

    def test_resolve_removes_dotdot(self, tmp_path):
        p = str(tmp_path / "a" / ".." / "b.txt")
        resolved = _validate_path(p)
        assert ".." not in str(resolved)


# ---------------------------------------------------------------------------
# T-RUN-01  safe_run dispatches to worker, on_success fires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun01_safe_run_on_success():
    """safe_run dispatches to worker; on_success fires via call_from_thread."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    success_args = []

    def on_success(out, err, rc):
        success_args.append((out, err, rc))

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = b"hello"
    fake_result.stderr = b""

    with patch("hermes_cli.tui.io_boundary.subprocess.run", return_value=fake_result):
        async with app.run_test(size=(80, 24)) as pilot:
            w = safe_run(app, ["echo", "hello"], timeout=5, on_success=on_success)
            assert w is not None
            await pilot.pause(delay=0.2)

    assert len(success_args) == 1
    assert success_args[0] == ("hello", "", 0)


# ---------------------------------------------------------------------------
# T-RUN-02  on_error fires on non-zero rc
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun02_safe_run_on_error_nonzero():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    error_args = []

    def on_error(exc, stderr):
        error_args.append((exc, stderr))

    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = b""
    fake_result.stderr = b"error text"

    with patch("hermes_cli.tui.io_boundary.subprocess.run", return_value=fake_result):
        async with app.run_test(size=(80, 24)) as pilot:
            safe_run(app, ["false"], timeout=5, on_error=on_error)
            await pilot.pause(delay=0.2)

    assert len(error_args) == 1
    exc, stderr = error_args[0]
    assert isinstance(exc, subprocess.CalledProcessError)
    assert stderr == "error text"


# ---------------------------------------------------------------------------
# T-RUN-03  on_timeout fires; on_error does NOT fire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun03_safe_run_on_timeout():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    timeout_args = []
    error_args = []

    def on_timeout(elapsed):
        timeout_args.append(elapsed)

    def on_error(exc, stderr):
        error_args.append((exc, stderr))

    with patch(
        "hermes_cli.tui.io_boundary.subprocess.run",
        side_effect=subprocess.TimeoutExpired("sleep", 5),
    ):
        async with app.run_test(size=(80, 24)) as pilot:
            safe_run(
                app, ["sleep", "100"], timeout=0.001,
                on_timeout=on_timeout, on_error=on_error
            )
            await pilot.pause(delay=0.2)

    assert len(timeout_args) == 1
    assert len(error_args) == 0


# ---------------------------------------------------------------------------
# T-RUN-04  cancelled worker → no callbacks fire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun04_cancelled_worker_no_callbacks():
    from hermes_cli.tui.app import HermesApp
    import threading, time

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    success_args = []
    error_args = []

    barrier = threading.Event()

    def slow_run(*args, **kw):
        barrier.wait(timeout=2)
        result = MagicMock()
        result.returncode = 0
        result.stdout = b"out"
        result.stderr = b""
        return result

    with patch("hermes_cli.tui.io_boundary.subprocess.run", side_effect=slow_run):
        async with app.run_test(size=(80, 24)) as pilot:
            w = safe_run(
                app, ["echo", "hi"], timeout=5,
                on_success=lambda *a: success_args.append(a),
                on_error=lambda *a: error_args.append(a),
            )
            assert w is not None
            w.cancel()
            barrier.set()
            await pilot.pause(delay=0.2)

    # With cancellation, callbacks should not fire
    assert len(success_args) == 0
    assert len(error_args) == 0


# ---------------------------------------------------------------------------
# T-RUN-05  empty cmd → returns None, on_error fires synchronously
# ---------------------------------------------------------------------------

def test_trun05_empty_cmd_returns_none():
    """safe_run with empty cmd list returns None; on_error fires synchronously."""
    error_args = []

    def on_error(exc, stderr):
        error_args.append((exc, stderr))

    # Use a mock app (no Textual event loop needed — validation is synchronous)
    app = MagicMock()
    result = safe_run(app, [], timeout=5, on_error=on_error)

    assert result is None
    assert len(error_args) == 1
    exc, stderr = error_args[0]
    assert isinstance(exc, ValidationError)
    assert stderr == ""


# ---------------------------------------------------------------------------
# T-RUN-06  on_timeout=None → timeout fires, no callback, no exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun06_on_timeout_none_silent():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    raised = []

    with patch(
        "hermes_cli.tui.io_boundary.subprocess.run",
        side_effect=subprocess.TimeoutExpired("sleep", 5),
    ):
        async with app.run_test(size=(80, 24)) as pilot:
            # on_timeout=None (default) — worker should exit cleanly, no exception
            try:
                safe_run(app, ["sleep", "100"], timeout=0.001)
                await pilot.pause(delay=0.2)
            except Exception as exc:
                raised.append(exc)

    assert len(raised) == 0


# ---------------------------------------------------------------------------
# T-RUN-07  capture=False → on_success("", "", 0)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trun07_capture_false():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    success_args = []

    def on_success(out, err, rc):
        success_args.append((out, err, rc))

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = None   # capture=False → None
    fake_result.stderr = None

    with patch("hermes_cli.tui.io_boundary.subprocess.run", return_value=fake_result):
        async with app.run_test(size=(80, 24)) as pilot:
            safe_run(
                app, ["true"], timeout=5,
                on_success=on_success, capture=False
            )
            await pilot.pause(delay=0.2)

    assert len(success_args) == 1
    assert success_args[0] == ("", "", 0)


# ---------------------------------------------------------------------------
# T-OPEN-URL-01  rejects invalid URL → on_error(ValidationError), no spawn
# ---------------------------------------------------------------------------

def test_topen_url01_rejects_invalid():
    """safe_open_url with javascript: URL → on_error(ValidationError) synchronously."""
    errors = []
    app = MagicMock()

    with patch("hermes_cli.tui.io_boundary.safe_run") as mock_run:
        safe_open_url(app, "javascript:alert(1)", on_error=lambda exc: errors.append(exc))

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# T-OPEN-URL-02  valid URL on linux → safe_run(["xdg-open", url])
# ---------------------------------------------------------------------------

def test_topen_url02_linux_opener():
    app = MagicMock()
    url = "https://example.com"

    with patch("hermes_cli.tui.io_boundary.safe_run") as mock_run, \
         patch("hermes_cli.tui.io_boundary.sys.platform", "linux"):
        safe_open_url(app, url)

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] is app
    assert args[1] == ["xdg-open", url]


# ---------------------------------------------------------------------------
# T-OPEN-URL-03  macOS and Windows openers
# ---------------------------------------------------------------------------

def test_topen_url03_macos_opener():
    app = MagicMock()
    url = "https://example.com"

    with patch("hermes_cli.tui.io_boundary.safe_run") as mock_run, \
         patch("hermes_cli.tui.io_boundary.sys.platform", "darwin"):
        safe_open_url(app, url)

    args, _ = mock_run.call_args
    assert args[1] == ["open", url]


def test_topen_url03_windows_opener():
    app = MagicMock()
    url = "https://example.com"

    with patch("hermes_cli.tui.io_boundary.safe_run") as mock_run, \
         patch("hermes_cli.tui.io_boundary.sys.platform", "win32"):
        safe_open_url(app, url)

    args, _ = mock_run.call_args
    assert args[1] == ["cmd.exe", "/c", "start", "", url]


# ---------------------------------------------------------------------------
# T-OPEN-URL-04  on_error=None → invalid URL silently discarded
# ---------------------------------------------------------------------------

def test_topen_url04_no_error_callback_no_crash():
    app = MagicMock()
    with patch("hermes_cli.tui.io_boundary.safe_run") as mock_run:
        # Should not raise even with invalid URL and no on_error
        safe_open_url(app, "javascript:alert(1)")
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# T-READ-01  safe_read_file dispatches to worker, on_done fires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tread01_reads_file(tmp_path):
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    target = tmp_path / "hello.txt"
    target.write_text("hello world", encoding="utf-8")

    done_args = []

    async with app.run_test(size=(80, 24)) as pilot:
        safe_read_file(app, target, on_done=lambda content: done_args.append(content))
        await pilot.pause(delay=0.2)

    assert done_args == ["hello world"]


# ---------------------------------------------------------------------------
# T-READ-02  file exceeds max_bytes → on_error(FileTooLargeError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tread02_file_too_large(tmp_path):
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    target = tmp_path / "big.txt"
    target.write_bytes(b"x" * 200)

    errors = []

    async with app.run_test(size=(80, 24)) as pilot:
        safe_read_file(
            app, target, max_bytes=100,
            on_done=lambda c: None,
            on_error=lambda exc: errors.append(exc),
        )
        await pilot.pause(delay=0.2)

    assert len(errors) == 1
    assert isinstance(errors[0], FileTooLargeError)


# ---------------------------------------------------------------------------
# T-READ-03  encoding=None → on_done(bytes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tread03_binary_mode(tmp_path):
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01\x02")

    done_args = []

    async with app.run_test(size=(80, 24)) as pilot:
        safe_read_file(
            app, target, encoding=None,
            on_done=lambda content: done_args.append(content),
        )
        await pilot.pause(delay=0.2)

    assert done_args == [b"\x00\x01\x02"]


# ---------------------------------------------------------------------------
# T-WRITE-01  safe_write_file append mode, fire-and-forget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrite01_append_fire_and_forget(tmp_path):
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    target = tmp_path / "history.txt"
    target.write_text("first\n", encoding="utf-8")

    async with app.run_test(size=(80, 24)) as pilot:
        # on_done=None — fire and forget
        safe_write_file(app, target, "second\n", mode="a", on_done=None)
        await pilot.pause(delay=0.2)

    assert target.read_text() == "first\nsecond\n"


# ---------------------------------------------------------------------------
# T-WRITE-02  shell-metachar path → on_error(ValidationError) synchronously
# ---------------------------------------------------------------------------

def test_twrite02_metachar_path_sync_error():
    errors = []
    app = MagicMock()

    with patch("hermes_cli.tui.io_boundary._dispatch_worker") as mock_dw:
        safe_write_file(
            app, "/tmp/foo;bar", "data",
            on_error=lambda exc: errors.append(exc),
        )

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    mock_dw.assert_not_called()


# ---------------------------------------------------------------------------
# T-WRITE-03  mkdir_parents=True → parent dir created; _validate_path called with mkdir_parents=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrite03_mkdir_parents(tmp_path):
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    target = tmp_path / "new_dir" / "subdir" / "file.txt"
    assert not target.parent.exists()

    done_args = []

    async with app.run_test(size=(80, 24)) as pilot:
        safe_write_file(
            app, target, "content", mkdir_parents=True,
            on_done=lambda n: done_args.append(n),
        )
        await pilot.pause(delay=0.2)

    assert target.exists()
    assert target.read_text() == "content"
    assert len(done_args) == 1


# ---------------------------------------------------------------------------
# T-EDIT-01  _suspend_busy=True → on_error(SuspendBusyError); no suspend called
# ---------------------------------------------------------------------------

def test_tedit01_suspend_busy():
    errors = []
    app = MagicMock()
    app._suspend_busy = True

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app):
        safe_edit_cmd(
            app, ["nvim"], "/tmp/foo.txt",
            on_error=lambda exc: errors.append(exc),
        )

    assert len(errors) == 1
    assert isinstance(errors[0], SuspendBusyError)
    app.suspend.assert_not_called()


# ---------------------------------------------------------------------------
# T-EDIT-02  GUI editor → delegates to safe_open_url; no suspend
# ---------------------------------------------------------------------------

def test_tedit02_gui_editor_delegates(tmp_path):
    errors = []
    app = MagicMock()
    app._suspend_busy = False

    target = tmp_path / "test.txt"
    target.write_text("hi")

    open_url_calls = []

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app), \
         patch("hermes_cli.tui.io_boundary.safe_open_url", side_effect=lambda *a, **kw: open_url_calls.append((a, kw))):
        safe_edit_cmd(
            app, ["code"], str(target),
            on_error=lambda exc: errors.append(exc),
        )

    assert len(open_url_calls) == 1
    assert len(errors) == 0
    app.suspend.assert_not_called()


# ---------------------------------------------------------------------------
# T-EDIT-03  empty cmd_argv, no $EDITOR/$VISUAL → delegates to safe_open_url
# ---------------------------------------------------------------------------

def test_tedit03_empty_cmd_no_editor(tmp_path):
    app = MagicMock()
    app._suspend_busy = False

    target = tmp_path / "test.txt"
    target.write_text("hi")

    open_url_calls = []

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app), \
         patch("hermes_cli.tui.io_boundary.safe_open_url", side_effect=lambda *a, **kw: open_url_calls.append((a, kw))), \
         patch.dict(os.environ, {}, clear=True):
        # Remove EDITOR and VISUAL from environment
        env_bak = {}
        for var in ("EDITOR", "VISUAL"):
            env_bak[var] = os.environ.pop(var, None)
        try:
            safe_edit_cmd(app, None, str(target))
        finally:
            for var, val in env_bak.items():
                if val is not None:
                    os.environ[var] = val

    assert len(open_url_calls) == 1


# ---------------------------------------------------------------------------
# T-EDIT-04  full happy path: terminal editor, suspend called
# ---------------------------------------------------------------------------

def test_tedit04_happy_path_suspend(tmp_path):
    exit_calls = []
    app = MagicMock()
    app._suspend_busy = False

    target = tmp_path / "test.txt"
    target.write_text("hello")

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app), \
         patch("hermes_cli.tui.io_boundary.subprocess.run") as mock_run:
        safe_edit_cmd(
            app, ["nvim"], str(target),
            on_exit=lambda: exit_calls.append(True),
        )

    app.suspend.assert_called_once()
    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv[0] == "nvim"
    assert str(target) in argv
    assert len(exit_calls) == 1
    # Flag must be reset after
    assert app._suspend_busy is False


# ---------------------------------------------------------------------------
# T-EDIT-05  line=42 → "+42" precedes filename
# ---------------------------------------------------------------------------

def test_tedit05_line_arg(tmp_path):
    app = MagicMock()
    app._suspend_busy = False

    target = tmp_path / "test.txt"
    target.write_text("hello")

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app), \
         patch("hermes_cli.tui.io_boundary.subprocess.run") as mock_run:
        safe_edit_cmd(app, ["nvim"], str(target), line=42)

    argv = mock_run.call_args[0][0]
    assert "+42" in argv
    path_idx = argv.index(str(target))
    plus_idx = argv.index("+42")
    assert plus_idx < path_idx


# ---------------------------------------------------------------------------
# T-EDIT-06  path with shell metachar → on_error(ValidationError) at step 2
# ---------------------------------------------------------------------------

def test_tedit06_metachar_path():
    errors = []
    app = MagicMock()
    app._suspend_busy = False

    with patch("hermes_cli.tui.io_boundary._resolve_app", return_value=app):
        safe_edit_cmd(
            app, ["nvim"], "/tmp/foo;bar",
            on_error=lambda exc: errors.append(exc),
        )

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    assert app._suspend_busy is False
    app.suspend.assert_not_called()


# ---------------------------------------------------------------------------
# T-BOUND-01a  smoke test — scanner runs, prints results (never fails)
# ---------------------------------------------------------------------------

def test_tbound01a_scanner_smoke(capsys):
    """T-BOUND-01a: scan real TUI tree; print results; test always passes."""
    tui_dir = Path(__file__).parents[2] / "hermes_cli" / "tui"
    files = list(tui_dir.rglob("*.py"))
    # Skip io_boundary.py itself (sanctioned site); desktop_notify.py migrated in Phase B
    files = [
        f for f in files
        if f.name not in ("io_boundary.py",)
    ]
    violations = scan_sync_io(files)
    if violations:
        print(f"\n[T-BOUND-01a] {len(violations)} unexempted sync-io site(s):")
        for path, lineno, name in violations:
            rel = path.relative_to(tui_dir.parent.parent)
            print(f"  {rel}:{lineno}  {name}")
    # Always passes — Phase A warning-only
    assert True


# ---------------------------------------------------------------------------
# T-BOUND-01b  scanner detection works on synthetic file
# ---------------------------------------------------------------------------

def test_tbound01b_scanner_detects_synthetic(tmp_path):
    """T-BOUND-01b: scanner finds exactly 1 violation in a controlled test file."""
    synthetic = tmp_path / "synthetic.py"
    synthetic.write_text(
        "import subprocess\n"
        "def foo():\n"
        "    subprocess.run(['ls'])\n",
        encoding="utf-8",
    )
    violations = scan_sync_io([synthetic])
    assert len(violations) == 1
    path, lineno, name = violations[0]
    assert path == synthetic
    assert lineno == 3
    assert "subprocess.run" in name


# ---------------------------------------------------------------------------
# T-BOUND-02  hard-fail scan (skipif until Phase C)
# ---------------------------------------------------------------------------

def test_no_sync_io():
    """T-BOUND-02: assert zero unexempted sync-io violations in hermes_cli/tui/."""
    tui_dir = Path(__file__).parents[2] / "hermes_cli" / "tui"
    files = [
        f for f in tui_dir.rglob("*.py")
        if f.name not in ("io_boundary.py",)
    ]
    violations = scan_sync_io(files)
    if violations:
        lines = [f"  {p.relative_to(tui_dir.parent.parent)}:{n}  {c}" for p, n, c in violations]
        raise AssertionError(
            f"{len(violations)} unexempted sync-io violation(s):\n" + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# T-BOUND-03  # allow-sync-io: reason opts out a call
# ---------------------------------------------------------------------------

def test_tbound03_allow_comment(tmp_path):
    f = tmp_path / "allowed.py"
    f.write_text(
        "import subprocess\n"
        "def foo():  # allow-sync-io: intentional for tests\n"
        "    subprocess.run(['ls'])\n",
        encoding="utf-8",
    )
    violations = scan_sync_io([f])
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# T-BOUND-04  short reason or missing reason still flagged
# ---------------------------------------------------------------------------

def test_tbound04_short_reason_flagged(tmp_path):
    """# allow-sync-io: ok (2 chars) and # allow-sync-io: (0 chars) are flagged."""
    f1 = tmp_path / "short.py"
    f1.write_text(
        "import subprocess\n"
        "def foo():\n"
        "    subprocess.run(['ls'])  # allow-sync-io: ok\n",
        encoding="utf-8",
    )
    violations = scan_sync_io([f1])
    assert len(violations) == 1  # 'ok' = 2 chars, too short

    f2 = tmp_path / "empty.py"
    f2.write_text(
        "import subprocess\n"
        "def foo():\n"
        "    subprocess.run(['ls'])  # allow-sync-io:\n",
        encoding="utf-8",
    )
    violations2 = scan_sync_io([f2])
    assert len(violations2) == 1  # empty reason, flagged


# ---------------------------------------------------------------------------
# T-BOUND-05  two-line lookback: comment on line N-1 exempts
# ---------------------------------------------------------------------------

def test_tbound05_lookback(tmp_path):
    f = tmp_path / "lookback.py"
    f.write_text(
        "import subprocess\n"
        "def foo():\n"
        "    # allow-sync-io: runs in worker thread\n"
        "    subprocess.run(['ls'])\n",
        encoding="utf-8",
    )
    violations = scan_sync_io([f])
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# T-BOUND-06  two-line look-ahead: comment two lines BELOW exempts
# ---------------------------------------------------------------------------

def test_tbound06_lookahead(tmp_path):
    f = tmp_path / "lookahead.py"
    f.write_text(
        "import subprocess\n"
        "def foo():\n"
        "    subprocess.run(\n"
        "        ['ls'],\n"
        "        timeout=15  # allow-sync-io: runs in worker thread\n"
        "    )\n",
        encoding="utf-8",
    )
    violations = scan_sync_io([f])
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# T-INT-01  integration: safe_open_url with javascript: → on_error(ValidationError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tint01_integration_invalid_url():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    errors = []

    async with app.run_test(size=(80, 24)) as pilot:
        # Call safe_open_url directly from within the running app context
        app.call_after_refresh(
            safe_open_url,
            app,
            "javascript:alert(1)",
            on_error=lambda exc: errors.append(exc),
        )
        await pilot.pause(delay=0.1)

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)


# ---------------------------------------------------------------------------
# T-INT-02  integration: safe_open_url with valid URL + mocked subprocess → no on_error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tint02_integration_valid_url_no_error():
    from hermes_cli.tui.app import HermesApp

    cli = MagicMock()
    cli.session_start = None
    app = HermesApp(cli=cli, clipboard_available=True)

    error_calls = []

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = b""
    fake_result.stderr = b""

    with patch("hermes_cli.tui.io_boundary.subprocess.run", return_value=fake_result):
        async with app.run_test(size=(80, 24)) as pilot:
            app.call_after_refresh(
                safe_open_url,
                app,
                "https://example.com",
                on_error=lambda exc: error_calls.append(exc),
            )
            await pilot.pause(delay=0.2)

    assert len(error_calls) == 0
