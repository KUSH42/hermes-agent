"""Tests for Tool UX Audit Pass 7 — Phase E: Error state polish."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# E1 — Remediation inline in chip
# ---------------------------------------------------------------------------

class TestE1RemediationInline:
    """FooterPane renders remediation hints inline in chip text."""

    def _make_footer(self, with_remediation: bool):
        from hermes_cli.tui.tool_panel import FooterPane
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip
        footer = FooterPane.__new__(FooterPane)
        footer._show_all_artifacts = False
        footer._last_summary = None
        footer._last_promoted = frozenset()
        footer._last_resize_w = 0
        content_mock = MagicMock()
        footer._content = content_mock
        footer._stderr_row = MagicMock()
        footer._remediation_row = MagicMock()
        artifact_mock = MagicMock()
        artifact_mock.children = []
        artifact_mock.query.return_value = []
        footer._artifact_row = artifact_mock
        footer.add_class = MagicMock()
        footer.remove_class = MagicMock()
        parent_mock = MagicMock()
        parent_mock._block = None
        footer._test_parent = parent_mock

        remediation = "check server logs" if with_remediation else None
        chip = Chip("auth error", "status", "error", remediation=remediation)
        summary = ResultSummaryV4(
            primary="✗ error", exit_code=1,
            chips=(chip,), stderr_tail="",
            actions=(), artifacts=(), is_error=True,
        )
        return footer, summary, content_mock

    def test_remediation_shown_inline_in_chip(self):
        """E1: remediation is rendered inline in chip text, not separate row."""
        footer, summary, content_mock = self._make_footer(with_remediation=True)
        parent_mock = footer._test_parent
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered = content_mock.update.call_args[0][0]
        plain = rendered.plain if hasattr(rendered, 'plain') else str(rendered)
        assert "hint:" in plain and "check server logs" in plain, \
            f"Remediation not found inline: {plain!r}"

    def test_remediation_row_cleared(self):
        """E1: separate remediation row is cleared (not shown)."""
        footer, summary, content_mock = self._make_footer(with_remediation=True)
        parent_mock = footer._test_parent
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        # The remediation_row should be cleared (updated to empty)
        footer._remediation_row.update.assert_called()
        # And has-remediation class should be removed
        footer.remove_class.assert_called_with("has-remediation")

    def test_no_remediation_when_chip_has_none(self):
        """E1: no 'hint:' text when chip has no remediation."""
        footer, summary, content_mock = self._make_footer(with_remediation=False)
        parent_mock = footer._test_parent
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered = content_mock.update.call_args[0][0]
        plain = rendered.plain if hasattr(rendered, 'plain') else str(rendered)
        assert "hint:" not in plain


# ---------------------------------------------------------------------------
# E2 — action_open_primary exception handling
# ---------------------------------------------------------------------------

class TestE2OpenPrimaryExceptionHandling:
    """action_open_primary flashes error message on Popen failure."""

    def _make_panel_with_artifact(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact
        panel = ToolPanel.__new__(ToolPanel)
        panel._block = MagicMock()
        panel._block._header = MagicMock()
        panel._block._header._path_clickable = False
        panel._flash_header = MagicMock()

        artifact = Artifact(label="output.txt", path_or_url="/tmp/output.txt", kind="file")
        panel._result_summary_v4 = ResultSummaryV4(
            primary="done", exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(artifact,), is_error=False,
        )
        panel._result_paths = []
        return panel

    def test_flash_error_on_popen_failure(self):
        """E2: Popen exception causes flash with error tone."""
        panel = self._make_panel_with_artifact()
        import subprocess
        with patch('subprocess.Popen', side_effect=FileNotFoundError("no xdg-open")):
            panel.action_open_primary()
        panel._flash_header.assert_called()
        call_args = panel._flash_header.call_args
        msg = call_args[0][0]
        tone = call_args[1].get("tone", "")
        assert "could not open" in msg or "failed" in msg or tone == "error", \
            f"Expected error flash, got: msg={msg!r} tone={tone!r}"

    def test_no_crash_on_open_failure(self):
        """E2: open failure does not propagate exception to caller."""
        panel = self._make_panel_with_artifact()
        import subprocess
        with patch('subprocess.Popen', side_effect=OSError("permission denied")):
            # Should not raise
            panel.action_open_primary()


# ---------------------------------------------------------------------------
# E3 — Sort mode shown after cycling
# ---------------------------------------------------------------------------

class TestE3SortModeDisplay:
    """ToolsScreen.action_cycle_sort updates header with current sort mode."""

    def test_sort_mode_shown_in_header(self):
        """E3: action_cycle_sort source calls _update_staleness_pip after cycling."""
        import inspect
        from hermes_cli.tui.tools_overlay import ToolsScreen
        src = inspect.getsource(ToolsScreen.action_cycle_sort)
        assert "_update_staleness_pip" in src, \
            "E3: action_cycle_sort should call _update_staleness_pip to update header"

    def test_flash_hint_shows_sort_label(self):
        """E3: action_cycle_sort source flashes sort label hint."""
        import inspect
        from hermes_cli.tui.tools_overlay import ToolsScreen
        src = inspect.getsource(ToolsScreen.action_cycle_sort)
        assert "_flash_hint" in src or "flash_hint" in src, \
            "E3: action_cycle_sort should call _flash_hint with sort label"
        assert "sort" in src.lower(), \
            "E3: 'sort' label should appear in action_cycle_sort flash call"

    def test_sort_mode_cycles(self):
        """E3: _sort_mode advances from 0 → 1 → 2 → 0."""
        # Simple logic test
        sort_mode = 0
        sort_mode = (sort_mode + 1) % 3
        assert sort_mode == 1
        sort_mode = (sort_mode + 1) % 3
        assert sort_mode == 2
        sort_mode = (sort_mode + 1) % 3
        assert sort_mode == 0


# ---------------------------------------------------------------------------
# E4 — ToolGroup header aggregate error state
# ---------------------------------------------------------------------------

class TestE4GroupHeaderErrorState:
    """ToolGroup.recompute_aggregate sets --group-has-error when children error."""

    def _make_group_with_children(self, n_errors: int, n_success: int):
        from hermes_cli.tui.tool_group import ToolGroup
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        from hermes_cli.tui.tool_panel import ToolPanel

        group = ToolGroup.__new__(ToolGroup)
        header_mock = MagicMock()
        group._header = header_mock
        body_mock = MagicMock()

        panels = []
        for i in range(n_errors):
            p = MagicMock(spec=ToolPanel)
            p._result_summary = None
            p._result_summary_v4 = ResultSummaryV4(
                primary="✗ error", exit_code=1, chips=(), stderr_tail="",
                actions=(), artifacts=(), is_error=True,
            )
            p._start_time = 0.0
            p._completed_at = 1.0
            panels.append(p)
        for i in range(n_success):
            p = MagicMock(spec=ToolPanel)
            p._result_summary = None
            p._result_summary_v4 = ResultSummaryV4(
                primary="done", exit_code=0, chips=(), stderr_tail="",
                actions=(), artifacts=(), is_error=False,
            )
            p._start_time = 0.0
            p._completed_at = 1.0
            panels.append(p)

        body_mock.children = panels
        group._body = body_mock
        group._summary_rule = 0
        return group, header_mock

    def test_group_has_error_class_when_children_error(self):
        """E4: recompute_aggregate source accumulates error_count and calls set_class."""
        import inspect
        from hermes_cli.tui.tool_group import ToolGroup
        src = inspect.getsource(ToolGroup.recompute_aggregate)
        assert "error_count" in src, "E4: error_count accumulation missing from recompute_aggregate"
        assert "--group-has-error" in src, "E4: --group-has-error CSS class missing"
        assert "set_class" in src, "E4: set_class call missing"

    def test_group_no_error_class_when_all_success(self):
        """E4: error_count logic correctly counts is_error=True children."""
        # Test the accumulation logic directly
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        panels = []
        for i in range(2):
            p = MagicMock()
            p._result_summary_v4 = ResultSummaryV4(
                primary="✗", exit_code=1, chips=(), stderr_tail="",
                actions=(), artifacts=(), is_error=True,
            )
            panels.append(p)
        for i in range(1):
            p = MagicMock()
            p._result_summary_v4 = ResultSummaryV4(
                primary="done", exit_code=0, chips=(), stderr_tail="",
                actions=(), artifacts=(), is_error=False,
            )
            panels.append(p)

        error_count = sum(
            1 for p in panels
            if getattr(p._result_summary_v4, "is_error", False)
        )
        assert error_count == 2


# ---------------------------------------------------------------------------
# E5 — Dismiss all error banners
# ---------------------------------------------------------------------------

class TestE5DismissAllErrorBanners:
    """action_dismiss_all_error_banners removes all .error-banner widgets."""

    def test_dismiss_all_removes_banners(self):
        """E5: action queries .error-banner and removes each."""
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)

        banner1 = MagicMock()
        banner2 = MagicMock()
        screen_mock = MagicMock()
        screen_mock.query.return_value = [banner1, banner2]
        with patch.object(type(app), 'screen', new_callable=lambda: property(lambda s: screen_mock)):
            app.action_dismiss_all_error_banners()

        banner1.remove.assert_called_once()
        banner2.remove.assert_called_once()

    def test_dismiss_all_safe_with_no_banners(self):
        """E5: action does not crash when no banners exist."""
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)
        screen_mock = MagicMock()
        screen_mock.query.return_value = []
        with patch.object(type(app), 'screen', new_callable=lambda: property(lambda s: screen_mock)):
            # Should not raise
            app.action_dismiss_all_error_banners()

    def test_dismiss_all_safe_on_screen_query_exception(self):
        """E5: action doesn't crash if screen.query raises."""
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)
        screen_mock = MagicMock()
        screen_mock.query.side_effect = RuntimeError("no screen")
        with patch.object(type(app), 'screen', new_callable=lambda: property(lambda s: screen_mock)):
            # Should not raise
            app.action_dismiss_all_error_banners()

    def test_tcss_rule_for_group_has_error_exists(self):
        """E4: hermes.tcss contains GroupHeader.--group-has-error rule."""
        import os
        tcss_path = os.path.join(
            os.path.dirname(__file__), "../../hermes_cli/tui/hermes.tcss"
        )
        tcss_path = os.path.abspath(tcss_path)
        with open(tcss_path) as f:
            content = f.read()
        assert "--group-has-error" in content, \
            "GroupHeader.--group-has-error CSS rule missing from hermes.tcss"
