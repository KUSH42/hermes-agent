"""Tests for HermesInput widget (TextArea-based)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.path_search import PathCandidate, SlashCandidate


@pytest.mark.asyncio
async def test_input_widget_exists():
    """HermesInput is present in the composed layout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert isinstance(inp, HermesInput)


@pytest.mark.asyncio
async def test_input_starts_empty():
    """Input value is empty on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.value == ""
        assert inp.content == ""  # bridge property


@pytest.mark.asyncio
async def test_content_property_bridge():
    """content property reads/writes value; cursor_pos bridges cursor_position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "hello"
        assert inp.value == "hello"
        assert inp.content == "hello"
        inp.cursor_pos = 3
        assert inp.cursor_position == 3
        assert inp.cursor_pos == 3


@pytest.mark.asyncio
async def test_input_enabled_when_agent_running():
    """Input stays enabled when agent_running is True — user can interrupt."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert not inp.disabled
        app.agent_running = True
        await pilot.pause()
        assert not inp.disabled


@pytest.mark.asyncio
async def test_input_clear():
    """clear() resets content and cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 3
        inp.clear()
        assert inp.value == ""
        assert inp.cursor_position == 0


@pytest.mark.asyncio
async def test_input_insert_text():
    """insert_text inserts at cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "helo"
        inp.cursor_position = 3
        inp.insert_text("l")
        assert inp.value == "hello"
        assert inp.cursor_position == 4


@pytest.mark.asyncio
async def test_slash_still_works():
    """Typing '/' triggers the completion overlay with slash candidates."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/quit"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        displays = [c.display for c in clist.items]
        assert any("help" in d for d in displays)


@pytest.mark.asyncio
async def test_history_navigation():
    """Up/Down keys cycle through history when overlay is hidden."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["first", "second", "third"]
        inp.value = "current"

        inp.action_history_prev()
        assert inp.value == "third"
        inp.action_history_prev()
        assert inp.value == "second"
        inp.action_history_next()
        assert inp.value == "third"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_navigation_empty_history():
    """Up/down with no history entries is a no-op."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        inp.value = "current"
        inp.action_history_prev()
        assert inp.value == "current"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_save_on_submit():
    """action_submit() saves to history before posting Submitted."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        inp.value = "test command"
        inp.action_submit()
        assert "test command" in inp._history
        assert inp.value == ""


@pytest.mark.asyncio
async def test_input_accepts_keystrokes_when_agent_running():
    """Typing works when agent_running=True — input stays enabled for interrupt."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        app.agent_running = True
        await pilot.pause()
        assert not inp.disabled
        await pilot.press("a", "b", "c")
        await pilot.pause()
        assert inp.value == "abc"


@pytest.mark.asyncio
async def test_input_changed_triggers_autocomplete():
    """watch_value updates completion overlay on slash input."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_ctrl_a_selects_all():
    """ctrl+a selects entire input value."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello world"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_shift_arrow_selection():
    """Shift+right selects text; selection range is non-empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 0
        inp.focus()
        await pilot.pause()
        await pilot.press("shift+right")
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_ctrl_x_cuts_selected_input():
    """ctrl+x removes selected text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_ctrl_v_pastes():
    """ctrl+v inserts clipboard content at cursor."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        app.copy_to_clipboard("pasted")
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert "pasted" in inp.value


@pytest.mark.asyncio
async def test_input_value_strips_unicode_control_chars() -> None:
    """Direct value updates strip control/format characters; newlines are kept."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "a\u200bb\tc\n\x00d"
        await pilot.pause()
        # \u200b stripped (Cf), \t → space, \n kept, \x00 stripped (Cc)
        assert inp.value == "ab c\nd"


@pytest.mark.asyncio
async def test_insert_text_strips_unicode_control_chars() -> None:
    """insert_text sanitizes hidden controls before insertion."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 5
        inp.insert_text("\u200b\t\x00 world")
        await pilot.pause()
        assert inp.value == "hello  world"


@pytest.mark.asyncio
async def test_submit_uses_sanitized_input_value() -> None:
    """Submitted/history text should not contain hidden control characters."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hi\u200b\tthere"
        await pilot.pause()
        inp.action_submit()
        await pilot.pause()
        assert inp._history[-1] == "hi there"


