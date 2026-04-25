"""Tests for TUI Mechanical Sweep C — Performance Micro-Fixes (PERF-1..PERF-4)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ---------------------------------------------------------------------------
# PERF-1 — Style cache in VirtualCompletionList
# ---------------------------------------------------------------------------


class TestPerf1StyleCache:
    def _make_widget(self):
        from hermes_cli.tui.completion_list import VirtualCompletionList

        return VirtualCompletionList()

    def _make_candidate(self, display="abc", match_spans=()):
        """Non-PathCandidate Candidate — uses the base dataclass (display + match_spans only)."""
        from hermes_cli.tui.path_search import Candidate

        return Candidate(display=display, match_spans=match_spans)

    def _make_path_candidate(self, display="x", insert_text="x.py"):
        from hermes_cli.tui.path_search import PathCandidate

        return PathCandidate(
            display=display, insert_text=insert_text, match_spans=(), abs_path=insert_text
        )

    def test_styles_cached_across_renders(self):
        """Style object identities must be stable across repeated _styled_candidate calls."""
        widget = self._make_widget()

        # Capture ids of the two skin-independent caches.
        id_normal = id(widget._style_text_normal)
        id_selected = id(widget._style_text_selected)

        c = self._make_candidate(display="hello", match_spans=())

        for _ in range(50):
            widget._styled_candidate(c, selected=True)
        for _ in range(50):
            widget._styled_candidate(c, selected=False)

        # Identities must be unchanged — no re-allocation on each call.
        assert id(widget._style_text_normal) == id_normal
        assert id(widget._style_text_selected) == id_selected

        # Now test path suffix style identity via PathCandidate.
        pc = self._make_path_candidate(display="x", insert_text="x.py")
        result = widget._styled_candidate(pc, selected=False)

        # The suffix "  →  x.py" is appended with self._style_path_suffix.
        # Rich Text stores spans as Span(start, end, style); the last span
        # should carry the cached style object by identity.
        spans = result._spans
        assert spans, "Expected at least one span in path candidate result"
        last_span = spans[-1]
        assert last_span.style is widget._style_path_suffix, (
            "Path suffix span must use the cached _style_path_suffix object"
        )

    def test_style_empty_invalidated_on_skin_refresh(self):
        """_style_empty must be rebuilt when _refresh_fuzzy_color() is called."""
        from rich.color import Color

        widget = self._make_widget()
        old_id = id(widget._style_empty)

        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {
            "completion-empty-bg": "#FF0000",
            "fuzzy-match-color": "#FFD866",
            "cursor-selection-bg": "#3A5A8C",
            "path-suffix-color": "#AABBCC",
        }

        with patch.object(type(widget), "app", new_callable=PropertyMock, return_value=mock_app):
            widget._refresh_fuzzy_color()

        # Identity must change — a new Style was constructed.
        assert id(widget._style_empty) != old_id
        # Color must reflect the new value.
        assert widget._style_empty.bgcolor == Color.parse("#FF0000")

    def test_styled_candidate_returns_cached_base_style(self):
        """Non-highlighted candidate rows must use the cached _style_text_normal object."""
        widget = self._make_widget()

        # match_spans = ((1, 2),) so the trailing character "c" falls through
        # the post-loop append at last < len(display).
        c = self._make_candidate(display="abc", match_spans=((1, 2),))
        result = widget._styled_candidate(c, selected=False)

        # Span covering the trailing segment (offset 2 onward) must be the cached object.
        target_spans = [s for s in result._spans if s.style is widget._style_text_normal]
        assert target_spans, (
            "At least one span must use the cached _style_text_normal object for unmatched segments"
        )


# ---------------------------------------------------------------------------
# PERF-2 — Null _stale_timer after stop in ToolsScreen.on_unmount
# ---------------------------------------------------------------------------


class TestPerf2StaleTimerNulled:
    def test_stale_timer_nulled_on_unmount(self):
        """on_unmount must null both _stale_timer and _refresh_timer after stopping them."""
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen = ToolsScreen(snapshot=[])

        mock_stale = MagicMock()
        mock_refresh = MagicMock()
        screen._stale_timer = mock_stale
        screen._refresh_timer = mock_refresh

        # Patch task attrs so the task-cancel loop doesn't blow up.
        screen._rebuild_task = None
        screen._filter_task = None

        screen.on_unmount()

        assert screen._stale_timer is None
        assert screen._refresh_timer is None
        mock_stale.stop.assert_called_once()
        mock_refresh.stop.assert_called_once()


# ---------------------------------------------------------------------------
# PERF-3 — WatchersService.on_compact dedup guard
# ---------------------------------------------------------------------------


class TestPerf3CompactGuard:
    def _make_service(self):
        from hermes_cli.tui.services.watchers import WatchersService
        from textual.css.query import NoMatches

        mock_app = MagicMock()
        # Provide _classes so the CSS-class branch doesn't raise.
        mock_app._classes = set()
        mock_app.add_class = MagicMock()
        mock_app.remove_class = MagicMock()
        mock_app.query = MagicMock(return_value=[])
        # Must raise the real NoMatches so the except NoMatches guard in on_compact catches it.
        mock_app.query_one = MagicMock(side_effect=NoMatches())
        svc = WatchersService(mock_app)
        return svc, mock_app

    def test_on_compact_noop_when_value_unchanged(self):
        """on_compact must short-circuit all DOM ops when value equals _last_compact_value."""
        svc, mock_app = self._make_service()

        # Simulate a prior call that set the cache to True.
        svc._last_compact_value = True

        svc.on_compact(True)

        mock_app.query.assert_not_called()
        mock_app.add_class.assert_not_called()
        mock_app.remove_class.assert_not_called()

    def test_on_compact_first_call_runs_body(self):
        """First call after construction must run the body even when value matches reactive default."""
        svc, mock_app = self._make_service()

        assert svc._last_compact_value is None

        svc.on_compact(False)

        # Cache must be updated.
        assert svc._last_compact_value is False
        # remove_class must have been called (value=False branch).
        mock_app.remove_class.assert_called()


# ---------------------------------------------------------------------------
# PERF-4 — StreamingToolBlock flush-slow timer guard
# ---------------------------------------------------------------------------


class TestPerf4FlushSlowGuard:
    def test_flush_slow_does_not_resurrect_timer_after_unmount(self):
        """_flush_pending must not call set_interval after on_unmount sets _is_unmounted."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        block = StreamingToolBlock(label="test_tool", tool_name="test_tool", tool_input={})

        # Step 1: manually inject timer mocks (bypassing on_mount / event loop).
        mock_timer = MagicMock()
        block._render_timer = mock_timer
        block._spinner_timer = MagicMock()
        block._duration_timer = MagicMock()
        original_timer = block._render_timer

        # Step 2: empty pending list so _flush_pending returns after the slow-trigger block.
        block._pending = []

        # Step 3: patch set_interval before unmounting so any accidental call is captured.
        block.set_interval = MagicMock()

        # Step 4: unmount — sets _is_unmounted = True.
        # on_unmount calls stop() once via the existing try block; reset call count after.
        block.on_unmount()
        assert block._is_unmounted is True
        original_timer.stop.reset_mock()  # isolate: only count calls from _flush_pending below

        # Step 5: drive _flush_pending into the slow-trigger branch.
        block._flush_slow = False
        block._completed = False
        block._last_line_time = time.monotonic() - 10.0

        # Step 6: call _flush_pending.
        block._flush_pending()

        # Step 7: assertions.
        assert block._render_timer is None, "_render_timer must be nulled by the guard"
        block.set_interval.assert_not_called()  # unmount flag must have suppressed reassign
        original_timer.stop.assert_called_once()  # proves PERF-4 guard entered and called stop()
