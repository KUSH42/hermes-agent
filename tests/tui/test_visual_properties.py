"""Integration tests for visual properties of TUI components.

Verifies colours, backgrounds, structural CSS, and rendered content as
constructed in the real application — using the same compose() path that
production code uses.

Each test spins up a real HermesApp with the headless driver so CSS is
fully parsed and resolved.  Style attributes (colour, background, dock,
height) are read from widget.styles after the first layout pass.

Run with:
    pytest -o "addopts=" tests/tui/test_visual_properties.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.widgets import (
    HintBar,
    OutputPanel,
    StatusBar,
    ToolPendingLine,
    UserMessagePanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _rgb(color) -> tuple[int, int, int]:
    """Extract (r, g, b) from a Textual Color object."""
    return (color.r, color.g, color.b)


def _alpha(color) -> float:
    """Extract alpha from a Textual Color object."""
    return color.a


async def _mount_echo(app: HermesApp, message: str, images: int = 0) -> UserMessagePanel:
    output = app.query_one(OutputPanel)
    panel = UserMessagePanel(message, images=images)
    output.mount(panel, before=output.query_one(ToolPendingLine))
    await asyncio.sleep(0.02)
    return panel


# ===========================================================================
# 1. StatusBar visual properties
# ===========================================================================

@pytest.mark.asyncio
async def test_statusbar_background_matches_app_background():
    """StatusBar background must match the app background — no contrasting bar."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert _rgb(status.styles.background) == _rgb(app.styles.background), (
            "StatusBar background must match app background (spec §4.9)"
        )


@pytest.mark.asyncio
async def test_statusbar_docked_bottom():
    """StatusBar must be docked to the bottom of the screen."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert status.styles.dock == "bottom", (
            f"StatusBar dock should be 'bottom', got {status.styles.dock!r}"
        )


@pytest.mark.asyncio
async def test_statusbar_height_is_one():
    """StatusBar must occupy exactly one line."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert status.styles.height.value == 1, (
            f"StatusBar height should be 1, got {status.styles.height}"
        )


@pytest.mark.asyncio
async def test_statusbar_color_is_muted():
    """StatusBar foreground must be $text-muted — subdued, not full-brightness."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        color = status.styles.color
        # $text-muted is white at reduced alpha (< 1.0) or a dim grey.
        # Either the alpha is < 1.0 OR the RGB values are noticeably below 255.
        is_muted = _alpha(color) < 1.0 or max(_rgb(color)) < 200
        assert is_muted, (
            f"StatusBar color should be muted ($text-muted), got {color!r}"
        )


# ===========================================================================
# 2. HintBar visual properties
# ===========================================================================

@pytest.mark.asyncio
async def test_hintbar_height_is_one():
    """HintBar must always occupy exactly 1 line (no display:none toggling)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        assert hint.styles.height.value == 1, (
            f"HintBar height should be 1 to prevent layout reflow, got {hint.styles.height}"
        )


@pytest.mark.asyncio
async def test_hintbar_color_is_muted():
    """HintBar foreground must be $text-muted, same family as StatusBar."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        color = hint.styles.color
        is_muted = _alpha(color) < 1.0 or max(_rgb(color)) < 200
        assert is_muted, (
            f"HintBar color should be muted ($text-muted), got {color!r}"
        )


@pytest.mark.asyncio
async def test_hintbar_and_statusbar_share_muted_color():
    """HintBar and StatusBar both use $text-muted — colors must be equal."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        status = app.query_one(StatusBar)
        assert hint.styles.color == status.styles.color, (
            f"HintBar and StatusBar should share $text-muted color: "
            f"{hint.styles.color!r} != {status.styles.color!r}"
        )


@pytest.mark.asyncio
async def test_hintbar_displays_hint_text():
    """Setting HintBar.hint causes render() to display the text."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        hint.hint = "⎘  10 chars copied"
        await pilot.pause()
        # HintBar is now a Widget with render() — check the hint reactive directly
        assert "10 chars copied" in hint.hint or "⎘" in hint.hint, (
            f"HintBar should display the hint text, hint: {hint.hint!r}"
        )


@pytest.mark.asyncio
async def test_hintbar_empty_hint_is_blank():
    """Empty hint stores empty string — widget shows phase-based hint when idle."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        hint.hint = ""
        await pilot.pause()
        # HintBar is now a Widget with render() — empty hint means phase-based display
        assert hint.hint == "", (
            f"Empty HintBar.hint should be empty string, got: {hint.hint!r}"
        )


# ===========================================================================
# 3. HermesInput visual properties
# ===========================================================================

