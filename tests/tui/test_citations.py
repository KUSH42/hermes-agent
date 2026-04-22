"""Tests for Citations & SourcesBar (Phase B).

Covers:
- _CITE_RE regex parsing
- _extract_domain / _truncate helpers
- ResponseFlowEngine cite detection + suppression
- SourcesBar widget composition and click handling
- End-of-turn flush / SourcesBar mounting
- ReasoningFlowEngine mirroring + _reasoning_rich_prose flag
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.response_flow import (
    ReasoningFlowEngine,
    ResponseFlowEngine,
    _CITE_RE,
)
from hermes_cli.tui.widgets import SourcesBar, _extract_domain, _truncate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(citations_enabled: bool = True) -> ResponseFlowEngine:
    """Build a ResponseFlowEngine with mock panel; citations flag wired."""
    panel = MagicMock()
    panel.app.get_css_variables.return_value = {}
    panel.app._citations_enabled = citations_enabled
    panel.app._math_enabled = False
    panel.app._mermaid_enabled = False
    panel.current_prose_log = MagicMock(return_value=MagicMock(
        write_with_source=MagicMock(),
        write=MagicMock(),
        _plain_lines=[],
    ))
    panel.response_log = panel.current_prose_log.return_value

    with patch("agent.rich_output.StreamingBlockBuffer", MagicMock()):
        engine = ResponseFlowEngine.__new__(ResponseFlowEngine)
        ResponseFlowEngine.__init__(engine, panel=panel)

    log = MagicMock()
    log.write_with_source = MagicMock()
    log.write = MagicMock()
    log._plain_lines = []
    engine._prose_log = log
    engine._skin_vars = {}
    # Make block buf return None (buffering) so prose lines don't crash in tests
    engine._block_buf.process_line.return_value = None
    engine._block_buf.flush.return_value = None
    return engine


def _make_reasoning_engine(citations_enabled: bool = True, reasoning_rich_prose: bool = True) -> ReasoningFlowEngine:
    """Build a ReasoningFlowEngine with both flags set."""
    panel = MagicMock()
    panel.app._citations_enabled = citations_enabled
    panel.app._reasoning_rich_prose = reasoning_rich_prose
    panel.app.get_css_variables.return_value = {}
    panel._reasoning_log = MagicMock()
    panel._reasoning_log.write = MagicMock()
    panel._plain_lines = []
    panel._live_line = MagicMock()

    with patch("agent.rich_output.StreamingBlockBuffer", MagicMock()):
        engine = ReasoningFlowEngine.__new__(ReasoningFlowEngine)
        ReasoningFlowEngine.__init__(engine, panel=panel)

    log = MagicMock()
    log.write_with_source = MagicMock()
    log.write = MagicMock()
    log._plain_lines = []
    engine._prose_log = log
    engine._skin_vars = {}
    # Make block buf return None (buffering) so prose lines don't crash in tests
    engine._block_buf.process_line.return_value = None
    engine._block_buf.flush.return_value = None
    return engine


# ---------------------------------------------------------------------------
# Regex / parsing (5 tests)
# ---------------------------------------------------------------------------

def test_cite_re_full_match():
    line = "[CITE:1 Title \u2014 https://example.com]"
    m = _CITE_RE.match(line)
    assert m is not None
    assert m.group(1) == "1"
    assert m.group(2) == "Title"
    assert m.group(3) == "https://example.com"


def test_cite_re_multi_word_title():
    line = "[CITE:2 OpenAI Research Paper \u2014 https://openai.com/research]"
    m = _CITE_RE.match(line)
    assert m is not None
    assert m.group(2) == "OpenAI Research Paper"
    assert m.group(3) == "https://openai.com/research"


def test_cite_re_no_match_missing_url():
    line = "[CITE:1 No URL here]"
    assert _CITE_RE.match(line) is None


def test_cite_re_no_match_bad_scheme():
    line = "[CITE:1 X \u2014 ftp://x.com]"
    assert _CITE_RE.match(line) is None


def test_cite_re_no_match_partial_brackets():
    line = "CITE:1 X \u2014 https://x.com"
    assert _CITE_RE.match(line) is None


# ---------------------------------------------------------------------------
# Domain extraction (3 tests)
# ---------------------------------------------------------------------------

def test_extract_domain_strips_www():
    assert _extract_domain("https://www.openai.com/page") == "openai.com"


def test_extract_domain_no_www():
    assert _extract_domain("https://anthropic.com") == "anthropic.com"


def test_extract_domain_fallback_on_bad_url():
    result = _extract_domain("notaurl")
    assert result == "notaurl"[:30]


# ---------------------------------------------------------------------------
# Detection and suppression in engine (5 tests)
# ---------------------------------------------------------------------------

def test_cite_line_suppressed_from_prose():
    engine = _make_engine()
    engine.process_line("[CITE:1 T \u2014 https://x.com]")
    engine._prose_log.write_with_source.assert_not_called()


def test_cite_collected_in_entries():
    engine = _make_engine()
    engine.process_line("[CITE:1 T \u2014 https://x.com]")
    assert engine._cite_entries[1] == ("T", "https://x.com")


def test_cite_order_tracked():
    engine = _make_engine()
    engine.process_line("[CITE:3 C \u2014 https://c.com]")
    engine.process_line("[CITE:1 A \u2014 https://a.com]")
    engine.process_line("[CITE:2 B \u2014 https://b.com]")
    assert engine._cite_order == [3, 1, 2]


def test_duplicate_n_uses_last():
    engine = _make_engine()
    engine.process_line("[CITE:1 First \u2014 https://first.com]")
    engine.process_line("[CITE:1 Second \u2014 https://second.com]")
    assert engine._cite_entries[1] == ("Second", "https://second.com")
    assert engine._cite_order == [1]  # order unchanged


def test_cite_inside_fence_not_suppressed():
    engine = _make_engine()
    engine._state = "IN_CODE"
    block = MagicMock()
    engine._active_block = block
    engine.process_line("[CITE:1 T \u2014 https://x.com]")
    assert engine._cite_entries == {}
    block.append_line.assert_called_once_with("[CITE:1 T \u2014 https://x.com]")


# ---------------------------------------------------------------------------
# SourcesBar widget (5 tests)
# ---------------------------------------------------------------------------

def test_sources_bar_composes_chips():
    from textual.widgets import Button, Label
    entries = [(1, "Title A", "https://a.com"), (2, "Title B", "https://b.com")]
    bar = SourcesBar(entries)
    children = list(bar.compose())
    buttons = [c for c in children if isinstance(c, Button)]
    assert len(buttons) == 2


def test_chip_label_format():
    from textual.widgets import Button
    entries = [(1, "OpenAI Research", "https://openai.com/r")]
    bar = SourcesBar(entries)
    children = list(bar.compose())
    buttons = [c for c in children if isinstance(c, Button)]
    assert len(buttons) == 1
    label = str(buttons[0].label)
    assert "[1]" in label
    assert "openai.com" in label
    assert "OpenAI Research" in label


def test_chip_label_title_truncated():
    from textual.widgets import Button
    long_title = "A" * 50
    entries = [(1, long_title, "https://example.com")]
    bar = SourcesBar(entries)
    children = list(bar.compose())
    buttons = [c for c in children if isinstance(c, Button)]
    label = str(buttons[0].label)
    # Truncated at 40 chars + ellipsis
    assert "\u2026" in label


def test_chip_click_calls_xdg_open():
    entries = [(1, "Title", "https://example.com")]
    bar = SourcesBar(entries)

    event = MagicMock()
    event.button.id = "cite-1"

    with patch("hermes_cli.tui.widgets.status_bar.safe_open_url") as mock_open:
        bar.on_button_pressed(event)
    mock_open.assert_called_once()
    assert mock_open.call_args[0] == (bar, "https://example.com")

    event.stop.assert_called_once()


def test_chip_unknown_url_ignored():
    entries = [(1, "Title", "https://example.com")]
    bar = SourcesBar(entries)

    event = MagicMock()
    event.button.id = "cite-999"  # not in entries

    # Should not raise, and should not call Popen
    with patch("subprocess.Popen") as mock_popen:
        bar.on_button_pressed(event)
    mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# End-of-turn integration (7 tests)
# ---------------------------------------------------------------------------

def test_flush_mounts_sources_bar():
    engine = _make_engine()
    engine.process_line("[CITE:1 T \u2014 https://x.com]")

    # Patch _mount_sources_bar to verify it's called
    engine._mount_sources_bar = MagicMock()
    with patch("hermes_cli.tui.response_flow.ResponseFlowEngine._render_footnote_section"):
        engine.flush()

    engine._mount_sources_bar.assert_called_once()


def test_flush_no_bar_when_no_cites():
    engine = _make_engine()
    engine.process_line("No citation here")

    engine._mount_sources_bar = MagicMock()
    with patch("hermes_cli.tui.response_flow.ResponseFlowEngine._render_footnote_section"):
        engine.flush()

    engine._mount_sources_bar.assert_not_called()


def test_flush_clears_cite_state():
    engine = _make_engine()
    engine.process_line("[CITE:1 T \u2014 https://x.com]")

    with patch.object(engine, "_mount_sources_bar"):
        with patch("hermes_cli.tui.response_flow.ResponseFlowEngine._render_footnote_section"):
            engine.flush()

    assert engine._cite_entries == {}
    assert engine._cite_order == []


def test_reasoning_engine_citations_when_flag_on():
    engine = _make_reasoning_engine(citations_enabled=True, reasoning_rich_prose=True)
    assert engine._citations_enabled is True
    engine.process_line("[CITE:1 T \u2014 https://x.com]")
    assert engine._cite_entries[1] == ("T", "https://x.com")
    engine._prose_log.write_with_source.assert_not_called()

    mounted_bar: list = []

    def _fake_mount(widget) -> None:
        mounted_bar.append(widget)

    engine._panel.mount.side_effect = _fake_mount
    engine._panel.call_after_refresh.side_effect = lambda fn: fn()

    with patch("hermes_cli.tui.response_flow.ResponseFlowEngine._render_footnote_section"):
        engine.flush()

    assert len(mounted_bar) == 1
    assert isinstance(mounted_bar[0], SourcesBar)


def test_reasoning_engine_citations_flag_off():
    engine = _make_reasoning_engine(citations_enabled=True, reasoning_rich_prose=False)
    # When _reasoning_rich_prose=False, _citations_enabled should be False
    assert engine._citations_enabled is False

    # Cite line should pass through (not be suppressed)
    engine.process_line("[CITE:1 T \u2014 https://x.com]")
    assert engine._cite_entries == {}  # not collected

    engine._mount_sources_bar = MagicMock()
    with patch("hermes_cli.tui.response_flow.ResponseFlowEngine._render_footnote_section"):
        engine.flush()

    engine._mount_sources_bar.assert_not_called()


def test_reasoning_engine_footnotes_flag_on():
    engine = _make_reasoning_engine(citations_enabled=True, reasoning_rich_prose=True)
    engine._panel.app._reasoning_rich_prose = True

    # super()._render_footnote_section should be called
    with patch.object(ResponseFlowEngine, "_render_footnote_section") as mock_super:
        engine._render_footnote_section()
    mock_super.assert_called_once()


def test_reasoning_engine_footnotes_flag_off():
    engine = _make_reasoning_engine(citations_enabled=True, reasoning_rich_prose=False)
    engine._panel.app._reasoning_rich_prose = False

    with patch.object(ResponseFlowEngine, "_render_footnote_section") as mock_super:
        engine._render_footnote_section()
    mock_super.assert_not_called()
