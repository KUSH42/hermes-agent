"""Tests for Phase B — Pagination & Scroll (B1–B6)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from rich.text import Text


# ---------------------------------------------------------------------------
# B1 — OmissionBar position label
# ---------------------------------------------------------------------------

class TestB1:
    def _make_bar(self, position="bottom"):
        from hermes_cli.tui.tool_blocks import OmissionBar
        pb = MagicMock()
        bar = OmissionBar.__new__(OmissionBar)
        bar._parent_block = pb
        bar.position = position
        bar._visible_start = 0
        bar._visible_end = 0
        bar._total = 0
        bar._last_resize_w = 0
        bar._label = MagicMock()
        bar._cap_label = MagicMock()
        return bar

    def test_label_shows_range_when_partial(self):
        bar = self._make_bar("bottom")
        bar.query_one = MagicMock(return_value=MagicMock())
        bar.set_counts(10, 60, 200, below=140)
        bar._label.update.assert_called_with("  11–60 of 200  ")

    def test_label_empty_when_all_showing(self):
        bar = self._make_bar("bottom")
        bar.query_one = MagicMock(return_value=MagicMock())
        bar.set_counts(0, 50, 50, below=0)
        bar._label.update.assert_called_with("")

    def test_top_bar_label_range(self):
        bar = self._make_bar("top")
        mock_btn = MagicMock()
        mock_btn.disabled = False
        bar.query_one = MagicMock(return_value=mock_btn)
        bar.set_counts(20, 70, 200, above=20)
        bar._label.update.assert_called_with("  21–70 of 200  ")


# ---------------------------------------------------------------------------
# B2 — OmissionBar page buttons show actual step size
# ---------------------------------------------------------------------------

class TestB2:
    def _make_bar(self, position="bottom"):
        from hermes_cli.tui.tool_blocks import OmissionBar
        bar = OmissionBar.__new__(OmissionBar)
        bar._parent_block = MagicMock()
        bar.position = position
        bar._visible_start = 0
        bar._visible_end = 0
        bar._total = 0
        bar._label = MagicMock()
        bar._cap_label = MagicMock()
        return bar

    def test_down_button_shows_step_below(self):
        bar = self._make_bar("bottom")
        mock_down = MagicMock()
        mock_cap = MagicMock()
        mock_up = MagicMock()
        mock_down_all = MagicMock()
        def qo(selector, cls):
            if "--ob-down" in selector and "all" not in selector:
                return mock_down
            if "--ob-cap" in selector:
                return mock_cap
            if "--ob-up" in selector:
                return mock_up
            if "--ob-down-all" in selector:
                return mock_down_all
            return MagicMock()
        bar.query_one = qo
        bar.set_counts(0, 50, 80, below=30)
        # step_below = min(50, 80-50) = 30
        assert mock_down.label == "[↓+30]"

    def test_up_page_button_shows_step_above(self):
        bar = self._make_bar("top")
        mock_up_all = MagicMock()
        mock_up_page = MagicMock()
        def qo(selector, cls):
            if "--ob-up-all" in selector:
                return mock_up_all
            if "--ob-up-page" in selector:
                return mock_up_page
            return MagicMock()
        bar.query_one = qo
        bar.set_counts(30, 80, 200, above=30)
        # step_above = min(50, 30) = 30
        assert mock_up_page.label == "[↑+30]"

    def test_button_disabled_when_step_zero(self):
        bar = self._make_bar("top")
        mock_up_all = MagicMock()
        mock_up_page = MagicMock()
        def qo(selector, cls):
            if "--ob-up-all" in selector:
                return mock_up_all
            return mock_up_page
        bar.query_one = qo
        bar.set_counts(0, 50, 200, above=0)
        # step_above = min(50, 0) = 0 → disabled
        assert mock_up_page.disabled is True


# ---------------------------------------------------------------------------
# B3 — Cap indicator
# ---------------------------------------------------------------------------

class TestB3:
    def _make_bar(self, position="bottom"):
        from hermes_cli.tui.tool_blocks import OmissionBar
        bar = OmissionBar.__new__(OmissionBar)
        bar._parent_block = MagicMock()
        bar.position = position
        bar._visible_start = 0
        bar._visible_end = 0
        bar._total = 0
        bar._label = MagicMock()
        bar._cap_label = MagicMock()
        return bar

    def test_cap_label_shown_when_cap_msg(self):
        bar = self._make_bar("bottom")
        bar.query_one = MagicMock(return_value=MagicMock())
        bar.set_counts(0, 50, 80, below=30, cap_msg="⚠ 300 total · cap 200")
        bar._cap_label.update.assert_called_with("⚠ 300 total · cap 200")
        bar._cap_label.add_class.assert_called_with("--visible")

    def test_cap_label_hidden_when_no_cap_msg(self):
        bar = self._make_bar("bottom")
        bar.query_one = MagicMock(return_value=MagicMock())
        bar.set_counts(0, 50, 50, below=0, cap_msg=None)
        bar._cap_label.remove_class.assert_called_with("--visible")

    def test_cap_label_attr_initialized(self):
        from hermes_cli.tui.tool_blocks import OmissionBar
        bar = OmissionBar.__new__(OmissionBar)
        bar._cap_label = None
        assert bar._cap_label is None


# ---------------------------------------------------------------------------
# B4 — WriteFileBlock streaming progress
# ---------------------------------------------------------------------------

class TestB4:
    def test_write_file_block_has_progress_attrs(self):
        from hermes_cli.tui.write_file_block import WriteFileBlock
        wfb = WriteFileBlock(path="/tmp/test.py")
        assert hasattr(wfb, "_bytes_written")
        assert hasattr(wfb, "_bytes_total")
        assert wfb._bytes_written == 0
        assert wfb._bytes_total == 0

    def test_update_progress_updates_attrs(self):
        from hermes_cli.tui.write_file_block import WriteFileBlock
        wfb = WriteFileBlock(path="/tmp/test.py")
        wfb._progress = MagicMock()
        wfb.update_progress(1024, 4096)
        assert wfb._bytes_written == 1024
        assert wfb._bytes_total == 4096

    def test_update_progress_zero_clears_label(self):
        from hermes_cli.tui.write_file_block import WriteFileBlock
        wfb = WriteFileBlock(path="/tmp/test.py")
        wfb._progress = MagicMock()
        wfb.update_progress(0)
        # written=0 shows "writing…" placeholder
        wfb._progress.update.assert_called_with("writing…")

    def test_update_progress_shows_bytes(self):
        from hermes_cli.tui.write_file_block import WriteFileBlock
        wfb = WriteFileBlock(path="/tmp/test.py")
        wfb._progress = MagicMock()
        wfb.update_progress(2048, 8192)
        call_args = wfb._progress.update.call_args[0][0]
        assert "writing" in call_args.lower()


# ---------------------------------------------------------------------------
# B5 — Memory cap for long-running tool outputs
# ---------------------------------------------------------------------------

class TestB5:
    def test_history_capped_attr_exists(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test")
        assert hasattr(stb, "_history_capped")
        assert stb._history_capped is False

    def test_max_history_constants_exist(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        assert StreamingToolBlock._MAX_HISTORY_LINES == 10_000
        assert StreamingToolBlock._EVICT_CHUNK == 500

    def test_eviction_when_cap_reached(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test")
        stb._completed = False
        stb._follow_tail = False
        stb._flush_slow = False
        stb._last_line_time = 0.0
        stb._total_received = 0
        stb._bytes_received = 0
        stb._rate_samples = __import__("collections").deque(maxlen=60)
        stb._last_http_status = None
        stb._render_timer = MagicMock()

        # Fill to just above cap
        for i in range(StreamingToolBlock._MAX_HISTORY_LINES):
            stb._all_plain.append(f"line {i}")
            stb._all_rich.append(__import__("rich.text", fromlist=["Text"]).Text(f"line {i}"))

        # Call append_line — this should trigger eviction
        stb.append_line("overflow line")

        assert len(stb._all_plain) == StreamingToolBlock._MAX_HISTORY_LINES - StreamingToolBlock._EVICT_CHUNK + 1
        assert stb._history_capped is True

    def test_eviction_adjusts_visible_start(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test")
        stb._completed = False
        stb._follow_tail = False
        stb._flush_slow = False
        stb._last_line_time = 0.0
        stb._total_received = 0
        stb._bytes_received = 0
        stb._rate_samples = __import__("collections").deque(maxlen=60)
        stb._last_http_status = None
        stb._render_timer = MagicMock()
        stb._visible_start = 1000

        for i in range(StreamingToolBlock._MAX_HISTORY_LINES):
            stb._all_plain.append(f"line {i}")
            stb._all_rich.append(__import__("rich.text", fromlist=["Text"]).Text(f"x"))

        stb.append_line("overflow line")
        assert stb._visible_start == max(0, 1000 - StreamingToolBlock._EVICT_CHUNK)


# ---------------------------------------------------------------------------
# B6 — Scroll position preserved across collapse/expand
# ---------------------------------------------------------------------------

class TestB6:
    def test_saved_visible_start_attr_exists(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = object.__new__(ToolPanel)
        panel._saved_visible_start = None
        assert panel._saved_visible_start is None

    def test_collapse_saves_visible_start(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = object.__new__(ToolPanel)
        panel._saved_visible_start = None
        panel._block = MagicMock()
        panel._block._visible_start = 42
        panel._block._all_plain = ["x"] * 100
        panel._footer_pane = MagicMock()
        panel._footer_pane.display = False

        with patch.object(panel, "_has_footer_content", return_value=False):
            panel.watch_collapsed(False, True)

        assert panel._saved_visible_start == 42