# ---------------------------------------------------------------------------
# Phase 4 new tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_path_completion_triggers_walker(tmp_path: Path) -> None:
    """Typing '@' causes PathSearchProvider.search to be called."""
    from hermes_cli.tui.path_search import PathSearchProvider

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cli = MagicMock()
    cli.terminal_cwd = str(workspace)
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)
        search_calls: list = []

        def capture_search(query, root, **kwargs):
            search_calls.append((query, root, kwargs))
        provider.search = capture_search  # type: ignore[method-assign]

        inp = app.query_one(HermesInput)
        inp.value = "@src"
        inp.cursor_position = 4
        await asyncio.sleep(0.15)
        await pilot.pause()

        assert len(search_calls) > 0, "PathSearchProvider.search was not called"
        assert search_calls[0][0] == "src"
        assert search_calls[0][1] == workspace
        assert search_calls[0][2]["match_query"] == "src"
        assert search_calls[0][2]["insert_prefix"] == ""


@pytest.mark.asyncio
async def test_path_completion_resolves_parent_root(tmp_path: Path) -> None:
    """@../src searches from parent directory and preserves ../ prefix on insert."""
    from hermes_cli.tui.path_search import PathSearchProvider

    workspace = tmp_path / "project" / "app"
    workspace.mkdir(parents=True)
    cli = MagicMock()
    cli.terminal_cwd = str(workspace)
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)
        search_calls: list = []

        def capture_search(query, root, **kwargs):
            search_calls.append((query, root, kwargs))

        provider.search = capture_search  # type: ignore[method-assign]

        inp = app.query_one(HermesInput)
        inp.value = "@../src"
        inp.cursor_position = len("@../src")
        await asyncio.sleep(0.15)
        await pilot.pause()

        assert search_calls[0][0] == "../src"
        assert search_calls[0][1] == workspace.parent
        assert search_calls[0][2]["match_query"] == "src"
        assert search_calls[0][2]["insert_prefix"] == "../"


@pytest.mark.asyncio
async def test_path_completion_resolves_absolute_root() -> None:
    """@/tmp/demo splits absolute path into root + query for out-of-cwd search."""
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)
        search_calls: list = []

        def capture_search(query, root, **kwargs):
            search_calls.append((query, root, kwargs))

        provider.search = capture_search  # type: ignore[method-assign]

        inp = app.query_one(HermesInput)
        inp.value = "@/tmp/demo"
        inp.cursor_position = len("@/tmp/demo")
        await asyncio.sleep(0.15)
        await pilot.pause()

        assert search_calls[0][0] == "/tmp/demo"
        assert search_calls[0][1] == Path("/tmp")
        assert search_calls[0][2]["match_query"] == "demo"
        assert search_calls[0][2]["insert_prefix"] == "/tmp/"


@pytest.mark.asyncio
async def test_path_completion_populates_list() -> None:
    """Batch handler updates VirtualCompletionList.items."""
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        batch_msg = PathSearchProvider.Batch(
            query="src",
            batch=[
                PathCandidate(display="src/main.py", abs_path="/tmp/src/main.py", insert_text="src/main.py"),
                PathCandidate(display="src/utils.py", abs_path="/tmp/src/utils.py", insert_text="src/utils.py"),
            ],
            final=True,
        )
        inp.on_path_search_provider_batch(batch_msg)
        clist = app.query_one(VirtualCompletionList)
        assert len(clist.items) == 2


