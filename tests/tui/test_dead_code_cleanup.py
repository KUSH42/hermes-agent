"""Tests for TUI Dead Code Cleanup spec (D1–D7)."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


class TestDeletedModules:
    def test_turn_phase_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui.turn_phase  # noqa: F401

    def test_turn_phase_test_file_absent(self):
        assert not (Path(__file__).parent / "test_turn_phase.py").exists()

    def test_input_section_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui.input_section  # noqa: F401

    def test_section_divider_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui.section_divider  # noqa: F401

    def test_hint_fmt_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui._hint_fmt  # noqa: F401

    def test_finalize_queue_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui.finalize_queue  # noqa: F401

    def test_osc52_probe_module_absent(self):
        with pytest.raises(ModuleNotFoundError):
            import hermes_cli.tui.osc52_probe  # noqa: F401


class TestActionCopyInputNoInputSection:
    def _make_panel(self):
        from unittest.mock import MagicMock
        from hermes_cli.tui.tool_panel import ToolPanel

        block_mock = MagicMock()
        block_mock._total_received = 0
        block_mock._all_plain = []
        panel = ToolPanel(block=block_mock, tool_name="bash")
        panel._body_pane = MagicMock()
        panel._footer_pane = MagicMock()
        panel._accent = MagicMock()
        panel.add_class = MagicMock()
        panel.remove_class = MagicMock()
        return panel

    def test_action_copy_input_uses_format_summary(self):
        import sys
        from unittest.mock import MagicMock, patch, PropertyMock

        p = self._make_panel()
        p._tool_args = {"command": "ls -la"}

        app_mock = MagicMock()
        copied = []
        fake_pyperclip = MagicMock()
        fake_pyperclip.copy = lambda text: copied.append(text)
        original = sys.modules.get("pyperclip")
        sys.modules["pyperclip"] = fake_pyperclip
        try:
            with patch.object(type(p), "app", new_callable=PropertyMock, return_value=app_mock):
                p.action_copy_input()
            assert "ls -la" in copied
        finally:
            if original is None:
                sys.modules.pop("pyperclip", None)
            else:
                sys.modules["pyperclip"] = original

    def test_action_copy_input_no_input_section_attr_needed(self):
        import sys
        from unittest.mock import MagicMock, patch, PropertyMock

        p = self._make_panel()
        p._tool_args = {"command": "pwd"}
        assert not hasattr(p, "_input_section")

        app_mock = MagicMock()
        copied = []
        fake_pyperclip = MagicMock()
        fake_pyperclip.copy = lambda text: copied.append(text)
        original = sys.modules.get("pyperclip")
        sys.modules["pyperclip"] = fake_pyperclip
        try:
            with patch.object(type(p), "app", new_callable=PropertyMock, return_value=app_mock):
                p.action_copy_input()
            assert "pwd" in copied
        finally:
            if original is None:
                sys.modules.pop("pyperclip", None)
            else:
                sys.modules["pyperclip"] = original


class TestDeprecatedMethodsAbsent:
    @pytest.mark.parametrize("method", [
        "_turn_tool_calls",
        "_tick_fps",
        "_set_chevron_phase",
        "_apply_browse_focus",
        "_focus_anchor",
        "_clear_browse_highlight",
        "_clear_browse_pips",
        "_apply_browse_pips",
        "_update_browse_status",
        "_has_rollback_checkpoint",
        "_handle_layout_command",
        "_open_anim_config",
        "_handle_anim_command",
        "_try_auto_title",
        "_toggle_drawbraille_overlay",
        "_initiate_undo",
        "_run_undo_sequence",
        "_initiate_rollback",
        "_run_rollback_sequence",
        "_auto_clear_status_error",
    ])
    def test_deprecated_method_absent(self, method):
        from hermes_cli.tui.app import HermesApp
        assert not hasattr(HermesApp, method), (
            f"HermesApp.{method} should have been deleted (DEPRECATED forwarder)"
        )
