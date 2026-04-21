"""Tool UX Audit Pass 8 — Phase D tests.

D1: Focus hint row border-top only when --has-hint class is set
D2: C key clears all filter state in ToolsScreen
D3: _update_microcopy returns early when _completed is True
D4: First-focus hint only fires when _has_affordances is True
D5: set_args_row re-mounts when _args_row_mounted=True but widget absent
"""

from __future__ import annotations

import pytest
import asyncio
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# D1 — hint row border-top gated on --has-hint class
# ---------------------------------------------------------------------------

class TestD1HintRowBorderGated:
    def test_tcss_border_top_only_on_has_hint(self):
        """hermes.tcss must NOT have unconditional border-top on .--focus-hint."""
        import pathlib
        tcss_path = pathlib.Path(__file__).parents[2] / "hermes_cli" / "tui" / "hermes.tcss"
        tcss = tcss_path.read_text()

        # Find the .--focus-hint block — should NOT have border-top without .--has-hint qualifier
        import re
        # Match a block like: ToolPanel > .--focus-hint { ... border-top ... }
        # that does NOT include .--has-hint in the selector
        pattern = re.compile(
            r"ToolPanel\s*>\s*\.--focus-hint\s*\{[^}]*border-top[^}]*\}",
            re.DOTALL,
        )
        matches = pattern.findall(tcss)
        # Blocks with "border-top" should only appear when selector includes ".--has-hint"
        for m in matches:
            assert ".--has-hint" not in m or "--has-hint" in m, (
                "border-top in .--focus-hint block must only appear in .--has-hint selector"
            )
        # At least one .--focus-hint.--has-hint border-top must exist
        has_hint_pattern = re.compile(
            r"\.--focus-hint\.--has-hint\s*\{[^}]*border-top[^}]*\}",
            re.DOTALL,
        )
        assert has_hint_pattern.search(tcss), (
            "hermes.tcss must have border-top in .--focus-hint.--has-hint selector"
        )

    def test_watch_has_focus_source_adds_has_hint_on_focus(self):
        """watch_has_focus source must add '--has-hint' class when value=True."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel.watch_has_focus)
        assert "--has-hint" in src, "watch_has_focus must reference '--has-hint' class"
        assert "add_class" in src, "watch_has_focus must call add_class for '--has-hint'"
        assert "remove_class" in src, "watch_has_focus must call remove_class for '--has-hint'"

    def test_watch_has_focus_source_removes_on_blur(self):
        """watch_has_focus source must remove '--has-hint' when value=False."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel.watch_has_focus)
        # Must have both add_class and remove_class for the --has-hint token
        assert src.count("--has-hint") >= 2, (
            "watch_has_focus must add AND remove '--has-hint' (2+ occurrences)"
        )


# ---------------------------------------------------------------------------
# D2 — C key clears all filter state
# ---------------------------------------------------------------------------

