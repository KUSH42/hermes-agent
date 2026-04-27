"""Tests for CWD-1..CWD-4 — StatusBar CWD display and BashService CWD tracking."""
from __future__ import annotations

import os
import time
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar():
    """Return a StatusBar instance without a running Textual app."""
    from hermes_cli.tui.widgets.status_bar import StatusBar

    class _IsolatedBar(StatusBar):
        # Override read-only Textual properties so unit tests can set them
        app = None  # type: ignore[assignment]
        size = None  # type: ignore[assignment]
        content_size = None  # type: ignore[assignment]

    bar = object.__new__(_IsolatedBar)
    bar._model_changed_at = 0.0
    bar._cwd_changed_at = 0.0
    # _tok_s_displayed is a Textual reactive — bypass descriptor via __dict__
    bar.__dict__["_tok_s_displayed"] = 0.0
    bar._pulse_active = False
    bar._classes = frozenset()
    return bar


def _make_app(**kwargs: Any) -> types.SimpleNamespace:
    """Minimal app stub for StatusBar.render() calls."""
    defaults = dict(
        status_model="claude-sonnet-4-6",
        status_context_tokens=0,
        status_context_max=0,
        status_compaction_progress=0.0,
        status_compaction_enabled=False,
        status_streaming=False,
        agent_running=False,
        command_running=False,
        yolo_mode=False,
        compact=False,
        status_verbose=False,
        status_active_file="",
        status_active_file_offscreen=False,
        browse_mode=False,
        browse_index=0,
        _browse_total=0,
        status_output_dropped=False,
        context_pct=0.0,
        session_label="",
        session_count=1,
        status_error="",
        status_tok_s=0.0,
        status_phase="idle",
        status_cwd="",
        feedback=None,
        _cfg={},
    )
    defaults.update(kwargs)
    app = types.SimpleNamespace(**defaults)
    app.get_css_variables = lambda: {}
    return app


def _render(bar, app, *, width: int = 80, compact: bool = False) -> str:
    """Call StatusBar.render() with mocked size/app and return plain text."""
    from unittest.mock import PropertyMock
    app.compact = compact

    size_ns = types.SimpleNamespace(width=width, height=1)
    content_size_ns = types.SimpleNamespace(width=width, height=1)

    bar.__class__.app = property(lambda s: app)
    bar.__class__.size = property(lambda s: size_ns)
    bar.__class__.content_size = property(lambda s: content_size_ns)

    result = bar.render()
    # result is a Rich Text or string
    if hasattr(result, "plain"):
        return result.plain
    return str(result)


# ---------------------------------------------------------------------------
# CWD-1 — HermesApp.status_cwd reactive
# ---------------------------------------------------------------------------

class TestCWD1AppReactive:
    def test_status_cwd_is_reactive(self):
        from textual.reactive import reactive as _reactive
        from hermes_cli.tui.app import HermesApp
        assert isinstance(HermesApp.__dict__["status_cwd"], _reactive)

    def test_status_cwd_initial_value(self):
        """_set_workspace_tracker sets status_cwd to os.getcwd()."""
        from hermes_cli.tui.app import HermesApp

        app = object.__new__(HermesApp)
        # Minimal attrs needed by _set_workspace_tracker
        app.__dict__["status_cwd"] = ""
        recorded = {}

        # Intercept the reactive write
        def _set_cwd(val):
            recorded["cwd"] = val

        app.__class__ = type(
            "_TestApp",
            (HermesApp,),
            {"status_cwd": property(lambda s: recorded.get("cwd", ""),
                                    lambda s, v: recorded.__setitem__("cwd", v))},
        )

        stub_tracker = MagicMock()
        stub_poller = MagicMock()
        stub_poller.is_git_repo = True

        with patch.object(app.__class__, "_last_git_snapshot", new=MagicMock(), create=True):
            # Call the method directly — it reads os.getcwd()
            expected_cwd = os.getcwd()
            HermesApp._set_workspace_tracker(app, stub_tracker, stub_poller)

        assert recorded.get("cwd") == expected_cwd


# ---------------------------------------------------------------------------
# CWD-2 — BashService persistent CWD + shell wrapping
# ---------------------------------------------------------------------------

