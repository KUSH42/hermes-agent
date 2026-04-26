"""Tests for Crush easy-wins features:
  A — context_pct meter in StatusBar
  B — OSC 9;4 progress bar (osc_progress.py)
  C — desktop notification + sound (desktop_notify.py)
  D — yolo mode indicator + runtime toggle
"""
from __future__ import annotations

import json
import os
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.widgets import StatusBar


# ===========================================================================
# Helpers
# ===========================================================================

def _make_app():
    """Create a minimal HermesApp for testing."""
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.agent = None
    cli._cfg = {"display": {"osc_progress": True, "context_pct": True,
                             "context_pct_mode": "overflow",
                             "desktop_notify": False, "notify_min_seconds": 10.0,
                             "notify_sound": False, "notify_sound_name": "Glass"}}
    return HermesApp(cli=cli)


# ===========================================================================
# Feature B — osc_progress module
# ===========================================================================

class TestOscProgress:
    def _env(self, **kwargs):
        base = {"TERM_PROGRAM": "", "WT_SESSION": "", "HERMES_OSC_PROGRESS": ""}
        base.update(kwargs)
        return {k: v for k, v in base.items() if v}  # omit empty strings

    def _is_supported(self, **env_kwargs):
        from hermes_cli.tui import osc_progress as op
        env = self._env(**env_kwargs)
        with patch.dict(os.environ, env, clear=False):
            # Clear the keys we set to empty
            for k in ["TERM_PROGRAM", "WT_SESSION", "HERMES_OSC_PROGRESS"]:
                if k not in env:
                    os.environ.pop(k, None)
            return op.is_supported()

    def test_ghostty_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "ghostty"}, clear=False):
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert op.is_supported()

    def test_iterm_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "iterm.app"}, clear=False):
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert op.is_supported()

    def test_rio_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "rio"}, clear=False):
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert op.is_supported()

    def test_wezterm_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "wezterm"}, clear=False):
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert op.is_supported()

    def test_windows_terminal_wt_session(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"WT_SESSION": "some-guid"}, clear=False):
            os.environ.pop("TERM_PROGRAM", None)
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert op.is_supported()

    def test_xterm_not_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "xterm"}, clear=False):
            os.environ.pop("WT_SESSION", None)
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert not op.is_supported()

    def test_unknown_term_not_supported(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"TERM_PROGRAM": "kitty"}, clear=False):
            os.environ.pop("WT_SESSION", None)
            os.environ.pop("HERMES_OSC_PROGRESS", None)
            assert not op.is_supported()

    def test_override_force_on(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "1", "TERM_PROGRAM": "xterm"}, clear=False):
            assert op.is_supported()

    def test_override_force_off(self):
        from hermes_cli.tui import osc_progress as op
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "0", "TERM_PROGRAM": "ghostty"}, clear=False):
            assert not op.is_supported()

    def test_start_writes_correct_bytes(self):
        from hermes_cli.tui import osc_progress as op
        written = []
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "1"}, clear=False):
            with patch("os.write", side_effect=lambda fd, data: written.append(data)):
                op.osc_progress_start()
        assert written == [b"\x1b]9;4;3;\x07"]

    def test_end_writes_correct_bytes(self):
        from hermes_cli.tui import osc_progress as op
        written = []
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "1"}, clear=False):
            with patch("os.write", side_effect=lambda fd, data: written.append(data)):
                op.osc_progress_end()
        assert written == [b"\x1b]9;4;0;\x07"]

    def test_start_noop_when_not_supported(self):
        from hermes_cli.tui import osc_progress as op
        written = []
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "0"}, clear=False):
            with patch("os.write", side_effect=lambda fd, data: written.append(data)):
                op.osc_progress_start()
        assert written == []

    def test_end_noop_when_not_supported(self):
        from hermes_cli.tui import osc_progress as op
        written = []
        with patch.dict(os.environ, {"HERMES_OSC_PROGRESS": "0"}, clear=False):
            with patch("os.write", side_effect=lambda fd, data: written.append(data)):
                op.osc_progress_end()
        assert written == []


# ===========================================================================
# Feature C — desktop_notify module
# ===========================================================================

