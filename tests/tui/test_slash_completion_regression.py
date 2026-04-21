"""Regression tests for slash command completion coverage.

Bug: five commands (/usage, /verbose, /voice, /workspace, /yolo) were silently
dropped from the slash completion overlay when the user typed '/'.

Root cause: ``_show_slash_completions`` called ``fuzzy_rank(fragment, items,
limit=50)``.  The registry held exactly 50 non-gateway names+aliases before
Phase 1.  Phase 1 (commit c48b4adb) added two ``tui_only`` commands
(``/density`` and ``/sessions``) and their aliases, pushing the sorted list to
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
    The count exceeded 50 in Phase 1 when /density and /sessions were added.
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
        "No tui_only commands found in registry.  At minimum /density and "
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


# ---------------------------------------------------------------------------
# Regression: / flicker loop — equality guard on _update_autocomplete
# ---------------------------------------------------------------------------

def _make_inp_harness():
    """Build a minimal HermesInput harness without a running Textual app.

    Returns (inp, _NoOpMeasure). Use patch('hermes_cli.tui.perf.measure', _NoOpMeasure)
    to suppress the perf context manager — measure is now an inline import in _autocomplete.
    """
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    inp = HermesInput.__new__(HermesInput)
    inp._suppress_autocomplete_once = False
    inp._current_trigger = CompletionTrigger(CompletionContext.NONE, "", 0)
    inp._raw_candidates = []
    inp._last_slash_hint_fragment = ""
    inp._slash_commands = ["/help", "/density", "/sessions", "/workspace"]
    inp._slash_descriptions = {}
    inp._slash_args_hints = {}
    inp._slash_keybind_hints = {}
    inp._slash_subcommands = {}
    inp._path_debounce_timer = None

    class _NoOpMeasure:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    return inp, _NoOpMeasure


def test_slash_update_autocomplete_no_reentry_on_same_trigger():
    """Calling _update_autocomplete twice with the same trigger pushes items once.

    Regression for the flicker loop: without the equality guard, every call to
    _update_autocomplete would reassign _current_trigger and call _push_to_list,
    causing watch_items → refresh → watch_value → _update_autocomplete re-entry.

    With the guard, the second call sees new_trigger == self._current_trigger
    and returns early, so _show_slash_completions is called exactly once.
    """
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    inp, _NoOpMeasure = _make_inp_harness()

    slash_call_count = 0

    def _fake_show_slash(fragment):
        nonlocal slash_call_count
        slash_call_count += 1

    fake_app = MagicMock()
    fake_app.choice_overlay_active = False

    with patch("hermes_cli.tui.perf.measure", _NoOpMeasure), \
         patch.object(inp, "_show_slash_completions", side_effect=_fake_show_slash), \
         patch.object(inp, "_hide_completion_overlay"), \
         patch.object(type(inp), "value", new_callable=lambda: property(lambda self: "/")), \
         patch.object(type(inp), "cursor_position", new_callable=lambda: property(lambda self: 1)), \
         patch.object(type(inp), "app", new_callable=lambda: property(lambda self: fake_app)):
        # First call — trigger is NONE, so it computes and calls _show_slash_completions.
        inp._update_autocomplete()
        assert slash_call_count == 1, (
            f"Expected 1 _show_slash_completions call after first invocation, got {slash_call_count}"
        )

        # Second call with same value "/" — new_trigger == _current_trigger, early return.
        inp._update_autocomplete()
        assert slash_call_count == 1, (
            f"Expected still 1 call after second invocation with same trigger, "
            f"got {slash_call_count}. Equality guard is missing or broken."
        )


def test_slash_typing_single_slash_no_flicker():
    """Simulate typing '/' and verify _show_slash_completions is called exactly once.

    This is a unit-level guard for the flicker loop: the _update_autocomplete
    equality guard must prevent any re-entrant call after the first computation.

    The loop signature is: _show_slash_completions → _push_to_list → watch_items
    → refresh → watch_value fires → _update_autocomplete → _show_slash_completions
    again → repeat.  The guard breaks this by returning early when the trigger
    is unchanged.

    The test simulates the re-entrant call by having _show_slash_completions
    call _update_autocomplete again — exactly what happens via Textual reactives.
    """
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    inp, _NoOpMeasure = _make_inp_harness()

    slash_calls: list[str] = []

    def _reentrant_show_slash(fragment):
        slash_calls.append(fragment)
        # Simulate watch_items firing _update_autocomplete re-entrantly.
        inp._update_autocomplete()

    fake_app = MagicMock()
    fake_app.choice_overlay_active = False

    with patch("hermes_cli.tui.perf.measure", _NoOpMeasure), \
         patch.object(inp, "_show_slash_completions", side_effect=_reentrant_show_slash), \
         patch.object(inp, "_hide_completion_overlay"), \
         patch.object(type(inp), "value", new_callable=lambda: property(lambda self: "/")), \
         patch.object(type(inp), "cursor_position", new_callable=lambda: property(lambda self: 1)), \
         patch.object(type(inp), "app", new_callable=lambda: property(lambda self: fake_app)):
        inp._update_autocomplete()

    assert len(slash_calls) == 1, (
        f"Expected exactly 1 _show_slash_completions call (no flicker loop), "
        f"got {len(slash_calls)} calls with fragments: {slash_calls}. "
        "The equality guard in _update_autocomplete is not preventing re-entry."
    )


def test_typing_slash_does_not_trigger_file_drop_detection():
    """Bare '/' must NOT trigger the fallback DnD file-drop detection.

    Root cause: ``on_text_area_changed`` called ``detect_file_drop_text("/")``
    which returned a match for the root directory (Path("/").exists() is True).
    This cleared the input and re-inserted "/" via FilesDropped → infinite loop.

    Fix: added ``len(stripped) > 1`` guard before calling detect_file_drop_text.
    """
    from unittest.mock import MagicMock, patch, PropertyMock
    from hermes_cli.tui.input_widget import HermesInput

    inp = object.__new__(HermesInput)
    inp._handling_file_drop = False
    inp._sanitizing = False

    posted: list = []

    def fake_post_message(msg):
        posted.append(msg)

    def fake_load_text(text):
        inp._loaded = text

    with patch.object(inp, "post_message", side_effect=fake_post_message), \
         patch.object(inp, "load_text", side_effect=fake_load_text), \
         patch.object(inp, "_update_autocomplete"), \
         patch.object(type(inp), "text", new_callable=PropertyMock, return_value="/"):
        event = MagicMock()
        inp.on_text_area_changed(event)

    assert not posted, (
        "Typing '/' must not post FilesDropped — bare slash is a slash command "
        f"prefix, not a file drop.  Got messages: {posted}"
    )
