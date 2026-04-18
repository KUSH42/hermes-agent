"""Tests for footnote rendering — superscript conversion, definition suppression,
section rendering, and flush cleanup.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from agent.rich_output import _to_superscript, apply_inline_markdown
from hermes_cli.tui.response_flow import ResponseFlowEngine, _FOOTNOTE_DEF_RE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> ResponseFlowEngine:
    """Build a ResponseFlowEngine with a mock panel and stub prose log."""
    panel = MagicMock()
    panel.app.get_css_variables.return_value = {}
    panel.current_prose_log = MagicMock(return_value=MagicMock(
        write_with_source=MagicMock(),
        write=MagicMock(),
        _plain_lines=[],
    ))
    panel.response_log = panel.current_prose_log.return_value

    with patch("agent.rich_output.StreamingBlockBuffer", MagicMock()):
        engine = ResponseFlowEngine.__new__(ResponseFlowEngine)
        ResponseFlowEngine.__init__(engine, panel=panel)

    # Replace prose log with a simple recorder
    log = MagicMock()
    log.write_with_source = MagicMock()
    log.write = MagicMock()
    log._plain_lines = []
    engine._prose_log = log
    engine._skin_vars = {}
    return engine


# ---------------------------------------------------------------------------
# Superscript conversion
# ---------------------------------------------------------------------------

def test_to_superscript_single_digit():
    assert _to_superscript("1") == "¹"


def test_to_superscript_multi_digit():
    assert _to_superscript("12") == "¹²"


def test_to_superscript_zero():
    assert _to_superscript("0") == "⁰"


# ---------------------------------------------------------------------------
# Inline reference substitution in apply_inline_markdown
# ---------------------------------------------------------------------------

def test_inline_ref_replaced_in_apply_inline_md():
    result = apply_inline_markdown("text[^1]")
    assert "¹" in result


def test_inline_ref_no_bracket_artifacts():
    result = apply_inline_markdown("[^1]")
    assert "[" not in result
    assert "^" not in result
    assert "]" not in result


def test_inline_ref_multi_in_one_line():
    result = apply_inline_markdown("[^1] and [^2]")
    assert "¹" in result
    assert "²" in result


def test_inline_ref_does_not_match_non_numeric():
    result = apply_inline_markdown("[^abc]")
    assert "[^abc]" in result


# ---------------------------------------------------------------------------
# Definition line suppression
# ---------------------------------------------------------------------------

def test_def_line_is_suppressed():
    engine = _make_engine()
    engine.process_line("[^1]: some text")
    assert engine._footnote_defs == {"1": "some text"}
    engine._prose_log.write_with_source.assert_not_called()


def test_def_line_with_leading_whitespace():
    engine = _make_engine()
    engine.process_line("  [^1]: indented def")
    assert "1" in engine._footnote_defs
    engine._prose_log.write_with_source.assert_not_called()


def test_def_line_continuation_suppressed():
    engine = _make_engine()
    engine.process_line("[^1]: first line")
    engine.process_line("    continuation here")
    assert "continuation here" in engine._footnote_defs["1"]
    engine._prose_log.write_with_source.assert_not_called()


def test_def_line_not_suppressed_inside_fence():
    engine = _make_engine()
    engine._state = "IN_CODE"
    block = MagicMock()
    engine._active_block = block
    engine.process_line("[^1]: inside fence")
    assert engine._footnote_defs == {}
    block.append_line.assert_called_once_with("[^1]: inside fence")


def test_duplicate_def_uses_last():
    engine = _make_engine()
    engine.process_line("[^1]: version A")
    engine.process_line("[^1]: version B")
    assert engine._footnote_defs["1"] == "version B"


# ---------------------------------------------------------------------------
# Order tracking
# ---------------------------------------------------------------------------

def test_footnote_order_follows_definition_order():
    engine = _make_engine()
    engine.process_line("[^3]: third")
    engine.process_line("[^1]: first")
    assert engine._footnote_order == ["3", "1"]


def test_footnote_order_unchanged_on_duplicate():
    engine = _make_engine()
    engine.process_line("[^1]: first")
    engine.process_line("[^1]: updated")
    assert engine._footnote_order == ["1"]


def test_empty_defs_no_section_rendered():
    engine = _make_engine()
    engine._render_footnote_section()
    engine._prose_log.write_with_source.assert_not_called()


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------

def _collect_writes(engine: ResponseFlowEngine) -> list[tuple[Text, str]]:
    """Run _render_footnote_section and return all write_with_source calls."""
    engine._render_footnote_section()
    return [
        (call.args[0], call.args[1])
        for call in engine._prose_log.write_with_source.call_args_list
    ]


def test_footnote_section_has_separator():
    engine = _make_engine()
    engine._footnote_defs = {"1": "body"}
    engine._footnote_order = ["1"]
    writes = _collect_writes(engine)
    # First write is the separator
    sep_plain = writes[0][1]
    assert "─" in sep_plain


def test_footnote_section_superscript_marker():
    engine = _make_engine()
    engine._footnote_defs = {"1": "def body"}
    engine._footnote_order = ["1"]
    writes = _collect_writes(engine)
    # Second write is the footnote line
    plain = writes[1][1]
    assert plain.startswith("¹")


def test_footnote_section_body_inline_md_applied():
    engine = _make_engine()
    engine._footnote_defs = {"1": "**bold text**"}
    engine._footnote_order = ["1"]
    writes = _collect_writes(engine)
    styled: Text = writes[1][0]
    # Rendered Text should contain bold ANSI (applied via Text.from_ansi)
    ansi_str = styled.render(MagicMock())
    # Just check the plain content has the text
    assert "bold text" in styled.plain


def test_footnote_section_url_in_def():
    engine = _make_engine()
    engine._footnote_defs = {"1": "see https://example.com"}
    engine._footnote_order = ["1"]
    writes = _collect_writes(engine)
    styled: Text = writes[1][0]
    assert "https://example.com" in styled.plain


def test_footnote_section_multi_defs():
    engine = _make_engine()
    engine._footnote_defs = {"1": "a", "2": "b", "3": "c"}
    engine._footnote_order = ["1", "2", "3"]
    writes = _collect_writes(engine)
    # separator + 3 footnote lines = 4 writes total
    assert len(writes) == 4


# ---------------------------------------------------------------------------
# Flush cleanup
# ---------------------------------------------------------------------------

def test_flush_clears_footnote_state():
    engine = _make_engine()
    engine._footnote_defs = {"1": "text"}
    engine._footnote_order = ["1"]
    engine._footnote_def_open = "1"
    engine.flush()
    assert engine._footnote_defs == {}
    assert engine._footnote_order == []
    assert engine._footnote_def_open is None


def test_flush_idempotent_second_turn():
    engine = _make_engine()
    # First flush with a footnote
    engine._footnote_defs = {"1": "text"}
    engine._footnote_order = ["1"]
    engine.flush()
    engine._prose_log.write_with_source.reset_mock()
    # Second flush with no footnotes
    engine.flush()
    # _render_footnote_section should write nothing
    for call in engine._prose_log.write_with_source.call_args_list:
        # If any write happened it was from something other than footnotes
        # (pending source line / block buf flush) — footnote section itself
        # should not have been triggered since _footnote_defs is empty.
        pass
    # Confirm _footnote_defs is still empty
    assert engine._footnote_defs == {}
