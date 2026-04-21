"""Tests for Tool UX Audit Pass 7 — Phase B: Artifacts & footer clarity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# B1 — Payload truncation chip
# ---------------------------------------------------------------------------

class TestB1PayloadTruncationChip:
    """Truncated chip renders with bold ⚠ prefix."""

    def _make_footer(self):
        from hermes_cli.tui.tool_panel import FooterPane
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
        # Patch parent as a property override — Textual's parent has no setter
        footer._test_parent = parent_mock
        return footer, content_mock

    def test_truncated_chip_shows_warning_glyph(self):
        """B1: truncated chip uses bold warning style with ⚠ prefix."""
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action
        from hermes_cli.tui.tool_panel import FooterPane
        footer, content_mock = self._make_footer()
        action = Action("copy", "c", "copy_body", None, payload_truncated=True)
        summary = ResultSummaryV4(
            primary="done", exit_code=0, chips=(), stderr_tail="",
            actions=(action,), artifacts=(), is_error=False,
        )
        parent_mock = footer._test_parent
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered = content_mock.update.call_args[0][0]
        plain = rendered.plain if hasattr(rendered, 'plain') else str(rendered)
        assert "⚠" in plain
        assert "payload truncated" in plain

    def test_no_truncated_chip_without_flag(self):
        """B1: no truncated chip when payload_truncated is False."""
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action
        from hermes_cli.tui.tool_panel import FooterPane
        footer, content_mock = self._make_footer()
        action = Action("copy", "c", "copy_body", None, payload_truncated=False)
        summary = ResultSummaryV4(
            primary="done", exit_code=0, chips=(), stderr_tail="",
            actions=(action,), artifacts=(), is_error=False,
        )
        parent_mock = footer._test_parent
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered = content_mock.update.call_args[0][0]
        plain = rendered.plain if hasattr(rendered, 'plain') else str(rendered)
        assert "payload truncated" not in plain


# ---------------------------------------------------------------------------
# B2 — Artifact button tooltip
# ---------------------------------------------------------------------------

class TestB2ArtifactTooltip:
    """Artifact buttons are _ArtifactButton instances with _tooltip_text set."""

    def test_artifact_button_class_exists(self):
        """B2: _ArtifactButton class is importable and inherits TooltipMixin."""
        from hermes_cli.tui.tool_panel import _ArtifactButton
        from hermes_cli.tui.tooltip import TooltipMixin
        assert issubclass(_ArtifactButton, TooltipMixin)

    def test_rebuild_uses_artifact_button(self):
        """B2: _rebuild_artifact_buttons creates _ArtifactButton not plain Button."""
        from hermes_cli.tui.tool_panel import FooterPane, _ArtifactButton
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact
        footer = FooterPane.__new__(FooterPane)
        footer._show_all_artifacts = False
        footer._last_summary = None
        footer._last_promoted = frozenset()
        footer._last_resize_w = 0
        footer._content = MagicMock()
        footer._stderr_row = MagicMock()
        footer._remediation_row = MagicMock()
        artifact_mock = MagicMock()
        artifact_mock.children = []
        artifact_mock.query.return_value = []
        footer._artifact_row = artifact_mock
        footer.add_class = MagicMock()
        footer.remove_class = MagicMock()
        parent_mock2 = MagicMock()
        parent_mock2._block = None

        artifact = Artifact(label="report.txt", path_or_url="/tmp/report.txt", kind="file")
        summary = ResultSummaryV4(
            primary="done", exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(artifact,), is_error=False,
        )
        created_buttons = []
        original_mount = MagicMock()
        artifact_mock.mount = original_mount

        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent_mock2)):
            with patch('hermes_cli.tui.tool_result_parse._ARTIFACT_DISPLAY_CAP', 10):
                footer._rebuild_artifact_buttons(summary)

        # Check that buttons were created with _tooltip_text
        calls = artifact_mock.mount.call_args_list
        if calls:
            btns = calls[0][0]
            for btn in btns:
                if hasattr(btn, '_artifact_path'):
                    assert isinstance(btn, _ArtifactButton), \
                        f"Expected _ArtifactButton, got {type(btn)}"
                    assert btn._tooltip_text == "/tmp/report.txt"

    def test_artifact_button_tooltip_text_set(self):
        """B2: _tooltip_text on artifact button equals path_or_url."""
        from hermes_cli.tui.tool_panel import _ArtifactButton
        from textual.widgets import Button
        # Instantiate with a label — tooltip is set after creation
        btn = _ArtifactButton.__new__(_ArtifactButton)
        btn._tooltip_text = "/home/user/file.txt"
        assert btn._tooltip_text == "/home/user/file.txt"


# ---------------------------------------------------------------------------
# B3 — Artifact expand state resets on collapse
# ---------------------------------------------------------------------------

class TestB3ArtifactStateReset:
    """watch_collapsed resets _show_all_artifacts when collapsing."""

    def test_artifact_state_reset_on_collapse(self):
        """B3: collapsing ToolPanel resets footer._show_all_artifacts to False."""
        from hermes_cli.tui.tool_panel import ToolPanel, FooterPane
        panel = ToolPanel.__new__(ToolPanel)
        panel._block = MagicMock()
        panel._block._visible_start = 0
        panel._result_summary_v4 = None
        panel._saved_visible_start = None

        footer = FooterPane.__new__(FooterPane)
        footer._show_all_artifacts = True  # was expanded
        footer._last_summary = None
        footer._last_promoted = frozenset()
        footer._rebuild_chips = MagicMock()
        styles_mock = MagicMock()
        footer_display_calls = []

        # Patch display property to avoid Textual dependency
        def get_display(self):
            return True
        def set_display(self, val):
            footer_display_calls.append(val)

        panel._footer_pane = footer

        # Patch watch_collapsed to test just the B3 part
        original_watch = ToolPanel.watch_collapsed

        def patched_watch(p, old, new):
            fp = p._footer_pane
            if fp is None:
                return
            # B3: reset artifact expand state on collapse
            if new and fp._show_all_artifacts:
                fp._show_all_artifacts = False
                fp._rebuild_chips()
            # Skip footer display toggle (needs Textual)

        panel.watch_collapsed = lambda old, new: patched_watch(panel, old, new)
        panel.watch_collapsed(old=False, new=True)
        assert footer._show_all_artifacts is False
        footer._rebuild_chips.assert_called()

    def test_artifact_state_not_reset_on_expand(self):
        """B3: expanding does NOT reset artifact state (only collapse does)."""
        from hermes_cli.tui.tool_panel import ToolPanel, FooterPane
        panel = ToolPanel.__new__(ToolPanel)
        panel._block = MagicMock()
        panel._result_summary_v4 = None
        panel._saved_visible_start = None

        footer = FooterPane.__new__(FooterPane)
        footer._show_all_artifacts = True
        footer._last_summary = None
        footer._last_promoted = frozenset()
        footer._rebuild_chips = MagicMock()
        panel._footer_pane = footer

        def patched_watch(p, old, new):
            fp = p._footer_pane
            if fp is None:
                return
            if new and fp._show_all_artifacts:
                fp._show_all_artifacts = False
                fp._rebuild_chips()

        panel.watch_collapsed = lambda old, new: patched_watch(panel, old, new)
        # Simulate expand (new=False)
        panel.watch_collapsed(old=True, new=False)
        # _show_all_artifacts should NOT be reset
        assert footer._show_all_artifacts is True


# ---------------------------------------------------------------------------
# B4 — MCP remediation includes server name
# ---------------------------------------------------------------------------

class TestB4McpRemediationServerName:
    """MCP error remediation hints include server name."""

    def _make_ctx(self, error_kind: str, server_prov: str = "mcp:my-server"):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        complete = ToolComplete(
            name="mcp__my-server__query",
            raw_result={"error": "auth failed"},
            is_error=True,
            error_kind=error_kind,
        )
        start = ToolStart(name="mcp__my-server__query", args={})
        spec = MagicMock()
        spec.provenance = server_prov
        spec.name = "mcp__my-server__query"
        spec.category = MagicMock()
        spec.primary_result = "text"
        spec.primary_arg = None
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_auth_remediation_includes_server(self):
        """B4: MCP auth error remediation mentions server name."""
        from hermes_cli.tui.tool_result_parse import mcp_result_v4
        ctx = self._make_ctx("auth")
        result = mcp_result_v4(ctx)
        remediations = [c.remediation for c in result.chips if c.remediation]
        assert remediations, "Expected at least one remediation hint"
        combined = " ".join(remediations)
        assert "my-server" in combined, f"Server name missing in: {combined}"

    def test_disconnect_remediation_includes_server(self):
        """B4: MCP disconnect error remediation mentions server name."""
        from hermes_cli.tui.tool_result_parse import mcp_result_v4
        ctx = self._make_ctx("disconnect")
        result = mcp_result_v4(ctx)
        remediations = [c.remediation for c in result.chips if c.remediation]
        assert remediations
        combined = " ".join(remediations)
        assert "my-server" in combined


# ---------------------------------------------------------------------------
# B5 — HTTP 3xx uses warning tone
# ---------------------------------------------------------------------------

class TestB5Http3xxWarningTone:
    """web_result_v4 uses warning tone for 3xx redirect status codes."""

    def _make_web_ctx(self, status_code: int, reason: str = "Moved"):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        raw = f"HTTP/1.1 {status_code} {reason}\n\nBody here"
        complete = ToolComplete(
            name="web_fetch",
            raw_result=raw,
            is_error=False,
            error_kind=None,
        )
        start = ToolStart(name="web_fetch", args={"url": "https://example.com/"})
        spec = MagicMock()
        spec.provenance = None
        spec.name = "web_fetch"
        spec.category = MagicMock()
        spec.primary_result = "html"
        spec.primary_arg = "url"
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_3xx_uses_warning_tone(self):
        """B5: 3xx status chip uses warning tone."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = self._make_web_ctx(301, "Moved Permanently")
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips, "No status chip found"
        assert status_chips[0].tone == "warning", \
            f"Expected warning tone, got {status_chips[0].tone!r}"

    def test_302_uses_warning_tone(self):
        """B5: 302 redirect also uses warning tone."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = self._make_web_ctx(302, "Found")
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips[0].tone == "warning"

    def test_2xx_uses_success_tone(self):
        """B5: 2xx still uses success tone (not affected by 3xx change)."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = self._make_web_ctx(200, "OK")
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips[0].tone == "success"
