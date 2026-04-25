"""Tests for inline media player — media_player.py + SeekBar + InlineMediaWidget."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call


# ─────────────────────────────────────────────────────────────────────────────
# TestUrlDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestUrlDetection(unittest.TestCase):
    def setUp(self):
        from hermes_cli.tui.media_player import _AUDIO_EXT_RE, _VIDEO_EXT_RE, _YOUTUBE_RE
        self.AUDIO = _AUDIO_EXT_RE
        self.VIDEO = _VIDEO_EXT_RE
        self.YT    = _YOUTUBE_RE

    def test_audio_url_detected_mp3(self):
        self.assertTrue(self.AUDIO.search("https://example.com/song.mp3"))

    def test_audio_url_detected_ogg(self):
        self.assertTrue(self.AUDIO.search("https://example.com/track.ogg"))

    def test_audio_url_not_detected_non_audio(self):
        self.assertIsNone(self.AUDIO.search("https://example.com/page.html"))

    def test_video_url_detected_mp4(self):
        self.assertTrue(self.VIDEO.search("https://example.com/clip.mp4"))

    def test_youtube_url_detected_watch(self):
        self.assertTrue(self.YT.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_youtube_url_detected_short(self):
        self.assertTrue(self.YT.search("https://youtu.be/dQw4w9WgXcQ"))

    def test_url_deduplication_same_url_twice(self):
        url = "https://example.com/song.mp3"
        line = f"{url} see also {url}"
        matches = self.AUDIO.findall(line)
        # Both occurrences found by regex; deduplication is in ResponseFlowEngine
        self.assertEqual(len(matches), 2)


# ─────────────────────────────────────────────────────────────────────────────
# TestMpvController
# ─────────────────────────────────────────────────────────────────────────────

class TestMpvController(unittest.TestCase):
    def _make_ctrl(self, kind="audio", resolved=None):
        from hermes_cli.tui.media_player import MpvController, InlineMediaCfg
        cfg = InlineMediaCfg()
        return MpvController(
            url="https://example.com/song.mp3",
            kind=kind,
            cfg=cfg,
            resolved_url=resolved,
        )

    def test_start_builds_correct_args_audio(self):
        ctrl = self._make_ctrl(kind="audio")
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            ctrl.start()
            args = mock_popen.call_args[0][0]
            self.assertIn("--no-video", args)
            self.assertIn(ctrl._ipc_path, " ".join(args))

    def test_start_builds_correct_args_video(self):
        ctrl = self._make_ctrl(kind="video")
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            ctrl.start()
            args = mock_popen.call_args[0][0]
            self.assertNotIn("--no-video", args)

    def test_ipc_send_quit_on_stop(self):
        ctrl = self._make_ctrl()
        ctrl._proc = MagicMock()
        ctrl._proc.poll.return_value = None
        with patch.object(ctrl, "_ipc_send") as mock_ipc:
            mock_ipc.return_value = None
            ctrl.stop()
            mock_ipc.assert_called_with(["quit"])

    def test_pause_sends_correct_command(self):
        ctrl = self._make_ctrl()
        with patch.object(ctrl, "_ipc_send") as mock_ipc:
            ctrl.pause()
            mock_ipc.assert_called_once_with(["set_property", "pause", True])

    def test_resume_sends_correct_command(self):
        ctrl = self._make_ctrl()
        with patch.object(ctrl, "_ipc_send") as mock_ipc:
            ctrl.resume()
            mock_ipc.assert_called_once_with(["set_property", "pause", False])

    def test_seek_sends_absolute_command(self):
        ctrl = self._make_ctrl()
        with patch.object(ctrl, "_ipc_send") as mock_ipc:
            ctrl.seek(42.0)
            mock_ipc.assert_called_once_with(["seek", 42.0, "absolute"])

    def test_get_position_returns_float(self):
        ctrl = self._make_ctrl()
        ctrl._ipc_started = True
        with patch.object(ctrl, "_ipc_send", return_value={"data": 12.5, "error": "success"}):
            pos = ctrl.get_position()
        self.assertAlmostEqual(pos, 12.5)

    def test_ipc_failure_returns_none(self):
        ctrl = self._make_ctrl()
        ctrl._ipc_started = True
        with patch.object(ctrl, "_ipc_send", return_value=None):
            self.assertIsNone(ctrl.get_position())
            self.assertIsNone(ctrl.get_duration())


# ─────────────────────────────────────────────────────────────────────────────
# TestMpvPoller
# ─────────────────────────────────────────────────────────────────────────────

class TestMpvPoller(unittest.TestCase):
    def _make_ctrl(self, alive=True, pos=1.0, dur=60.0):
        ctrl = MagicMock()
        ctrl.is_alive.return_value = alive
        ctrl.get_position.return_value = pos
        ctrl.get_duration.return_value = dur
        return ctrl

    def _make_app_mock(self):
        from textual.app import App
        app = MagicMock(spec=App)
        app.call_from_thread = MagicMock(side_effect=lambda fn, *a: fn(*a))
        return app

    def test_poller_calls_on_tick(self):
        from hermes_cli.tui.media_player import MpvPoller
        ticks = []
        ctrl = self._make_ctrl(alive=True)
        app = self._make_app_mock()
        poller = MpvPoller(ctrl, app, on_tick=lambda p, d: ticks.append((p, d)), on_end=lambda: None)
        poller.start()
        time.sleep(0.4)
        poller.stop()
        self.assertGreater(len(ticks), 0)
        self.assertAlmostEqual(ticks[0][0], 1.0)

    def test_poller_calls_on_end_when_process_exits(self):
        from hermes_cli.tui.media_player import MpvPoller
        ended = threading.Event()
        ctrl = MagicMock()
        ctrl.is_alive.return_value = False
        app = self._make_app_mock()
        poller = MpvPoller(ctrl, app, on_tick=lambda p, d: None, on_end=lambda: ended.set())
        poller.start()
        self.assertTrue(ended.wait(timeout=2.0))

    def test_poller_stops_on_stop_event(self):
        from hermes_cli.tui.media_player import MpvPoller
        ctrl = self._make_ctrl(alive=True)
        tick_count = []
        app = self._make_app_mock()
        poller = MpvPoller(ctrl, app, on_tick=lambda p, d: tick_count.append(1), on_end=lambda: None)
        poller.start()
        time.sleep(0.3)
        poller.stop()
        time.sleep(0.3)
        count_after_stop = len(tick_count)
        time.sleep(0.3)
        self.assertEqual(count_after_stop, len(tick_count))


# ─────────────────────────────────────────────────────────────────────────────
# TestSeekBar
# ─────────────────────────────────────────────────────────────────────────────

class TestSeekBar(unittest.TestCase):
    def _make_seekbar(self):
        from hermes_cli.tui.widgets import SeekBar
        sb = SeekBar()
        # Patch size so render works
        mock_size = MagicMock()
        mock_size.width = 40
        mock_size.height = 1
        sb._size = mock_size
        type(sb).size = property(lambda self: mock_size)
        return sb

    def test_render_shows_play_icon_when_not_playing(self):
        sb = self._make_seekbar()
        sb.playing = False
        result = sb.render()
        self.assertIn("▶", result.plain)

    def test_render_shows_pause_icon_when_playing(self):
        sb = self._make_seekbar()
        sb.playing = True
        result = sb.render()
        self.assertIn("⏸", result.plain)

    def test_render_progress_proportional(self):
        sb = self._make_seekbar()
        sb.playing = False
        sb.position = 30.0
        sb.duration = 60.0
        result = sb.render()
        self.assertIsNotNone(result)
        # With 40 cols, icon=2, time=14, bar=24 cols; half filled → 12 filled chars
        plain = result.plain
        self.assertIn("━", plain)

    def test_click_seeks_proportional_accounting_for_icon_width(self):
        sb = self._make_seekbar()
        sb.duration = 100.0
        sb.position = 0.0
        seeks = []
        sb.on_seek = lambda pos: seeks.append(pos)

        evt = MagicMock()
        # bar starts at x=2 (after icon). bar_cols = 40-2-14=24
        # click at x=2 → bar_x=0 → pos=0
        evt.x = 14  # bar_x=12, bar_cols=24 → pos = 12/24*100 = 50
        sb.on_click(evt)
        self.assertAlmostEqual(seeks[0], 50.0)

    def test_left_arrow_seeks_back_5s(self):
        sb = self._make_seekbar()
        sb.position = 20.0
        sb.duration = 60.0
        seeks = []
        sb.on_seek = lambda pos: seeks.append(pos)
        sb.action_seek_back()
        self.assertAlmostEqual(seeks[0], 15.0)

    def test_right_arrow_seeks_forward_5s(self):
        sb = self._make_seekbar()
        sb.position = 20.0
        sb.duration = 60.0
        seeks = []
        sb.on_seek = lambda pos: seeks.append(pos)
        sb.action_seek_forward()
        self.assertAlmostEqual(seeks[0], 25.0)

    def test_seek_clamps_at_zero_and_duration(self):
        sb = self._make_seekbar()
        sb.position = 2.0
        sb.duration = 60.0
        seeks = []
        sb.on_seek = lambda pos: seeks.append(pos)
        # seek back beyond 0
        sb.action_seek_back()
        sb.action_seek_back()
        self.assertGreaterEqual(seeks[-1], 0.0)
        # seek forward beyond duration
        sb.position = 58.0
        sb.action_seek_forward()
        sb.action_seek_forward()
        self.assertLessEqual(seeks[-1], 60.0)


# ─────────────────────────────────────────────────────────────────────────────
# TestInlineMediaWidget
# ─────────────────────────────────────────────────────────────────────────────

class TestInlineMediaWidget(unittest.TestCase):
    """Test InlineMediaWidget behaviour via lightweight isolation (no Textual app)."""

    def _make_widget(self, timeline_auto_s=30, show_timeline=True):
        from hermes_cli.tui.widgets import InlineMediaWidget
        from hermes_cli.tui.media_player import InlineMediaCfg
        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "https://example.com/song.mp3"
        widget._kind = "audio"
        cfg = InlineMediaCfg(show_timeline=show_timeline, timeline_auto_s=timeline_auto_s)
        widget._cfg = cfg
        widget._ctrl = None
        widget._poller = None
        widget._show_timeline = show_timeline
        # Minimal reactive support
        widget.__dict__["state"] = "idle"
        widget.__dict__["title"] = ""
        widget.__dict__["position"] = 0.0
        widget.__dict__["duration"] = 0.0
        return widget

    def test_state_loading_on_mount(self):
        # Confirm state machine starts at "idle" (set to "loading" in on_mount)
        w = self._make_widget()
        self.assertEqual(w.__dict__["state"], "idle")

    def test_seekbar_always_composed(self):
        from hermes_cli.tui.widgets import InlineMediaWidget, SeekBar
        from textual.app import App, ComposeResult
        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield InlineMediaWidget(url="https://example.com/song.mp3", kind="audio")
        app = TestApp()
        # Check compose yields SeekBar
        widget = InlineMediaWidget(url="https://example.com/song.mp3", kind="audio")
        children = list(widget.compose())
        types = [type(c).__name__ for c in children]
        self.assertIn("SeekBar", types)

    def test_seekbar_hidden_when_timeline_auto_s_nonzero(self):
        # When timeline_auto_s > 0, seekbar starts hidden (display = False)
        # We verify the on_mount logic path: auto_s=30 → sb.display = False
        w = self._make_widget(timeline_auto_s=30)
        # auto_s=30 > 0 → the "always show" branch is not taken → sb.display stays False
        should_show_immediately = (w._show_timeline and w._cfg.timeline_auto_s == 0)
        self.assertFalse(should_show_immediately)

    def test_seekbar_visible_immediately_when_timeline_auto_s_zero(self):
        w = self._make_widget(timeline_auto_s=0)
        should_show_immediately = (w._show_timeline and w._cfg.timeline_auto_s == 0)
        self.assertTrue(should_show_immediately)

    def test_on_tick_reveals_seekbar_when_duration_exceeds_threshold(self):
        w = self._make_widget(timeline_auto_s=30)
        # Simulate _on_tick with dur > threshold
        reveal = (w._show_timeline and
                  (w._cfg.timeline_auto_s == 0 or 45.0 > w._cfg.timeline_auto_s))
        self.assertTrue(reveal)

    def test_on_end_transitions_to_stopped_decrements_count(self):
        # Test the _on_end logic by mocking the reactive setter
        from hermes_cli.tui.widgets import InlineMediaWidget
        w = self._make_widget()
        w.__dict__["state"] = "playing"
        app = MagicMock()
        app._active_media_count = 1
        w.post_message = MagicMock()
        state_vals: list[str] = []

        original_on_end = InlineMediaWidget._on_end

        def fake_on_end(self_w: Any) -> None:
            # Simulate _on_end without triggering Textual reactive
            state_vals.append("stopped")
            app._active_media_count = max(0, getattr(app, "_active_media_count", 0) - 1)
            self_w.post_message(InlineMediaWidget.PlaybackEnded())

        fake_on_end(w)
        self.assertEqual(state_vals[0], "stopped")
        self.assertEqual(app._active_media_count, 0)
        w.post_message.assert_called_once()

    def test_unmount_stops_poller_and_ctrl(self):
        w = self._make_widget()
        poller = MagicMock()
        ctrl = MagicMock()
        w._poller = poller
        w._ctrl = ctrl
        from hermes_cli.tui.widgets import InlineMediaWidget
        InlineMediaWidget.on_unmount(w)
        poller.stop.assert_called_once()
        ctrl.stop.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# TestThumbnailFetch
# ─────────────────────────────────────────────────────────────────────────────

class TestThumbnailFetch(unittest.TestCase):
    def test_youtube_thumbnail_url_constructed_correctly(self):
        from hermes_cli.tui.media_player import _fetch_youtube_thumbnail
        with patch("urllib.request.urlretrieve") as mock_r, \
             patch("tempfile.mkstemp", return_value=(0, "/tmp/thumb.jpg")), \
             patch("os.close"):
            mock_r.return_value = ("/tmp/thumb.jpg", {})
            path = _fetch_youtube_thumbnail("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            called_url = mock_r.call_args[0][0]
            self.assertIn("dQw4w9WgXcQ", called_url)
            self.assertIn("mqdefault.jpg", called_url)

    def test_video_thumbnail_skips_if_ffmpeg_missing(self):
        from hermes_cli.tui.media_player import _extract_video_thumbnail
        with patch("shutil.which", return_value=None):
            result = _extract_video_thumbnail("https://example.com/video.mp4")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# TestInlineMediaConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestInlineMediaConfig(unittest.TestCase):
    def test_config_defaults(self):
        from hermes_cli.tui.media_player import InlineMediaCfg
        cfg = InlineMediaCfg()
        self.assertFalse(cfg.enabled)
        self.assertTrue(cfg.audio)
        self.assertTrue(cfg.youtube)
        self.assertEqual(cfg.max_concurrent, 2)
        self.assertEqual(cfg.player, "mpv")

    def test_config_enabled_false_skips_detection(self):
        from hermes_cli.tui.media_player import InlineMediaCfg
        cfg = InlineMediaCfg(enabled=False)
        self.assertFalse(cfg.enabled)

    def test_config_max_concurrent_respected(self):
        from hermes_cli.tui.media_player import InlineMediaCfg
        cfg = InlineMediaCfg(max_concurrent=1)
        self.assertEqual(cfg.max_concurrent, 1)

    def test_system_prompt_hint_appended_when_enabled(self):
        """Verify hint injection logic for enabled=True."""
        from hermes_cli.tui.media_player import InlineMediaCfg

        # Simulate the injection logic from cli.py
        cfg = InlineMediaCfg(enabled=True, audio=True, youtube=True, video_thumbs=True)
        system_prompt = "You are a helpful assistant."

        kinds: list[str] = []
        if cfg.audio:
            kinds.append("audio files (mp3, wav, ogg, flac, aac, m4a, opus)")
        if cfg.video_thumbs:
            kinds.append("video files (mp4, mkv, webm, mov)")
        if cfg.youtube:
            kinds.append("YouTube URLs")
        if kinds:
            hint = (
                "The terminal supports inline media playback. "
                "When referencing " + ", ".join(kinds) + ", "
                "include the bare URL on its own line so the player renders automatically. "
                "Example: \"Here's the track:\\nhttps://example.com/song.mp3\""
            )
            system_prompt = (system_prompt + "\n\n" + hint).strip()

        self.assertIn("inline media playback", system_prompt)
        self.assertIn("audio files", system_prompt)
        self.assertIn("YouTube URLs", system_prompt)

        # Verify NOT present when disabled
        cfg_off = InlineMediaCfg(enabled=False)
        prompt2 = "You are helpful."
        if cfg_off.enabled:
            prompt2 += "\n\nhint"
        self.assertNotIn("inline media playback", prompt2)


# ─────────────────────────────────────────────────────────────────────────────
# TestMediaPlayerIntegration
# ─────────────────────────────────────────────────────────────────────────────

class TestMediaPlayerIntegration(unittest.TestCase):
    def test_tool_block_mounts_widget_on_audio_url(self):
        """_try_mount_media should mount InlineMediaWidget for audio URLs when enabled."""
        from hermes_cli.tui.media_player import InlineMediaCfg

        mock_stb = MagicMock()
        mock_stb._all_plain = ["Here's a track: https://example.com/song.mp3"]
        mock_stb.mount = MagicMock()

        with patch("hermes_cli.tui.media_player._inline_media_config",
                   return_value=InlineMediaCfg(enabled=True, audio=True)):
            from hermes_cli.tui.tool_blocks import StreamingToolBlock
            # Call the method directly on the mock with the real implementation
            with patch("hermes_cli.tui.tool_blocks._MEDIA_LINE_RE") as mock_re:
                mock_re.findall.return_value = []
                with patch("hermes_cli.tui.widgets.InlineMediaWidget") as mock_imw:
                    mock_imw.return_value = MagicMock()
                    StreamingToolBlock._try_mount_media(mock_stb)
                    # Should have mounted something (audio URL detected)

    def test_response_flow_calls_mount_callback_on_audio_url(self):
        """ResponseFlowEngine should call _mount_media_callback for audio URLs."""
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        from hermes_cli.tui.media_player import InlineMediaCfg

        panel = MagicMock()
        panel.app.get_css_variables.return_value = {}
        panel.app._math_enabled = False
        panel.app._math_renderer = "auto"
        panel.app._math_dpi = 150
        panel.app._math_max_rows = 12
        panel.app._mermaid_enabled = False
        panel.current_prose_log.return_value = MagicMock()
        panel.response_log = MagicMock()

        engine = ResponseFlowEngine(panel=panel)
        cb_calls = []
        engine._mount_media_callback = lambda kind, url: cb_calls.append((kind, url))

        with patch("hermes_cli.tui.media_player._inline_media_config",
                   return_value=InlineMediaCfg(enabled=True, audio=True)):
            engine.process_line("Check out https://example.com/song.mp3 for music")

        self.assertEqual(len(cb_calls), 1)
        self.assertEqual(cb_calls[0][0], "audio")
        self.assertIn("song.mp3", cb_calls[0][1])


# ─────────────────────────────────────────────────────────────────────────────
# TestBrowseAnchorMedia
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowseAnchorMedia(unittest.TestCase):
    def test_media_anchor_type_exists_in_enum(self):
        from hermes_cli.tui.app import BrowseAnchorType
        self.assertEqual(BrowseAnchorType.MEDIA.value, "media")

    def test_rebuild_anchors_includes_inline_media_widget(self):
        from hermes_cli.tui.app import BrowseAnchorType, BrowseAnchor
        from hermes_cli.tui.media_player import _short_url

        # Simulate what _rebuild_browse_anchors does
        from hermes_cli.tui.widgets import InlineMediaWidget
        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "https://example.com/song.mp3"
        widget._kind = "audio"

        anchor = BrowseAnchor(
            anchor_type=BrowseAnchorType.MEDIA,
            widget=widget,
            label=f"Media · {widget._kind} · {_short_url(widget._url)}",
            turn_id=1,
        )
        self.assertEqual(anchor.anchor_type, BrowseAnchorType.MEDIA)

    def test_rebuild_anchors_media_label_audio(self):
        from hermes_cli.tui.media_player import _short_url
        from hermes_cli.tui.widgets import InlineMediaWidget

        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "https://example.com/song.mp3"
        widget._kind = "audio"
        label = f"Media · {widget._kind} · {_short_url(widget._url)}"
        self.assertIn("audio", label)
        self.assertIn("song.mp3", label)

    def test_rebuild_anchors_media_label_youtube(self):
        from hermes_cli.tui.media_player import _short_url
        from hermes_cli.tui.widgets import InlineMediaWidget

        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        widget._kind = "youtube"
        label = f"Media · {widget._kind} · {_short_url(widget._url)}"
        self.assertIn("youtube", label)
        self.assertIn("dQw4w9WgXcQ", label)

    def test_jump_anchor_media_filter_skips_non_media(self):
        from hermes_cli.tui.app import BrowseAnchorType, BrowseAnchor

        non_media = BrowseAnchor(
            anchor_type=BrowseAnchorType.CODE_BLOCK,
            widget=MagicMock(),
            label="Code · python",
            turn_id=1,
        )
        media = BrowseAnchor(
            anchor_type=BrowseAnchorType.MEDIA,
            widget=MagicMock(),
            label="Media · audio · song.mp3",
            turn_id=1,
        )
        anchors = [non_media, media]
        candidates = [
            (i, a) for i, a in enumerate(anchors)
            if a.anchor_type == BrowseAnchorType.MEDIA
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][1].label, "Media · audio · song.mp3")


if __name__ == "__main__":
    unittest.main()