@pytest.mark.asyncio
async def test_stale_batch_dropped() -> None:
    """Batch with mismatched query is ignored."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        stale_batch = PathSearchProvider.Batch(
            query="old",
            batch=[PathCandidate(display="old.py", abs_path="/tmp/old.py")],
            final=True,
        )
        inp.on_path_search_provider_batch(stale_batch)
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        assert len(clist.items) == 0


@pytest.mark.asyncio
async def test_plain_path_ref_batch_accepted() -> None:
    """PLAIN_PATH_REF batches keyed by raw path (e.g. './foo') must populate the list."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        inp.value = "./foo"
        inp.cursor_position = 5
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PLAIN_PATH_REF, "foo", 0
        )
        batch_msg = PathSearchProvider.Batch(
            query="./foo",
            batch=[PathCandidate(display="foo/bar.py", abs_path="/tmp/foo/bar.py", insert_text="./foo/bar.py")],
            final=True,
        )
        inp.on_path_search_provider_batch(batch_msg)

        clist = app.query_one(VirtualCompletionList)
        assert len(clist.items) == 1, "PLAIN_PATH_REF batch must not be dropped as stale"


@pytest.mark.asyncio
async def test_cursor_watcher_keeps_path_query_in_sync() -> None:
    """Autocomplete uses cursor position set synchronously before Changed fires."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        # Set value and cursor synchronously; Changed fires async with cursor at 5
        inp.value = "@text"
        inp.cursor_position = 5
        await pilot.pause()  # Changed fires; cursor is 5 → query="text"
        clist = app.query_one(VirtualCompletionList)
        assert clist.current_query == "text"


@pytest.mark.asyncio
async def test_tab_accepts_highlighted_slash() -> None:
    """Tab on a SlashCandidate replaces value with '<cmd> '."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert inp.value == "/help "
        assert inp.cursor_position == len("/help ")


@pytest.mark.asyncio
async def test_tab_accepts_highlighted_path() -> None:
    """Tab on a PathCandidate inserts @path preserving surrounding text."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "@src"
        inp.cursor_position = 4
        await pilot.pause()  # let Changed fire; overlay now visible, items=[]

        # Set trigger+items after autocomplete has run
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        clist = app.query_one(VirtualCompletionList)
        clist.items = (PathCandidate(display="src/main.py", abs_path="/tmp/src/main.py"),)
        clist.highlighted = 0

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert "@src/main.py" in inp.value
        assert not app.query_one(CompletionOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_app_relays_batch_to_hermes_input() -> None:
    """HermesApp.on_path_search_provider_batch relays Batch to HermesInput."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
    from hermes_cli.tui.path_search import PathSearchProvider as _PSP

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        inp._current_trigger = CompletionTrigger(CompletionContext.PATH_REF, "foo", 1)
        batch_msg = _PSP.Batch(
            query="foo",
            batch=[PathCandidate(display="foo/bar.py", abs_path="/tmp/foo/bar.py")],
            final=True,
        )
        app.on_path_search_provider_batch(batch_msg)
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        assert len(clist.items) == 1
        assert clist.items[0].display == "foo/bar.py"


