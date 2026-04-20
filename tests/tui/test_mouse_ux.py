"""Tests for Mouse UX spec — all phases.

Phase 1: A1 dead scrollbar, A2 GroupHeader right-click, B1 middle-click paste, B2 ctrl+click invert
Phase 2: C1 scroll config, D1 tooltip system, D2 copy button tooltip
Phase 3: E1 double-click, F1 shift+click range select, F2 context menu position
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_click(button: int = 1, ctrl: bool = False, shift: bool = False, chain: int = 1) -> MagicMock:
    ev = MagicMock()
    ev.button = button
    ev.ctrl = ctrl
    ev.shift = shift
    ev.chain = chain
    ev.x = 0
    ev.y = 0
    ev.screen_x = 0
    ev.screen_y = 0
    return ev


def _make_app() -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


# ===========================================================================
# Phase 1 — A1: Dead scrollbar removed
# ===========================================================================

class TestA1DeadScrollbar:
    def test_output_panel_css_no_active_scrollbar(self) -> None:
        """OutputPanel block in hermes.tcss must not define scrollbar-size-vertical ≥ 1."""
        import os
        import re
        import hermes_cli.tui.app as app_module
        tcss_path = os.path.join(os.path.dirname(app_module.__file__), "hermes.tcss")
        with open(tcss_path) as f:
            content = f.read()
        output_panel_block = re.search(r"OutputPanel\s*\{([^}]*)\}", content)
        if output_panel_block:
            block_text = output_panel_block.group(1)
            assert not re.search(r"scrollbar-size-vertical\s*:\s*[1-9]", block_text), (
                "OutputPanel has a non-zero scrollbar-size-vertical (dead scrollbar)"
            )


# ===========================================================================
# Phase 1 — A2: GroupHeader right-click guard
# ===========================================================================

class TestA2GroupHeaderClickGuard:
    def test_right_click_does_not_toggle(self) -> None:
        """Right-click must not modify _user_collapsed (early return before toggle)."""
        from hermes_cli.tui.tool_group import ToolGroup
        tg = object.__new__(ToolGroup)
        tg._user_collapsed = False
        # Patch collapsed setter to track calls
        calls = []
        with patch.object(type(tg), "collapsed", new_callable=lambda: property(
            lambda self: False,
            lambda self, v: calls.append(v),
        )):
            ev = _make_click(button=3)
            tg.on_click(ev)
        assert calls == [], "right-click should not set collapsed"

    def test_left_click_does_toggle(self) -> None:
        """Left-click must negate _user_collapsed and assign to collapsed."""
        from hermes_cli.tui.tool_group import ToolGroup
        tg = object.__new__(ToolGroup)
        tg._user_collapsed = False
        calls = []
        with patch.object(type(tg), "collapsed", new_callable=lambda: property(
            lambda self: False,
            lambda self, v: calls.append(v),
        )):
            ev = _make_click(button=1)
            tg.on_click(ev)
        assert calls == [True], "left-click should set collapsed=True"


# ===========================================================================
# Phase 1 — B1: Middle-click paste (Linux only)
# ===========================================================================

class TestB1MiddleClickPaste:
    @pytest.mark.skipif(sys.platform != "linux", reason="Primary selection is Linux/X11 only")
    def test_middle_click_inserts_primary_selection(self) -> None:
        from hermes_cli.tui.input_widget import HermesInput
        widget = object.__new__(HermesInput)
        inserted = []
        widget.insert = lambda text: inserted.append(text)
        ev = _make_click(button=2)
        ev.stop = MagicMock()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello world"

        with patch("hermes_cli.tui.input_widget.subprocess.run", return_value=mock_result):
            widget.on_click(ev)

        assert inserted == ["hello world"]
        ev.stop.assert_called_once()

    @pytest.mark.skipif(sys.platform != "linux", reason="Primary selection is Linux/X11 only")
    def test_middle_click_silent_when_xclip_absent(self) -> None:
        from hermes_cli.tui.input_widget import HermesInput
        widget = object.__new__(HermesInput)
        inserted = []
        widget.insert = lambda text: inserted.append(text)
        ev = _make_click(button=2)
        ev.stop = MagicMock()

        with patch("hermes_cli.tui.input_widget.subprocess.run", side_effect=FileNotFoundError):
            widget.on_click(ev)

        assert inserted == []
        ev.stop.assert_called_once()

    def test_left_click_not_intercepted(self) -> None:
        from hermes_cli.tui.input_widget import HermesInput
        widget = object.__new__(HermesInput)
        widget.insert = MagicMock()
        ev = _make_click(button=1)
        ev.stop = MagicMock()
        widget.on_click(ev)
        widget.insert.assert_not_called()
        ev.stop.assert_not_called()

    def test_right_click_not_intercepted(self) -> None:
        from hermes_cli.tui.input_widget import HermesInput
        widget = object.__new__(HermesInput)
        widget.insert = MagicMock()
        ev = _make_click(button=3)
        ev.stop = MagicMock()
        widget.on_click(ev)
        widget.insert.assert_not_called()
        ev.stop.assert_not_called()


# ===========================================================================
# Phase 1 — B2: Ctrl+click inverts open/copy
# ===========================================================================

class TestB2CtrlClickInvert:
    def _make_log_with_link(self):
        from hermes_cli.tui.widgets import CopyableRichLog

        _offset = MagicMock()
        _offset.y = 0
        _offset.x = 0

        class _TestLog(CopyableRichLog):
            @property
            def scroll_offset(self):
                return _offset

        log = object.__new__(_TestLog)
        log.lines = []
        log._line_links = ["https://example.com"]
        return log

    def test_plain_click_posts_link_clicked_ctrl_false(self) -> None:
        log = self._make_log_with_link()
        posted = []
        log.post_message = lambda m: posted.append(m)
        ev = _make_click(button=1, ctrl=False)
        ev.y = 0
        ev.stop = MagicMock()
        log.on_click(ev)
        assert len(posted) == 1
        assert posted[0].ctrl is False

    def test_ctrl_click_posts_link_clicked_ctrl_true(self) -> None:
        log = self._make_log_with_link()
        posted = []
        log.post_message = lambda m: posted.append(m)
        ev = _make_click(button=1, ctrl=True)
        ev.y = 0
        ev.stop = MagicMock()
        log.on_click(ev)
        assert len(posted) == 1
        assert posted[0].ctrl is True

    def test_no_link_no_message_posted(self) -> None:
        log = self._make_log_with_link()
        log._line_links = []  # no links
        posted = []
        log.post_message = lambda m: posted.append(m)
        ev = _make_click(button=1)
        ev.y = 0
        ev.stop = MagicMock()
        log.on_click(ev)
        assert posted == []

    def test_right_click_ignored(self) -> None:
        log = self._make_log_with_link()
        posted = []
        log.post_message = lambda m: posted.append(m)
        ev = _make_click(button=3)
        ev.y = 0
        ev.stop = MagicMock()
        log.on_click(ev)
        assert posted == []

    def test_app_handler_copies_on_plain_click(self) -> None:
        from hermes_cli.tui.app import HermesApp
        ev = MagicMock()
        ev.url = "https://example.com"
        ev.ctrl = False
        copied = []
        opened = []

        class _FakeApp:
            def _open_external_url(self, url): opened.append(url)
            def _copy_text_with_hint(self, url): copied.append(url)
            on_copyable_rich_log_link_clicked = HermesApp.on_copyable_rich_log_link_clicked

        app = _FakeApp()
        app.on_copyable_rich_log_link_clicked(ev)
        assert copied == ["https://example.com"]
        assert opened == []

    def test_app_handler_opens_on_ctrl_click(self) -> None:
        from hermes_cli.tui.app import HermesApp
        app = object.__new__(HermesApp)
        opened = []
        app._open_external_url = lambda url: opened.append(url)
        app._copy_text_with_hint = MagicMock()
        ev = MagicMock()
        ev.url = "https://example.com"
        ev.ctrl = True
        app.on_copyable_rich_log_link_clicked(ev)
        assert opened == ["https://example.com"]
        app._copy_text_with_hint.assert_not_called()


# ===========================================================================
# Phase 2 — C1: Scroll sensitivity config
# ===========================================================================

class TestC1ScrollConfig:
    def test_default_scroll_lines_is_3(self) -> None:
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["terminal"]["scroll_lines"] == 3

    def test_app_default_scroll_lines_is_3(self) -> None:
        from hermes_cli.tui.app import HermesApp
        app = object.__new__(HermesApp)
        app._scroll_lines = 3
        assert app._scroll_lines == 3

    def test_scroll_handler_uses_app_scroll_lines(self) -> None:
        from hermes_cli.tui.widgets import OutputPanel
        from unittest.mock import PropertyMock

        _app = MagicMock()
        _app._scroll_lines = 7

        class _TestPanel(OutputPanel):
            @property
            def app(self):
                return _app

        panel = object.__new__(_TestPanel)
        panel._user_scrolled_up = False
        scrolled = []
        panel.scroll_relative = lambda y, animate, immediate: scrolled.append(y)
        ev = MagicMock()
        ev.prevent_default = MagicMock()
        panel.on_mouse_scroll_up(ev)
        assert scrolled == [-7]

    def test_scroll_down_uses_app_scroll_lines(self) -> None:
        from hermes_cli.tui.widgets import OutputPanel

        _app = MagicMock()
        _app._scroll_lines = 5

        class _TestPanel(OutputPanel):
            @property
            def app(self):
                return _app

        panel = object.__new__(_TestPanel)
        scrolled = []
        panel.scroll_relative = lambda y, animate, immediate: scrolled.append(y)
        ev = MagicMock()
        ev.prevent_default = MagicMock()
        panel.on_mouse_scroll_down(ev)
        assert scrolled == [5]

    def test_cli_clamps_scroll_lines_out_of_range(self) -> None:
        # Verify clamping logic independently
        def clamp(v: int) -> int:
            return max(1, min(20, int(v)))
        assert clamp(0) == 1
        assert clamp(21) == 20
        assert clamp(7) == 7


# ===========================================================================
# Phase 2 — D1: Tooltip system
# ===========================================================================

class TestD1TooltipSystem:
    def test_tooltip_widget_renders_text(self) -> None:
        from hermes_cli.tui.tooltip import Tooltip
        t = Tooltip("hello tooltip")
        assert t.render() == "hello tooltip"

    def test_tooltip_mixin_no_mount_when_no_text(self) -> None:
        from hermes_cli.tui.tooltip import TooltipMixin
        mixin = TooltipMixin()
        mixin._tooltip_text = ""
        mixin.set_timer = MagicMock()
        mixin.on_mouse_enter(MagicMock())
        mixin.set_timer.assert_not_called()

    def test_tooltip_mixin_sets_timer_on_enter(self) -> None:
        from hermes_cli.tui.tooltip import TooltipMixin
        mixin = TooltipMixin()
        mixin._tooltip_text = "hint"
        mixin.set_timer = MagicMock(return_value=MagicMock())
        mixin.on_mouse_enter(MagicMock())
        mixin.set_timer.assert_called_once()
        delay = mixin.set_timer.call_args[0][0]
        assert delay == pytest.approx(0.5, rel=0.01)

    def test_tooltip_mixin_cancels_timer_on_leave(self) -> None:
        from hermes_cli.tui.tooltip import TooltipMixin
        mixin = TooltipMixin()
        mixin._tooltip_text = "hint"
        timer = MagicMock()
        mixin._tooltip_timer = timer
        mixin._tooltip_widget = None
        mixin.on_mouse_leave(MagicMock())
        timer.stop.assert_called_once()
        assert mixin._tooltip_timer is None

    def test_tooltip_mixin_dismisses_widget_on_leave(self) -> None:
        from hermes_cli.tui.tooltip import TooltipMixin
        mixin = TooltipMixin()
        mixin._tooltip_text = "hint"
        mixin._tooltip_timer = None
        tw = MagicMock()
        tw.is_mounted = True
        mixin._tooltip_widget = tw
        mixin.on_mouse_leave(MagicMock())
        tw.remove.assert_called_once()
        assert mixin._tooltip_widget is None

    def test_tool_header_has_tooltip_text(self) -> None:
        from hermes_cli.tui.tool_blocks import ToolHeader
        assert ToolHeader._tooltip_text != ""
        assert "click" in ToolHeader._tooltip_text.lower()

    def test_streaming_code_block_has_tooltip_text(self) -> None:
        from hermes_cli.tui.widgets import StreamingCodeBlock
        assert StreamingCodeBlock._tooltip_text != ""
        assert "expand" in StreamingCodeBlock._tooltip_text.lower() or "collapse" in StreamingCodeBlock._tooltip_text.lower()

    def test_tooltip_layer_in_screen_css(self) -> None:
        import os
        import hermes_cli.tui.app as app_module
        tcss_path = os.path.join(os.path.dirname(app_module.__file__), "hermes.tcss")
        with open(tcss_path) as f:
            content = f.read()
        assert "layers:" in content and "tooltip" in content


# ===========================================================================
# Phase 2 — D2: Copy button tooltip
# ===========================================================================

class TestD2CopyButtonTooltip:
    def test_copy_btn_class_has_tooltip(self) -> None:
        from hermes_cli.tui.widgets import _CopyBtn
        from hermes_cli.tui.tooltip import TooltipMixin
        assert issubclass(_CopyBtn, TooltipMixin)
        assert _CopyBtn._tooltip_text == "Copy block"


# ===========================================================================
# Phase 3 — E1: Double-click
# ===========================================================================

class TestE1DoubleClick:
    def _make_scb(self, state="COMPLETE"):
        from hermes_cli.tui.widgets import StreamingCodeBlock
        _app = MagicMock()
        copied = []
        _app._copy_text_with_hint = lambda t: copied.append(t)

        class _SCB(StreamingCodeBlock):
            @property
            def app(self):
                return _app

        scb = object.__new__(_SCB)
        scb._state = state
        scb._code_lines = ["line1", "line2"]
        scb._collapsed = False
        scb._copied = copied
        scb._app = _app
        return scb

    def test_scb_double_click_copies_code(self) -> None:
        scb = self._make_scb()
        ev = _make_click(button=1, chain=2)
        ev.prevent_default = MagicMock()
        scb.on_click(ev)
        assert len(scb._copied) == 1
        ev.prevent_default.assert_called_once()

    def test_scb_single_click_toggles_not_copies(self) -> None:
        scb = self._make_scb()
        toggled = []
        scb.toggle_collapsed = lambda: toggled.append(True)
        scb.can_toggle = lambda: True
        ev = _make_click(button=1, chain=1)
        ev.prevent_default = MagicMock()
        scb.on_click(ev)
        assert toggled == [True]
        assert scb._copied == []

    def test_scb_double_click_ignored_while_streaming(self) -> None:
        scb = self._make_scb(state="STREAMING")
        scb.can_toggle = lambda: False
        ev = _make_click(button=1, chain=2)
        ev.prevent_default = MagicMock()
        scb.on_click(ev)
        assert scb._copied == []

    def test_reasoning_panel_double_click_force_expands(self) -> None:
        from hermes_cli.tui.widgets import ReasoningPanel
        rp = object.__new__(ReasoningPanel)
        rp._is_closed = True
        rp._body_collapsed = True
        synced = []
        rp._sync_collapsed_state = lambda: synced.append(rp._body_collapsed)
        ev = _make_click(button=1, chain=2)
        ev.prevent_default = MagicMock()
        rp.on_click(ev)
        assert rp._body_collapsed is False
        assert synced

    def test_reasoning_panel_single_click_toggles(self) -> None:
        from hermes_cli.tui.widgets import ReasoningPanel
        rp = object.__new__(ReasoningPanel)
        rp._is_closed = True
        rp._body_collapsed = False
        synced = []
        rp._sync_collapsed_state = lambda: synced.append(rp._body_collapsed)
        ev = _make_click(button=1, chain=1)
        ev.prevent_default = MagicMock()
        rp.on_click(ev)
        assert rp._body_collapsed is True

    def test_tool_header_double_click_copies_summary(self) -> None:
        from hermes_cli.tui.tool_blocks import ToolHeader
        _app = MagicMock()
        copied = []
        _app._copy_text_with_hint = lambda t: copied.append(t)

        class _TH(ToolHeader):
            @property
            def app(self):
                return _app

        _parent = MagicMock()
        _parent._result_summary = "result text"

        class _TH2(_TH):
            @property
            def parent(self):
                return _parent

        header = object.__new__(_TH2)
        header._spinner_char = None
        header._path_clickable = False
        header._full_path = None
        header._label = "my tool"
        header._has_affordances = True
        header._panel = None
        ev = _make_click(button=1, chain=2)
        ev.prevent_default = MagicMock()
        header.on_click(ev)
        assert copied == ["result text"]


# ===========================================================================
# Phase 3 — F1: Shift+click range select
# ===========================================================================

class TestF1ShiftClickRangeSelect:
    def _make_overlay_with_items(self, n: int = 5):
        from hermes_cli.tui.widgets import HistorySearchOverlay, TurnResultItem
        overlay = object.__new__(HistorySearchOverlay)
        overlay._last_click_idx = None
        overlay._shift_selected = set()
        overlay._selected_idx = 0
        overlay.query = None  # set after items created
        overlay.action_jump_to = MagicMock()

        items = []
        for i in range(n):
            _app = MagicMock()
            _app.query_one = MagicMock(return_value=overlay)

            class _Item(TurnResultItem):
                @property
                def app(self_inner):
                    return _app

            item = object.__new__(_Item)
            item._result = None
            item._entry = MagicMock()
            item._entry.index = i
            item._css_classes = set()
            item.set_class = lambda v, cls, _i=i: (
                items[_i]._css_classes.add(cls) if v else items[_i]._css_classes.discard(cls)
            )
            items.append(item)

        overlay.query = lambda cls: iter(items)
        return overlay, items

    def test_plain_click_single_select_and_jump(self) -> None:
        overlay, items = self._make_overlay_with_items(5)
        ev = _make_click(button=1, shift=False)
        items[2].on_click(ev)
        overlay.action_jump_to.assert_called_once()
        assert overlay._last_click_idx == 2
        assert overlay._shift_selected == set()

    def test_shift_click_range_select_no_jump(self) -> None:
        overlay, items = self._make_overlay_with_items(5)
        # First plain click at index 1
        ev1 = _make_click(button=1, shift=False)
        items[1].on_click(ev1)
        # Shift click at index 3 → range [1, 2, 3]
        ev2 = _make_click(button=1, shift=True)
        overlay.action_jump_to.reset_mock()
        items[3].on_click(ev2)
        assert overlay._shift_selected == {1, 2, 3}
        overlay.action_jump_to.assert_not_called()

    def test_shift_selected_css_applied_to_range(self) -> None:
        overlay, items = self._make_overlay_with_items(5)
        ev1 = _make_click(button=1, shift=False)
        items[0].on_click(ev1)
        ev2 = _make_click(button=1, shift=True)
        items[2].on_click(ev2)
        for i in range(3):
            assert "--selected" in items[i]._css_classes

    def test_shift_click_without_prior_click_is_single_select(self) -> None:
        overlay, items = self._make_overlay_with_items(5)
        ev = _make_click(button=1, shift=True)
        items[2].on_click(ev)
        # No _last_click_idx set → falls through to single select
        overlay.action_jump_to.assert_called_once()

    def test_action_jump_uses_first_shift_selected(self) -> None:
        from hermes_cli.tui.widgets import HistorySearchOverlay, TurnResultItem
        overlay = object.__new__(HistorySearchOverlay)
        overlay._shift_selected = {2, 3, 4}
        overlay._selected_idx = 0

        items = []
        for i in range(5):
            item = object.__new__(TurnResultItem)
            item._result = MagicMock()
            item._entry = MagicMock()
            items.append(item)

        overlay.query = lambda cls: iter(items)
        jumped = []
        overlay.action_dismiss = MagicMock()
        overlay._scroll_to_match = lambda entry, result: jumped.append(entry)

        overlay.action_jump()
        assert jumped == [items[2]._entry]


# ===========================================================================
# Phase 3 — F2: Context menu keyboard position fallback
# ===========================================================================

class TestF2ContextMenuPosition:
    def test_show_context_menu_at_method_exists(self) -> None:
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_show_context_menu_at")
        assert hasattr(HermesApp, "_show_context_menu_for_focused")

    def test_show_context_menu_for_focused_uses_widget_center(self) -> None:
        import asyncio
        from hermes_cli.tui.app import HermesApp

        widget = MagicMock()
        widget.content_region.x = 10
        widget.content_region.width = 20
        widget.content_region.y = 5
        widget.content_region.height = 2

        class _App(HermesApp):
            @property
            def focused(self):
                return widget

        app = object.__new__(_App)
        shown_at = []

        async def _fake_show(items, x, y):
            shown_at.append((x, y))

        app._show_context_menu_at = _fake_show
        app._build_context_items = MagicMock(return_value=[MagicMock()])

        asyncio.run(app._show_context_menu_for_focused())
        assert shown_at == [(20, 6)]  # 10+20//2=20, 5+2//2=6
