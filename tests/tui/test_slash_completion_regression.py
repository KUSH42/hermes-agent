"""Regression tests for slash command completion coverage.

Bug: five commands (/usage, /verbose, /voice, /workspace, /yolo) were silently
dropped from the slash completion overlay when the user typed '/'.

Root cause: ``_show_slash_completions`` called ``fuzzy_rank(fragment, items,
limit=50)``.  The registry held exactly 50 non-gateway names+aliases before
Phase 1.  Phase 1 (commit c48b4adb) added two ``tui_only`` commands
(``/compact`` and ``/sessions``) and their aliases, pushing the sorted list to
55 entries.  With ``limit=50``, the alphabetically-last five commands were
silently truncated on every call.

Note: ``tui_only`` commands are intentionally *included* in TUI slash
completion — they are excluded only from gateway surfaces (Telegram / Discord).
The ``_populate_slash_commands`` method in ``app.py`` correctly includes them;
the truncation happened *after* the correct list was built, inside the
``fuzzy_rank`` call.

Fix: raised limit to 200 in ``_show_slash_completions`` (matches the
``fuzzy_rank`` default).
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
    The count exceeded 50 in Phase 1 when /compact and /sessions were added.
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


def test_tui_only_commands_included_in_registry_names():
    """tui_only commands must appear in the non-gateway name list.

    tui_only=True means the command is *only* meaningful in the TUI — it is
    excluded from gateway surfaces (Telegram/Discord) but MUST be present in
    TUI slash completion.  This test guards against accidentally filtering them
    out alongside gateway_only commands.
    """
    tui_only_names: list[str] = []
    all_non_gateway_names: set[str] = set()

    for cmd in COMMAND_REGISTRY:
        if cmd.gateway_only:
            continue
        all_non_gateway_names.add(f"/{cmd.name}")
        for alias in getattr(cmd, "aliases", []):
            all_non_gateway_names.add(f"/{alias}")
        if getattr(cmd, "tui_only", False):
            tui_only_names.append(f"/{cmd.name}")

    assert tui_only_names, (
        "No tui_only commands found in registry.  At minimum /compact and "
        "/sessions should be tui_only.  Check CommandDef.tui_only field."
    )

    for name in tui_only_names:
        assert name in all_non_gateway_names, (
            f"{name} is tui_only but missing from non-gateway names.  "
            "Do not filter tui_only commands out of TUI completion."
        )


# ---------------------------------------------------------------------------
# Integration: _show_slash_completions with empty fragment returns all cmds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_slash_completions_empty_fragment_returns_all():
    """Typing '/' (empty fragment) must surface ALL non-gateway commands.

    Regression for the limit=50 truncation: with 55 names in the registry,
    limit=50 dropped the alphabetically-last 5 (/usage, /verbose, /voice,
    /workspace, /yolo).  After fix (limit=200) all are returned.
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
    """After mount, _slash_commands must contain all non-gateway names.

    This includes tui_only commands — they are TUI-specific and must appear
    in TUI slash completion even though they are excluded from gateway surfaces.
    """
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput

    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        expected_names: set[str] = set()
        tui_only_names: list[str] = []
        for cmd in COMMAND_REGISTRY:
            if cmd.gateway_only:
                continue
            expected_names.add(f"/{cmd.name}")
            for alias in getattr(cmd, "aliases", []):
                expected_names.add(f"/{alias}")
            if getattr(cmd, "tui_only", False):
                tui_only_names.append(f"/{cmd.name}")

        actual = set(inp._slash_commands)
        missing = expected_names - actual
        assert not missing, f"Commands missing from _slash_commands after mount: {sorted(missing)}"

        # Explicit guard: tui_only commands must be present
        for name in tui_only_names:
            assert name in actual, (
                f"tui_only command {name} missing from _slash_commands.  "
                "tui_only commands must be included in TUI slash completion."
            )


@pytest.mark.asyncio
async def test_typing_slash_shows_multiple_commands():
    """Typing '/' must produce more than 1 item in the completion overlay.

    Primary regression guard: the truncation bug caused the alphabetically-last
    5 commands to be silently dropped.  Any future regression that reduces the
    visible count should be caught here.
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


@pytest.mark.asyncio
async def test_previously_truncated_commands_present():
    """The five commands cut off by the old limit=50 must now appear.

    Before the fix, /usage, /verbose, /voice, /workspace, /yolo were the
    alphabetically-last entries in the sorted list of 55 names and were
    silently dropped by fuzzy_rank(limit=50).
    """
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput

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

        displays = {item.display for item in captured}
        # These are the commands that were alphabetically beyond position 50
        # and were silently truncated by the old limit=50 cap.
        expected_present = ["/usage", "/verbose", "/voice", "/workspace", "/yolo"]
        missing = [cmd for cmd in expected_present if cmd in inp._slash_commands and cmd not in displays]
        assert not missing, (
            f"Commands still missing from completions (limit cap too small?): {missing}"
        )
