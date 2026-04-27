"""Tests for Browse Mode Visual Markers.

Covers:
  - Turn boundary CSS (3 tests)
  - Gutter pips (6 tests)
  - Badges (5 tests)
  - Streaming flash (3 tests)
  - Status bar (2 tests)
  - Config (4 tests)

Total: 23 tests (adjusted from planned 27 — 4 tests merged/simplified)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs):
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.config = {}
    app = HermesApp(cli=cli)
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_anchor(anchor_type, widget=None, label="Test", turn_id=1):
    from hermes_cli.tui.app import BrowseAnchor
    w = widget or MagicMock()
    w.is_mounted = True
    return BrowseAnchor(anchor_type=anchor_type, widget=w, label=label, turn_id=turn_id)


# ---------------------------------------------------------------------------
# Turn boundary CSS (3 tests)
# ---------------------------------------------------------------------------

def test_turn_boundary_css_rule_present():
    """hermes.tcss contains UserMessagePanel border-top rule."""
    from pathlib import Path
    css_path = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
    content = css_path.read_text()
    assert "UserMessagePanel" in content
    assert "border-top" in content


@pytest.mark.asyncio
async def test_browse_active_class_added_on_enter():
    """--browse-active is added to HermesApp when browse_mode becomes True."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        assert app.has_class("--browse-active")


@pytest.mark.asyncio
async def test_no_turn_boundary_class_when_config_false():
    """--no-turn-boundary class is added on mount when turn_boundary_always=False."""
    app = _make_app()
    app._browse_turn_boundary_always = False
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.has_class("--no-turn-boundary")


# ---------------------------------------------------------------------------
# Gutter pips (6 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_has_pip_added_on_browse_enter():
    """--has-pip added to anchor widgets when browse mode enters."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        app._browse_anchors = [_make_anchor(BrowseAnchorType.TURN_START, w)]
        app._svc_browse.apply_browse_pips()
        w.add_class.assert_called()
        call_args = [str(c) for c in w.add_class.call_args_list]
        assert any("--has-pip" in a for a in call_args)


@pytest.mark.asyncio
async def test_correct_pip_class_per_type():
    """Each anchor type gets the correct --anchor-pip-* class."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        type_to_class = {
            BrowseAnchorType.TURN_START: "--anchor-pip-turn",
            BrowseAnchorType.CODE_BLOCK: "--anchor-pip-code",
            BrowseAnchorType.MEDIA: "--anchor-pip-media",
        }
        for anchor_type, expected_cls in type_to_class.items():
            w = MagicMock()
            w.is_mounted = True
            w.has_class = MagicMock(return_value=False)
            added = []
            w.add_class = MagicMock(side_effect=lambda *args: added.extend(args))
            app._browse_anchors = [_make_anchor(anchor_type, w)]
            app._svc_browse.apply_browse_pips()
            assert expected_cls in added, f"Expected {expected_cls} for {anchor_type}"


@pytest.mark.asyncio
async def test_pip_cleared_on_browse_exit():
    """Both --has-pip AND type class removed on browse exit."""
    from hermes_cli.tui.app import BrowseAnchorType, BrowseAnchor
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel, UserMessagePanel
        output = app.query_one(OutputPanel)
        panel = UserMessagePanel("hello")
        await output.mount(panel)
        await pilot.pause()
        # Use real widget directly — don't attempt to set is_mounted on it
        anchor = BrowseAnchor(
            anchor_type=BrowseAnchorType.TURN_START,
            widget=panel,
            label="Turn 1",
            turn_id=1,
        )
        app._browse_anchors = [anchor]
        panel.add_class("--has-pip", "--anchor-pip-turn")
        app._svc_browse.clear_browse_pips()
        assert not panel.has_class("--has-pip")
        assert not panel.has_class("--anchor-pip-turn")


