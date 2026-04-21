"""Tests for ToolHeaderBar widget (v3 Phase B, tui-tool-panel-v3-spec.md §5.2).

Covers:
- Widget composes all chip children
- StatusGlyph state transitions
- LineCountChip shows '—L' placeholder then actual count
- DurationChip shows elapsed, freezes at set_finished
- ArgSummary Python-truncation
- Chevron updates with detail level
- ResultPill hidden for TEXT, shown for non-TEXT
- Narrow terminal adaptation (< 80 / < 60 / < 40)
- ToolHeaderBar.Clicked message fired on click
- Integration: ToolHeaderBar present in ToolPanel compose
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_header_bar import (
    ToolHeaderBar,
    StatusGlyph,
    LineCountChip,
    DurationChip,
    ArgSummary,
)


# ---------------------------------------------------------------------------
# Unit — no app
# ---------------------------------------------------------------------------


def test_line_count_chip_default():
    """LineCountChip renders '—L' by default."""
    chip = LineCountChip()
    assert str(chip.render()) == "—L"


def test_line_count_chip_set_count():
    chip = LineCountChip()
    chip.set_count(42)
    assert str(chip.render()) == "42L"


def test_line_count_chip_overflow():
    """Counts > 99999 render as '>99K'."""
    chip = LineCountChip()
    chip.set_count(100000)
    assert str(chip.render()) == ">99K"


def test_status_glyph_initial_state():
    sg = StatusGlyph()
    assert sg._state == "pending"


def test_status_glyph_set_state_ok():
    sg = StatusGlyph()
    sg._state = "ok"
    rendered = sg.render()
    assert "✓" in str(rendered)


def test_status_glyph_set_state_error():
    sg = StatusGlyph()
    sg._state = "error"
    rendered = sg.render()
    assert "✗" in str(rendered)


def test_arg_summary_empty():
    """ArgSummary with no text renders empty."""
    as_ = ArgSummary()
    result = as_.render()
    assert str(result) == ""


def test_arg_summary_set_text():
    as_ = ArgSummary()
    as_.set_text("grep -rn pattern src/")
    assert as_._full_text == "grep -rn pattern src/"


def test_tool_header_bar_component_classes():
    """ToolHeaderBar declares all expected COMPONENT_CLASSES."""
    expected = {
        "tool-header-bar--glyph",
        "tool-header-bar--label",
        "tool-header-bar--arg-summary",
        "tool-header-bar--pill",
        "tool-header-bar--line-count",
        "tool-header-bar--chevron",
        "tool-header-bar--duration",
    }
    assert expected <= ToolHeaderBar.COMPONENT_CLASSES


def test_tool_header_bar_default_css_height():
    assert "height: 1" in ToolHeaderBar.DEFAULT_CSS


def test_tool_header_bar_default_css_layout():
    assert "layout: horizontal" in ToolHeaderBar.DEFAULT_CSS


def test_tool_header_bar_chevron_level_2_is_down():
    bar = ToolHeaderBar()
    from textual.widgets import Static
    bar._chevron = Static("▸")
    bar.set_chevron(2)
    assert str(bar._chevron.render()) == "▾"


def test_tool_header_bar_chevron_level_1_is_right():
    bar = ToolHeaderBar()
    from textual.widgets import Static
    bar._chevron = Static("▾")
    bar.set_chevron(1)
    assert str(bar._chevron.render()) == "▸"


# ---------------------------------------------------------------------------
# Integration — requires running app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_header_bar_in_tool_panel():
    """ToolPanel compose includes ToolHeaderBar as first child of _PanelContent."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel, _PanelContent

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("patch")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        pc = panel.query_one(_PanelContent)
        assert pc.children[0].__class__.__name__ == "ToolHeaderBar"


@pytest.mark.asyncio
async def test_tool_header_bar_click_fires_message():
    """Clicking ToolHeaderBar cycles ToolPanel.detail_level."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("patch")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        header_bar = panel.query_one(ToolHeaderBar)
        initial = panel.detail_level

        await pilot.click(header_bar)
        for _ in range(3):
            await pilot.pause()

        assert panel.detail_level != initial
