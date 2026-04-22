"""
Phase 4: /layout slash command — unit tests for _handle_layout_command
and routing via _handle_tui_command.

These are pure unit tests — no Textual app required. All I/O is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers — build a mock _CommandsMixin host
# ---------------------------------------------------------------------------

def _make_host(
    display_layout: str = "v2",
    pm_enabled: bool = True,
    left_w_before: int | None = None,
    right_w_before: int | None = None,
) -> MagicMock:
    """Return a mock object that satisfies _CommandsMixin's attribute expectations."""
    host = MagicMock()
    host._display_layout = display_layout

    pm = MagicMock()
    pm.enabled = pm_enabled
    if left_w_before is not None:
        pm._left_w_override = left_w_before
    if right_w_before is not None:
        pm._right_w_override = right_w_before
    host._pane_manager = pm

    host._flash_hint = MagicMock()
    return host


def _call_handle_layout(host: MagicMock, args: str) -> None:
    """Invoke _handle_layout_command directly via the mixin (unbound)."""
    from hermes_cli.tui._app_commands import _CommandsMixin
    _CommandsMixin._handle_layout_command(host, args)


# ---------------------------------------------------------------------------
# /layout (no args)
# ---------------------------------------------------------------------------

class TestLayoutNoArgs:
    def test_no_args_flashes_current_version(self) -> None:
        host = _make_host(display_layout="v1")
        _call_handle_layout(host, "")
        host._flash_hint.assert_called_once()
        msg = host._flash_hint.call_args[0][0]
        assert "v1" in msg

    def test_no_args_v2_shows_v2(self) -> None:
        host = _make_host(display_layout="v2")
        _call_handle_layout(host, "")
        msg = host._flash_hint.call_args[0][0]
        assert "v2" in msg


# ---------------------------------------------------------------------------
# /layout v1 / v2
# ---------------------------------------------------------------------------

class TestLayoutVersionSwitch:
    def test_layout_v1_persists_to_config(self) -> None:
        host = _make_host()
        with patch("hermes_cli.tui._app_commands.re") as mock_re, \
             patch("hermes_cli.config.read_raw_config") as mock_read, \
             patch("hermes_cli.config.save_config") as mock_save:
            mock_re.findall.return_value = []  # no kv pairs
            mock_read.return_value = {"display": {}}
            _call_handle_layout(host, "v1")
            mock_save.assert_called_once()
            saved_cfg = mock_save.call_args[0][0]
            assert saved_cfg["display"]["layout"] == "v1"

    def test_layout_v2_persists_to_config(self) -> None:
        host = _make_host()
        with patch("hermes_cli.tui._app_commands.re") as mock_re, \
             patch("hermes_cli.config.read_raw_config") as mock_read, \
             patch("hermes_cli.config.save_config") as mock_save:
            mock_re.findall.return_value = []
            mock_read.return_value = {}
            _call_handle_layout(host, "v2")
            mock_save.assert_called_once()
            saved_cfg = mock_save.call_args[0][0]
            assert saved_cfg["display"]["layout"] == "v2"

    def test_layout_v2_flashes_restart_hint(self) -> None:
        host = _make_host()
        with patch("hermes_cli.tui._app_commands.re") as mock_re, \
             patch("hermes_cli.config.read_raw_config", return_value={}), \
             patch("hermes_cli.config.save_config"):
            mock_re.findall.return_value = []
            _call_handle_layout(host, "v2")
        host._flash_hint.assert_called_once()
        msg = host._flash_hint.call_args[0][0]
        assert "restart" in msg.lower() or "Restart" in msg

    def test_layout_v1_flashes_restart_hint(self) -> None:
        host = _make_host()
        with patch("hermes_cli.tui._app_commands.re") as mock_re, \
             patch("hermes_cli.config.read_raw_config", return_value={}), \
             patch("hermes_cli.config.save_config"):
            mock_re.findall.return_value = []
            _call_handle_layout(host, "v1")
        msg = host._flash_hint.call_args[0][0]
        assert "restart" in msg.lower() or "Restart" in msg


