"""Tests for TOOL-1, TOOL-2, TOOL-3, TOOL-4 spec."""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text


# ---------------------------------------------------------------------------
# TestFooterActionRouting  (TOOL-1)
# ---------------------------------------------------------------------------

class TestFooterActionRouting:
    """TOOL-1: every implemented action kind routes to the correct panel method."""

    def test_footer_action_map_covers_implemented_actions(self):
        from hermes_cli.tui.tool_panel._footer import (
            _IMPLEMENTED_ACTIONS,
            ACTION_KIND_TO_PANEL_METHOD,
        )
        extra = set(ACTION_KIND_TO_PANEL_METHOD) - _IMPLEMENTED_ACTIONS
        missing = _IMPLEMENTED_ACTIONS - set(ACTION_KIND_TO_PANEL_METHOD)
        assert missing == set(), f"ACTION_KIND_TO_PANEL_METHOD missing: {missing}"
        assert extra == set(), f"ACTION_KIND_TO_PANEL_METHOD has extra keys: {extra}"

    def _make_footer_with_panel(self, FooterPane, panel):
        """Create a FooterPane whose .parent returns the given panel mock."""
        footer = FooterPane.__new__(FooterPane)
        # parent is a read-only property on Widget; patch on the class for this instance
        with patch.object(type(footer), "parent", new_callable=PropertyMock, return_value=panel):
            yield footer

    def test_footer_action_chip_routes_every_rendered_action(self):
        from hermes_cli.tui.tool_panel._footer import (
            ACTION_KIND_TO_PANEL_METHOD,
            FooterPane,
        )

        def _run(footer, kind, panel=None):
            btn = MagicMock()
            btn.classes = ["--action-chip"]
            btn.name = kind
            event = MagicMock()
            event.button = btn
            footer.on_button_pressed(event)
            return event

        # --- happy path: each kind calls the mapped method --------------------
        for kind, method_name in ACTION_KIND_TO_PANEL_METHOD.items():
            panel = MagicMock()
            panel.is_mounted = True
            footer = FooterPane.__new__(FooterPane)
            with patch.object(FooterPane, "parent", new_callable=PropertyMock, return_value=panel):
                event = _run(footer, kind)
                event.stop.assert_called_once()
                getattr(panel, method_name).assert_called_once()

        # --- open_first maps to action_open_primary, not action_open_first ---
        panel = MagicMock()
        panel.is_mounted = True
        footer = FooterPane.__new__(FooterPane)
        with patch.object(FooterPane, "parent", new_callable=PropertyMock, return_value=panel):
            _run(footer, "open_first")
            panel.action_open_primary.assert_called_once()
            panel.action_open_first.assert_not_called()

        # --- missing mapped handler → flash "Action unavailable" -------------
        panel_missing = MagicMock()
        panel_missing.is_mounted = True
        footer2 = FooterPane.__new__(FooterPane)
        with patch.object(FooterPane, "parent", new_callable=PropertyMock, return_value=panel_missing):
            _run(footer2, "__nonexistent_kind__")
            panel_missing._flash_header.assert_called_once_with("Action unavailable", tone="error")

        # --- handler raises → flash "Action failed" then re-raise ------------
        panel_raise = MagicMock()
        panel_raise.is_mounted = True
        panel_raise.action_copy_body.side_effect = RuntimeError("boom")
        footer3 = FooterPane.__new__(FooterPane)
        with patch.object(FooterPane, "parent", new_callable=PropertyMock, return_value=panel_raise):
            with pytest.raises(RuntimeError, match="boom"):
                _run(footer3, "copy_body")
            panel_raise._flash_header.assert_called_once_with("Action failed", tone="error")


# ---------------------------------------------------------------------------
# TestCollapsedActionStrip  (TOOL-2)
# ---------------------------------------------------------------------------

