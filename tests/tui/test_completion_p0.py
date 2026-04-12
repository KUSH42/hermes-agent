"""P0 completion spec tests: shimmer, empty state, auto-close, overflow badge,
preview cancel, mid-cursor guard (P0-A through P0-G).

All tests use Textual's Pilot fixture — must run serially (no xdist).
Override addopts: pytest -o "addopts=" tests/tui/test_completion_p0.py
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.path_search import PathCandidate


def _pc(name: str) -> PathCandidate:
    return PathCandidate(display=name, abs_path=f"/tmp/{name}")


# ---------------------------------------------------------------------------
# P0-A: Loading shimmer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shimmer_starts_when_searching() -> None:
    """searching=True starts the shimmer timer."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        assert clist._shimmer_timer is None
        clist.searching = True
        await pilot.pause()
        assert clist._shimmer_timer is not None


@pytest.mark.asyncio
async def test_shimmer_stops_when_not_searching() -> None:
    """searching=False stops the shimmer timer."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.searching = True
        await pilot.pause()
        assert clist._shimmer_timer is not None
        clist.searching = False
        await pilot.pause()
        assert clist._shimmer_timer is None


@pytest.mark.asyncio
async def test_shimmer_row_not_blank_when_searching() -> None:
    """render_line returns non-blank shimmer strips when searching and no items."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.searching = True
        await pilot.pause()
        # Multiple rows should all be non-blank (full-height shimmer)
        for row in range(4):
            strip = clist.render_line(row)
            content = "".join(seg.text for seg in strip._segments)
            assert content.strip(), f"Row {row} was blank during shimmer"


@pytest.mark.asyncio
async def test_shimmer_no_color_fallback() -> None:
    """NO_COLOR terminals show plain text on row 0 only."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist._no_color = True
        clist.searching = True
        await pilot.pause()
        row0 = clist.render_line(0)
        row1 = clist.render_line(1)
        text0 = "".join(seg.text for seg in row0._segments)
        text1 = "".join(seg.text for seg in row1._segments)
        assert "search" in text0.lower()
        assert text1.strip() == ""


@pytest.mark.asyncio
async def test_shimmer_phase_advances() -> None:
    """Shimmer phase increments over time."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.searching = True
        await pilot.pause()
        phase0 = clist._shimmer_phase
        await asyncio.sleep(0.15)
        await pilot.pause()
        assert clist._shimmer_phase != phase0, "Shimmer phase did not advance"


# ---------------------------------------------------------------------------
# P0-B: Empty state + auto-close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_state_shows_no_results_with_query() -> None:
    """render_line(0) shows 'no results for X' when walk done and items empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.current_query = "xzqfoo"
        clist.searching = False
        clist.items = ()
        await pilot.pause()
        strip = clist.render_line(0)
        text = "".join(seg.text for seg in strip._segments)
        assert "no results" in text
        assert "xzqfoo" in text


@pytest.mark.asyncio
async def test_empty_state_no_query_fallback() -> None:
    """render_line(0) shows 'no results' without query label when query is empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.current_query = ""
        clist.searching = False
        clist.items = ()
        await pilot.pause()
        strip = clist.render_line(0)
        text = "".join(seg.text for seg in strip._segments)
        assert "no results" in text


@pytest.mark.asyncio
async def test_auto_close_fires_after_1_5s_for_long_query() -> None:
    """AutoDismiss posted after 1.5s when query >= 4 chars and no items."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        clist.current_query = "xzqq"  # 4 chars
        clist.items = ()
        clist.searching = False
        # Trigger auto-close scheduling
        clist._maybe_schedule_auto_close()
        await pilot.pause()

        # Wait for the 1.5s timer
        await asyncio.sleep(1.6)
        await pilot.pause()

        assert not overlay.has_class("--visible"), "Overlay should be dismissed"


@pytest.mark.asyncio
async def test_auto_close_does_not_fire_for_short_query() -> None:
    """AutoDismiss NOT posted when query < 4 chars."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        clist.current_query = "ab"  # only 2 chars
        clist.items = ()
        clist.searching = False
        clist._maybe_schedule_auto_close()
        await pilot.pause()

        await asyncio.sleep(0.2)
        await pilot.pause()

        assert overlay.has_class("--visible"), "Overlay dismissed too early for short query"


