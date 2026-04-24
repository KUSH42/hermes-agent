"""Tests for BrowseMinimap widget.

Covers:
  - Mount on \\ key
  - Unmount on second \\ key
  - render_line returns glyph for anchor at matching Y
  - Blank Strip for empty anchor list
  - Cursor row uses reverse style
  - minimap_default=True auto-mounts on browse enter
  - Handles 0-height OutputPanel gracefully
  - _browse_markers_enabled=False blocks mount
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


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


@pytest.mark.asyncio
async def test_minimap_render_line_glyph_for_anchor():
    """render_line returns correct glyph when anchor Y falls in band."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mm = BrowseMinimap()
        await output.mount(mm)
        await pilot.pause()
        # Set up a synthetic anchor with virtual_region.y = 0
        w = MagicMock()
        region = MagicMock()
        region.y = 0
        w.virtual_region = region
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
        app._browse_anchors = [anchor]
        app._browse_cursor = 0
        strip = mm.render_line(0)
        segments = list(strip)
        text = "".join(s.text for s in segments if s.text.strip())
        # Should be the code_block glyph ‹ (U+2039)
        assert "\u2039" in text


@pytest.mark.asyncio
async def test_minimap_render_line_blank_for_empty_anchors():
    """render_line returns blank Strip when no anchors."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mm = BrowseMinimap()
        await output.mount(mm)
        await pilot.pause()
        app._browse_anchors = []
        strip = mm.render_line(0)
        segments = list(strip)
        text = "".join(s.text for s in segments)
        assert text.strip() == ""


@pytest.mark.asyncio
async def test_minimap_cursor_row_uses_reverse_style():
    """Anchor at cursor position uses reverse style."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from hermes_cli.tui.app import BrowseAnchorType
    from rich.style import Style
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mm = BrowseMinimap()
        await output.mount(mm)
        await pilot.pause()
        w = MagicMock()
        region = MagicMock()
        region.y = 0
        w.virtual_region = region
        anchor = _make_anchor(BrowseAnchorType.TURN_START, w)
        app._browse_anchors = [anchor]
        app._browse_cursor = 0
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


@pytest.mark.asyncio
async def test_minimap_handles_zero_height_output():
    """render_line does not raise when OutputPanel has zero virtual height."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mm = BrowseMinimap()
        await output.mount(mm)
        await pilot.pause()
        w = MagicMock()
        region = MagicMock()
        region.y = 0
        w.virtual_region = region
        app._browse_anchors = [_make_anchor(BrowseAnchorType.CODE_BLOCK, w)]
        # render_line should not raise regardless of virtual size state
        try:
            strip = mm.render_line(0)
        except Exception as e:
            pytest.fail(f"render_line raised unexpectedly: {e}")
        segments = list(strip)
        assert len(segments) >= 1


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