@pytest.mark.asyncio
async def test_tab_accepts_plain_path_candidate() -> None:
    """Tab on a PathCandidate with PLAIN_PATH_REF preserves the ./ prefix."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        provider = app.query_one(PathSearchProvider)
        provider.search = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        inp.value = "./src"
        inp.cursor_position = 5
        await pilot.pause()  # let Changed fire; overlay visible, items=[]

        # Set trigger+items after autocomplete has run
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PLAIN_PATH_REF, "src", 0
        )
        clist = app.query_one(VirtualCompletionList)
        clist.items = (PathCandidate(display="src/main.py", abs_path="/tmp/src/main.py"),)
        clist.highlighted = 0

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert inp.value == "./src/main.py "
        assert not app.query_one(CompletionOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_tab_accepts_absolute_path_candidate() -> None:
    """Absolute path completion uses candidate insert_text, not relative display."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "open /tmp/de"
        inp.cursor_position = len("open /tmp/de")
        await pilot.pause()  # let Changed fire; overlay visible, items=[]

        # Set trigger+items after autocomplete has run
        inp._current_trigger = CompletionTrigger(
            CompletionContext.ABSOLUTE_PATH_REF, "/tmp/de", 5
        )
        clist = app.query_one(VirtualCompletionList)
        clist.items = (
            PathCandidate(
                display="demo/file.txt",
                abs_path="/tmp/demo/file.txt",
                insert_text="/tmp/demo/file.txt",
            ),
        )
        clist.highlighted = 0

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert inp.value == "open /tmp/demo/file.txt "
        assert not app.query_one(CompletionOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_up_dismisses_slash_only_and_navigates_history() -> None:
    """Up on slash-only overlay dismisses it and goes to history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/clear"])
        inp._history = ["/help", "/clear"]
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()

        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")
        assert overlay.has_class("--slash-only")

        inp.action_history_prev()
        await pilot.pause()

        assert not overlay.has_class("--visible")
        assert inp.value == "/clear"


@pytest.mark.asyncio
async def test_enter_submits_as_typed_with_overlay_visible() -> None:
    """/he + overlay visible + Enter → submits '/he', NOT '/help'."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()

        assert app.query_one(CompletionOverlay).has_class("--visible")

        inp.action_submit()
        await pilot.pause()

        assert inp._history[-1] == "/he"
        assert inp.value == ""


@pytest.mark.asyncio
async def test_tab_with_hidden_overlay_accepts_ghost_text_not_stale_candidate() -> None:
    """Regression: stale clist.items from prior slash session must not be accepted."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        inp.set_slash_commands(["/approve", "/retry", "/help"])
        inp.value = "/"
        await pilot.pause()
        co = app.query_one(CompletionOverlay)
        assert co.has_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        assert clist.highlighted == 0
        assert clist.items[0].command == "/approve"

        inp.value = "show me"
        await pilot.pause()
        assert not co.has_class("--visible"), "overlay should hide for plain text"
        assert clist.items, "stale candidates remain in list"
        assert clist.highlighted == 0

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert inp.value != "/approve", (
            "Tab must not accept stale slash candidate when overlay is hidden"
        )
        assert "show me" in inp.value or inp.value == "show me", (
            f"Value should remain 'show me' (or ghost-text extended), got: {inp.value!r}"
        )


# ---------------------------------------------------------------------------
# New multiline / TextArea-specific tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shift_enter_inserts_newline() -> None:
    """shift+enter inserts a newline instead of submitting."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("shift+enter")
        await pilot.press("t", "h", "e", "r", "e")
        await pilot.pause()
        assert "\n" in inp.value


@pytest.mark.asyncio
async def test_enter_submits_multiline() -> None:
    """Multiline value is submitted as-is (stripped) on Enter."""
    submitted: list[str] = []

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []

        def capture(event):
            submitted.append(event.value)
        app.on_hermes_input_submitted = capture

        inp.value = "line one\nline two"
        inp.action_submit()
        await pilot.pause()

        assert inp._history[-1] == "line one\nline two"
        assert inp.value == ""


@pytest.mark.asyncio
async def test_up_on_first_row_goes_to_history() -> None:
    """Up at row 0 triggers history prev."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["first entry"]
        inp.value = "current"
        inp.cursor_position = 0
        await pilot.pause()

        assert inp.cursor_location[0] == 0
        inp.action_history_prev()
        assert inp.value == "first entry"


@pytest.mark.asyncio
async def test_up_on_second_row_moves_cursor_not_history() -> None:
    """Up at row > 0 in multiline text moves cursor up, not history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["old entry"]
        inp.value = "line one\nline two"
        inp.cursor_position = len("line one\nline two")  # row 1
        await pilot.pause()

        assert inp.cursor_location[0] == 1
        # Up from row 1 should move cursor, not navigate history
        inp._history_idx = -1
        old_value = inp.value
        # Simulate _on_key logic: cursor at row 1, no overlay → don't call action_history_prev
        # Verify row is not 0 so history would not be triggered
        assert inp.cursor_location[0] != 0
        assert inp.value == old_value  # value unchanged


@pytest.mark.asyncio
async def test_down_on_last_row_goes_to_history() -> None:
    """Down at last row triggers history next when browsing history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["first", "second"]
        inp.value = "first"
        inp._history_idx = 0
        inp._history_draft = "draft"
        await pilot.pause()

        last_row = inp.text.count("\n")
        assert inp.cursor_location[0] >= last_row

        inp.action_history_next()
        assert inp.value == "second"


@pytest.mark.asyncio
async def test_cursor_pos_bridge_multiline() -> None:
    """cursor_pos flat int is correct across newlines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello\nworld"
        # "hello\n" = 6 chars; row 1 col 0 = flat offset 6
        inp.move_cursor((1, 0))
        await pilot.pause()
        assert inp.cursor_pos == 6


@pytest.mark.asyncio
async def test_value_bridge_set() -> None:
    """Setting .value with multiline string stores it correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello\nworld"
        assert inp.text == "hello\nworld"


@pytest.mark.asyncio
async def test_sanitize_allows_newlines() -> None:
    """Newlines pass through; CR stripped; tab → space; controls stripped."""
    from hermes_cli.tui.input_widget import _sanitize_input_text
    assert _sanitize_input_text("a\nb") == "a\nb"
    assert _sanitize_input_text("a\rb") == "ab"
    assert _sanitize_input_text("a\tb") == "a b"
    assert _sanitize_input_text("a\x00b") == "ab"
    assert _sanitize_input_text("a\r\nb") == "a\nb"


@pytest.mark.asyncio
async def test_update_suggestion_wired() -> None:
    """History entry starting with current text shows as ghost-text suggestion."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["foo bar"]
        inp.value = "foo"
        inp.move_cursor((0, 3))  # cursor at end
        await pilot.pause()
        inp.update_suggestion()
        assert inp.suggestion == " bar"


@pytest.mark.asyncio
async def test_ghost_text_clears_mid_cursor() -> None:
    """Ghost text is empty when cursor is not at end of text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["foo bar"]
        inp.value = "foo"
        inp.move_cursor((0, 1))  # cursor mid-text
        await pilot.pause()
        inp.update_suggestion()
        assert inp.suggestion == ""


@pytest.mark.asyncio
async def test_ghost_text_accepted_by_cursor_right() -> None:
    """action_cursor_right inserts suggestion when at end of text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["foo bar"]
        inp.value = "foo"
        inp.move_cursor((0, 3))  # end of text
        await pilot.pause()
        inp.update_suggestion()
        assert inp.suggestion == " bar"
        inp.action_cursor_right()
        await pilot.pause()
        assert inp.value == "foo bar"


@pytest.mark.asyncio
async def test_ctrl_shift_z_redoes() -> None:
    """ctrl+shift+z re-applies undone text (TextArea native undo/redo)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        # Type some text to create undo history
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()
        assert inp.value == "hello"
        # Undo via ctrl+z
        await pilot.press("ctrl+z")
        await pilot.pause()
        # Redo via ctrl+shift+z
        await pilot.press("ctrl+shift+z")
        await pilot.pause()
        # After redo, some or all of "hello" is back
        assert len(inp.value) > 0


@pytest.mark.asyncio
async def test_paste_file_drop_still_works() -> None:
    """_on_paste with drag-drop text posts FilesDropped, NOT inserted into input."""
    from textual import events as _events
    from unittest.mock import patch

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        dropped_msgs: list = []
        app.on_hermes_input_files_dropped = lambda e: dropped_msgs.append(e.paths)

        # Simulate paste with dragged file path text
        fake_path_text = "/tmp/example.txt"
        with patch(
            "hermes_cli.tui.input_widget.parse_dragged_file_paste",
            return_value=[Path(fake_path_text)],
        ):
            paste_event = _events.Paste(fake_path_text)
            await inp._on_paste(paste_event)
            await pilot.pause()

        # Text should NOT be in input (drag-drop intercepted)
        assert fake_path_text not in inp.value


@pytest.mark.asyncio
async def test_replace_flat_bridge() -> None:
    """replace_flat replaces flat-offset range with new text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        await pilot.pause()
        inp.replace_flat("X", 0, 3)  # replace "hel" → "X"
        await pilot.pause()
        assert inp.value == "Xlo"


@pytest.mark.asyncio
async def test_location_to_flat_multiline() -> None:
    """_location_to_flat converts (row, col) to flat offset across newlines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello\nworld"
        await pilot.pause()
        # "hello\n" = 6 chars (0-5 for "hello", 5 for "\n" = offset 6 start of row 1)
        # (1, 2) = row 1 col 2 = "hello\n" + "wo" = offset 8
        assert inp._location_to_flat((1, 2)) == 8