class TestDesktopNotify:
    def _run_sync(self, *args, **kwargs):
        """Call notify() and replay dispatched commands synchronously."""
        from hermes_cli.tui import desktop_notify as dn
        import subprocess as _sp
        mock_caller = MagicMock()

        def _fake_safe_run(caller, cmd, *, timeout=5, on_error=None, **kw):
            _sp.run(cmd, timeout=timeout)

        with patch("hermes_cli.tui.desktop_notify.safe_run", side_effect=_fake_safe_run):
            dn.notify(*args, caller=mock_caller, **kwargs)

    def test_notify_send_called_with_correct_args(self):
        from hermes_cli.tui import desktop_notify as dn
        calls = []
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
                with patch.object(sys, "platform", "linux"):
                    self._run_sync("Hermes", "Task done")
        assert any(c == ["notify-send", "Hermes", "Task done"] for c in calls)

    def test_osascript_called_when_no_notify_send(self):
        from hermes_cli.tui import desktop_notify as dn
        calls = []

        def which(cmd):
            return "/usr/bin/osascript" if cmd == "osascript" else None

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
                with patch.object(sys, "platform", "darwin"):
                    self._run_sync("Hermes", "Hello")
        assert any(c[0] == "osascript" for c in calls)

    def test_osascript_uses_json_dumps_escaping(self):
        from hermes_cli.tui import desktop_notify as dn
        scripts = []

        def which(cmd):
            return "/usr/bin/osascript" if cmd == "osascript" else None

        def capture_run(cmd, **kw):
            if cmd[0] == "osascript":
                scripts.append(cmd[2])  # -e <script>

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=capture_run):
                with patch.object(sys, "platform", "darwin"):
                    self._run_sync("Hermes", 'body with "quotes"')
        assert scripts
        script = scripts[0]
        # json.dumps produces double-quoted strings — must not have raw unescaped quotes
        assert json.dumps('body with "quotes"') in script

    def test_noop_when_no_tool_found(self):
        from hermes_cli.tui import desktop_notify as dn
        calls = []
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
                self._run_sync("Hermes", "Test")
        assert calls == []

    def test_dispatches_via_safe_run(self):
        from hermes_cli.tui import desktop_notify as dn
        mock_caller = MagicMock()
        with patch("hermes_cli.tui.desktop_notify.safe_run") as mock_safe_run:
            with patch("shutil.which", return_value="/usr/bin/notify-send"):
                with patch.object(sys, "platform", "linux"):
                    dn.notify("Hermes", "Test", caller=mock_caller)
        mock_safe_run.assert_called_once()
        assert mock_safe_run.call_args[0][0] is mock_caller

    def test_notify_sound_adds_sound_name_macos(self):
        from hermes_cli.tui import desktop_notify as dn
        scripts = []

        def which(cmd):
            return "/usr/bin/osascript" if cmd == "osascript" else None

        def capture_run(cmd, **kw):
            if cmd[0] == "osascript":
                scripts.append(cmd[2])

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=capture_run):
                with patch.object(sys, "platform", "darwin"):
                    self._run_sync("Hermes", "Done", sound=True, sound_name="Ping")
        assert scripts
        assert "Ping" in scripts[0]
        assert "sound name" in scripts[0]

    def test_notify_no_sound_skips_sound_name(self):
        from hermes_cli.tui import desktop_notify as dn
        scripts = []

        def which(cmd):
            return "/usr/bin/osascript" if cmd == "osascript" else None

        def capture_run(cmd, **kw):
            if cmd[0] == "osascript":
                scripts.append(cmd[2])

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=capture_run):
                with patch.object(sys, "platform", "darwin"):
                    self._run_sync("Hermes", "Done", sound=False)
        assert scripts
        assert "sound name" not in scripts[0]

    def test_notify_sound_linux_calls_canberra(self):
        from hermes_cli.tui import desktop_notify as dn
        calls = []

        def which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("notify-send", "canberra-gtk-play") else None

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
                with patch.object(sys, "platform", "linux"):
                    self._run_sync("Hermes", "Done", sound=True)
        assert any("canberra-gtk-play" in c[0] for c in calls)

    def test_notify_sound_false_no_sound_on_linux(self):
        from hermes_cli.tui import desktop_notify as dn
        calls = []

        def which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("notify-send", "canberra-gtk-play") else None

        with patch("shutil.which", side_effect=which):
            with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
                with patch.object(sys, "platform", "linux"):
                    self._run_sync("Hermes", "Done", sound=False)
        assert all("canberra" not in str(c) for c in calls)