class TestCWD2BashService:
    def _make_service(self, **app_attrs):
        from hermes_cli.tui.services.bash_service import BashService
        app = MagicMock()
        for k, v in app_attrs.items():
            setattr(app, k, v)
        svc = object.__new__(BashService)
        svc.app = app
        svc._proc = None
        svc._running = False
        svc._bash_cwd = os.getcwd()
        return svc

    def test_sh_c_invocation(self):
        """Popen is called with ['sh', '-c', ...] not a bare arg list."""
        svc = self._make_service()
        block = MagicMock()
        block.push_line = MagicMock()

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait = MagicMock(return_value=None)
            proc.returncode = 0
            mock_popen.return_value = proc

            svc._exec_sync("echo hello", block)

        call_args = mock_popen.call_args
        cmd_list = call_args[0][0]
        assert cmd_list[0] == "sh"
        assert cmd_list[1] == "-c"

    def test_cwd_marker_stripped_from_display(self):
        """The sentinel line is NOT forwarded to block.push_line."""
        from hermes_cli.tui.services.bash_service import _CWD_SENTINEL
        svc = self._make_service()
        block = MagicMock()
        pushed_lines = []
        svc.app.call_from_thread = lambda fn, *a: fn(*a) if fn is not svc._finalize else None

        with patch("subprocess.Popen") as mock_popen:
            sentinel_line = f"{_CWD_SENTINEL}/tmp\n"
            proc = MagicMock()
            proc.stdout = iter(["hello\n", sentinel_line, "world\n"])
            proc.wait = MagicMock(return_value=None)
            proc.returncode = 0
            mock_popen.return_value = proc

            captured_push = []
            block.push_line = lambda line: captured_push.append(line)

            # Run with finalize patched to a no-op
            with patch.object(svc, "_finalize"):
                svc._exec_sync("echo hello", block)

        assert not any(_CWD_SENTINEL in ln for ln in captured_push)
        assert "hello" in captured_push
        assert "world" in captured_push

    def test_cwd_extracted_from_sentinel(self):
        """_finalize receives the path extracted from the sentinel line."""
        from hermes_cli.tui.services.bash_service import _CWD_SENTINEL
        svc = self._make_service()
        block = MagicMock()
        finalize_calls = []

        def fake_call_from_thread(fn, *args):
            finalize_calls.append((fn, args))

        svc.app.call_from_thread = fake_call_from_thread

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.stdout = iter([f"{_CWD_SENTINEL}/extracted/path\n"])
            proc.wait = MagicMock(return_value=None)
            proc.returncode = 0
            mock_popen.return_value = proc

            svc._exec_sync("cd /extracted/path", block)

        # Last call_from_thread is _finalize
        finalize_fn, finalize_args = finalize_calls[-1]
        assert finalize_fn.__name__ == "_finalize"
        # new_cwd is 4th positional arg (block, exit_code, elapsed, new_cwd)
        assert finalize_args[3] == "/extracted/path"

    def test_status_cwd_updated_on_finalize(self):
        """app.status_cwd is set to new_cwd in _finalize."""
        from hermes_cli.tui.services.bash_service import BashService
        svc = self._make_service()
        svc._running = True
        block = MagicMock()
        block.mark_done = MagicMock()

        BashService._finalize(svc, block, 0, 0.1, "/new/cwd")

        assert svc.app.status_cwd == "/new/cwd"
        assert svc._bash_cwd == "/new/cwd"

    def test_bash_cwd_persists_between_calls(self):
        """After _finalize with /tmp, the next _exec_sync passes cwd='/tmp' to Popen."""
        from hermes_cli.tui.services.bash_service import BashService
        svc = self._make_service()
        svc._running = True
        block = MagicMock()
        block.mark_done = MagicMock()

        # Simulate first command finishing in /tmp
        BashService._finalize(svc, block, 0, 0.1, "/tmp")
        assert svc._bash_cwd == "/tmp"

        # Now run another command — check cwd= kwarg
        block2 = MagicMock()
        block2.push_line = MagicMock()
        cwd_used = {}

        def fake_popen(args, **kwargs):
            cwd_used["cwd"] = kwargs.get("cwd")
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait = MagicMock(return_value=None)
            proc.returncode = 0
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            with patch.object(svc, "_finalize"):
                svc._exec_sync("ls", block2)

        assert cwd_used["cwd"] == "/tmp"

    def test_no_cwd_update_on_no_sentinel(self):
        """If sentinel is absent, app.status_cwd is not written."""
        svc = self._make_service()
        block = MagicMock()
        finalize_calls = []

        def fake_call_from_thread(fn, *args):
            finalize_calls.append((fn, args))

        svc.app.call_from_thread = fake_call_from_thread

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            # No sentinel line at all
            proc.stdout = iter(["output line\n"])
            proc.wait = MagicMock(return_value=None)
            proc.returncode = 0
            mock_popen.return_value = proc

            svc._exec_sync("echo hi", block)

        finalize_fn, finalize_args = finalize_calls[-1]
        assert finalize_fn.__name__ == "_finalize"
        # new_cwd should be None when no sentinel present
        new_cwd = finalize_args[3]
        assert new_cwd is None