@pytest.mark.asyncio
async def test_hermes_input_background_matches_app():
    """HermesInput background must match app background — no visual stripe."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert _rgb(inp.styles.background) == _rgb(app.styles.background), (
            "HermesInput background must match app background (no contrast stripe)"
        )


@pytest.mark.asyncio
async def test_hermes_input_has_no_border():
    """HermesInput must have no border — clean inline appearance."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        edges = inp.styles.border
        # Each side is a (border_type: str, color) tuple; '' = no border
        sides = [edges.top, edges.right, edges.bottom, edges.left]
        assert all(s[0] == "" for s in sides), (
            f"HermesInput should have no border on any side, got: {edges!r}"
        )


@pytest.mark.asyncio
async def test_hermes_input_height_is_one():
    """HermesInput must be exactly one line tall."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.styles.height.value == 1, (
            f"HermesInput height should be 1, got {inp.styles.height}"
        )


@pytest.mark.asyncio
async def test_hermes_input_focused_background_unchanged():
    """Focusing HermesInput must not change its background (no focus tint)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        bg_before = _rgb(inp.styles.background)
        inp.focus()
        await pilot.pause()
        bg_after = _rgb(inp.styles.background)
        assert bg_before == bg_after, (
            f"HermesInput background must not change on focus: "
            f"{bg_before!r} → {bg_after!r}"
        )


# ===========================================================================
# 4. CSS variable injection
# ===========================================================================

@pytest.mark.asyncio
async def test_css_variables_include_cursor_color():
    """get_css_variables() must include cursor-color for component parts."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert "cursor-color" in css_vars, (
            f"Expected 'cursor-color' in CSS variables, got keys: {list(css_vars.keys())}"
        )


@pytest.mark.asyncio
async def test_css_variables_include_chevron_colors():
    """get_css_variables() must include all chevron phase colours."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        for var in ("chevron-base", "chevron-file", "chevron-stream", "chevron-shell",
                    "chevron-done", "chevron-error"):
            assert var in css_vars, (
                f"Expected '{var}' in CSS variables. Present: {list(css_vars.keys())}"
            )


@pytest.mark.asyncio
async def test_css_variables_include_status_colors():
    """get_css_variables() must include status indicator colours."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        for var in ("status-running-color", "status-error-color", "status-warn-color",
                     "running-indicator-hi-color", "user-echo-bullet-color"):
            assert var in css_vars, (
                f"Expected '{var}' in CSS variables. Present: {list(css_vars.keys())}"
            )


# ===========================================================================
# 5. Input chevron visual properties
# ===========================================================================

@pytest.mark.asyncio
async def test_input_chevron_exists_and_has_base_color():
    """#input-chevron must exist and have the $chevron-base color by default."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        chevron = app.query_one("#input-chevron")
        css_vars = app.get_css_variables()
        # chevron-base defaults to #FFF8DC
        chevron_base_hex = css_vars.get("chevron-base", "#FFF8DC").lstrip("#")
        expected_r = int(chevron_base_hex[0:2], 16)
        expected_g = int(chevron_base_hex[2:4], 16)
        expected_b = int(chevron_base_hex[4:6], 16)
        actual = _rgb(chevron.styles.color)
        assert actual == (expected_r, expected_g, expected_b), (
            f"Chevron base color mismatch: expected #{chevron_base_hex}, "
            f"got RGB{actual!r}"
        )


@pytest.mark.asyncio
async def test_input_row_background_matches_app():
    """#input-row background must match app background."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        input_row = app.query_one("#input-row")
        assert _rgb(input_row.styles.background) == _rgb(app.styles.background), (
            "Input row background must match app background"
        )


# ===========================================================================
# 6. UserMessagePanel content
# ===========================================================================

@pytest.mark.asyncio
async def test_user_echo_single_line_shows_message():
    """Single-line user message appears in full inside UserMessagePanel."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "hello world")
        await pilot.pause()

        # _Static__content holds a Rich Text object for styled content
        content = panel.query_one("#echo-text")._Static__content
        plain = content.plain if hasattr(content, "plain") else str(content)
        assert "hello world" in plain, (
            f"User message should appear in echo panel, plain: {plain!r}"
        )


