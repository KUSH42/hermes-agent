"""Tests for EL-1 through EL-7: error logging sweep across 7 TUI modules."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest


# ── EL-1: _browse_types._is_in_reasoning ──────────────────────────────────────

class TestBrowseTypesIsInReasoning:
    def test_is_in_reasoning_returns_false_on_exception(self):
        from hermes_cli.tui._browse_types import _is_in_reasoning
        widget = MagicMock()
        type(widget).ancestors_with_self = PropertyMock(side_effect=RuntimeError("dom error"))
        with patch("hermes_cli.tui._browse_types.logger") as mock_log:
            result = _is_in_reasoning(widget)
        assert result is False
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_is_in_reasoning_no_log_on_success(self):
        from hermes_cli.tui._browse_types import _is_in_reasoning
        from hermes_cli.tui.widgets import ReasoningPanel
        widget = MagicMock()
        rp = MagicMock(spec=ReasoningPanel)
        type(widget).ancestors_with_self = PropertyMock(return_value=[rp])
        with patch("hermes_cli.tui._browse_types.logger") as mock_log:
            result = _is_in_reasoning(widget)
        assert result is True
        mock_log.debug.assert_not_called()


# ── EL-2: CompletionOverlay handlers ──────────────────────────────────────────

class TestCompletionOverlayHandlers:
    def _make_overlay(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        overlay = CompletionOverlay.__new__(CompletionOverlay)
        overlay._last_applied_w = 0
        return overlay

    def test_on_mount_narrow_exception_logged(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        overlay = self._make_overlay()
        mock_app = MagicMock()
        type(mock_app).size = PropertyMock(side_effect=RuntimeError("no size"))
        with patch.object(type(overlay), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.completion_overlay.logger") as mock_log:
                overlay.on_mount()
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_on_resize_max_height_exception_logged(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        overlay = self._make_overlay()
        overlay._last_applied_w = 80
        mock_styles = MagicMock()
        type(mock_styles).max_height = PropertyMock(side_effect=TypeError("read-only"))
        # styles is on Widget base; patch on the instance via __dict__ trick
        overlay.__dict__["styles"] = mock_styles
        event = MagicMock()
        event.size.width = 80
        event.size.height = 24
        with patch("hermes_cli.tui.completion_overlay.logger") as mock_log:
            overlay.on_resize(event)
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_clear_highlighted_candidate_exception_logged(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        overlay = self._make_overlay()
        mock_app = MagicMock()
        type(mock_app).highlighted_candidate = PropertyMock(side_effect=AttributeError("no attr"))
        with patch.object(type(overlay), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.completion_overlay.logger") as mock_log:
                overlay._clear_highlighted_candidate()
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True


# ── EL-3: HeadlessSession logging ─────────────────────────────────────────────

class TestHeadlessSessionLogging:
    def _make_writer(self, tmp_path):
        from hermes_cli.tui.headless_session import OutputJSONLWriter
        return OutputJSONLWriter(tmp_path / "output.jsonl")

    def test_get_branch_logs_on_failure(self, tmp_path):
        from hermes_cli.tui.headless_session import HeadlessSession
        hs = HeadlessSession.__new__(HeadlessSession)
        hs._session_dir = tmp_path
        with patch("subprocess.run", side_effect=OSError("no git")):
            with patch("hermes_cli.tui.headless_session.logger") as mock_log:
                result = hs._get_branch()
        assert result == ""
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_on_complete_logs_on_notification_failure(self, tmp_path):
        from hermes_cli.tui.headless_session import HeadlessSession
        hs = HeadlessSession.__new__(HeadlessSession)
        hs._session_id = "sess-1"
        hs._session_dir = tmp_path / "sess-1"
        hs._session_dir.mkdir(parents=True, exist_ok=True)

        mock_idx = MagicMock()
        mock_idx.get_active_id.return_value = "other-sess"

        with patch("hermes_cli.tui.session_manager.SessionIndex", return_value=mock_idx):
            with patch("hermes_cli.tui.session_manager.send_notification", side_effect=OSError("socket gone")):
                with patch("hermes_cli.tui.headless_session.logger") as mock_log:
                    hs._on_complete()
        mock_log.warning.assert_called_once()
        _, kwargs = mock_log.warning.call_args
        assert kwargs.get("exc_info") is True

    def test_write_logs_on_oserror(self, tmp_path):
        writer = self._make_writer(tmp_path)
        with patch("builtins.open", side_effect=OSError("disk full")):
            with patch("hermes_cli.tui.headless_session.logger") as mock_log:
                writer.write("hello")
        mock_log.warning.assert_called_once()
        _, kwargs = mock_log.warning.call_args
        assert kwargs.get("exc_info") is True
        # buf still holds the appended entry
        assert len(writer._buf) == 1

    def test_load_lines_logs_on_oserror(self, tmp_path):
        writer = self._make_writer(tmp_path)
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("unreadable")
        writer._path = mock_path
        with patch("hermes_cli.tui.headless_session.logger") as mock_log:
            result = writer.load_lines()
        assert result == []
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True


# ── EL-4: InlineImageCache logging ────────────────────────────────────────────

class TestInlineImageCacheLogging:
    def _make_span(self):
        span = MagicMock()
        span.alt_text = "img.png"
        span.cell_width = 4
        span.cell_height = 2
        return span

    def _make_cache(self):
        from hermes_cli.tui.inline_prose import InlineImageCache
        cache = InlineImageCache.__new__(InlineImageCache)
        cache._entries = {}
        return cache

    def _make_mode(self, cap_name: str):
        """Build a _RenderMode-like object with the given cap."""
        from hermes_cli.tui.kitty_graphics import GraphicsCap
        from hermes_cli.tui.inline_prose import _RenderMode
        cap = getattr(GraphicsCap, cap_name)
        return _RenderMode(cap=cap)

    def test_tgp_render_failure_returns_alt_strips_and_logs(self):
        cache = self._make_cache()
        span = self._make_span()
        mock_img = MagicMock()
        mock_img.mode = "RGBA"
        mock_img.convert.return_value = mock_img
        mock_img.resize.return_value = mock_img

        from hermes_cli.tui.inline_prose import _RenderMode
        from hermes_cli.tui.kitty_graphics import GraphicsCap
        mode = _RenderMode(cap=GraphicsCap.TGP, placeholders=True)

        mock_renderer = MagicMock()
        mock_renderer._alloc_id.return_value = 1
        with patch("hermes_cli.tui.kitty_graphics._load_image", return_value=mock_img):
            with patch("hermes_cli.tui.kitty_graphics._get_renderer", return_value=mock_renderer):
                with patch("hermes_cli.tui.kitty_graphics.transmit_only_sequence", side_effect=RuntimeError("TGP fail")):
                    with patch("hermes_cli.tui.inline_prose.logger") as mock_log:
                        with patch.object(cache, "_alt_strips", return_value=["alt"]):
                            result = cache._render(span, mode)
        assert result == (["alt"], 0)
        mock_log.debug.assert_called()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_halfblock_render_failure_returns_alt_strips_and_logs(self):
        cache = self._make_cache()
        span = self._make_span()
        mock_img = MagicMock()
        mock_img.mode = "RGBA"
        mock_img.convert.return_value = mock_img
        mock_img.resize.return_value = mock_img

        from hermes_cli.tui.inline_prose import _RenderMode
        from hermes_cli.tui.kitty_graphics import GraphicsCap
        mode = _RenderMode(cap=GraphicsCap.HALFBLOCK)

        with patch("hermes_cli.tui.kitty_graphics._load_image", return_value=mock_img):
            with patch("hermes_cli.tui.kitty_graphics.render_halfblock", side_effect=RuntimeError("halfblock fail")):
                with patch("hermes_cli.tui.inline_prose.logger") as mock_log:
                    with patch.object(cache, "_alt_strips", return_value=["alt"]):
                        result = cache._render(span, mode)
        assert result == (["alt"], 0)
        mock_log.debug.assert_called()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_drop_entry_kitty_delete_failure_logged(self):
        cache = self._make_cache()
        key = ("img.png", 4, 2)
        entry = MagicMock()
        entry.image_id = 42
        cache._entries[key] = entry

        mock_stdout = Mock()
        mock_stdout.write = Mock(side_effect=OSError("broken pipe"))
        mock_stdout.flush = Mock()

        with patch.object(sys, "stdout", mock_stdout):
            with patch("hermes_cli.tui.inline_prose.logger") as mock_log:
                cache._drop_entry(key)
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True


# ── EL-5: ContextMenu action failures ─────────────────────────────────────────

class TestContextMenuActionFailure:
    def _make_menu(self):
        from hermes_cli.tui.context_menu import ContextMenu
        menu = ContextMenu.__new__(ContextMenu)
        menu._selected_index = -1
        menu._prev_focus = None
        menu._classes = set()  # DOMNode.__init__ sets this; __new__ skips it
        return menu

    def _make_item_widget(self, action_fn, label="Copy"):
        from hermes_cli.tui.context_menu import _ContextItem, MenuItem
        mi = MenuItem(label=label, shortcut="", action=action_fn)
        item = _ContextItem.__new__(_ContextItem)
        item._item = mi
        return item

    def test_on_click_action_failure_logs_exception(self):
        from hermes_cli.tui.context_menu import ContextMenu
        item = self._make_item_widget(action_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        mock_app = MagicMock()
        mock_app.query_one.side_effect = lambda q: MagicMock() if q == ContextMenu else MagicMock()

        with patch.object(type(item), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.context_menu.logger") as mock_log:
                item.on_click()
        mock_log.exception.assert_called_once()
        call_args = mock_log.exception.call_args[0]
        assert "Copy" in str(call_args)

    def test_on_click_action_failure_notifies_user(self):
        from hermes_cli.tui.context_menu import ContextMenu
        item = self._make_item_widget(action_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        mock_app = MagicMock()

        with patch.object(type(item), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.context_menu.logger"):
                item.on_click()
        mock_app.notify.assert_called_once()
        _, kwargs = mock_app.notify.call_args
        assert kwargs.get("severity") == "error"

    def test_execute_selected_action_failure_logs_exception(self):
        from hermes_cli.tui.context_menu import _ContextItem, MenuItem
        menu = self._make_menu()
        mi = MenuItem(label="Open", shortcut="", action=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        item_widget = MagicMock(spec=_ContextItem)
        item_widget._item = mi
        menu._selected_index = 0

        mock_app = MagicMock()
        with patch.object(type(menu), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch.object(menu, "_items", return_value=[item_widget]):
                with patch.object(menu, "dismiss"):
                    with patch("hermes_cli.tui.context_menu.logger") as mock_log:
                        menu.action_execute_selected()
        mock_log.exception.assert_called_once()
        call_args = mock_log.exception.call_args[0]
        assert "Open" in str(call_args)

    def test_execute_selected_action_failure_still_dismisses(self):
        from hermes_cli.tui.context_menu import _ContextItem, MenuItem
        menu = self._make_menu()
        mi = MenuItem(label="Open", shortcut="", action=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        item_widget = MagicMock(spec=_ContextItem)
        item_widget._item = mi
        menu._selected_index = 0

        mock_app = MagicMock()
        with patch.object(type(menu), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch.object(menu, "_items", return_value=[item_widget]):
                with patch.object(menu, "dismiss") as mock_dismiss:
                    with patch("hermes_cli.tui.context_menu.logger"):
                        menu.action_execute_selected()
        mock_dismiss.assert_called_once()

    def test_focus_restore_failure_logged_debug(self):
        from hermes_cli.tui.context_menu import ContextMenu, NoMatches
        item = self._make_item_widget(action_fn=lambda: None)

        mock_menu = MagicMock()
        mock_menu._prev_focus = None

        def query_one_side_effect(q):
            if q == ContextMenu:
                return mock_menu
            raise NoMatches()

        mock_app = MagicMock()
        mock_app.query_one.side_effect = query_one_side_effect

        with patch.object(type(item), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.context_menu.logger") as mock_log:
                item.on_click()
        mock_log.debug.assert_called()
        debug_msgs = [str(call) for call in mock_log.debug.call_args_list]
        assert any("focus" in m.lower() for m in debug_msgs)

    def test_action_dismiss_focus_restore_failure_logged(self):
        from hermes_cli.tui.context_menu import ContextMenu, NoMatches
        menu = self._make_menu()

        mock_app = MagicMock()
        mock_app.focused = menu  # so `app.focused is self` is True
        mock_app.query_one.side_effect = NoMatches()

        with patch.object(type(menu), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.context_menu.logger") as mock_log:
                menu.dismiss()
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True


# ── EL-6: media_player logging ────────────────────────────────────────────────

class TestMediaPlayerLogging:
    def test_resolve_youtube_url_logs_on_subprocess_failure(self):
        from hermes_cli.tui.media_player import _resolve_youtube_url
        with patch("hermes_cli.tui.media_player.shutil.which", return_value="/usr/bin/yt-dlp"):
            with patch(
                "hermes_cli.tui.media_player.subprocess.run",
                side_effect=subprocess.TimeoutExpired("yt-dlp", 20),
            ):
                with patch("hermes_cli.tui.media_player.logger") as mock_log:
                    result = _resolve_youtube_url("https://youtu.be/test123")
        assert result is None
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args
        assert "test123" in str(call_args)
        assert call_args.kwargs.get("exc_info") is True

    def test_resolve_youtube_url_logs_on_generic_exception(self):
        from hermes_cli.tui.media_player import _resolve_youtube_url
        with patch("hermes_cli.tui.media_player.shutil.which", return_value="/usr/bin/yt-dlp"):
            with patch(
                "hermes_cli.tui.media_player.subprocess.run",
                side_effect=RuntimeError("network gone"),
            ):
                with patch("hermes_cli.tui.media_player.logger") as mock_log:
                    result = _resolve_youtube_url("https://youtu.be/abc")
        assert result is None
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs.get("exc_info") is True

    def test_inline_media_config_logs_on_read_failure(self):
        from hermes_cli.tui.media_player import InlineMediaCfg, _inline_media_config
        with patch("hermes_cli.tui.media_player.logger") as mock_log:
            with patch("hermes_cli.config.read_raw_config", side_effect=RuntimeError("cfg error")):
                cfg = _inline_media_config()
        assert isinstance(cfg, InlineMediaCfg)
        # Defaults
        assert cfg.enabled is False
        assert cfg.audio is True
        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs.get("exc_info") is True


# ── EL-7: SDFBaker logging ────────────────────────────────────────────────────

class TestSDFBakerLogging:
    def _make_baker(self):
        from hermes_cli.tui.sdf_morph import SDFBaker
        return SDFBaker(resolution=32, font_size=24, timeout_s=5.0)

    def test_sdf_baker_bake_sets_failed_on_exception(self):
        baker = self._make_baker()
        with patch.object(baker, "_bake_char", side_effect=RuntimeError("font error")):
            with patch("hermes_cli.tui.sdf_morph.logger"):
                baker.bake(["A"])
        assert baker.failed.is_set()

    def test_sdf_baker_bake_logs_on_exception(self):
        baker = self._make_baker()
        with patch.object(baker, "_bake_char", side_effect=RuntimeError("font error")):
            with patch("hermes_cli.tui.sdf_morph.logger") as mock_log:
                baker.bake(["A"])
        mock_log.warning.assert_called_once()
        _, kwargs = mock_log.warning.call_args
        assert kwargs.get("exc_info") is True

    def test_sdf_baker_bake_does_not_propagate(self):
        baker = self._make_baker()
        with patch.object(baker, "_bake_char", side_effect=RuntimeError("font error")):
            with patch("hermes_cli.tui.sdf_morph.logger"):
                try:
                    baker.bake(["A"])
                except Exception as exc:
                    pytest.fail(f"bake() propagated exception: {exc}")