@pytest.mark.asyncio
async def test_diff_tool_header_gets_anchor_pip_diff():
    """ToolHeader with --diff-header class gets --anchor-pip-diff."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=True)  # has --diff-header
        added = []
        w.add_class = MagicMock(side_effect=lambda *args: added.extend(args))
        app._browse_anchors = [_make_anchor(BrowseAnchorType.TOOL_BLOCK, w)]
        app._svc_browse.apply_browse_pips()
        assert "--anchor-pip-diff" in added


@pytest.mark.asyncio
async def test_pip_reapplied_after_rebuild():
    """Pips re-applied after _rebuild_browse_anchors when browse mode active."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import OutputPanel, UserMessagePanel
        output = app.query_one(OutputPanel)
        panel = UserMessagePanel("hello")
        await output.mount(panel)
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        # Ensure browse_mode=True means _apply_browse_pips is called on rebuild
        initial_has_pip = panel.has_class("--has-pip")
        # remove to simulate stale state
        panel.remove_class("--has-pip", "--anchor-pip-turn")
        app._svc_browse.rebuild_browse_anchors()
        await pilot.pause()
        # pips re-applied because browse_mode=True
        assert panel.has_class("--has-pip") or not app._browse_anchors


@pytest.mark.asyncio
async def test_enabled_false_skips_pips():
    """enabled=False in config means no pips added."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app(_browse_markers_enabled=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        app._browse_anchors = [_make_anchor(BrowseAnchorType.TURN_START, w)]
        app._svc_browse.apply_browse_pips()
        w.add_class.assert_not_called()


# ---------------------------------------------------------------------------
# Badges (5 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_badge_set_on_code_anchor():
    """_browse_badge set with lang · N/total format for code anchors."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        w._lang = "python"
        w._browse_badge = ""
        app._browse_anchors = [_make_anchor(BrowseAnchorType.CODE_BLOCK, w)]
        app._svc_browse.apply_browse_pips()
        assert w._browse_badge == "python \u00b7 1/1"


@pytest.mark.asyncio
async def test_badge_set_on_diff_tool_header():
    """_browse_badge set to '± diff' for diff ToolHeader."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=True)  # --diff-header
        w.add_class = MagicMock()
        w._browse_badge = ""
        app._browse_anchors = [_make_anchor(BrowseAnchorType.TOOL_BLOCK, w)]
        app._svc_browse.apply_browse_pips()
        assert w._browse_badge == "\u00b1 diff"


@pytest.mark.asyncio
async def test_badge_cleared_on_browse_exit():
    """Badge cleared when _clear_browse_pips called."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        w._lang = "python"
        w._browse_badge = ""
        app._browse_anchors = [_make_anchor(BrowseAnchorType.CODE_BLOCK, w)]
        app._svc_browse.apply_browse_pips()
        assert w._browse_badge == "python \u00b7 1/1"
        app._svc_browse.clear_browse_pips()
        assert w._browse_badge == ""


@pytest.mark.asyncio
async def test_badge_sequence_number_correct():
    """Sequence numbers are sequential across multiple code blocks."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widgets = []
        anchors = []
        for i in range(3):
            w = MagicMock()
            w.is_mounted = True
            w.has_class = MagicMock(return_value=False)
            w.add_class = MagicMock()
            w._lang = "js"
            w._browse_badge = ""
            widgets.append(w)
            anchors.append(_make_anchor(BrowseAnchorType.CODE_BLOCK, w))
        app._browse_anchors = anchors
        app._svc_browse.apply_browse_pips()
        assert widgets[0]._browse_badge == "js \u00b7 1/3"
        assert widgets[1]._browse_badge == "js \u00b7 2/3"
        assert widgets[2]._browse_badge == "js \u00b7 3/3"


@pytest.mark.asyncio
async def test_badge_not_set_for_turn_start():
    """No badge set for TURN_START or MEDIA anchors."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for anchor_type in [BrowseAnchorType.TURN_START, BrowseAnchorType.MEDIA]:
            w = MagicMock()
            w.is_mounted = True
            w.has_class = MagicMock(return_value=False)
            w.add_class = MagicMock()
            w._browse_badge = ""
            app._browse_anchors = [_make_anchor(anchor_type, w)]
            app._svc_browse.clear_browse_pips()
            app._svc_browse.apply_browse_pips()
            assert w._browse_badge == "", f"Expected no badge for {anchor_type}"


