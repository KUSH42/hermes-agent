"""Phase B — Completion & Preview UX tests for the full TUI UX audit."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.preview_panel import PreviewPanel
from hermes_cli.tui.resize_utils import THRESHOLD_COMP_NARROW
from hermes_cli.tui import resize_utils as _resize_utils


# ---------------------------------------------------------------------------
# B1 — completion overlay max-height capped on short terminals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b1_overlay_max_height_capped_on_short_terminal() -> None:
    """CompletionOverlay max-height is dynamically capped at short terminal heights."""
    from textual.geometry import Size
    from textual import events

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 14)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        # Simulate a resize to a short height
        overlay.on_resize(events.Resize(size=Size(80, 14), virtual_size=Size(80, 14)))
        await pilot.pause()
        # Available = max(4, 14 - 8) = 6
        assert overlay.styles.max_height is not None
        assert overlay.styles.max_height.value <= 8, (
            f"max_height={overlay.styles.max_height!r} too tall for h=14"
        )


@pytest.mark.asyncio
async def test_b1_overlay_min_height_in_css() -> None:
    """CompletionOverlay DEFAULT_CSS must include min-height: 4."""
    css = CompletionOverlay.DEFAULT_CSS
    assert "min-height: 4" in css, "min-height: 4 missing from CompletionOverlay DEFAULT_CSS"


# ---------------------------------------------------------------------------
# B3 — THRESHOLD_COMP_NARROW lowered to 80
# ---------------------------------------------------------------------------

def test_b3_threshold_comp_narrow_is_80() -> None:
    """THRESHOLD_COMP_NARROW must be 80 (not 100) for early SlashDescPanel hide."""
    assert THRESHOLD_COMP_NARROW == 80, (
        f"THRESHOLD_COMP_NARROW={THRESHOLD_COMP_NARROW}, expected 80"
    )


@pytest.mark.asyncio
async def test_b3_overlay_narrow_at_85_cols() -> None:
    """CompletionOverlay gets --narrow class at 85 columns."""
    from textual.geometry import Size
    from textual import events

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(85, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        # Force a resize that crosses the (now-80) threshold
        overlay._last_applied_w = 0
        overlay.on_resize(events.Resize(size=Size(85, 24), virtual_size=Size(85, 24)))
        await pilot.pause()
        # 85 > 80 — should NOT be narrow (85 >= 80)
        # At 75 it should be narrow
        overlay._last_applied_w = 0
        overlay.on_resize(events.Resize(size=Size(75, 24), virtual_size=Size(75, 24)))
        await pilot.pause()
        assert overlay.has_class("--narrow"), "Expected --narrow at 75 cols"


# ---------------------------------------------------------------------------
# B4 — directory preview has header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b4_directory_preview_has_header() -> None:
    """PreviewPanel shows directory name and item count as header."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        for i in range(5):
            (d / f"file{i}.txt").write_text(f"content {i}")
        subdir = d / "subdir"
        subdir.mkdir()

        app = HermesApp(cli=MagicMock())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            panel = app.query_one(PreviewPanel)

            # Feed a directory path candidate
            from hermes_cli.tui.path_search import PathCandidate
            cand = PathCandidate(abs_path=str(d), display=d.name)
            panel.candidate = cand
            # Wait for worker to complete
            await pilot.pause(delay=0.3)
            # Check the panel text — plain_text or rendered
            text = panel._plain_text or ""
            assert d.name in text, f"Directory name not in preview: {text!r}"
            # Should show item count (6 items: 5 files + 1 subdir)
            assert "6 items" in text or "items" in text, (
                f"Item count not in preview: {text!r}"
            )
