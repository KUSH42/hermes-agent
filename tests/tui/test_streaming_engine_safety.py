"""Streaming engine safety guards — 18 tests.

L2 (5): ANSI orphaned-CSI stripping in feed()
L3 (7): Panel unmount race guard in _mount_code_block()
L4 (6): Emoji mount-count cap in _mount_emoji()

Run with:
    pytest -o "addopts=" tests/tui/test_streaming_engine_safety.py -v
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """ResponseFlowEngine with a fully-mounted mock panel."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    panel = MagicMock()
    panel._msg_id = 1
    panel._prose_blocks = []
    panel.is_mounted = True
    panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    engine = ResponseFlowEngine(panel=panel)
    return engine, panel


def _make_reasoning_engine():
    """ReasoningFlowEngine with a fully-mounted mock panel."""
    from hermes_cli.tui.response_flow import ReasoningFlowEngine

    panel = MagicMock()
    panel.is_mounted = True
    panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    panel.app._reasoning_rich_prose = True
    panel.app._citations_enabled = True
    panel.app._emoji_reasoning = False
    panel.app._emoji_images_enabled = False
    panel.app._emoji_registry = None
    engine = ReasoningFlowEngine(panel=panel)
    return engine, panel


# ---------------------------------------------------------------------------
# TestPartialAnsiGuard — L2 (5 tests)
# ---------------------------------------------------------------------------

class TestPartialAnsiGuard:
    def test_partial_orphaned_csi_stripped_before_route(self):
        engine, _panel = _make_engine()
        routed = []
        engine._route_partial = lambda frag: routed.append(frag)

        engine.feed("[38;2;0;0;0mtext")

        assert len(routed) == 1
        assert "[38;2;0;0;0m" not in routed[0]
        assert "text" in routed[0]

    def test_partial_valid_ansi_not_stripped(self):
        engine, _panel = _make_engine()
        routed = []
        engine._route_partial = lambda frag: routed.append(frag)

        engine.feed("\x1b[32mhello")

        assert len(routed) == 1
        assert routed[0] == "\x1b[32mhello"

    def test_partial_raw_unchanged_after_feed(self):
        engine, _panel = _make_engine()
        engine._route_partial = lambda frag: None

        engine.feed("[38;2;0;0;0mtext")

        # _partial holds raw (un-stripped) accumulated bytes
        assert engine._partial == "[38;2;0;0;0mtext"

    def test_partial_empty_not_routed(self):
        engine, _panel = _make_engine()
        routed = []
        engine._route_partial = lambda frag: routed.append(frag)

        engine.feed("")

        assert routed == []

    def test_partial_no_route_when_clean_is_empty(self):
        """Chunk is purely orphaned CSI with no text — stripped clean is empty."""
        engine, _panel = _make_engine()
        routed = []
        engine._route_partial = lambda frag: routed.append(frag)

        engine.feed("[0m")

        assert routed == []


# ---------------------------------------------------------------------------
# TestPanelUnmountRace — L3 (7 tests)
# ---------------------------------------------------------------------------

class TestPanelUnmountRace:
    def test_mount_code_block_when_panel_mounted(self):
        engine, panel = _make_engine()
        panel.is_mounted = True
        block = MagicMock()

        engine._mount_code_block(block)

        panel._mount_nonprose_block.assert_called_once_with(block)
        assert engine._detached is False

    def test_mount_code_block_skipped_when_panel_unmounted(self):
        engine, panel = _make_engine()
        panel.is_mounted = False
        block = MagicMock()

        engine._mount_code_block(block)

        panel._mount_nonprose_block.assert_not_called()

    def test_detached_sets_on_unmount_guard(self):
        engine, panel = _make_engine()
        panel.is_mounted = False
        block = MagicMock()

        engine._mount_code_block(block)

        assert engine._detached is True

    def test_process_line_noop_when_detached(self):
        engine, panel = _make_engine()
        engine._detached = True

        # Should not raise and should not call any DOM method
        engine.process_line("some text")

        panel._mount_nonprose_block.assert_not_called()

    def test_feed_noop_when_detached(self):
        engine, panel = _make_engine()
        engine._detached = True
        routed = []
        engine._route_partial = lambda frag: routed.append(frag)

        engine.feed("hello")

        assert routed == []

    def test_debug_logged_on_unmount_guard(self):
        engine, panel = _make_engine()
        panel.is_mounted = False
        block = MagicMock()

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            engine._mount_code_block(block)
            mock_log.debug.assert_called_once()
            assert "panel unmounted" in mock_log.debug.call_args[0][0]

    def test_reasoning_engine_mount_code_block_guarded(self):
        engine, panel = _make_reasoning_engine()
        panel.is_mounted = False
        block = MagicMock()

        engine._mount_code_block(block)

        panel.mount.assert_not_called()
        assert engine._detached is True


# ---------------------------------------------------------------------------
# TestEmojiMountCap — L4 (6 tests)
# ---------------------------------------------------------------------------

def _make_emoji_engine_with_registry():
    """Engine wired with a minimal emoji registry mock."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    panel = MagicMock()
    panel.is_mounted = True
    panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    engine = ResponseFlowEngine(panel=panel)

    entry = MagicMock()
    entry.n_frames = 1
    entry.pil_image = None  # no image — skips InlineImage branch

    registry = MagicMock()
    registry.get.return_value = entry
    engine._emoji_registry = registry
    return engine, panel, entry


class TestEmojiMountCap:
    def test_emoji_mount_increments_counter(self):
        engine, panel, _entry = _make_emoji_engine_with_registry()
        # Patch _do_mount path so no real widget mount is attempted
        panel.app._thread_id = threading.get_ident()

        with patch.object(engine, "_has_image_support", return_value=False):
            engine._mount_emoji("smile")

        assert engine._emoji_mounts == 1

    def test_emoji_mount_cap_prevents_excess(self):
        engine, panel, _entry = _make_emoji_engine_with_registry()
        panel.app._thread_id = threading.get_ident()
        engine._emoji_mounts = 0

        with patch.object(engine, "_has_image_support", return_value=False):
            for _ in range(55):
                engine._mount_emoji("smile")

        assert engine._emoji_mounts == 50

    def test_emoji_mount_cap_logs_debug(self):
        engine, panel, _entry = _make_emoji_engine_with_registry()
        panel.app._thread_id = threading.get_ident()
        engine._emoji_mounts = 50  # already at cap

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            with patch.object(engine, "_has_image_support", return_value=False):
                engine._mount_emoji("smile")

            mock_log.debug.assert_called_once()
            assert "cap reached" in mock_log.debug.call_args[0][0]

    def test_emoji_mount_reset_on_flush(self):
        engine, panel, _entry = _make_emoji_engine_with_registry()
        engine._emoji_mounts = 50

        engine.flush()

        assert engine._emoji_mounts == 0

    def test_emoji_mount_cap_constant(self):
        from hermes_cli.tui.response_flow import ResponseFlowEngine

        assert hasattr(ResponseFlowEngine, "_MAX_EMOJI_MOUNTS")
        assert ResponseFlowEngine._MAX_EMOJI_MOUNTS >= 10

    def test_emoji_mount_skipped_no_exception(self):
        engine, panel, _entry = _make_emoji_engine_with_registry()
        panel.app._thread_id = threading.get_ident()
        engine._emoji_mounts = 50  # already at cap

        with patch.object(engine, "_has_image_support", return_value=False):
            # Must not raise
            engine._mount_emoji("smile")
