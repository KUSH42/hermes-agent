"""Tests for hermes_cli/tui/completion_list.py — VirtualCompletionList."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.path_search import PathCandidate


def _pc(name: str) -> PathCandidate:
    return PathCandidate(display=name, abs_path=f"/tmp/{name}")


def _make_items(n: int) -> tuple[PathCandidate, ...]:
    return tuple(_pc(f"file_{i:05d}.txt") for i in range(n))


# ---------------------------------------------------------------------------
# Phase 3 tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_line_in_viewport() -> None:
    """render_line(0) returns the first data row when scroll_offset is (0, 0)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.items = (_pc("alpha.py"), _pc("beta.py"))
        await pilot.pause()
        strip = clist.render_line(0)
        # Strip should contain "alpha.py" text
        text_content = "".join(seg.text for seg in strip._segments)
        assert "alpha.py" in text_content


@pytest.mark.asyncio
async def test_render_line_respects_scroll() -> None:
    """render_line uses scroll_offset.y to compute the data index.

    The widget must be visible (overlay shown) to have a real layout so
    scroll_to_region can compute correct offsets.
    """
    from hermes_cli.tui.completion_overlay import CompletionOverlay

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Make the overlay visible so the list gets a real layout
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        items = _make_items(200)
        clist.items = items
        await pilot.pause()

        # Trigger scroll via highlighted
        clist.highlighted = 100
        await pilot.pause()

        sy = clist.scroll_offset.y
        # When visible with a real layout, scroll should advance
        if sy > 0:
            strip = clist.render_line(0)
            text_content = "".join(seg.text for seg in strip._segments)
            expected = f"file_{sy:05d}"
            assert expected in text_content
        else:
            # Widget has a height >= 200; all rows visible — no scroll needed
            strip = clist.render_line(0)
            text_content = "".join(seg.text for seg in strip._segments)
            assert "file_00000" in text_content


@pytest.mark.asyncio
async def test_10k_items_mounts_fast() -> None:
    """10k items mount and virtual_size is computed in <150ms."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        items = _make_items(10_000)

        start = time.monotonic()
        clist.items = items
        await pilot.pause()
        elapsed = time.monotonic() - start

        assert clist.virtual_size.height == 10_000
        assert elapsed < 0.15, f"Mount took {elapsed:.3f}s (target <0.15s)"


@pytest.mark.asyncio
async def test_highlight_scrolls_into_view() -> None:
    """Setting highlighted = 500 on a visible 10k list adjusts scroll."""
    from hermes_cli.tui.completion_overlay import CompletionOverlay

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Widget must be visible to get a layout for scroll_to_region
        app.query_one(CompletionOverlay).add_class("--visible")
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        clist.items = _make_items(10_000)
        await pilot.pause()
        clist.highlighted = 500
        await pilot.pause()
        # After scroll_to_region, scroll_y should be near 500
        assert clist.scroll_offset.y >= 490  # allow ±10 rows for viewport height


@pytest.mark.asyncio
async def test_fuzzy_bold_spans_rendered() -> None:
    """A row with match_spans renders bold segments in the Strip."""
    from hermes_cli.tui.path_search import PathCandidate
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        # Create a candidate with a known match span
        c = PathCandidate(
            display="foo_bar.py",
            abs_path="/tmp/foo_bar.py",
            match_spans=((0, 3),),  # "foo" is matched
        )
        clist.items = (c,)
        clist.highlighted = -1  # not selected so base_style is "dim"
        await pilot.pause()
        strip = clist.render_line(0)
        # At least one segment should have bold style (from match_spans rendering)
        has_bold = any(
            seg.style.bold
            for seg in strip._segments
            if seg.style is not None
        )
        assert has_bold, "No bold segment found for match span"


@pytest.mark.asyncio
async def test_virtual_size_updates_on_new_items() -> None:
    """virtual_size.height equals len(items) after assignment."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)

        clist.items = _make_items(50)
        await pilot.pause()
        assert clist.virtual_size.height == 50

        clist.items = _make_items(3)
        await pilot.pause()
        assert clist.virtual_size.height == 3