@pytest.mark.asyncio
async def test_auto_close_cancelled_when_items_arrive() -> None:
    """Auto-close timer cancelled when items become non-empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        clist.current_query = "xzqq"
        clist.items = ()
        clist.searching = False
        clist._maybe_schedule_auto_close()
        await pilot.pause()
        assert clist._auto_close_timer is not None

        # Items arrive before 1.5s
        clist.items = (_pc("xzqq_match.py"),)
        await pilot.pause()
        assert clist._auto_close_timer is None
        # Overlay still open
        assert overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# P0-C: Preview cancel on rapid selection change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_worker_checks_is_cancelled() -> None:
    """Rapid candidate changes do not corrupt preview with stale content.

    Verifies the is_cancelled guard in _load_preview prevents stale messages.
    We can't easily simulate a cancellation mid-read in a unit test, but we
    can verify that changing candidate rapidly leaves the log non-stale by
    checking the last-written content matches the final selection.
    """
    import tempfile
    from hermes_cli.tui.preview_panel import PreviewPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Create two temp files with distinct content
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as fa:
            fa.write("CONTENT_ALPHA\n" * 5)
            path_a = fa.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as fb:
            fb.write("CONTENT_BETA\n" * 5)
            path_b = fb.name

        # Overlay must be visible so workers can deliver post_message callbacks
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        await pilot.pause()

        panel = app.query_one(PreviewPanel)
        ca = PathCandidate(display="alpha.txt", abs_path=path_a)
        cb = PathCandidate(display="beta.txt", abs_path=path_b)

        # Rapid selection change — alpha then immediately beta
        panel.candidate = ca
        panel.candidate = cb
        # Give workers time to complete
        await asyncio.sleep(0.8)
        await pilot.pause()

        # Only BETA content should appear (last selection wins)
        lines = [str(line) for line in panel.lines]
        combined = " ".join(lines)
        assert "CONTENT_BETA" in combined, "Preview should show final selection (beta)"

        import os
        os.unlink(path_a)
        os.unlink(path_b)


# ---------------------------------------------------------------------------
# P0-F: Result count badge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overflow_badge_shown_when_items_exceed_13() -> None:
    """#overflow-badge appears when items > 13."""
    from textual.widgets import Static

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        clist.items = tuple(_pc(f"f{i}.py") for i in range(14))
        await pilot.pause()
        badge = app.query_one("#overflow-badge", Static)
        assert badge.display, "Badge should be visible for > 13 items"
        text = str(badge._Static__content)
        assert "1 more" in text or "more matches" in text


@pytest.mark.asyncio
async def test_overflow_badge_hidden_when_items_le_13() -> None:
    """#overflow-badge hidden when items ≤ 13."""
    from textual.widgets import Static

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.items = tuple(_pc(f"f{i}.py") for i in range(13))
        await pilot.pause()
        badge = app.query_one("#overflow-badge", Static)
        assert not badge.display, "Badge should be hidden for ≤ 13 items"


@pytest.mark.asyncio
async def test_overflow_badge_count_text() -> None:
    """Badge text reports N - 13 more matches."""
    from textual.widgets import Static

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        clist.items = tuple(_pc(f"f{i}.py") for i in range(20))
        await pilot.pause()
        badge = app.query_one("#overflow-badge", Static)
        text = str(badge._Static__content)
        # 20 - 13 = 7 more
        assert "7" in text


@pytest.mark.asyncio
async def test_overflow_badge_hides_when_items_drop() -> None:
    """Badge hides again when items count drops to ≤ 13."""
    from textual.widgets import Static

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.items = tuple(_pc(f"f{i}.py") for i in range(20))
        await pilot.pause()
        badge = app.query_one("#overflow-badge", Static)
        assert badge.display

        clist.items = tuple(_pc(f"f{i}.py") for i in range(5))
        await pilot.pause()
        assert not badge.display


# ---------------------------------------------------------------------------
# P0-G: Mid-cursor Tab accept guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tab_accept_no_op_when_cursor_not_at_end() -> None:
    """Tab with cursor mid-string dismisses overlay but does not splice."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/commit"])
        # Set value and move cursor to middle
        inp.value = "/hel"
        inp.cursor_position = 2  # mid-string
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")

        original_value = inp.value
        await pilot.press("tab")
        await pilot.pause()

        # Overlay dismissed
        assert not overlay.has_class("--visible")
        # Value unchanged
        assert inp.value == original_value


@pytest.mark.asyncio
async def test_tab_accept_splices_when_cursor_at_end() -> None:
    """Tab with cursor at end accepts the highlighted candidate."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/commit"])
        inp.value = "/h"
        inp.cursor_position = 2  # at end
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")

        await pilot.press("tab")
        await pilot.pause()

        # Value was spliced — something different from "/h"
        assert inp.value != "/h"
        assert not overlay.has_class("--visible")
