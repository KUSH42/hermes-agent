"""Tests for TCS Skin Contract Tightening (SCT-1 microcopy + SCT-2 error glyphs).

Spec: /home/xush/.hermes/spec_tcs_skin_contract_tightening.md
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from rich.text import Text

from hermes_cli.tui.streaming_microcopy import StreamingState, microcopy_line
from hermes_cli.tui.tool_category import ToolCategory, ToolSpec
from hermes_cli.tui.body_renderers._grammar import SkinColors
from hermes_cli.tui.tool_result_parse import error_glyph, _ERROR_DISPLAY


def _spec(category: ToolCategory, primary_result: str = "none", provenance: str | None = None) -> ToolSpec:
    return ToolSpec(
        name="test",
        category=category,
        primary_result=primary_result,
        provenance=provenance,
    )


def _state(**kwargs) -> StreamingState:
    defaults = dict(lines_received=0, bytes_received=0, elapsed_s=1.0)
    defaults.update(kwargs)
    return StreamingState(**defaults)


def _skin(**overrides) -> SkinColors:
    base = SkinColors.default()
    if not overrides:
        return base
    fields = dict(
        accent=base.accent, muted=base.muted, success=base.success,
        error=base.error, warning=base.warning, info=base.info,
        icon_dim=base.icon_dim, separator_dim=base.separator_dim,
        diff_add_bg=base.diff_add_bg, diff_del_bg=base.diff_del_bg,
        syntax_theme=base.syntax_theme, syntax_scheme=base.syntax_scheme,
    )
    fields.update(overrides)
    return SkinColors(**fields)


# ---------------------------------------------------------------------------
# SCT-1 — microcopy stall warning skin routing
# ---------------------------------------------------------------------------

class TestSCT1MicrocopyStallSkin:

    def test_stall_uses_skin_warning_full(self):
        """AGENT branch with skin colors → stall span uses skin warning hex."""
        spec = _spec(ToolCategory.AGENT)
        state = _state(elapsed_s=3.0)
        colors = _skin(warning="#ff8800")
        result = microcopy_line(
            spec, state, reduced_motion=True, stalled=True, colors=colors,
        )
        assert isinstance(result, Text)
        # Walk spans, find one styled with #ff8800
        styles = [str(span.style) for span in result.spans]
        assert any("#ff8800" in s for s in styles), f"expected #ff8800 in spans, got {styles}"

    def test_stall_falls_back_to_yellow_without_colors(self):
        """colors=None + AGENT + stalled → "bold yellow" preserved."""
        spec = _spec(ToolCategory.AGENT)
        state = _state(elapsed_s=3.0)
        result = microcopy_line(
            spec, state, reduced_motion=True, stalled=True, colors=None,
        )
        assert isinstance(result, Text)
        styles = [str(span.style) for span in result.spans]
        assert any("yellow" in s for s in styles), f"expected 'yellow' in styles, got {styles}"

    def test_warning_glyph_routes_through_grammar(self):
        """accessibility_mode=True → '!' replaces '⚠' in stall suffix (SHELL path)."""
        spec = _spec(ToolCategory.SHELL)
        state = _state(lines_received=10, bytes_received=512, elapsed_s=3.0)
        with patch("hermes_cli.tui.constants.accessibility_mode", return_value=True):
            result = microcopy_line(spec, state, stalled=True)
        # MCC-1: microcopy_line always returns Text; check .plain for content
        assert isinstance(result, Text)
        assert "! stalled?" in result.plain
        assert "⚠" not in result.plain

    def test_no_stall_returns_no_warning_styling(self):
        """stalled=False, AGENT, with colors → no warning span."""
        spec = _spec(ToolCategory.AGENT)
        state = _state(elapsed_s=3.0)
        colors = _skin(warning="#ff8800")
        result = microcopy_line(
            spec, state, reduced_motion=True, stalled=False, colors=colors,
        )
        assert isinstance(result, Text)
        plain = result.plain
        assert "stalled" not in plain
        styles = [str(span.style) for span in result.spans]
        assert not any("#ff8800" in s for s in styles)

    def test_str_fast_path_preserved(self):
        """SHELL, stalled=False, colors=None → returns Text with expected plain content."""
        spec = _spec(ToolCategory.SHELL)
        state = _state(lines_received=42, bytes_received=2048)
        result = microcopy_line(spec, state, stalled=False, colors=None)
        # MCC-1: microcopy_line always returns Text (str fast-path removed)
        assert isinstance(result, Text)
        assert result.plain == "▸ 42 lines · 2.0kB"


# ---------------------------------------------------------------------------
# SCT-2 — canonical error glyph helper
# ---------------------------------------------------------------------------

class TestSCT2ErrorGlyphCentralization:

    def test_error_glyph_emoji_mode(self):
        with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
            assert error_glyph("timeout") == "⏳"

    def test_error_glyph_ascii_mode(self):
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            assert error_glyph("timeout") == "[T]"

    def test_error_glyph_unknown_kind_falls_back(self):
        # explicit icon_mode bypasses agent.display lookup
        assert error_glyph("bogus", icon_mode="ascii") == _ERROR_DISPLAY["network"][2]
        assert error_glyph("bogus", icon_mode="ascii") == "[W]"

    @pytest.mark.asyncio
    async def test_sub_agent_panel_uses_canonical_glyphs(self):
        """SubAgentHeader.update → error-kinds segment uses canonical glyphs (⏳🔑 not ⏱🔒)."""
        from textual.app import App
        from hermes_cli.tui.sub_agent_panel import SubAgentHeader

        captured: dict = {}

        class _MinApp(App):
            def compose(self):
                yield SubAgentHeader()

        with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
            app = _MinApp()
            async with app.run_test() as pilot:
                header = app.query_one(SubAgentHeader)
                # Stub width via property override (Widget.app.size is read-only — capture renderable on _badges)
                orig_update = header._badges.update

                def _capture(renderable=""):
                    captured["renderable"] = renderable
                    return orig_update(renderable)

                header._badges.update = _capture
                header.update(
                    child_count=2,
                    error_count=2,
                    elapsed_ms=500,
                    done=True,
                    error_kinds=["timeout", "auth"],
                )
                await pilot.pause()

        rend = captured.get("renderable", "")
        plain = rend.plain if isinstance(rend, Text) else str(rend)
        assert "⏳" in plain, f"expected canonical timeout glyph ⏳, got {plain!r}"
        assert "🔑" in plain, f"expected canonical auth glyph 🔑, got {plain!r}"
        assert "⏱" not in plain
        assert "🔒" not in plain
