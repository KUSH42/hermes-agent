"""Tests for VFD-D1 — OutputPanel viewport underfill diagnostic."""
import pytest
from unittest.mock import MagicMock, patch
from hermes_cli.tui.widgets.output_panel import OutputPanel, ScrollState


class TestUnderfillDiagnostic:
    _MODULE = "hermes_cli.tui.widgets.output_panel"

    def _make_panel(self, scroll_state=ScrollState.ANCHORED, viewport_h=50):
        """Return an OutputPanel stub with minimal fakes for _check_underfill.

        Approach:
        - Create a fresh subclass per call so we can override `size` (read-only
          property on Textual Widget) without mutating the shared OutputPanel class.
        - Set _id + _reactive_scroll_state directly to satisfy the reactive
          descriptor without going through super().__init__().
        """
        size_mock = MagicMock()
        size_mock.height = viewport_h

        class _Stub(OutputPanel):
            @property
            def size(self_):  # noqa: N805
                return size_mock

        panel = object.__new__(_Stub)
        panel._id = "test-output-panel"
        panel._reactive_scroll_state = scroll_state
        panel._last_resize_geom = (80, viewport_h)
        panel._underfill_logged_for_geom = None
        return panel

    def _make_message_panel(self, height: int):
        mp = MagicMock()
        mp.region = MagicMock()
        mp.region.height = height
        return mp

    def test_underfill_logs_on_short_content(self, caplog):
        panel = self._make_panel(scroll_state=ScrollState.ANCHORED, viewport_h=50)
        mp = self._make_message_panel(5)
        with patch.object(panel, "query", return_value=[mp]):
            with caplog.at_level("WARNING", logger=self._MODULE):
                panel._check_underfill()
        assert any("viewport underfill" in r.message for r in caplog.records)

    def test_underfill_quiet_when_full(self, caplog):
        panel = self._make_panel(scroll_state=ScrollState.ANCHORED, viewport_h=50)
        mp = self._make_message_panel(40)
        with patch.object(panel, "query", return_value=[mp]):
            with caplog.at_level("WARNING", logger=self._MODULE):
                panel._check_underfill()
        assert not any("viewport underfill" in r.message for r in caplog.records)

    def test_underfill_quiet_when_pinned(self, caplog):
        panel = self._make_panel(scroll_state=ScrollState.PINNED, viewport_h=50)
        mp = self._make_message_panel(5)
        with patch.object(panel, "query", return_value=[mp]):
            with caplog.at_level("WARNING", logger=self._MODULE):
                panel._check_underfill()
        assert not any("viewport underfill" in r.message for r in caplog.records)

    def test_underfill_dedup_per_geom(self, caplog):
        panel = self._make_panel(scroll_state=ScrollState.ANCHORED, viewport_h=50)
        mp = self._make_message_panel(5)
        with patch.object(panel, "query", return_value=[mp]):
            with caplog.at_level("WARNING", logger=self._MODULE):
                panel._check_underfill()
                panel._check_underfill()  # same geom key — must not re-log
        underfill_logs = [r for r in caplog.records if "viewport underfill" in r.message]
        assert len(underfill_logs) == 1

        # Changing geom key → fires again
        panel._last_resize_geom = (80, 60)
        panel.size.height = 60
        with patch.object(panel, "query", return_value=[mp]):
            with caplog.at_level("WARNING", logger=self._MODULE):
                panel._check_underfill()
        underfill_logs2 = [r for r in caplog.records if "viewport underfill" in r.message]
        assert len(underfill_logs2) == 2
