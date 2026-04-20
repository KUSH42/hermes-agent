"""Regression tests for slash command completion coverage.

Bug: only /help appeared in the slash completion overlay when typing '/'.
Root cause: fuzzy_rank was called with limit=50 inside _show_slash_completions,
but the registry contains 55 non-gateway-only names (canonical + aliases),
silently dropping the last 5 commands alphabetically.

Fix: raised limit to 200 in _show_slash_completions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.commands import COMMAND_REGISTRY


# ---------------------------------------------------------------------------
# Unit-level: registry count
# ---------------------------------------------------------------------------

def test_non_gateway_command_count_exceeds_50():
    """Registry must have more than 50 non-gateway-only names (canonical + aliases).

    If this fails, the limit=50 cap would silently drop commands again.
    """
    names: list[str] = []
    for cmd in COMMAND_REGISTRY:
        if cmd.gateway_only:
            continue
        names.append(f"/{cmd.name}")
        for alias in getattr(cmd, "aliases", []):
            names.append(f"/{alias}")
    assert len(names) > 50, (
        f"Expected >50 non-gateway-only slash names, got {len(names)}. "
        "If registry shrinks below 50, this test can be relaxed."
    )


# ---------------------------------------------------------------------------
# Integration: _show_slash_completions with empty fragment returns all cmds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_slash_completions_empty_fragment_returns_all():
    """Typing '/' (empty fragment) must surface ALL non-gateway commands.

    Regression for the limit=50 bug: with 55 names in the registry,
    limit=50 dropped 5 commands. After fix (limit=200) all are returned.
    """
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.completion_list import VirtualCompletionList

    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        # Capture whatever _push_to_list is called with
        captured: list = []

        original_push = inp._push_to_list

        def _capture(items, *args, **kwargs):
            captured.clear()
            captured.extend(items)
            return original_push(items, *args, **kwargs)

        with patch.object(inp, "_push_to_list", side_effect=_capture), \
             patch.object(inp, "_show_completion_overlay"), \
             patch.object(inp, "_set_overlay_mode"):
            inp._show_slash_completions("")

        # Count expected names
        expected_names: list[str] = []
        for cmd in COMMAND_REGISTRY:
            if cmd.gateway_only:
                continue
            expected_names.append(f"/{cmd.name}")
            for alias in getattr(cmd, "aliases", []):
                expected_names.append(f"/{alias}")

        assert len(captured) == len(expected_names), (
            f"_show_slash_completions('') returned {len(captured)} items, "
            f"expected {len(expected_names)}. "
            "The limit cap may be too small again."
        )


@pytest.mark.asyncio
async def test_slash_commands_populated_after_mount():
    """After mount, _slash_commands must contain all non-gateway names."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput

    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        expected_names: set[str] = set()
        for cmd in COMMAND_REGISTRY:
            if cmd.gateway_only:
                continue
            expected_names.add(f"/{cmd.name}")
            for alias in getattr(cmd, "aliases", []):
                expected_names.add(f"/{alias}")

        actual = set(inp._slash_commands)
        missing = expected_names - actual
        assert not missing, f"Commands missing from _slash_commands after mount: {sorted(missing)}"


@pytest.mark.asyncio
async def test_typing_slash_shows_multiple_commands():
    """Typing '/' must produce more than 1 item in the completion overlay.

    Primary regression guard: the bug caused only /help to appear.
    """
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.completion_list import VirtualCompletionList

    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        captured: list = []
        original_push = inp._push_to_list

        def _capture(items, *args, **kwargs):
            captured.clear()
            captured.extend(items)
            return original_push(items, *args, **kwargs)

        with patch.object(inp, "_push_to_list", side_effect=_capture), \
             patch.object(inp, "_show_completion_overlay"), \
             patch.object(inp, "_set_overlay_mode"):
            inp._show_slash_completions("")

        assert len(captured) > 1, (
            f"Expected multiple completion candidates for '/', got {len(captured)}. "
            "Only /help appearing is the known regression."
        )
        displays = [item.display for item in captured]
        assert "/help" in displays
        # Should also contain other common commands — not just /help
        other = [d for d in displays if d != "/help"]
        assert len(other) > 0, "Only /help in completions — regression confirmed."