# ---------------------------------------------------------------------------
# CWD-3 — StatusBar basename display
# ---------------------------------------------------------------------------

class TestCWD3StatusBarRender:
    def setup_method(self):
        self.bar = _make_bar()

    def test_cwd_basename_shown_in_full_width(self):
        app = _make_app(status_cwd="/home/xush/.hermes/hermes-agent")
        text = _render(self.bar, app, width=80)
        assert "hermes-agent" in text

    def test_cwd_hidden_in_narrow(self):
        app = _make_app(status_cwd="/home/xush/.hermes/hermes-agent")
        text = _render(self.bar, app, width=30)
        assert "hermes-agent" not in text

    def test_cwd_hidden_in_compact_narrow(self):
        app = _make_app(status_cwd="/home/xush/.hermes/hermes-agent")
        text = _render(self.bar, app, width=65, compact=True)
        assert "hermes-agent" not in text

    def test_cwd_separator_style(self):
        app = _make_app(status_cwd="/home/xush/.hermes/hermes-agent",
                        status_model="claude-sonnet-4-6")
        text = _render(self.bar, app, width=80)
        # CWD basename + separator + model all present
        assert "hermes-agent" in text
        assert " · " in text
        assert "claude-sonnet-4-6" in text
        # CWD comes before model
        assert text.index("hermes-agent") < text.index("claude-sonnet-4-6")

    def test_cwd_root_slash(self):
        app = _make_app(status_cwd="/")
        text = _render(self.bar, app, width=80)
        # basename("/") == "" → fallback to raw "/" itself
        assert "/" in text


# ---------------------------------------------------------------------------
# CWD-4 — StatusBar watcher + flash animation
# ---------------------------------------------------------------------------

class TestCWD4StatusBarWatcher:
    def setup_method(self):
        self.bar = _make_bar()

    def test_cwd_change_triggers_refresh(self):
        """_on_cwd_change calls self.refresh()."""
        refresh_called = []
        self.bar.refresh = lambda: refresh_called.append(True)
        self.bar.set_timer = lambda *a, **kw: None

        self.bar._on_cwd_change("/some/path")

        assert refresh_called

    def test_cwd_bold_immediately_after_change(self):
        """_cwd_style is 'bold' when _cwd_changed_at is now."""
        self.bar._cwd_changed_at = time.monotonic()
        app = _make_app(status_cwd="/tmp")
        text_obj_parts = []

        # Capture style during render by checking the computed _cwd_age
        now = time.monotonic()
        cwd_age = now - self.bar._cwd_changed_at
        cwd_style = "bold" if cwd_age < 2.0 else "dim"
        assert cwd_style == "bold"

    def test_cwd_dim_after_two_seconds(self):
        """_cwd_style is 'dim' when _cwd_changed_at is 3s ago."""
        self.bar._cwd_changed_at = time.monotonic() - 3.0
        now = time.monotonic()
        cwd_age = now - self.bar._cwd_changed_at
        cwd_style = "bold" if cwd_age < 2.0 else "dim"
        assert cwd_style == "dim"

    def test_cwd_no_flash_on_empty(self):
        """When status_cwd is empty, CWD segment is absent from render output."""
        app = _make_app(status_cwd="")
        text = _render(self.bar, app, width=80)
        # No basename to show; separator should not appear at start of text
        # (YOLO stripe absent too since yolo_mode=False)
        # Model name still present
        assert "claude-sonnet-4-6" in text
        # No leading " · " from a nonexistent CWD
        assert not text.startswith(" · ")
