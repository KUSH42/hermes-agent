"""Tests for BrowseMinimap widget.

Covers:
  - Mount on \\ key
  - Unmount on second \\ key
  - render_line returns glyph for anchor at matching Y (unit)
  - Blank Strip for empty anchor list (unit)
  - Cursor row uses reverse style (unit)
  - minimap_default=True auto-mounts on browse enter
  - Does not raise on default state — MMP-L6 rename (unit)
  - render_line returns blank for zero virtual height — MMP-L6 new (unit)
  - _browse_markers_enabled=False blocks mount
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _make_minimap_unit(anchors=None, cursor=0, vh=24, virtual_h=100):
    """Create a BrowseMinimap with a fully mocked app for sync unit tests."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from textual.geometry import Size
    mm = BrowseMinimap.__new__(BrowseMinimap)
    mm._accent_cached = "#7aa2f7"
    mm._accent_dirty = False
    mm._full_miss_warned = False
    mock_app = MagicMock()
    mock_app._browse_anchors = anchors or []
    mock_app._browse_cursor = cursor
    mock_app.get_css_variables.return_value = {"accent": "#7aa2f7"}
    mock_output = MagicMock()
    type(mock_output).virtual_size = PropertyMock(return_value=Size(1, virtual_h))
    mock_app.query_one.return_value = mock_output
    mock_size = MagicMock()
    mock_size.height = vh
    type(mm).size = PropertyMock(return_value=mock_size)
    type(mm).app = PropertyMock(return_value=mock_app)
    return mm, mock_app


def _make_app(**kwargs):
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.config = {}
    app = HermesApp(cli=cli)
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_anchor(anchor_type, widget=None, label="Test", turn_id=1):
    from hermes_cli.tui.app import BrowseAnchor
    w = widget or MagicMock()
    w.is_mounted = True
    return BrowseAnchor(anchor_type=anchor_type, widget=w, label=label, turn_id=turn_id)


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_minimap_mounts_on_backslash():
    """BrowseMinimap mounts on \\ key press while browse mode active."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from textual.css.query import NoMatches
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        await app.action_toggle_minimap()
        await pilot.pause()
        assert app._browse_minimap is True
        # BrowseMinimap should now be mounted
        try:
            app.query_one(BrowseMinimap)
            found = True
        except NoMatches:
            found = False
        assert found


@pytest.mark.asyncio
async def test_minimap_unmounts_on_second_backslash():
    """Second \\ unmounts BrowseMinimap."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from textual.css.query import NoMatches
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        # First toggle: mount
        await app.action_toggle_minimap()
        await pilot.pause()
        assert app._browse_minimap is True
        # Second toggle: unmount
        await app.action_toggle_minimap()
        await pilot.pause()
        assert app._browse_minimap is False
        try:
            app.query_one(BrowseMinimap)
            found = True
        except NoMatches:
            found = False
        assert not found


def test_minimap_render_line_glyph_for_anchor():
    """render_line returns correct glyph when anchor Y falls in band (unit)."""
    from hermes_cli.tui._browse_types import BrowseAnchorType
    w = MagicMock()
    region = MagicMock()
    region.y = 0
    w.virtual_region = region
    anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
    mm, _ = _make_minimap_unit(anchors=[anchor], cursor=0, vh=24, virtual_h=24)
    strip = mm.render_line(0)
    segments = list(strip)
    text = "".join(s.text for s in segments if s.text.strip())
    # Should be the code_block narrow glyph ‹
    assert "‹" in text


def test_minimap_render_line_blank_for_empty_anchors():
    """render_line returns blank Strip when no anchors (unit)."""
    mm, _ = _make_minimap_unit(anchors=[], cursor=0)
    strip = mm.render_line(0)
    segments = list(strip)
    text = "".join(s.text for s in segments)
    assert text.strip() == ""


def test_minimap_cursor_row_uses_reverse_style():
    """Anchor at cursor position uses reverse style (unit)."""
    from hermes_cli.tui._browse_types import BrowseAnchorType
    from rich.style import Style
    w = MagicMock()
    region = MagicMock()
    region.y = 0
    w.virtual_region = region
    anchor = _make_anchor(BrowseAnchorType.TURN_START, w)
    mm, _ = _make_minimap_unit(anchors=[anchor], cursor=0, vh=24, virtual_h=24)
    strip = mm.render_line(0)
    segments = list(strip)
    has_reverse = any(
        getattr(s.style, "reverse", False) or (
            isinstance(s.style, Style) and s.style.reverse
        )
        for s in segments if s.text.strip()
    )
    assert has_reverse


@pytest.mark.asyncio
async def test_minimap_default_true_auto_mounts():
    """minimap_default=True auto-mounts BrowseMinimap on browse enter."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    app = _make_app(_browse_markers_enabled=True, _browse_minimap_default=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause(0.2)
        # _browse_minimap should become True and BrowseMinimap mounted
        assert app._browse_minimap is True


def test_minimap_does_not_raise_on_default_state():
    """render_line does not raise on default/typical app state (unit)."""
    from hermes_cli.tui._browse_types import BrowseAnchorType
    w = MagicMock()
    region = MagicMock()
    region.y = 0
    w.virtual_region = region
    anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
    mm, _ = _make_minimap_unit(anchors=[anchor], cursor=0)
    try:
        strip = mm.render_line(0)
    except Exception as e:
        pytest.fail(f"render_line raised unexpectedly: {e}")
    segments = list(strip)
    assert len(segments) >= 1


def test_minimap_zero_virtual_height_returns_blank():
    """render_line returns blank when OutputPanel has zero virtual height (unit)."""
    from hermes_cli.tui._browse_types import BrowseAnchorType
    from textual.geometry import Size
    w = MagicMock()
    region = MagicMock()
    region.y = 0
    w.virtual_region = region
    anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
    mm, mock_app = _make_minimap_unit(anchors=[anchor], cursor=0, vh=24, virtual_h=0)
    # The mock output already returns Size(1, 0) — height=0 triggers blank
    strip = mm.render_line(0)
    segments = list(strip)
    text = "".join(s.text for s in segments)
    assert text.strip() == ""


@pytest.mark.asyncio
async def test_minimap_blocked_when_markers_disabled():
    """action_toggle_minimap is no-op when _browse_markers_enabled=False."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from textual.css.query import NoMatches
    app = _make_app(_browse_markers_enabled=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        await app.action_toggle_minimap()
        await pilot.pause()
        # Should NOT have mounted
        try:
            app.query_one(BrowseMinimap)
            found = True
        except NoMatches:
            found = False
        assert not found
        assert app._browse_minimap is False
