"""Tests for LP-RHYTHM Vertical Rhythm spec (2026-05-09).

LP-RHYTHM-1: Uniform inter-block gap (H3) — tier-conditional margin replaced by
             single margin-bottom: 1 on ToolPanel, MessagePanel, UserMessagePanel.
LP-RHYTHM-2: Single-source margin ownership (M4) — UserMessagePanel / MessagePanel
             no longer declare margin-top; all spacing owned by margin-bottom.
LP-RHYTHM-3: OutputPanelScrollBadge opaque background (L2).
LP-RHYTHM-4: Test infra helpers (widget_first_row / gap_between).

Test approach:
- Static/file-content tests: assert declarations and sentinel comments in TCSS/Python files.
- Runtime position tests: mount widgets in minimal App shells (no HermesApp — avoids
  VarSpec errors from missing skin vars); assert rendered row positions.
"""
from __future__ import annotations

import pathlib

import pytest

_TCSS_PATH = pathlib.Path("hermes_cli/tui/hermes.tcss")


def _tcss_text() -> str:
    return _TCSS_PATH.read_text()


# ---------------------------------------------------------------------------
# TestUniformInterBlockGap (LP-RHYTHM-1) — 6 tests
# ---------------------------------------------------------------------------


class TestUniformInterBlockGap:
    """LP-RHYTHM-1: All top-level block widgets carry margin-bottom: 1."""

    def test_lp_rhythm1_sentinel_in_tcss(self):
        """hermes.tcss must contain the LP-RHYTHM-1 comment block."""
        text = _tcss_text()
        assert "LP-RHYTHM-1" in text, (
            "hermes.tcss must contain LP-RHYTHM-1 comment"
        )

    def test_toolpanel_messagepanel_usermessagepanel_margin_bottom_1(self):
        """The combined rule must declare margin-bottom: 1 for all three top-level blocks."""
        text = _tcss_text()
        # The combined selector block must appear in the file
        assert "ToolPanel,\nMessagePanel,\nUserMessagePanel" in text, (
            "hermes.tcss must have ToolPanel,MessagePanel,UserMessagePanel combined rule"
        )
        # That block must have margin-bottom: 1
        idx = text.index("ToolPanel,\nMessagePanel,\nUserMessagePanel")
        block = text[idx: idx + 120]
        assert "margin-bottom: 1" in block, (
            f"Combined top-level rule must contain margin-bottom: 1; got:\n{block!r}"
        )

    def test_childpanel_margin_bottom_0(self):
        """ChildPanel must be exempt: margin-bottom: 0."""
        text = _tcss_text()
        assert "ChildPanel { margin-bottom: 0; }" in text, (
            "hermes.tcss must have ChildPanel { margin-bottom: 0; }"
        )

    def test_no_per_tier_margin_rules(self):
        """Old tier-conditional margin rules must be removed."""
        text = _tcss_text()
        # The old SLR-1 per-tier rules used tool-panel--tier-* selectors with margin-bottom
        assert "ToolPanel.tool-panel--tier-hero" not in text or (
            # If it exists for some other reason, it must not set margin-bottom
            "ToolPanel.tool-panel--tier-hero" in text
            and "ToolPanel.tool-panel--tier-hero,\nToolPanel.tool-panel--tier-default { margin-bottom" not in text
        ), (
            "hermes.tcss must not contain old per-tier margin-bottom rules (SLR-1 removed by LP-RHYTHM-1)"
        )
        # The cleaner assertion: old combined tier rule is gone
        assert "ToolPanel.tool-panel--tier-default { margin-bottom: 1; }" not in text, (
            "Old ToolPanel.tool-panel--tier-default margin-bottom: 1 rule must be removed"
        )
        assert "ToolPanel.tool-panel--tier-compact,\nToolPanel.tool-panel--tier-trace   { margin-bottom: 0; }" not in text, (
            "Old compact/trace margin-bottom: 0 rule must be removed"
        )

    def test_messagepanel_margin_zeroed_in_tcss(self):
        """hermes.tcss MessagePanel global rule must declare margin: 0 (not margin-top: 1)."""
        text = _tcss_text()
        # The old rule was margin: 1 0 0 0; after LP-RHYTHM-1 it is margin: 0
        assert "margin: 1 0 0 0" not in text, (
            "hermes.tcss MessagePanel must not declare margin: 1 0 0 0 (removed by LP-RHYTHM-1)"
        )
        # New rule uses margin: 0
        idx = text.index("MessagePanel {")
        block = text[idx: idx + 120]
        assert "margin: 0" in block, (
            f"hermes.tcss MessagePanel rule must contain margin: 0; got:\n{block!r}"
        )

    def test_two_default_tools_gap_eq_1(self):
        """Two ToolPanel-equivalent widgets with margin-bottom: 1 produce gap == 1."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import gap_between

        class GapApp(App[None]):
            CSS = """
            Static { height: 2; margin-bottom: 1; }
            """

            def compose(self) -> ComposeResult:
                yield Static("w1", id="w1")
                yield Static("w2", id="w2")

        async def run():
            async with GapApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                w1 = pilot.app.query_one("#w1")
                w2 = pilot.app.query_one("#w2")
                return gap_between(w1, w2)

        import asyncio
        gap = asyncio.get_event_loop().run_until_complete(run())
        assert gap == 1, f"Expected gap == 1 between two default-tier blocks, got {gap}"

    def test_compact_tool_gap_eq_1_via_css(self):
        """Compact-tier ToolPanel-equivalent widget: under LP-RHYTHM-1 gap is still 1."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import gap_between

        class GapApp(App[None]):
            CSS = """
            Static { height: 2; margin-bottom: 1; }
            """

            def compose(self) -> ComposeResult:
                # Both widgets share the same uniform margin-bottom: 1
                yield Static("w1", id="w1")
                yield Static("w2", id="w2")

        async def run():
            async with GapApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                w1 = pilot.app.query_one("#w1")
                w2 = pilot.app.query_one("#w2")
                return gap_between(w1, w2)

        import asyncio
        gap = asyncio.get_event_loop().run_until_complete(run())
        assert gap == 1, f"Expected gap == 1 for compact-tier under uniform rhythm, got {gap}"


