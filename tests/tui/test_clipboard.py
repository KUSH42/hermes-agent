"""Tests for clipboard / copy-paste integration (CB-H1, CB-H2, CB-M1, CB-M2)."""
from __future__ import annotations

import base64
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# TestOsc52Write — CB-H1
# ---------------------------------------------------------------------------

class TestOsc52Write:
    def setup_method(self):
        # Remove cached module so env-var changes take effect
        sys.modules.pop("hermes_cli.tui.osc52", None)

    def _import(self):
        import hermes_cli.tui.osc52 as m
        return m

    def test_write_encodes_base64(self):
        mod = self._import()
        captured = []
        with patch("os.write", side_effect=lambda fd, data: captured.append(data)):
            result = mod.write("hello")
        assert result is True
        raw_b64 = base64.b64encode(b"hello").decode("ascii")
        expected = f"\033]52;c;{raw_b64}\a".encode("ascii")
        assert captured[0] == expected

    def test_write_tmux_wraps(self):
        mod = self._import()
        captured = []
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux.sock"}):
            with patch("os.write", side_effect=lambda fd, data: captured.append(data)):
                mod.write("hi")
        seq = captured[0].decode("ascii")
        assert seq.startswith("\033Ptmux;\033")
        assert seq.endswith("\033\\")
        assert "\033]52;c;" in seq

    def test_write_truncates_large_payload(self):
        mod = self._import()
        big = "x" * 60_000
        captured = []
        with patch("os.write", side_effect=lambda fd, data: captured.append(data)):
            import logging
            with patch.object(logging.getLogger("hermes_cli.tui.osc52"), "warning") as mock_warn:
                result = mod.write(big)
        assert result is True
        mock_warn.assert_called_once()
        # The base64 should encode exactly _MAX_RAW_BYTES
        seq = captured[0].decode("ascii")
        # Extract b64 payload
        b64_part = seq.split(";")[2].rstrip("\a")
        decoded = base64.b64decode(b64_part)
        assert len(decoded) == mod._MAX_RAW_BYTES

    def test_write_exact_limit_not_truncated(self):
        mod = self._import()
        exact = "a" * mod._MAX_RAW_BYTES
        captured = []
        with patch("os.write", side_effect=lambda fd, data: captured.append(data)):
            import logging
            with patch.object(logging.getLogger("hermes_cli.tui.osc52"), "warning") as mock_warn:
                result = mod.write(exact)
        assert result is True
        mock_warn.assert_not_called()

    def test_write_returns_false_on_fd_error(self):
        mod = self._import()
        with patch("os.write", side_effect=OSError("bad fd")):
            import logging
            with patch.object(logging.getLogger("hermes_cli.tui.osc52"), "debug") as mock_debug:
                result = mod.write("hello")
        assert result is False
        mock_debug.assert_called_once()

    def test_write_no_tmux_no_wrap(self):
        mod = self._import()
        captured = []
        env = {k: v for k, v in __import__("os").environ.items() if k != "TMUX"}
        with patch.dict("os.environ", env, clear=True):
            with patch("os.write", side_effect=lambda fd, data: captured.append(data)):
                mod.write("hello")
        seq = captured[0].decode("ascii")
        assert not seq.startswith("\033P")
        assert seq.startswith("\033]52;c;")


# ---------------------------------------------------------------------------
# TestCopyDispatchUnified — CB-H2
# ---------------------------------------------------------------------------

class _FakePanel:
    """Minimal stand-in for _ToolPanelActionsMixin."""

    def __init__(self, content="", arg_summary=""):
        self._content = content
        self._arg_summary = arg_summary
        self._flash_calls: list[tuple] = []
        self.app = MagicMock()

    def copy_content(self) -> str:
        return self._content

    def _format_arg_summary(self) -> str:
        return self._arg_summary

    def _flash_header(self, msg: str, *, tone: str = "info") -> None:
        self._flash_calls.append((msg, tone))

    # Bind the actual mixin methods
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    action_copy_output = _ToolPanelActionsMixin.action_copy_output
    action_copy_input = _ToolPanelActionsMixin.action_copy_input


class TestCopyDispatchUnified:
    def test_copy_output_calls_copy_text_with_hint(self):
        panel = _FakePanel(content="some output")
        panel.action_copy_output()
        panel.app._copy_text_with_hint.assert_called_once_with("some output")

    def test_copy_output_empty_flashes_warning(self):
        panel = _FakePanel(content="")
        panel.action_copy_output()
        panel.app._copy_text_with_hint.assert_not_called()
        assert any("nothing to copy" in msg for msg, tone in panel._flash_calls)
        assert any(tone == "warning" for msg, tone in panel._flash_calls)

    def test_copy_input_calls_copy_text_with_hint(self):
        panel = _FakePanel(arg_summary="tool_name(foo=bar)")
        panel.action_copy_input()
        panel.app._copy_text_with_hint.assert_called_once_with("tool_name(foo=bar)")

    def test_copy_input_empty_flashes_warning(self):
        panel = _FakePanel(arg_summary="")
        panel.action_copy_input()
        panel.app._copy_text_with_hint.assert_not_called()
        assert any("nothing to copy" in msg for msg, tone in panel._flash_calls)
        assert any(tone == "warning" for msg, tone in panel._flash_calls)

    def _make_bar(self, session_id: str):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        _mock_app = MagicMock()

        class _BarStub(StatusBar):
            @property
            def app(self):
                return _mock_app

        bar = object.__new__(_BarStub)
        bar._full_session_id = session_id
        bar._mock_app = _mock_app
        return bar

    def test_copy_session_id_calls_copy_text_with_hint(self):
        bar = self._make_bar("session-abc-123")
        bar.action_copy_session_id()
        bar._mock_app._copy_text_with_hint.assert_called_once_with("session-abc-123")

    def test_copy_session_id_empty_is_noop(self):
        bar = self._make_bar("")
        bar.action_copy_session_id()
        bar._mock_app._copy_text_with_hint.assert_not_called()