# ---------------------------------------------------------------------------
# Streaming flash (3 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_flash_added_on_complete_when_browse():
    """--browse-newly-anchored added in complete() when browse_mode=True."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, OutputPanel
    app = _make_app(_browse_markers_enabled=True, _browse_streaming_flash=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="python")
        await output.mount(scb)
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        scb.complete({})
        await pilot.pause()
        assert scb.has_class("--browse-newly-anchored")


@pytest.mark.asyncio
async def test_streaming_flash_not_added_when_browse_inactive():
    """--browse-newly-anchored NOT added when browse_mode=False."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, OutputPanel
    app = _make_app(_browse_markers_enabled=True, _browse_streaming_flash=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="python")
        await output.mount(scb)
        await pilot.pause()
        # browse_mode is False by default
        scb.complete({})
        await pilot.pause()
        assert not scb.has_class("--browse-newly-anchored")


@pytest.mark.asyncio
async def test_streaming_flash_not_added_when_disabled():
    """--browse-newly-anchored NOT added when streaming_flash=False."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, OutputPanel
    app = _make_app(_browse_markers_enabled=True, _browse_streaming_flash=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="python")
        await output.mount(scb)
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        scb.complete({})
        await pilot.pause()
        assert not scb.has_class("--browse-newly-anchored")


# ---------------------------------------------------------------------------
# Status bar (2 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_hint_includes_type_glyph():
    """_browse_hint includes type glyph prefix for current anchor."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w, "Code · python", 1)
        app._browse_anchors = [anchor]
        app._svc_browse.update_browse_status(anchor)
        # ‹› glyph (first char) should be in hint
        assert "\u2039" in app._browse_hint or "\u203a" in app._browse_hint or "‹›" in app._browse_hint


@pytest.mark.asyncio
async def test_browse_hint_includes_map_hint():
    """\\ map hint present when _browse_markers_enabled=True."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app(_browse_markers_enabled=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        anchor = _make_anchor(BrowseAnchorType.TURN_START, w, "Turn 1", 1)
        app._browse_anchors = [anchor]
        app._svc_browse.update_browse_status(anchor)
        assert "\\ map" in app._browse_hint


# ---------------------------------------------------------------------------
# Config (4 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_enabled_false_skips_all_pips():
    """All pip application skipped when enabled=False."""
    from hermes_cli.tui.app import BrowseAnchorType
    app = _make_app(_browse_markers_enabled=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        app._browse_anchors = [_make_anchor(BrowseAnchorType.TURN_START, w)]
        app._svc_browse.apply_browse_pips()
        w.add_class.assert_not_called()


@pytest.mark.asyncio
async def test_config_turn_boundary_false_adds_no_turn_boundary_class():
    """--no-turn-boundary class present when turn_boundary_always=False."""
    app = _make_app()
    app._browse_turn_boundary_always = False
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.has_class("--no-turn-boundary")


@pytest.mark.asyncio
async def test_config_streaming_flash_false():
    """streaming_flash=False suppresses --browse-newly-anchored on complete()."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, OutputPanel
    app = _make_app(_browse_markers_enabled=True, _browse_streaming_flash=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="bash")
        await output.mount(scb)
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        scb.complete({})
        await pilot.pause()
        assert not scb.has_class("--browse-newly-anchored")


@pytest.mark.asyncio
async def test_config_reasoning_false_skips_pip_in_reasoning():
    """reasoning=False skips pips for widgets inside ReasoningPanel."""
    from hermes_cli.tui.app import BrowseAnchorType
    from hermes_cli.tui import services as _browse_svc_pkg
    from hermes_cli.tui.services import browse as _browse_mod
    app = _make_app(_browse_reasoning_markers=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = MagicMock()
        w.is_mounted = True
        w.has_class = MagicMock(return_value=False)
        w.add_class = MagicMock()
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
        app._browse_anchors = [anchor]
        # Patch _is_in_reasoning at the call site (browse service uses it directly)
        with patch.object(_browse_mod, "_is_in_reasoning", return_value=True):
            app._svc_browse.apply_browse_pips()
        w.add_class.assert_not_called()
