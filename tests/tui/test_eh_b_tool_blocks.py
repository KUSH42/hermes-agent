"""EH-B compliance tests — exception-handling in tool_blocks / tool_panel / tool_group."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


class TestBlockDiffColors:  # EH-B-01 (2 tests)
    """_block.py: diff_bg_colors logs with exc_info=True, Syntax render fallback logs exc_info."""

    def test_block_diff_bg_colors_logs_exc_info(self) -> None:
        """_diff_bg_colors: when _component_vars raises, _log.debug is called with exc_info=True."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock, _DIFF_ADD_BG_FALLBACK, _DIFF_DEL_BG_FALLBACK

        block = object.__new__(ToolBlock)

        # _theme_manager._component_vars raises
        bad_tm = MagicMock()
        bad_tm._component_vars = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

        # ToolBlock.app is a Textual read-only property — subclass to override
        class _IsolatedBlock(ToolBlock):
            pass

        block.__class__ = _IsolatedBlock
        type(_IsolatedBlock).app = PropertyMock(return_value=SimpleNamespace(_theme_manager=bad_tm))

        # bad_tm._component_vars raises (set as attribute that raises)
        def _raise_on_access():
            raise RuntimeError("boom")

        app_ns = SimpleNamespace()
        # Make _component_vars access on the tm object raise
        class _RaisingTM:
            @property
            def _component_vars(self):
                raise RuntimeError("boom")

        type(_IsolatedBlock).app = PropertyMock(return_value=SimpleNamespace(_theme_manager=_RaisingTM()))

        with patch("hermes_cli.tui.tool_blocks._block._log") as mock_log:
            result = block._diff_bg_colors()

        # Should return the hardcoded fallback pair
        assert result == (_DIFF_ADD_BG_FALLBACK, _DIFF_DEL_BG_FALLBACK)
        # _log.debug must have been called with exc_info=True
        assert mock_log.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_log.debug.call_args_list
        )
        assert found, f"Expected _log.debug with exc_info=True, got: {mock_log.debug.call_args_list}"

    def test_block_render_body_syntax_logs_exc_info(self) -> None:
        """_render_body: when Syntax raises, _log.debug is called with exc_info=True."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock, _FILE_TOOL_NAMES

        block = object.__new__(ToolBlock)
        # Set attributes needed to reach the Syntax try block
        block._tool_name = next(iter(_FILE_TOOL_NAMES))
        block._label = "main.py"  # extension maps to "python" via _code_lang
        block._plain_lines = ["print('hello')"]
        block._lines = ["print('hello')"]
        # Also set _header_stats (accessed later in the method after the except)
        block._header_stats = None

        # Mock the CopyableRichLog query result
        mock_rl = MagicMock()
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body

        # ToolBlock.app is a read-only Textual property — subclass to override
        class _IsolatedBlock(ToolBlock):
            pass

        block.__class__ = _IsolatedBlock
        type(_IsolatedBlock).app = PropertyMock(
            return_value=SimpleNamespace(get_css_variables=lambda: {})
        )

        with patch("hermes_cli.tui.tool_blocks._block._log") as mock_log:
            with patch("rich.syntax.Syntax", side_effect=RuntimeError("syntax boom")):
                block._render_body()

        # _log.debug must have been called with exc_info=True
        assert mock_log.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_log.debug.call_args_list
        )
        assert found, f"Expected _log.debug with exc_info=True, got: {mock_log.debug.call_args_list}"


class TestStreamingMedia:  # EH-B-04 (2 tests)
    """_streaming.py: media mount failures log with exc_info=True."""

    def test_streaming_try_mount_media_image_logs_exc_info(self) -> None:
        """InlineImage mount failure → logger.debug called with exc_info=True."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        import hermes_cli.tui.tool_blocks._streaming as _streaming_mod

        block = object.__new__(StreamingToolBlock)
        block._all_plain = ["/tmp/test.png"]

        # Patch InlineImage to raise on instantiation
        fake_image_cls = MagicMock(side_effect=RuntimeError("img boom"))

        with patch.object(_streaming_mod, "logger") as mock_logger:
            # Make the image branch fire
            with patch.object(_streaming_mod, "_MEDIA_LINE_RE") as mock_re:
                mock_match = MagicMock()
                mock_match.group.return_value = "/tmp/test.png"
                mock_re.search.return_value = mock_match
                with patch.object(_streaming_mod, "_extract_image_path", return_value="/tmp/test.png"):
                    # Make InlineImage raise; also make media_player import raise so we
                    # only hit the image path
                    import sys
                    fake_widgets = MagicMock()
                    fake_widgets.InlineImage = fake_image_cls
                    saved_widgets = sys.modules.get("hermes_cli.tui.widgets")
                    saved_mp = sys.modules.get("hermes_cli.tui.media_player")
                    try:
                        sys.modules["hermes_cli.tui.widgets"] = fake_widgets
                        # Make media_player import fail so test is scoped to image path
                        sys.modules["hermes_cli.tui.media_player"] = None  # type: ignore[assignment]
                        block._try_mount_media()
                    finally:
                        if saved_widgets is not None:
                            sys.modules["hermes_cli.tui.widgets"] = saved_widgets
                        else:
                            sys.modules.pop("hermes_cli.tui.widgets", None)
                        if saved_mp is not None:
                            sys.modules["hermes_cli.tui.media_player"] = saved_mp
                        else:
                            sys.modules.pop("hermes_cli.tui.media_player", None)

        assert mock_logger.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_logger.debug.call_args_list
        )
        assert found, f"Expected logger.debug with exc_info=True, got: {mock_logger.debug.call_args_list}"

    def test_streaming_try_mount_media_player_logs_exc_info(self) -> None:
        """media_player import failure → logger.debug called with exc_info=True."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        import hermes_cli.tui.tool_blocks._streaming as _streaming_mod
        import sys

        block = object.__new__(StreamingToolBlock)
        block._all_plain = []  # no image lines

        # Ensure no image path is found
        with patch.object(_streaming_mod, "_MEDIA_LINE_RE") as mock_re:
            mock_re.search.return_value = None
            with patch.object(_streaming_mod, "logger") as mock_logger:
                saved = sys.modules.pop("hermes_cli.tui.media_player", None)
                try:
                    sys.modules["hermes_cli.tui.media_player"] = None  # type: ignore[assignment]
                    block._try_mount_media()
                finally:
                    if saved is not None:
                        sys.modules["hermes_cli.tui.media_player"] = saved
                    else:
                        sys.modules.pop("hermes_cli.tui.media_player", None)

        assert mock_logger.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_logger.debug.call_args_list
        )
        assert found, f"Expected logger.debug with exc_info=True, got: {mock_logger.debug.call_args_list}"


class TestCoreWatchCollapsed:  # EH-B-08 (1 test)
    """_core.py: rerender_window failure logs with exc_info=True."""

    def test_core_watch_collapsed_rerender_logs_exc_info(self) -> None:
        """watch_collapsed(old=True, new=False): rerender_window failure → _log.debug with exc_info=True."""
        from hermes_cli.tui.tool_panel._core import ToolPanel

        panel = object.__new__(ToolPanel)
        panel._saved_visible_start = 5

        # Set up _block with needed attributes; rerender_window raises
        mock_block = MagicMock()
        mock_block._visible_start = 5
        mock_block._all_plain = ["line"] * 50
        mock_block._visible_cap = 20
        mock_block.rerender_window.side_effect = RuntimeError("rerender boom")
        panel._block = mock_block

        # Stubs for the other watch_collapsed branches
        panel._refresh_collapsed_strip = MagicMock()
        panel.remove_class = MagicMock()
        panel.add_class = MagicMock()
        panel._hint_visible = False
        panel._hint_row = None
        panel._footer_pane = None

        with patch("hermes_cli.tui.tool_panel._core._log") as mock_log:
            panel.watch_collapsed(old=True, new=False)

        assert mock_log.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_log.debug.call_args_list
        )
        assert found, f"Expected _log.debug with exc_info=True, got: {mock_log.debug.call_args_list}"


class TestFooterPane:  # EH-B-09 (2 tests)
    """_footer.py: preview update and accent css lookup log with exc_info=True."""

    def test_footer_body_pane_preview_update_logs_exc_info(self) -> None:
        """_update_preview: rich.text.Text() raise → _log.debug called with exc_info=True."""
        from hermes_cli.tui.tool_panel._footer import BodyPane

        pane = object.__new__(BodyPane)
        mock_preview = MagicMock()

        # _update_preview reads lines from self._block._all_plain
        mock_block = MagicMock()
        mock_block._all_plain = ["line1", "line2", "line3"]
        mock_block._streaming = False
        mock_block._is_streaming = False
        pane._block = mock_block

        with patch("hermes_cli.tui.tool_panel._footer._log") as mock_log:
            # Text is imported inside the try block from rich.text — patch at source
            with patch("rich.text.Text", side_effect=RuntimeError("text boom")):
                pane._update_preview(mock_preview)

        assert mock_log.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_log.debug.call_args_list
        )
        assert found, f"Expected _log.debug with exc_info=True, got: {mock_log.debug.call_args_list}"

    def test_footer_render_footer_accent_exc_info(self) -> None:
        """_render_footer: get_css_variables raise for accent chip → _log.debug with exc_info=True."""
        from hermes_cli.tui.tool_panel._footer import FooterPane
        from hermes_cli.tui.tool_result_parse import Chip, ResultSummaryV4

        pane = object.__new__(FooterPane)
        pane._last_summary = None
        pane._last_promoted = frozenset()

        mock_content = MagicMock()
        pane._content = mock_content

        # Build a summary with an "accent"-tone chip (kind="mcp-source" allows accent)
        chip = Chip(text="my-server", kind="mcp-source", tone="accent")
        summary = ResultSummaryV4(
            primary=None,
            exit_code=None,
            chips=(chip,),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=False,
        )

        # FooterPane.app is a Textual property — subclass to override
        class _IsolatedFooter(FooterPane):
            pass

        pane.__class__ = _IsolatedFooter
        type(_IsolatedFooter).app = PropertyMock(
            return_value=SimpleNamespace(
                get_css_variables=MagicMock(side_effect=RuntimeError("css boom"))
            )
        )
        # parent is also a Textual read-only property — override via subclass
        type(_IsolatedFooter).parent = PropertyMock(return_value=None)

        pane._rebuild_action_buttons = MagicMock()
        pane._rebuild_artifact_buttons = MagicMock()

        with patch("hermes_cli.tui.tool_panel._footer._log") as mock_log:
            pane._render_footer(summary, promoted_chip_texts=frozenset())

        assert mock_log.debug.called
        found = any(
            call_args.kwargs.get("exc_info") is True
            for call_args in mock_log.debug.call_args_list
        )
        assert found, f"Expected _log.debug with exc_info=True, got: {mock_log.debug.call_args_list}"