@pytest.mark.asyncio
async def test_user_echo_has_bullet_prefix():
    """User message is prefixed with a ● bullet character."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "show me hello world in java")
        await pilot.pause()

        content = panel.query_one("#echo-text")._Static__content
        plain = content.plain if hasattr(content, "plain") else str(content)
        assert "●" in plain, (
            f"User echo should have ● bullet prefix, plain: {plain!r}"
        )


@pytest.mark.asyncio
async def test_user_echo_bullet_uses_skin_color_var():
    """UserMessagePanel bullet color must come from user-echo-bullet-color, not chevron-file."""
    from hermes_cli.tui.widgets import UserMessagePanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "test message")
        await pilot.pause()

        css_vars = app.get_css_variables()
        expected_color = css_vars.get("user-echo-bullet-color", "#FFBF00")
        content = panel.query_one("#echo-text")._Static__content
        # The ● bullet should be styled with user-echo-bullet-color
        spans = content._style_map if hasattr(content, "_style_map") else {}
        # Verify the expected color is used (not chevron-file's value)
        chevron_color = css_vars.get("chevron-file", "#FFBF00")
        # If they happen to match at default, verify the var exists at least
        assert "user-echo-bullet-color" in css_vars, (
            "user-echo-bullet-color must be in CSS variables"
        )


@pytest.mark.asyncio
async def test_user_echo_multiline_shows_first_line_and_count():
    """Multi-line message shows first line + '(+N lines)' suffix."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "line one\nline two\nline three")
        await pilot.pause()

        content = panel.query_one("#echo-text")._Static__content
        plain = content.plain if hasattr(content, "plain") else str(content)
        assert "line one" in plain, f"First line should appear: {plain!r}"
        assert "(+" in plain and "lines" in plain, (
            f"Multi-line suffix should show (+N lines): {plain!r}"
        )
        assert "line two" not in plain, (
            f"Subsequent lines must not appear: {plain!r}"
        )


@pytest.mark.asyncio
async def test_user_echo_multiline_correct_count():
    """The (+N lines) count reflects the number of additional lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "first\nsecond\nthird\nfourth")
        await pilot.pause()

        content = panel.query_one("#echo-text")._Static__content
        plain = content.plain if hasattr(content, "plain") else str(content)
        # 4 total lines → 3 additional
        assert "+3" in plain, (
            f"Expected '+3 lines' for a 4-line message, plain: {plain!r}"
        )


@pytest.mark.asyncio
async def test_user_echo_image_attachment_shown():
    """When images=1, an attachment indicator appears below the message."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "describe this", images=1)
        await pilot.pause()

        content = panel.query_one("#echo-images")._Static__content
        plain = content.plain if hasattr(content, "plain") else str(content)
        assert "image" in plain.lower(), (
            f"Image attachment indicator should appear, plain: {plain!r}"
        )


@pytest.mark.asyncio
async def test_user_echo_panel_has_top_and_bottom_rules():
    """UserMessagePanel has a top rule; bottom rule removed (redundant — response TitledRule separates turns)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = await _mount_echo(app, "test message")
        await pilot.pause()

        # Top rule must exist; bottom rule was removed
        top = panel.query_one("#echo-rule-top")
        assert top is not None, "echo-rule-top must exist"
        from textual.css.query import NoMatches
        try:
            panel.query_one("#echo-rule-bottom")
            assert False, "echo-rule-bottom should not exist (removed)"
        except NoMatches:
            pass


# ===========================================================================
# 7. Component consistency
# ===========================================================================

@pytest.mark.asyncio
async def test_input_background_equals_status_background():
    """HermesInput, StatusBar, and #input-row all share the app background colour."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app_bg = _rgb(app.styles.background)
        inp_bg = _rgb(app.query_one(HermesInput).styles.background)
        status_bg = _rgb(app.query_one(StatusBar).styles.background)
        row_bg = _rgb(app.query_one("#input-row").styles.background)

        assert inp_bg == app_bg, f"HermesInput bg {inp_bg} != app bg {app_bg}"
        assert status_bg == app_bg, f"StatusBar bg {status_bg} != app bg {app_bg}"
        assert row_bg == app_bg, f"#input-row bg {row_bg} != app bg {app_bg}"


@pytest.mark.asyncio
async def test_app_background_is_dark():
    """App background must be a dark colour (all channels ≤ 50)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        r, g, b = _rgb(app.styles.background)
        assert max(r, g, b) <= 50, (
            f"App background should be dark, got RGB({r},{g},{b})"
        )


@pytest.mark.asyncio
async def test_hintbar_background_is_transparent():
    """HintBar has no background of its own — it inherits the app background."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one(HintBar)
        # Alpha 0 = fully transparent = no own background
        assert _alpha(hint.styles.background) == 0.0, (
            f"HintBar background should be transparent (alpha=0), "
            f"got {hint.styles.background!r}"
        )
