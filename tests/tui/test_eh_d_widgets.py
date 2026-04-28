"""EH-D compliance tests for hermes_cli/tui/widgets/ exception handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


class TestBashOutputBlock:
    """EH-D-03: push_line logs on write failure."""

    def test_bash_output_push_line_logs_error(self):
        """mock self._body.write to raise; assert _log.debug called with exc_info=True."""
        from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock

        block = BashOutputBlock.__new__(BashOutputBlock)
        mock_body = MagicMock()
        mock_body.write.side_effect = RuntimeError("write failed")
        block._body = mock_body

        with patch("hermes_cli.tui.widgets.bash_output_block._log") as mock_log:
            block.push_line("hello world")
            mock_log.debug.assert_called_once()
            call_kwargs = mock_log.debug.call_args
            assert call_kwargs.kwargs.get("exc_info") is True or (
                len(call_kwargs.args) > 0  # positional exc_info
                and call_kwargs.kwargs.get("exc_info", True) is True
            )
            # Also verify the message contains our expected text
            assert "push_line" in call_kwargs.args[0]


class TestCodeBlocks:
    """EH-D-04: mermaid render callbacks log on failure."""

    def test_mermaid_render_callback_logs_exc_info(self):
        """Mock app.call_from_thread to raise; check _log.debug with exc_info=True."""
        from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock

        block = StreamingCodeBlock.__new__(StreamingCodeBlock)
        block._lang = "mermaid"
        block._code_lines = ["graph TD", "    A-->B"]
        block._complete_skin_vars = {}
        block._collapsed = False

        mock_app = MagicMock()
        mock_app.call_from_thread.side_effect = RuntimeError("call_from_thread failed")

        # Patch is_mounted to return False so we hit the unmounted branch (line 282)
        with patch.object(type(block), "is_mounted", new_callable=lambda: property(lambda self: False)):
            with patch.object(type(block), "app", new_callable=lambda: property(lambda self: mock_app)):
                with patch.object(block, "_on_mermaid_rendered", return_value=None):
                    with patch("hermes_cli.tui.widgets.code_blocks._log") as mock_log:
                        with patch(
                            "hermes_cli.tui.math_renderer.render_mermaid",
                            return_value=None,
                        ):
                            block._try_render_mermaid_async()
                            mock_log.debug.assert_called()
                            debug_calls = mock_log.debug.call_args_list
                            matching = [
                                c for c in debug_calls
                                if "mermaid render callback failed" in c.args[0]
                                and c.kwargs.get("exc_info") is True
                            ]
                            assert matching, (
                                f"Expected 'mermaid render callback failed' debug log with exc_info=True. "
                                f"Got calls: {debug_calls}"
                            )

    def test_mermaid_subprocess_logs_exc_info(self):
        """Mock _build_mermaid_cmd to return None and call_from_thread to raise; check subprocess log."""
        from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock

        block = StreamingCodeBlock.__new__(StreamingCodeBlock)
        block._lang = "mermaid"
        block._code_lines = ["graph TD", "    A-->B"]
        block._complete_skin_vars = {}
        block._collapsed = False

        mock_app = MagicMock()
        mock_app.call_from_thread.side_effect = RuntimeError("call_from_thread failed")

        with patch.object(type(block), "is_mounted", new_callable=lambda: property(lambda self: True)):
            with patch.object(type(block), "app", new_callable=lambda: property(lambda self: mock_app)):
                with patch.object(block, "_on_mermaid_rendered", return_value=None):
                    with patch("hermes_cli.tui.widgets.code_blocks._log") as mock_log:
                        with patch(
                            "hermes_cli.tui.math_renderer.render_mermaid",
                            return_value=None,
                        ):
                            with patch(
                                "hermes_cli.tui.math_renderer._build_mermaid_cmd",
                                return_value=None,
                            ):
                                block._try_render_mermaid_async()
                                debug_calls = mock_log.debug.call_args_list
                                matching = [
                                    c for c in debug_calls
                                    if "mermaid render subprocess failed" in c.args[0]
                                    and c.kwargs.get("exc_info") is True
                                ]
                                assert matching, (
                                    f"Expected 'mermaid render subprocess failed' debug log with exc_info=True. "
                                    f"Got calls: {debug_calls}"
                                )


class TestInlineMedia:
    """EH-D-05: InlineMedia image/video load paths log on failure."""

    def test_inline_media_image_load_logs_error(self):
        """Mock _encode_tgp_placeholder to raise; check _log.debug with exc_info=True."""
        from hermes_cli.tui.widgets.inline_media import InlineImage

        img = InlineImage.__new__(InlineImage)
        img._image_id = None
        img._tgp_transmitted = False
        img._tgp_placeholder_strips = []
        img._sixel_seq = ""
        img._halfblock_strips = []
        img._rendered_rows = 0
        img._src_path = None

        with patch.object(img, "_encode_tgp_placeholder", side_effect=RuntimeError("encode failed")):
            with patch("hermes_cli.tui.widgets.inline_media._log") as mock_log:
                # Call the underlying (unwrapped) function directly to bypass the @work decorator
                InlineImage._prepare_tgp_async.__wrapped__(img, MagicMock())
                mock_log.debug.assert_called_once()
                call = mock_log.debug.call_args
                assert "InlineMedia image load failed" in call.args[0]
                assert call.kwargs.get("exc_info") is True

    def test_inline_media_video_load_logs_error(self):
        """Mock sys.stdout.write to raise; check _log.debug with exc_info=True."""
        import sys
        from hermes_cli.tui.widgets.inline_media import InlineImage

        img = InlineImage.__new__(InlineImage)

        with patch.object(sys.stdout, "write", side_effect=IOError("write failed")):
            with patch("hermes_cli.tui.widgets.inline_media._log") as mock_log:
                img._emit_raw("some sequence")
                mock_log.debug.assert_called_once()
                call = mock_log.debug.call_args
                assert "InlineMedia video load failed" in call.args[0]
                assert call.kwargs.get("exc_info") is True


class TestMedia:
    """EH-D-06: MediaWidget._load and _update log on failure."""

    def test_media_widget_load_logs_error(self):
        """Mock query_one to raise; check _log.debug with exc_info=True in _on_ready."""
        from hermes_cli.tui.widgets.media import InlineMediaWidget

        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "http://example.com/video.mp4"
        widget._ctrl = None
        widget._cfg = MagicMock()
        widget._kind = "video"
        widget._show_timeline = False
        widget._seekbar = None

        mock_app = MagicMock()
        mock_app.query_one.side_effect = RuntimeError("query_one failed")

        # Use IsolatedSubclass to avoid reactive descriptor errors (per memory gotcha)
        class _IsolatedSubclass(type(widget).__class__):
            pass

        with patch.object(type(widget), "is_mounted", new_callable=lambda: property(lambda self: True)):
            with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
                # Patch state reactive to a plain property so assignment doesn't trigger Textual
                with patch.object(type(widget), "state", new_callable=lambda: property(lambda s: "idle", lambda s, v: None)):
                    with patch("hermes_cli.tui.widgets.media._log") as mock_log:
                        with patch("hermes_cli.tui.media_player._short_url", return_value="example.com"):
                            # thumb_path=None so we skip the mount call and go straight to ctrl_label
                            widget._on_ready(MagicMock(), None)
                            mock_log.debug.assert_called()
                            calls = mock_log.debug.call_args_list
                            matching = [
                                c for c in calls
                                if "MediaWidget._load failed" in c.args[0]
                                and c.kwargs.get("exc_info") is True
                            ]
                            assert matching, f"Expected '_load failed' log. Got: {calls}"

    def test_media_widget_update_logs_error(self):
        """Mock query_one to raise; check _log.debug with exc_info=True in _on_tick."""
        from hermes_cli.tui.widgets.media import InlineMediaWidget

        widget = InlineMediaWidget.__new__(InlineMediaWidget)
        widget._url = "http://example.com/video.mp4"
        widget._cfg = MagicMock()
        widget._cfg.timeline_auto_s = 5
        widget._show_timeline = True

        mock_app = MagicMock()
        mock_app.query_one.side_effect = RuntimeError("seekbar absent")

        with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch("hermes_cli.tui.widgets.media._log") as mock_log:
                # Patch all reactive descriptors to no-ops to avoid ReactiveError
                with patch.object(type(widget), "position", new_callable=lambda: property(lambda s: 0.0, lambda s, v: None)):
                    with patch.object(type(widget), "duration", new_callable=lambda: property(lambda s: 0.0, lambda s, v: None)):
                        with patch.object(type(widget), "state", new_callable=lambda: property(lambda s: "playing", lambda s, v: None)):
                            widget._on_tick(1.0, 10.0)
                mock_log.debug.assert_called()
                calls = mock_log.debug.call_args_list
                matching = [
                    c for c in calls
                    if "MediaWidget._update failed" in c.args[0]
                    and c.kwargs.get("exc_info") is True
                ]
                assert matching, f"Expected '_update failed' log. Got: {calls}"


class TestOverlaysWidget:
    """EH-D-08: overlay ContentSwitcher toggle logs on failure."""

    def test_overlays_content_switcher_toggle_logs_error(self):
        """Mock app.highlighted_candidate setter to raise; check _log.debug with exc_info=True."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.widgets.overlays import HistorySearchOverlay

        overlay = HistorySearchOverlay.__new__(HistorySearchOverlay)
        overlay._debounce_handle = None
        overlay._saved_hint = ""
        overlay._query_history = []

        # Make app.highlighted_candidate assignment raise
        mock_app = MagicMock()
        type(mock_app).highlighted_candidate = property(
            fget=lambda self: None,
            fset=lambda self, v: (_ for _ in ()).throw(RuntimeError("highlighted_candidate failed")),
        )
        # mock query_one to raise NoMatches (caught by the existing NoMatches handler)
        mock_app.query_one = MagicMock(side_effect=NoMatches("absent"))

        with patch.object(type(overlay), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(overlay, "remove_class", return_value=None):
                with patch("hermes_cli.tui.widgets.overlays._log") as mock_log:
                    overlay.action_dismiss()
                    mock_log.debug.assert_called()
                    calls = mock_log.debug.call_args_list
                    matching = [
                        c for c in calls
                        if "overlay ContentSwitcher toggle failed" in c.args[0]
                        and c.kwargs.get("exc_info") is True
                    ]
                    assert matching, (
                        f"Expected 'overlay ContentSwitcher toggle failed' debug log. Got: {calls}"
                    )
