"""Tests for KeymapOverlay structured data + renderer (SPEC-KM-REFRESH)."""
import pytest
from hermes_cli.tui.widgets.overlays import (
    _km_render_sections,
    _KM_SECTIONS_WIDE,
    _KM_SECTIONS_NARROW,
)


# ---------------------------------------------------------------------------
# KM-L1: renderer unit tests
# ---------------------------------------------------------------------------

def test_render_sections_basic():
    sections = [("Nav", [("Go back", "Alt+←"), ("Go forward", "Alt+→")])]
    out = _km_render_sections(sections, width=80)
    assert "Nav" in out
    assert "[dim]\\[Alt+←][/dim]" in out
    assert "[dim]\\[Alt+→][/dim]" in out
    assert "Go back" in out


def test_render_sections_no_keys_row():
    sections = [("Slash Commands", [("/clear",), ("/help",)])]
    out = _km_render_sections(sections, width=80)
    assert "/clear" in out
    assert "/help" in out
    # No trailing [dim]\[...][/dim] on description-only rows
    assert "[dim]\\[/clear][/dim]" not in out


def test_render_sections_width_clamp():
    out = _km_render_sections([], width=200)
    ruler_line = [l for l in out.splitlines() if set(l) == {"─"}]
    assert ruler_line, "expected a ruler line of ─ chars"
    assert len(ruler_line[0]) <= 61


# ---------------------------------------------------------------------------
# KM-H1: no stale Ctrl+G in history row
# ---------------------------------------------------------------------------

def _wide():
    return _km_render_sections(_KM_SECTIONS_WIDE, width=80)


def _narrow():
    return _km_render_sections(_KM_SECTIONS_NARROW, width=60)


def test_content_no_ctrl_g_in_history_row():
    assert "Ctrl+G" not in _wide()
    assert "Ctrl+G" not in _narrow()


# ---------------------------------------------------------------------------
# KM-H2: no stale Alt+Z
# ---------------------------------------------------------------------------

def test_content_no_alt_z():
    assert "Alt+Z" not in _wide()
    assert "Alt+Z" not in _narrow()


# ---------------------------------------------------------------------------
# KM-H3: no stale Space in collapse row
# ---------------------------------------------------------------------------

def test_content_no_space_in_collapse_row():
    wide = _wide()
    # "Space" should not appear anywhere as a key label
    assert "\\[Space][/dim]" not in wide


# ---------------------------------------------------------------------------
# KM-H4: F9 description
# ---------------------------------------------------------------------------

def test_content_f9_description():
    wide = _wide()
    assert "Cycle pane" in wide
    assert "Plan panel" not in wide
    assert "\\[F9][/dim]" in wide
    assert "\\[Shift+F9][/dim]" in wide


# ---------------------------------------------------------------------------
# KM-H5 / KM-M3: ? maps to Context menu, not "Help overlay"
# ---------------------------------------------------------------------------

def test_content_tool_panel_question_mark():
    wide = _wide()
    assert "Context menu" in wide
    assert "\\[?][/dim]" in wide
    assert "\\[F1][/dim]" in wide
    assert "Help overlay" not in wide
    assert "Help overlay" not in _narrow()


# ---------------------------------------------------------------------------
# KM-H6: no Ctrl+Q, Ctrl+C present
# ---------------------------------------------------------------------------

def test_content_no_ctrl_q():
    assert "Ctrl+Q" not in _wide()
    assert "Ctrl+Q" not in _narrow()


def test_content_ctrl_c_interrupt():
    wide = _wide()
    assert "Ctrl+C" in wide
    assert "Interrupt" in wide


# ---------------------------------------------------------------------------
# KM-M1: Overlays & Modes section
# ---------------------------------------------------------------------------

def test_content_ctrl_b_present():
    assert "Ctrl+B" in _wide()
    assert "Browse" in _wide()


def test_content_f4_present():
    wide = _wide()
    assert "\\[F4][/dim]" in wide
    assert "Workspace" in wide


def test_content_ctrl_j_present():
    assert "Ctrl+J" in _wide()
    assert "Session" in _wide()


# ---------------------------------------------------------------------------
# KM-M2: Pane Layout section
# ---------------------------------------------------------------------------

def test_content_pane_keys_f5_f6_f7():
    wide = _wide()
    assert "\\[F5][/dim]" in wide
    assert "\\[F6][/dim]" in wide
    assert "\\[F7][/dim]" in wide


def test_content_pane_collapse_keys():
    wide = _wide()
    assert "Ctrl+[" in wide
    assert "Ctrl+]" in wide


def test_content_subagent_nav():
    wide = _wide()
    assert "Ctrl+Alt+↑" in wide
    assert "Ctrl+Alt+↓" in wide


# ---------------------------------------------------------------------------
# KM-M3: expanded Tool Panel copy / density / scroll / edit keys
# ---------------------------------------------------------------------------

def test_content_tool_panel_copy_variants():
    wide = _wide()
    assert "\\[Y][/dim]" in wide
    assert "\\[I][/dim]" in wide
    assert "\\[e][/dim]" in wide
    assert "\\[p][/dim]" in wide


def test_content_tool_panel_density():
    wide = _wide()
    assert "\\[D][/dim]" in wide
    assert "Shift+D" in wide


def test_content_tool_panel_scroll_top_end():
    wide = _wide()
    assert "\\[<][/dim]" in wide
    assert "\\[>][/dim]" in wide


def test_content_tool_panel_edit_keys():
    wide = _wide()
    assert "\\[E][/dim]" in wide
    assert "\\[a][/dim]" in wide


# ---------------------------------------------------------------------------
# KM-M4: narrow layout Alt+↑/↓
# ---------------------------------------------------------------------------

def test_narrow_content_alt_arrows():
    narrow = _narrow()
    assert "Alt+↑" in narrow
    assert "Alt+↓" in narrow
