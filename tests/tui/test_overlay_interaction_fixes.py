"""Tests for OVERLAY-1/2/3 overlay interaction fixes spec."""

from __future__ import annotations

import ast
import inspect

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from hermes_cli.tui.overlays import ConfigOverlay, InterruptOverlay
from hermes_cli.tui.overlays.interrupt import InputSpec, InterruptKind, InterruptPayload


# ── Shared app fixtures ──────────────────────────────────────────────────────


class _ConfigApp(App):
    def compose(self) -> ComposeResult:
        yield ConfigOverlay(id="cfg")


class _InterruptApp(App):
    def compose(self) -> ComposeResult:
        yield InterruptOverlay(id="io")


# ── OVERLAY-1: No unwired option buttons ─────────────────────────────────────


class TestConfigOverlayNoOpControls:
    def test_config_overlay_has_no_unrouted_option_buttons(self):
        src = inspect.getsource(ConfigOverlay)
        for disallowed in ("co-bold-", "co-cur-", "co-anim-", "co-spin-"):
            assert disallowed not in src, (
                f"Found disallowed button id prefix '{disallowed}' in ConfigOverlay source"
            )

    def test_config_overlay_tab_hotkeys_are_contiguous_after_options_removed(self):
        from hermes_cli.tui.overlays.config import _TABS
        hotkeys = [int(t[1]) for t in _TABS]
        assert hotkeys == list(range(1, len(_TABS) + 1)), (
            f"_TABS hotkeys not contiguous 1..{len(_TABS)}: {hotkeys}"
        )
        assert len(_TABS) == 6

    def test_config_overlay_button_handler_has_no_stopped_noop_ids(self):
        src = inspect.getsource(ConfigOverlay)
        tree = ast.parse(src)

        # Collect all Button(..., id=...) call id= kwargs from entire class source.
        button_compose_ids: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name == "Button":
                    for kw in node.keywords:
                        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                            button_compose_ids.add(kw.value.value)

        assert button_compose_ids == {"co-yolo-enable", "co-yolo-disable", "co-yolo-cancel"}, (
            f"Expected only YOLO button IDs, got: {button_compose_ids}"
        )


# ── OVERLAY-2: New-session branch input focus ────────────────────────────────


class TestNewSessionFocus:
    @pytest.mark.asyncio
    async def test_new_session_overlay_focuses_branch_input_on_present(self):
        app = _InterruptApp()
        async with app.run_test() as pilot:
            ov = app.query_one(InterruptOverlay)
            resolved = []
            payload = InterruptPayload(
                kind=InterruptKind.NEW_SESSION,
                on_resolve=lambda v: resolved.append(v),
            )
            ov.present(payload)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            assert app.focused is not None
            assert app.focused.id == "ns-branch-input"

    @pytest.mark.asyncio
    async def test_new_session_escape_still_cancels_when_input_focused(self):
        app = _InterruptApp()
        async with app.run_test() as pilot:
            ov = app.query_one(InterruptOverlay)
            resolved = []
            payload = InterruptPayload(
                kind=InterruptKind.NEW_SESSION,
                on_resolve=lambda v: resolved.append(v),
            )
            ov.present(payload)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            assert resolved == ["__cancel__"]
            assert ov.current_kind is None
            assert not ov.has_class("--visible")


# ── OVERLAY-3: Masked input reveal hint ──────────────────────────────────────


class TestMaskedPromptHints:
    @pytest.mark.asyncio
    async def test_secret_overlay_renders_peek_shortcut_hint(self):
        app = _InterruptApp()
        async with app.run_test():
            ov = app.query_one(InterruptOverlay)
            payload = InterruptPayload(
                kind=InterruptKind.SECRET,
                title="Enter API key",
                on_resolve=lambda v: None,
            )
            ov.present(payload)
            hint = ov.query_one("#secret-hint", Static)
            assert "Alt+P" in str(hint.content)

    @pytest.mark.asyncio
    async def test_sudo_overlay_renders_peek_shortcut_hint(self):
        app = _InterruptApp()
        async with app.run_test():
            ov = app.query_one(InterruptOverlay)
            payload = InterruptPayload(
                kind=InterruptKind.SUDO,
                title="Enter sudo password",
                on_resolve=lambda v: None,
            )
            ov.present(payload)
            hint = ov.query_one("#sudo-hint", Static)
            assert "Alt+P" in str(hint.content)