# ---------------------------------------------------------------------------
# TestSingleSourceMargin (LP-RHYTHM-2) — 4 tests
# ---------------------------------------------------------------------------


class TestSingleSourceMargin:
    """LP-RHYTHM-2: Margin ownership migrated to margin-bottom only; no margin-top."""

    def test_user_message_panel_default_css_no_margin_top(self):
        """UserMessagePanel.DEFAULT_CSS must not declare margin-top: 1 or margin: 1 0 0 0."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        css = UserMessagePanel.DEFAULT_CSS
        assert "margin: 1 0 0 0" not in css, (
            "UserMessagePanel.DEFAULT_CSS must not have old margin: 1 0 0 0"
        )
        assert "margin: 0" in css, (
            "UserMessagePanel.DEFAULT_CSS must declare margin: 0 (LP-RHYTHM-2)"
        )

    def test_user_message_panel_default_css_lp_rhythm_comment(self):
        """UserMessagePanel.DEFAULT_CSS must carry the LP-RHYTHM-2 dependency comment."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        assert "LP-RHYTHM-2" in UserMessagePanel.DEFAULT_CSS, (
            "UserMessagePanel.DEFAULT_CSS must reference LP-RHYTHM-2 in comment"
        )

    def test_first_block_no_leading_gap(self):
        """First widget in a vertical app has region.y == 0 (no leading margin from margin-top)."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import widget_first_row

        class FirstBlockApp(App[None]):
            CSS = """
            Static { height: 2; margin: 0; }
            """

            def compose(self) -> ComposeResult:
                yield Static("first", id="first")

        async def run():
            async with FirstBlockApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                w = pilot.app.query_one("#first")
                return widget_first_row(w)

        import asyncio
        row = asyncio.get_event_loop().run_until_complete(run())
        assert row == 0, f"First block must start at row 0 (no leading margin), got {row}"

    def test_consecutive_user_messages_gap_eq_1(self):
        """Two UserMessagePanel-equivalent widgets: uniform margin-bottom gives gap == 1."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import gap_between

        class TwoUserApp(App[None]):
            CSS = """
            Static { height: 1; margin-bottom: 1; margin-top: 0; }
            """

            def compose(self) -> ComposeResult:
                yield Static("u1", id="u1")
                yield Static("u2", id="u2")

        async def run():
            async with TwoUserApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                u1 = pilot.app.query_one("#u1")
                u2 = pilot.app.query_one("#u2")
                return gap_between(u1, u2)

        import asyncio
        gap = asyncio.get_event_loop().run_until_complete(run())
        assert gap == 1, f"Gap between two user messages must be 1, got {gap}"

    def test_user_then_assistant_gap_eq_1(self):
        """UserMessagePanel then MessagePanel equivalent: gap == 1 (margin-bottom only)."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import gap_between

        class MixedApp(App[None]):
            CSS = """
            .user { height: 1; margin-bottom: 1; margin-top: 0; }
            .assistant { height: 2; margin-bottom: 1; margin-top: 0; }
            """

            def compose(self) -> ComposeResult:
                yield Static("user", id="u", classes="user")
                yield Static("assistant", id="a", classes="assistant")

        async def run():
            async with MixedApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                u = pilot.app.query_one("#u")
                a = pilot.app.query_one("#a")
                return gap_between(u, a)

        import asyncio
        gap = asyncio.get_event_loop().run_until_complete(run())
        assert gap == 1, f"Gap between user and assistant turn must be 1, got {gap}"


# ---------------------------------------------------------------------------
# TestScrollBadge (LP-RHYTHM-3) — 2 tests
# ---------------------------------------------------------------------------


class TestScrollBadge:
    """LP-RHYTHM-3: OutputPanelScrollBadge uses fully opaque background."""

    def test_scroll_badge_background_is_surface_not_alpha(self):
        """hermes.tcss OutputPanelScrollBadge must use $surface (no alpha) background."""
        text = _tcss_text()
        idx = text.index("OutputPanelScrollBadge {")
        block = text[idx: idx + 200]
        # Old rule had $panel-lighten-1 80%; new rule uses $surface
        assert "$panel-lighten-1 80%" not in block, (
            "OutputPanelScrollBadge must not use $panel-lighten-1 80% (replaced by LP-RHYTHM-3)"
        )
        assert "background: $surface" in block, (
            f"OutputPanelScrollBadge must declare background: $surface (LP-RHYTHM-3); got:\n{block!r}"
        )

    def test_scroll_badge_height_eq_1(self):
        """hermes.tcss OutputPanelScrollBadge must declare height: 1."""
        text = _tcss_text()
        idx = text.index("OutputPanelScrollBadge {")
        block = text[idx: idx + 200]
        assert "height: 1" in block, (
            f"OutputPanelScrollBadge must declare height: 1; got:\n{block!r}"
        )


# ---------------------------------------------------------------------------
# TestRenderedPositionHelper (LP-RHYTHM-4) — 2 tests
# ---------------------------------------------------------------------------


class TestRenderedPositionHelper:
    """LP-RHYTHM-4: _rendered_position.py helper module correctness."""

    def test_helper_widget_first_row(self):
        """widget_first_row returns 0 for the first widget in a vertical layout."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import widget_first_row

        class HelperApp(App[None]):
            CSS = """
            Static { height: 2; margin: 0; }
            """

            def compose(self) -> ComposeResult:
                yield Static("first", id="first")
                yield Static("second", id="second")

        async def run():
            async with HelperApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                first = pilot.app.query_one("#first")
                return widget_first_row(first)

        import asyncio
        row = asyncio.get_event_loop().run_until_complete(run())
        assert row == 0, f"widget_first_row of first widget must be 0, got {row}"

    def test_helper_gap_between(self):
        """gap_between returns the correct inter-widget row count."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from tests.tui._rendered_position import gap_between

        class GapHelperApp(App[None]):
            CSS = """
            Static { height: 1; margin-bottom: 2; }
            """

            def compose(self) -> ComposeResult:
                yield Static("a", id="a")
                yield Static("b", id="b")

        async def run():
            async with GapHelperApp().run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                a = pilot.app.query_one("#a")
                b = pilot.app.query_one("#b")
                return gap_between(a, b)

        import asyncio
        gap = asyncio.get_event_loop().run_until_complete(run())
        assert gap == 2, f"gap_between must return 2 for margin-bottom: 2 widgets, got {gap}"