# ---------------------------------------------------------------------------
# /layout left=N
# ---------------------------------------------------------------------------

class TestLayoutLeftWidth:
    def test_layout_left_calls_set_left_w(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "left=30")
        host._pane_manager.set_left_w.assert_called_once_with(30)

    def test_layout_left_applies_layout_when_enabled(self) -> None:
        host = _make_host(pm_enabled=True)
        _call_handle_layout(host, "left=30")
        host._pane_manager._apply_layout.assert_called_once_with(host)

    def test_layout_left_no_apply_when_disabled(self) -> None:
        host = _make_host(pm_enabled=False)
        _call_handle_layout(host, "left=30")
        host._pane_manager._apply_layout.assert_not_called()

    def test_layout_left_flashes_width_hint(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "left=28")
        host._flash_hint.assert_called_once()
        msg = host._flash_hint.call_args[0][0]
        assert "28" in msg

    def test_layout_left_clamps_minimum(self) -> None:
        """Values below MIN_SIDE_W (16) should be clamped."""
        host = _make_host()
        _call_handle_layout(host, "left=5")
        host._pane_manager.set_left_w.assert_called_once_with(16)


# ---------------------------------------------------------------------------
# /layout right=N
# ---------------------------------------------------------------------------

class TestLayoutRightWidth:
    def test_layout_right_calls_set_right_w(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "right=25")
        host._pane_manager.set_right_w.assert_called_once_with(25)

    def test_layout_right_applies_layout_when_enabled(self) -> None:
        host = _make_host(pm_enabled=True)
        _call_handle_layout(host, "right=25")
        host._pane_manager._apply_layout.assert_called_once_with(host)

    def test_layout_right_flashes_width_hint(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "right=25")
        msg = host._flash_hint.call_args[0][0]
        assert "25" in msg


# ---------------------------------------------------------------------------
# /layout left=N right=M (both)
# ---------------------------------------------------------------------------

class TestLayoutBothWidths:
    def test_layout_both_sets_left(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "left=30 right=28")
        host._pane_manager.set_left_w.assert_called_once_with(30)

    def test_layout_both_sets_right(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "left=30 right=28")
        host._pane_manager.set_right_w.assert_called_once_with(28)


# ---------------------------------------------------------------------------
# Unknown args → usage hint
# ---------------------------------------------------------------------------

class TestLayoutUnknown:
    def test_unknown_args_flash_usage(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "zzz")
        host._flash_hint.assert_called_once()
        msg = host._flash_hint.call_args[0][0]
        assert "Usage" in msg or "usage" in msg

    def test_unknown_numeric_no_key_flash_usage(self) -> None:
        host = _make_host()
        _call_handle_layout(host, "42")
        host._flash_hint.assert_called_once()
        msg = host._flash_hint.call_args[0][0]
        assert "Usage" in msg or "usage" in msg


# ---------------------------------------------------------------------------
# Routing: _handle_tui_command dispatches /layout
# ---------------------------------------------------------------------------

class TestLayoutRouting:
    def test_handle_tui_command_routes_layout(self) -> None:
        host = _make_host()
        # Patch _handle_layout_command on the instance to track calls
        host._handle_layout_command = MagicMock()
        from hermes_cli.tui._app_commands import _CommandsMixin
        result = _CommandsMixin._handle_tui_command(host, "/layout v2")
        assert result is True
        host._handle_layout_command.assert_called_once_with("v2")

    def test_handle_tui_command_routes_layout_no_args(self) -> None:
        host = _make_host()
        host._handle_layout_command = MagicMock()
        from hermes_cli.tui._app_commands import _CommandsMixin
        result = _CommandsMixin._handle_tui_command(host, "/layout")
        assert result is True
        host._handle_layout_command.assert_called_once_with("")

    def test_layout_in_known_slash_commands(self) -> None:
        from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS
        assert "/layout" in KNOWN_SLASH_COMMANDS