# ===========================================================================
# Feature A — model_context_window helper
# ===========================================================================

class TestModelContextWindow:
    def test_claude_sonnet_4(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("claude-sonnet-4-6") == 200_000

    def test_claude_haiku_4(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("claude-haiku-4-5-20251001") == 200_000

    def test_claude_opus_4(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("claude-opus-4-7") == 200_000

    def test_unknown_claude_fallback(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("claude-unknown-future-model") == 200_000

    def test_non_claude_returns_zero(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("gpt-4o") == 0

    def test_empty_string_returns_zero(self):
        from hermes_cli.config import model_context_window
        assert model_context_window("") == 0

    def test_none_like_empty_string(self):
        from hermes_cli.config import model_context_window
        assert model_context_window(None) == 0  # type: ignore[arg-type]


# ===========================================================================
# Feature A — StatusBar context_pct segment (via full app)
# ===========================================================================

@pytest.mark.asyncio
async def test_statusbar_context_pct_overflow_mode():
    """overflow mode: context_pct reactive shown as XX%."""
    app = _make_app()
    app.cli._cfg["display"]["context_pct_mode"] = "overflow"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.context_pct = 42.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        assert "42%" in rendered.plain


@pytest.mark.asyncio
async def test_statusbar_context_pct_compaction_mode():
    """compaction mode: status_compaction_progress * 100 shown as XX%."""
    app = _make_app()
    app.cli._cfg["display"]["context_pct_mode"] = "compaction"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.status_compaction_progress = 0.55
        await pilot.pause()
        bar = app.query_one(StatusBar)
        assert "55%" in bar.render().plain


@pytest.mark.asyncio
async def test_statusbar_context_pct_zero_hidden():
    """context_pct = 0 and compaction_progress = 0 → no % meter shown."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.context_pct = 0.0
        app.status_compaction_progress = 0.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        import re
        assert not re.search(r"▕ \d+%", rendered.plain)


@pytest.mark.asyncio
async def test_statusbar_context_pct_config_disabled():
    """display.context_pct=false suppresses % segment even when pct > 0."""
    app = _make_app()
    app.cli._cfg["display"]["context_pct"] = False
    app.cli._cfg["display"]["context_pct_mode"] = "overflow"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.context_pct = 50.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        import re
        assert not re.search(r"▕ \d+%", rendered.plain)


@pytest.mark.asyncio
async def test_statusbar_context_pct_100_overflow():
    app = _make_app()
    app.cli._cfg["display"]["context_pct_mode"] = "overflow"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.context_pct = 100.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        assert "100%" in bar.render().plain


@pytest.mark.asyncio
async def test_statusbar_context_pct_100_compaction():
    app = _make_app()
    app.cli._cfg["display"]["context_pct_mode"] = "compaction"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.status_compaction_progress = 1.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        assert "100%" in bar.render().plain


# ===========================================================================
# Feature D — yolo_mode reactive + StatusBar + chevron
# ===========================================================================

class TestYoloIndicator:
    @pytest.mark.asyncio
    async def test_yolo_true_adds_chevron_class(self):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.yolo_mode = True
            await pilot.pause()
            chevron = app.query_one("#input-chevron")
            assert "--yolo-active" in chevron.classes

    @pytest.mark.asyncio
    async def test_yolo_false_removes_chevron_class(self):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.yolo_mode = True
            await pilot.pause()
            app.yolo_mode = False
            await pilot.pause()
            chevron = app.query_one("#input-chevron")
            assert "--yolo-active" not in chevron.classes

    def _make_bar(self, yolo: bool):
        _mock_app = MagicMock()
        _mock_app.get_css_variables.return_value = {"warning-color": "#FFA500", "primary": "#5f87d7"}
        _mock_app.status_model = "test"
        _mock_app.status_context_tokens = 0
        _mock_app.status_context_max = 0
        _mock_app.status_compaction_progress = 0.0
        _mock_app.status_compaction_enabled = True
        _mock_app.agent_running = False
        _mock_app.command_running = False
        _mock_app.browse_mode = False
        _mock_app.browse_index = 0
        _mock_app._browse_total = 0
        _mock_app._browse_hint = ""
        _mock_app._completion_hint = ""
        _mock_app.status_output_dropped = False
        _mock_app.status_active_file = ""
        _mock_app.status_error = ""
        _mock_app._animations_enabled = False
        _mock_app.context_pct = 0.0
        _mock_app.yolo_mode = yolo
        _mock_app._cfg = {"display": {"context_pct": False}}
        _mock_app.cli = None

        _size = MagicMock()
        _size.width = 80

        # Use a throwaway subclass so class-level property mutations don't affect
        # the real StatusBar used by subsequent pilot tests.
        class _BarStub(StatusBar):
            app = property(lambda self: _mock_app)  # type: ignore[assignment]
            size = property(lambda self: _size)     # type: ignore[assignment]

        bar = _BarStub.__new__(_BarStub)
        object.__setattr__(bar, "_pulse_t", 0.0)
        object.__setattr__(bar, "_pulse_timer", None)
        object.__setattr__(bar, "_pulse_tick", 0)
        bar._hint_idx = 0
        bar._hint_phase = "idle"
        bar._idle_tips_cache = None
        return bar

    def test_statusbar_shows_yolo_badge(self):
        t = self._make_bar(yolo=True).render()
        assert "YOLO" in t.plain
        assert "⚡" in t.plain

    def test_statusbar_no_yolo_badge_when_false(self):
        t = self._make_bar(yolo=False).render()
        assert "YOLO" not in t.plain

    @pytest.mark.asyncio
    async def test_hermes_yolo_env_sets_reactive_at_startup(self):
        with patch.dict(os.environ, {"HERMES_YOLO_MODE": "1"}):
            app = _make_app()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert app.yolo_mode is True

    @pytest.mark.asyncio
    async def test_hermes_yolo_env_unset_leaves_false(self):
        env = {k: v for k, v in os.environ.items() if k != "HERMES_YOLO_MODE"}
        with patch.dict(os.environ, env, clear=True):
            app = _make_app()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert app.yolo_mode is False

    def test_yolo_active_class_in_tcss(self):
        tcss_path = __import__("pathlib").Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
        content = tcss_path.read_text()
        assert "--yolo-active" in content

    def test_yolo_active_coexists_with_phase_classes(self):
        """--yolo-active must not be in _CHEVRON_PHASE_CLASSES (separate concern)."""
        from hermes_cli.tui.app import HermesApp
        assert "--yolo-active" not in HermesApp._CHEVRON_PHASE_CLASSES

    def test_toggle_yolo_syncs_tui_reactive(self):
        """_toggle_yolo must call call_from_thread to sync yolo_mode reactive on TUI."""
        from unittest.mock import MagicMock, patch
        import os

        class FakeCli:
            _tui = MagicMock()
            def __init__(self):
                self._tui.call_from_thread = MagicMock()

        cli = FakeCli()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_YOLO_MODE", None)
            # Toggle ON
            from hermes_cli.tui.app import HermesApp
            # Call _toggle_yolo directly via unbound method
            import types
            # Bind the method to the fake cli instance
            method = None
            # Find _toggle_yolo from cli.py's CognitiveCoder or similar class
            # Use direct function lookup
            import cli as cli_module
            for name, obj in vars(cli_module).items():
                if isinstance(obj, type) and hasattr(obj, "_toggle_yolo"):
                    method = obj._toggle_yolo
                    break
            if method is None:
                pytest.skip("_toggle_yolo not found on a class in cli.py")
            method(cli)
            cli._tui.call_from_thread.assert_called_once()
            args = cli._tui.call_from_thread.call_args[0]
            assert args[0] is setattr
            assert args[1] is cli._tui
            assert args[2] == "yolo_mode"
            assert args[3] is True


# ===========================================================================
# Feature C — prose callback wiring
# ===========================================================================

class TestProseCallback:
    def test_prose_callback_fires_on_write_prose(self):
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        panel = MagicMock()
        panel.app.get_css_variables.return_value = {}
        panel.app._math_enabled = False
        panel.app._mermaid_enabled = False
        panel.app._citations_enabled = False
        panel.app._emoji_registry = None
        panel.app._emoji_images_enabled = False
        panel.app._math_renderer = "auto"
        panel.app._math_dpi = 150
        panel.app._math_max_rows = 12
        panel.current_prose_log = MagicMock(return_value=MagicMock())
        panel.response_log = MagicMock()
        engine = ResponseFlowEngine(panel=panel)
        received = []
        engine._prose_callback = received.append
        engine._write_prose(MagicMock(), "hello world")
        assert "hello world" in received

    def test_prose_callback_not_fired_for_blank_lines(self):
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        panel = MagicMock()
        panel.app.get_css_variables.return_value = {}
        panel.app._math_enabled = False
        panel.app._mermaid_enabled = False
        panel.app._citations_enabled = False
        panel.app._emoji_registry = None
        panel.app._emoji_images_enabled = False
        panel.app._math_renderer = "auto"
        panel.app._math_dpi = 150
        panel.app._math_max_rows = 12
        panel.current_prose_log = MagicMock(return_value=MagicMock())
        panel.response_log = MagicMock()
        engine = ResponseFlowEngine(panel=panel)
        received = []
        engine._prose_callback = received.append
        engine._write_prose(MagicMock(), "   ")
        assert received == []

    def test_prose_callback_exception_does_not_crash(self):
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        panel = MagicMock()
        panel.app.get_css_variables.return_value = {}
        panel.app._math_enabled = False
        panel.app._mermaid_enabled = False
        panel.app._citations_enabled = False
        panel.app._emoji_registry = None
        panel.app._emoji_images_enabled = False
        panel.app._math_renderer = "auto"
        panel.app._math_dpi = 150
        panel.app._math_max_rows = 12
        panel.current_prose_log = MagicMock(return_value=MagicMock())
        panel.response_log = MagicMock()
        engine = ResponseFlowEngine(panel=panel)
        engine._prose_callback = lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        # Must not raise
        engine._write_prose(MagicMock(), "text")


# ===========================================================================
# Feature C — _maybe_notify logic (unit)
# ===========================================================================

class TestMaybeNotify:
    def _make_app_with_cfg(self, notify=True, elapsed=15.0, min_s=10.0,
                           sound=False, sound_name="Glass"):
        from hermes_cli.tui.app import HermesApp
        cli = MagicMock()
        cli._cfg = {"display": {
            "desktop_notify": notify,
            "notify_min_seconds": min_s,
            "notify_sound": sound,
            "notify_sound_name": sound_name,
            "osc_progress": False,
            "context_pct": False,
        }}
        app = HermesApp.__new__(HermesApp)
        app.cli = cli
        app._turn_start_time = time.monotonic() - elapsed
        app._last_assistant_text = "First line\nSecond line"
        return app

    def test_fires_when_elapsed_exceeds_threshold(self):
        app = self._make_app_with_cfg(notify=True, elapsed=15.0, min_s=10.0)
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert len(calls) == 1
        assert calls[0][0][0] == "Hermes"

    def test_suppressed_when_elapsed_below_threshold(self):
        app = self._make_app_with_cfg(notify=True, elapsed=5.0, min_s=10.0)
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert calls == []

    def test_suppressed_when_config_disabled(self):
        app = self._make_app_with_cfg(notify=False, elapsed=15.0)
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert calls == []

    def test_body_uses_first_assistant_line(self):
        app = self._make_app_with_cfg(notify=True, elapsed=15.0)
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert calls[0][0][1] == "First line"

    def test_body_fallback_when_no_assistant_text(self):
        app = self._make_app_with_cfg(notify=True, elapsed=15.0)
        app._last_assistant_text = ""
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert calls[0][0][1] == "Task complete"

    def test_sound_kwargs_forwarded(self):
        app = self._make_app_with_cfg(notify=True, elapsed=15.0, sound=True, sound_name="Ping")
        calls = []
        with patch("hermes_cli.tui.desktop_notify.notify", side_effect=lambda *a, **kw: calls.append((a, kw))):
            app._maybe_notify()
        assert calls[0][1]["sound"] is True
        assert calls[0][1]["sound_name"] == "Ping"