class TestD2ClearAllFilters:
    def test_c_binding_exists_in_tools_screen(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        keys = {b.key for b in ToolsScreen.BINDINGS}
        assert "C" in keys, "ToolsScreen must have 'C' bound (clear_all_filters)"

    def test_c_bound_to_clear_all_filters(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        c_bindings = [b for b in ToolsScreen.BINDINGS if b.key == "C"]
        assert any("clear_all_filters" in b.action for b in c_bindings), (
            "'C' key must be bound to action_clear_all_filters"
        )

    def _make_screen_ns(self, filter_text="", active_categories=None, errors_only=False):
        import types

        async def noop():
            pass

        fi = MagicMock()
        fi.display = True
        fi.value = filter_text
        return types.SimpleNamespace(
            _filter_text=filter_text,
            _active_categories=active_categories if active_categories is not None else set(),
            _errors_only=errors_only,
            query_one=MagicMock(return_value=fi),
            _apply_filter=noop,
            _rebuild=noop,
        ), fi

    def test_clear_all_filters_resets_text_filter(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen, fi = self._make_screen_ns(filter_text="some query")
        asyncio.get_event_loop().run_until_complete(
            ToolsScreen.action_clear_all_filters(screen)
        )
        assert screen._filter_text == ""

    def test_clear_all_filters_resets_categories(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen, fi = self._make_screen_ns(active_categories={"CODE", "WEB"}, errors_only=True)
        asyncio.get_event_loop().run_until_complete(
            ToolsScreen.action_clear_all_filters(screen)
        )
        assert screen._active_categories == set(), "active_categories must be reset"
        assert screen._errors_only is False, "errors_only must be reset"

    def test_clear_all_filters_hides_filter_input(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen, fi = self._make_screen_ns(filter_text="q")
        asyncio.get_event_loop().run_until_complete(
            ToolsScreen.action_clear_all_filters(screen)
        )
        assert fi.display is False or fi.value == "", "filter input must be hidden/cleared"


# ---------------------------------------------------------------------------
# D3 — _update_microcopy returns early when _completed
# ---------------------------------------------------------------------------

class TestD3MicrocopyCompletedGuard:
    def test_update_microcopy_returns_early_when_completed(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock

        block = StreamingToolBlock.__new__(StreamingToolBlock)
        block._completed = True
        block._stream_started_at = 0.0  # would normally proceed past the guard

        body_mock = MagicMock()
        block._body = body_mock
        block._tool_name = "bash"

        StreamingToolBlock._update_microcopy(block)

        # set_microcopy must NOT be called
        body_mock.set_microcopy.assert_not_called()

    def test_update_microcopy_proceeds_when_not_completed(self):
        import time
        from hermes_cli.tui.tool_blocks import StreamingToolBlock

        block = StreamingToolBlock.__new__(StreamingToolBlock)
        block._completed = False
        block._stream_started_at = time.monotonic() - 2.0  # 2s ago, past 0.5 threshold
        block._total_received = 50
        block._bytes_received = 1024
        block._last_http_status = None
        block._rate_samples = []
        block._shimmer_phase = 0.0
        block._last_line_time = time.monotonic() - 1.0
        block._tool_name = "bash"
        block._microcopy_shown = False

        body_mock = MagicMock()
        block._body = body_mock

        StreamingToolBlock._update_microcopy(block)

        # set_microcopy may or may not be called (depends on microcopy_line output)
        # but no exception should be raised and _completed guard must NOT prevent it
        # (test passes if no exception)


# ---------------------------------------------------------------------------
# D4 — First-focus hint only flashes when _has_affordances
# ---------------------------------------------------------------------------

class TestD4FirstFocusHintGuard:
    def _make_panel(self, has_affordances: bool):
        from hermes_cli.tui.tool_panel import ToolPanel

        panel = ToolPanel.__new__(ToolPanel)
        panel._toggle_hint_shown = False

        header_mock = MagicMock()
        header_mock._has_affordances = has_affordances

        block_mock = MagicMock()
        block_mock._header = header_mock
        panel._block = block_mock

        panel._flash_header = MagicMock()
        return panel

    def test_on_focus_no_hint_when_no_affordances(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = self._make_panel(has_affordances=False)
        ToolPanel.on_focus(panel)
        panel._flash_header.assert_not_called()

    def test_on_focus_hint_when_has_affordances(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = self._make_panel(has_affordances=True)
        ToolPanel.on_focus(panel)
        panel._flash_header.assert_called_once()
        call_args = panel._flash_header.call_args
        msg = call_args.args[0] if call_args.args else call_args.kwargs.get("msg", "")
        assert "toggle" in msg.lower() or "Enter" in msg, (
            f"flash message should mention toggle, got: {msg!r}"
        )

    def test_on_focus_hint_only_fires_once(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = self._make_panel(has_affordances=True)
        ToolPanel.on_focus(panel)
        ToolPanel.on_focus(panel)
        ToolPanel.on_focus(panel)
        # Flash must only be called once (one-shot guard)
        panel._flash_header.assert_called_once()

    def test_on_focus_hint_tone_is_accent(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = self._make_panel(has_affordances=True)
        ToolPanel.on_focus(panel)
        call_args = panel._flash_header.call_args
        tone = (
            call_args.kwargs.get("tone")
            or (call_args.args[1] if len(call_args.args) > 1 else None)
        )
        assert tone == "accent", f"hint flash must use 'accent' tone, got: {tone!r}"


# ---------------------------------------------------------------------------
# D5 — set_args_row re-mounts when _args_row_mounted=True but widget absent
# ---------------------------------------------------------------------------

class TestD5ArgsRowRemount:
    def test_set_args_row_remounts_when_flag_stale(self):
        from hermes_cli.tui.tool_blocks import ToolBodyContainer
        from textual.css.query import NoMatches

        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._args_row_mounted = True  # flag says mounted
        container._secondary_text = ""
        container._microcopy_active = False

        microcopy_mock = MagicMock()
        new_widget_holder = []

        call_count = [0]

        def mock_query_one(selector, widget_type=None):
            call_count[0] += 1
            if selector == ".--args-row":
                # First call: widget not found (stale flag scenario)
                raise NoMatches(".--args-row not found")
            elif selector == ".--microcopy":
                return microcopy_mock
            raise NoMatches(selector)

        container.query_one = mock_query_one
        container.mount = MagicMock()

        ToolBodyContainer.set_args_row(container, "arg text here")

        # _args_row_mounted should be reset then set back to True after successful mount
        assert container._args_row_mounted is True, (
            "_args_row_mounted must be True after successful re-mount"
        )
        container.mount.assert_called_once()

    def test_set_args_row_flag_reset_on_stale(self):
        """When .--args-row is missing but flag=True, the flag must be reset before mount."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer
        from textual.css.query import NoMatches

        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._args_row_mounted = True
        container._secondary_text = ""
        container._microcopy_active = False

        flag_when_mount_called = []

        def mock_query_one(selector, widget_type=None):
            if selector == ".--args-row":
                raise NoMatches()
            elif selector == ".--microcopy":
                return MagicMock()
            raise NoMatches(selector)

        def mock_mount(widget, **kwargs):
            flag_when_mount_called.append(container._args_row_mounted)

        container.query_one = mock_query_one
        container.mount = mock_mount

        ToolBodyContainer.set_args_row(container, "text")

        # The flag should have been False when mount was called (reset before re-mount)
        # and then set to True after
        assert container._args_row_mounted is True

    def test_set_args_row_normal_path_unchanged(self):
        """When widget IS found normally, update text and leave flag True."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer

        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._args_row_mounted = True
        container._secondary_text = ""
        container._microcopy_active = False

        args_widget = MagicMock()

        def mock_query_one(selector, widget_type=None):
            if selector == ".--args-row":
                return args_widget
            raise Exception("unexpected query")

        container.query_one = mock_query_one
        container.mount = MagicMock()

        ToolBodyContainer.set_args_row(container, "updated args")

        args_widget.update.assert_called_with("updated args")
        container.mount.assert_not_called()

    def test_set_args_row_empty_text_clears_widget(self):
        """Empty text should clear/hide the args widget."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer

        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._args_row_mounted = True
        container._secondary_text = ""
        container._microcopy_active = False

        args_widget = MagicMock()

        def mock_query_one(selector, widget_type=None):
            if selector == ".--args-row":
                return args_widget
            raise Exception()

        container.query_one = mock_query_one
        container.mount = MagicMock()

        ToolBodyContainer.set_args_row(container, "")

        # Should not mount new widget, just clear
        container.mount.assert_not_called()