class TestCollapsedActionStrip:
    """TOOL-2: file category collapsed strip shows 'c copy', not 'c diff'."""

    def test_collapsed_file_strip_c_label_matches_binding(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.tool_panel._footer import _get_collapsed_actions

        actions = _get_collapsed_actions(ToolCategory.FILE)
        action_dict = {key: label for key, label in actions}

        assert action_dict.get("c") == "copy", (
            f"Expected 'c' → 'copy', got {action_dict.get('c')!r}"
        )
        assert "diff" not in action_dict.values(), (
            "File strip must not advertise 'diff'; found in labels"
        )


# ---------------------------------------------------------------------------
# TestToolHeaderTrim  (TOOL-3)
# ---------------------------------------------------------------------------

class TestToolHeaderTrim:
    """TOOL-3: flash survives narrow budget when competing with hero."""

    def test_tool_header_flash_survives_hero_under_narrow_budget(self):
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments

        hero = Text("  some longer hero text")
        flash = Text("  ✓ Copied")

        segments = [("hero", hero), ("flash", flash)]

        # budget fits flash but not both
        budget = flash.cell_len
        assert budget < hero.cell_len + flash.cell_len, "test precondition: budget too wide"

        result = _trim_tail_segments(segments, budget)
        names = [name for name, _ in result]

        assert "flash" in names, "flash must survive when budget fits it"
        assert "hero" not in names, "hero must be dropped to make room for flash"


# ---------------------------------------------------------------------------
# TestStaticFileSyntaxTheme  (TOOL-4)
# ---------------------------------------------------------------------------

class TestStaticFileSyntaxTheme:
    """TOOL-4: static file preview respects configured syntax theme."""

    def _make_block(self, css_vars: dict):
        from hermes_cli.tui.tool_blocks._block import ToolBlock

        block = ToolBlock.__new__(ToolBlock)
        block._plain_lines = ["x = 1", "y = 2"]
        block._label = "foo.py"
        block._tool_name = "read_file"
        block._streaming = False
        block._is_streaming = False

        app_mock = MagicMock()
        app_mock.get_css_variables.return_value = css_vars

        richlog = MagicMock()
        body = MagicMock()
        body.query_one.return_value = richlog
        block._body = body

        return block, richlog, app_mock

    def _render_and_capture_theme(self, block, richlog, app_mock):
        """Run _render_body and return the `theme` kwarg passed to Syntax(...)."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        import rich.syntax as _rich_syntax

        themes_seen: list[str] = []
        _real_Syntax = _rich_syntax.Syntax

        def _capturing_Syntax(*args, **kwargs):
            themes_seen.append(kwargs.get("theme", ""))
            return _real_Syntax(*args, **kwargs)

        with patch.object(ToolBlock, "app", new_callable=PropertyMock, return_value=app_mock), \
             patch("hermes_cli.tui.tool_blocks._block._code_lang", return_value="python"), \
             patch("hermes_cli.tui.tool_blocks._block._FILE_TOOL_NAMES", {"read_file"}), \
             patch.object(_rich_syntax, "Syntax", side_effect=_capturing_Syntax):
            block._render_body()

        return themes_seen[0] if themes_seen else None

    def test_static_toolblock_file_preview_uses_configured_preview_syntax_theme(self):
        from hermes_cli.tui.tool_blocks._block import _FILE_TOOL_NAMES, _code_lang

        assert "read_file" in _FILE_TOOL_NAMES
        assert _code_lang("foo.py") is not None

        # preview-syntax-theme wins over syntax-theme
        block, richlog, app_mock = self._make_block(
            {"preview-syntax-theme": "nord", "syntax-theme": "monokai"}
        )
        theme = self._render_and_capture_theme(block, richlog, app_mock)
        assert theme == "nord", f"Expected theme 'nord', got {theme!r}"

        # syntax-theme fallback when preview-syntax-theme absent
        block2, richlog2, app_mock2 = self._make_block({"syntax-theme": "dracula"})
        theme2 = self._render_and_capture_theme(block2, richlog2, app_mock2)
        assert theme2 == "dracula", f"Expected theme 'dracula', got {theme2!r}"

    def test_static_toolblock_file_preview_falls_back_to_monokai(self):
        block, richlog, app_mock = self._make_block({})
        theme = self._render_and_capture_theme(block, richlog, app_mock)
        assert theme == "monokai", f"Expected fallback 'monokai', got {theme!r}"