# ---------------------------------------------------------------------------
# TestCopyChainOsc52 — CB-M1
# ---------------------------------------------------------------------------

def _make_theme_svc(clipboard_available=False, xclip_cmd=None):
    """Build a minimal ThemeService-like stub exercising copy_text_with_hint."""
    from hermes_cli.tui.services.theme import ThemeService

    svc = object.__new__(ThemeService)
    app = MagicMock()
    app._clipboard_available = clipboard_available
    app._xclip_cmd = xclip_cmd
    svc.app = app

    # Wire flash_hint to a spy
    svc._flash_calls: list[str] = []

    def _flash_hint(text, duration=1.5):
        svc._flash_calls.append(text)

    svc.flash_hint = _flash_hint
    svc.set_status_error = MagicMock()
    return svc


class TestCopyChainOsc52:
    def test_copy_always_attempts_osc52(self):
        svc = _make_theme_svc()
        with patch("hermes_cli.tui.services.theme._osc52") as mock_osc:
            svc.copy_text_with_hint("hello")
        mock_osc.write.assert_called_once_with("hello")

    def test_copy_hint_flashed_without_xclip(self):
        svc = _make_theme_svc(clipboard_available=False, xclip_cmd=None)
        with patch("hermes_cli.tui.services.theme._osc52"):
            svc.copy_text_with_hint("hello")
        assert any("chars copied" in h for h in svc._flash_calls)

    def test_copy_shows_error_without_xclip(self):
        svc = _make_theme_svc(clipboard_available=False, xclip_cmd=None)
        with patch("hermes_cli.tui.services.theme._osc52"):
            svc.copy_text_with_hint("hello")
        svc.set_status_error.assert_called_once_with(
            "no clipboard — install xclip or xsel",
            auto_clear_s=0,
        )

    def test_copy_also_runs_xclip_if_present(self):
        svc = _make_theme_svc(clipboard_available=False, xclip_cmd=["xclip", "-sel", "c"])
        with patch("hermes_cli.tui.services.theme._osc52") as mock_osc:
            with patch("hermes_cli.tui.services.theme.safe_run") as mock_safe_run:
                svc.copy_text_with_hint("hello")
        mock_osc.write.assert_called_once_with("hello")
        mock_safe_run.assert_called_once()
        call_kwargs = mock_safe_run.call_args
        assert call_kwargs[0][1] == ["xclip", "-sel", "c"]

    def test_copy_also_runs_copy_to_clipboard_if_available(self):
        svc = _make_theme_svc(clipboard_available=True)
        with patch("hermes_cli.tui.services.theme._osc52") as mock_osc:
            svc.copy_text_with_hint("hello")
        mock_osc.write.assert_called_once_with("hello")
        svc.app.copy_to_clipboard.assert_called_once_with("hello")

    def test_clipboard_warning_widget_not_activated(self):
        # app.py should no longer add --active to #status-clipboard-warning
        import inspect
        import hermes_cli.tui.app as app_mod
        src = inspect.getsource(app_mod.HermesApp.on_mount)
        assert "status-clipboard-warning" not in src or "--active" not in src.split("status-clipboard-warning")[1][:200]


# ---------------------------------------------------------------------------
# TestPrimarySelectionCmd — CB-M2
# ---------------------------------------------------------------------------

class TestPrimarySelectionCmd:
    def _get_cmd(self):
        from hermes_cli.tui.input.widget import _primary_selection_cmd
        return _primary_selection_cmd

    def test_primary_cmd_wayland_prefers_wl_paste(self):
        fn = self._get_cmd()
        def which(name):
            return "/usr/bin/wl-paste" if name == "wl-paste" else None
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ":0"}):
            with patch("shutil.which", side_effect=which):
                result = fn()
        assert result == ["wl-paste", "--primary"]

    def test_primary_cmd_wayland_falls_back_to_xclip(self):
        fn = self._get_cmd()
        def which(name):
            return "/usr/bin/xclip" if name == "xclip" else None
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ":0"}):
            with patch("shutil.which", side_effect=which):
                result = fn()
        assert result == ["xclip", "-selection", "primary", "-o"]

    def test_primary_cmd_x11_xsel_fallback(self):
        fn = self._get_cmd()
        def which(name):
            return "/usr/bin/xsel" if name == "xsel" else None
        env = {k: v for k, v in __import__("os").environ.items() if k != "WAYLAND_DISPLAY"}
        with patch.dict("os.environ", env, clear=True):
            with patch("shutil.which", side_effect=which):
                result = fn()
        assert result == ["xsel", "--primary", "--output"]

    def test_primary_cmd_none_when_no_tool(self):
        fn = self._get_cmd()
        env = {k: v for k, v in __import__("os").environ.items() if k != "WAYLAND_DISPLAY"}
        with patch.dict("os.environ", env, clear=True):
            with patch("shutil.which", return_value=None):
                result = fn()
        assert result is None
