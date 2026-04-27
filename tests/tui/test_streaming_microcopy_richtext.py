"""MCC-1: microcopy_line() returns Rich Text for all branches."""
from __future__ import annotations

import pytest
from rich.text import Text

from hermes_cli.tui.streaming_microcopy import StreamingState, microcopy_line
from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph as _glyph


def _make_spec(category, primary_result="lines", name="tool", provenance=None):
    from types import SimpleNamespace
    return SimpleNamespace(
        category=category,
        primary_result=primary_result,
        name=name,
        provenance=provenance,
    )


def _default_state(**kw):
    defaults = dict(lines_received=5, bytes_received=1024, elapsed_s=0.5)
    defaults.update(kw)
    return StreamingState(**defaults)


class TestMCC1RichTextReturn:
    def test_shell_branch_returns_text_not_str(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = _make_spec(ToolCategory.SHELL)
        result = microcopy_line(spec, _default_state())
        assert isinstance(result, Text)

    def test_segment_separator_uses_grammar_glyph(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = _make_spec(ToolCategory.SHELL)
        result = microcopy_line(spec, _default_state())
        plain = result.plain
        sep = _glyph(GLYPH_META_SEP)
        assert sep in plain

    def test_elapsed_suffix_styled_dim(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = _make_spec(ToolCategory.SHELL)
        result = microcopy_line(spec, _default_state(elapsed_s=5.0))
        found = False
        for span in result._spans:
            fragment = result.plain[span.start:span.end]
            if "5.0s" in fragment:
                assert "dim" in str(span.style), (
                    f"elapsed span style should be dim, got {span.style!r}"
                )
                found = True
                break
        assert found, f"No span containing '5.0s' found in {result!r}"

    @pytest.mark.parametrize("cat_name", [
        "SHELL", "FILE", "SEARCH", "WEB", "MCP", "CODE", "AGENT", "UNKNOWN",
    ])
    def test_return_type_is_always_text(self, cat_name):
        from hermes_cli.tui.tool_category import ToolCategory
        cat = getattr(ToolCategory, cat_name)
        spec = _make_spec(cat, primary_result="lines", name="a__b__c")
        state = _default_state()
        result = microcopy_line(spec, state)
        assert isinstance(result, Text), f"{cat_name} returned {type(result).__name__}"

    def test_unknown_branch_returns_text(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = _make_spec(ToolCategory.UNKNOWN)
        result = microcopy_line(spec, _default_state(), stalled=True)
        assert isinstance(result, Text)
        assert "⚠ stalled?" in result.plain

    def test_agent_reduced_motion_returns_text(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = _make_spec(ToolCategory.AGENT)
        result = microcopy_line(spec, _default_state(), reduced_motion=True)
        assert isinstance(result, Text)
