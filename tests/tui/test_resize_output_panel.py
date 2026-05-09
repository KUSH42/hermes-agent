"""SPEC: Resize — OutputPanel & RichLog Hardening (RZ-OP-H2/H3/L3/L4/L7).

TestResolveLayoutGate       — 6 tests  (H2: gate _resolve_layout on geom change)
TestWidthCaptureSwallow     — 4 tests  (H3: replace bare swallows with logged paths)
TestWidthReadyFallback      — 3 tests  (L3: 2s deadline fallback for WIDTH_READY)
TestClearThinkingReserveLog — 2 tests  (L4: log _clear_thinking_reserve swallow)
TestRichLogWidthGuard       — 4 tests  (L7: guard CopyableRichLog._render_width on zero)

Total: 19 tests
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared fixture: reset OUTPUT_PANEL_WIDTH_READY between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_width_event():
    from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
    OUTPUT_PANEL_WIDTH_READY.clear()
    yield
    OUTPUT_PANEL_WIDTH_READY.clear()


# ---------------------------------------------------------------------------
# Duck-typed stub that satisfies OutputPanel.on_resize / on_mount
# without touching Textual reactive machinery.
# ---------------------------------------------------------------------------

class _PanelStub:
    """Minimal duck-type for OutputPanel method injection."""

    def __init__(self):
        self._last_resize_geom: tuple[int, int] = (-1, -1)
        self._user_scrolled_up: bool = False
        self.scroll_y: int = 0
        self.virtual_size = types.SimpleNamespace(height=0)
        self.app = MagicMock()
        self.app._startup_output_panel_width = None
        # DOM stubs
        self.query = MagicMock(return_value=[])
        self.call_after_refresh = MagicMock()
        self.scroll_end = MagicMock()
        self.set_timer = MagicMock()
        # size property — overridable
        self._size_width: int = 0
        self._size_raise: bool = False

    def _force_width_ready_fallback(self) -> None:
        """Stub — so set_timer(2.0, self._force_width_ready_fallback) works."""

    @property
    def size(self):
        if self._size_raise:
            raise RuntimeError("no size")
        return types.SimpleNamespace(width=self._size_width)

    def _resolve_layout(self):
        """Will be patched in tests."""

    def _live_anchor(self):
        return None

    def mount(self, *args, **kwargs):
        pass


def _call_on_resize(stub, width, height):
    """Call OutputPanel.on_resize on stub with a fake event."""
    from hermes_cli.tui.widgets.output_panel import OutputPanel
    event = types.SimpleNamespace(size=types.SimpleNamespace(width=width, height=height))
    OutputPanel.on_resize(stub, event)


def _call_on_mount(stub):
    """Call OutputPanel.on_mount on stub."""
    from hermes_cli.tui.widgets.output_panel import OutputPanel
    OutputPanel.on_mount(stub)


# ---------------------------------------------------------------------------
# TestResolveLayoutGate (H2)
# ---------------------------------------------------------------------------

class TestResolveLayoutGate:
    """_resolve_layout is gated on geometry change."""

    def test_first_resize_runs_resolve_layout(self):
        """Fresh stub: first Resize(100,30) must call _resolve_layout exactly once."""
        stub = _PanelStub()
        with patch.object(stub, "_resolve_layout") as mock_rl:
            _call_on_resize(stub, 100, 30)
        mock_rl.assert_called_once()

    def test_identical_resize_skips_resolve_layout(self):
        """Firing the same geometry twice must call _resolve_layout only once."""
        stub = _PanelStub()
        with patch.object(stub, "_resolve_layout") as mock_rl:
            _call_on_resize(stub, 100, 30)
            _call_on_resize(stub, 100, 30)
        assert mock_rl.call_count == 1

    def test_height_change_runs_resolve_layout(self):
        """(100,30) → (100,25): height changed so _resolve_layout must run twice."""
        stub = _PanelStub()
        with patch.object(stub, "_resolve_layout") as mock_rl:
            _call_on_resize(stub, 100, 30)
            _call_on_resize(stub, 100, 25)
        assert mock_rl.call_count == 2

    def test_width_change_runs_resolve_layout(self):
        """(100,30) → (80,30): width changed so _resolve_layout must run twice."""
        stub = _PanelStub()
        with patch.object(stub, "_resolve_layout") as mock_rl:
            _call_on_resize(stub, 100, 30)
            _call_on_resize(stub, 80, 30)
        assert mock_rl.call_count == 2

    def test_scroll_anchor_skipped_when_no_message_panel(self):
        """When query(MessagePanel) returns [], call_after_refresh is not called."""
        stub = _PanelStub()
        stub.query.return_value = []
        with patch.object(stub, "_resolve_layout"):
            _call_on_resize(stub, 100, 30)
            _call_on_resize(stub, 100, 30)  # identical — no _resolve_layout
        # scroll_end should NOT be called since there are no MessagePanels
        stub.call_after_refresh.assert_not_called()

    def test_geom_cache_updated_after_run(self):
        """After firing Resize(100,30), _last_resize_geom must be (100,30)."""
        stub = _PanelStub()
        with patch.object(stub, "_resolve_layout"):
            _call_on_resize(stub, 100, 30)
        assert stub._last_resize_geom == (100, 30)


# ---------------------------------------------------------------------------
# TestWidthCaptureSwallow (H3)
# ---------------------------------------------------------------------------

class TestWidthCaptureSwallow:
    """Bare swallows on width-capture path replaced with logged paths."""

    def test_on_resize_width_capture_logs_on_failure(self, caplog):
        """If size.width raises, on_resize must log WARNING with exc_info."""
        import logging
        stub = _PanelStub()
        stub._size_raise = True  # size.width will raise

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.output_panel"), \
             patch.object(stub, "_resolve_layout"):
            _call_on_resize(stub, 0, 0)

        assert any(
            "size.width unavailable" in r.message and r.exc_info
            for r in caplog.records
        ), f"Expected WARNING with exc_info; got: {[r.message for r in caplog.records]}"

    def test_on_resize_width_capture_does_not_set_event_on_zero(self):
        """If size.width == 0, OUTPUT_PANEL_WIDTH_READY must remain unset."""
        from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
        stub = _PanelStub()
        stub._size_width = 0

        with patch.object(stub, "_resolve_layout"):
            _call_on_resize(stub, 0, 30)

        assert not OUTPUT_PANEL_WIDTH_READY.is_set()

    def test_on_resize_width_capture_sets_event_on_positive(self):
        """If size.width == 100, event is set and _startup_output_panel_width == 99."""
        from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
        stub = _PanelStub()
        stub._size_width = 100

        with patch.object(stub, "_resolve_layout"):
            _call_on_resize(stub, 100, 30)

        assert OUTPUT_PANEL_WIDTH_READY.is_set()
        assert stub.app._startup_output_panel_width == 99

    def test_on_mount_width_capture_logs_on_failure(self, caplog):
        """If size.width raises in on_mount, WARNING with exc_info must be logged."""
        import logging
        stub = _PanelStub()
        stub._size_raise = True  # size.width will raise

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.output_panel"):
            _call_on_mount(stub)

        assert any(
            "size.width unavailable" in r.message and r.exc_info
            for r in caplog.records
        ), f"Expected WARNING with exc_info in on_mount; got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# TestWidthReadyFallback (L3)
# ---------------------------------------------------------------------------

class TestWidthReadyFallback:
    """2-second deadline fallback sets OUTPUT_PANEL_WIDTH_READY if no resize delivered width>0."""

    def test_fallback_fires_when_resize_never_set(self, caplog):
        """Calling _force_width_ready_fallback when event unset must set it + log WARNING."""
        import logging
        from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
        from hermes_cli.tui.widgets.output_panel import OutputPanel
        stub = _PanelStub()
        stub.app._startup_output_panel_width = None

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.output_panel"):
            OutputPanel._force_width_ready_fallback(stub)

        assert OUTPUT_PANEL_WIDTH_READY.is_set()
        assert any("WIDTH_READY fallback fired" in r.message for r in caplog.records)

    def test_fallback_does_not_fire_when_resize_set_normally(self, caplog):
        """If OUTPUT_PANEL_WIDTH_READY is already set, fallback must be a no-op."""
        import logging
        from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
        from hermes_cli.tui.widgets.output_panel import OutputPanel
        OUTPUT_PANEL_WIDTH_READY.set()
        stub = _PanelStub()
        stub.app._startup_output_panel_width = 99

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.output_panel"):
            OutputPanel._force_width_ready_fallback(stub)

        assert not any("fallback" in r.message for r in caplog.records)
        assert stub.app._startup_output_panel_width == 99

    def test_fallback_does_not_overwrite_existing_positive_width(self, caplog):
        """If _startup_output_panel_width is already truthy (50), fallback must not overwrite it."""
        import logging
        from hermes_cli.tui.widgets.output_panel import OutputPanel
        stub = _PanelStub()
        stub.app._startup_output_panel_width = 50  # truthy → guard fires

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.output_panel"):
            OutputPanel._force_width_ready_fallback(stub)

        assert stub.app._startup_output_panel_width == 50
        from hermes_cli.tui.widgets._events import OUTPUT_PANEL_WIDTH_READY
        assert OUTPUT_PANEL_WIDTH_READY.is_set()


# ---------------------------------------------------------------------------
# TestClearThinkingReserveLog (L4)
# ---------------------------------------------------------------------------

class TestClearThinkingReserveLog:
    """_clear_thinking_reserve logs on failure, silent on success."""

    def test_clear_reserve_logs_on_failure(self, caplog):
        """If clear_reserve raises, DEBUG log with exc_info must be emitted."""
        import logging
        from hermes_cli.tui.widgets.output_panel import _clear_thinking_reserve

        tw = MagicMock()
        tw.clear_reserve.side_effect = RuntimeError("widget unmounted")

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.output_panel"):
            _clear_thinking_reserve(tw)

        assert any(
            "clear_thinking_reserve" in r.message and r.exc_info
            for r in caplog.records
        )

    def test_clear_reserve_silent_on_success(self, caplog):
        """If clear_reserve succeeds, it must be called once and no DEBUG log emitted."""
        import logging
        from hermes_cli.tui.widgets.output_panel import _clear_thinking_reserve

        tw = MagicMock()

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.output_panel"):
            _clear_thinking_reserve(tw)

        tw.clear_reserve.assert_called_once()
        assert not any("clear_thinking_reserve" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TestRichLogWidthGuard (L7)
# ---------------------------------------------------------------------------

class TestRichLogWidthGuard:
    """CopyableRichLog._render_width is only updated when event.size.width > 0."""

    def _make_crl(self):
        """Minimal CopyableRichLog stub (no Textual DOM needed)."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        obj = object.__new__(CopyableRichLog)
        obj._render_width = None
        return obj

    def _resize_event(self, width: int, height: int = 24):
        return types.SimpleNamespace(size=types.SimpleNamespace(width=width, height=height))

    def test_render_width_updated_on_positive(self):
        """Resize(80, 24) must set _render_width to 80."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        obj = self._make_crl()
        CopyableRichLog.on_resize(obj, self._resize_event(80))
        assert obj._render_width == 80

    def test_render_width_preserved_on_zero(self, caplog):
        """If event.size.width == 0, _render_width must not change and DEBUG must be logged."""
        import logging
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        obj = self._make_crl()
        obj._render_width = 80

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.renderers"):
            CopyableRichLog.on_resize(obj, self._resize_event(0))

        assert obj._render_width == 80
        assert any("event.size.width == 0" in r.message for r in caplog.records)

    def test_render_width_initial_state(self):
        """Freshly stubbed CopyableRichLog has _render_width of None."""
        obj = self._make_crl()
        assert obj._render_width is None

    def test_render_width_handles_zero_then_positive(self):
        """(0,24) then (100,24): final _render_width must be 100."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        obj = self._make_crl()
        CopyableRichLog.on_resize(obj, self._resize_event(0))
        CopyableRichLog.on_resize(obj, self._resize_event(100))
        assert obj._render_width == 100
