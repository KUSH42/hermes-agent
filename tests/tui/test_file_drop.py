from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest
from textual import events

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput


def _make_cli() -> MagicMock:
    cli = MagicMock()
    cli._pending_input = queue.Queue()
    cli._attached_images = []
    return cli


@pytest.mark.asyncio
async def test_handle_file_drop_links_text_file(tmp_path, monkeypatch) -> None:
    app = HermesApp(cli=_make_cli())
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    file_path = tmp_path / "src" / "main.py"
    file_path.parent.mkdir()
    file_path.write_text("print('hi')\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.handle_file_drop([file_path])
        await pilot.pause()

        inp = app.query_one(HermesInput)
        assert inp.value == "@src/main.py"


@pytest.mark.asyncio
async def test_handle_file_drop_attaches_image_only(tmp_path, monkeypatch) -> None:
    cli = _make_cli()
    app = HermesApp(cli=cli)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.handle_file_drop([img])
        await pilot.pause()

        assert app.attached_images == [img]
        assert cli._attached_images == [img]

        inp = app.query_one(HermesInput)
        # Image attaches to ImageBar — no token inserted into input
        assert inp.value == ""


@pytest.mark.asyncio
async def test_handle_file_drop_image_submit_bundles_payload(tmp_path, monkeypatch) -> None:
    cli = _make_cli()
    app = HermesApp(cli=cli)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.handle_file_drop([img])
        await pilot.pause()

        inp = app.query_one(HermesInput)
        inp.value = "describe this"
        inp.action_submit()
        await pilot.pause()

        payload = cli._pending_input.get_nowait()
        assert payload == ("describe this", [img])
        assert app.attached_images == []
        assert cli._attached_images == []


@pytest.mark.asyncio
async def test_handle_file_drop_rejects_text_path_with_spaces(tmp_path, monkeypatch) -> None:
    app = HermesApp(cli=_make_cli())
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    file_path = tmp_path / "my notes.py"
    file_path.write_text("print('hi')\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.handle_file_drop([file_path])
        await pilot.pause()

        inp = app.query_one(HermesInput)
        # Spaces in @path unsupported — rejected, nothing inserted
        assert inp.value == ""
        hint = app.query_one("#hint-bar").hint
        assert "unsupported" in hint


@pytest.mark.asyncio
async def test_handle_file_drop_rejects_while_overlay_active(tmp_path, monkeypatch) -> None:
    from hermes_cli.tui.state import ChoiceOverlayState

    app = HermesApp(cli=_make_cli())
    monkeypatch.chdir(tmp_path)
    file_path = tmp_path / "main.py"
    file_path.write_text("print('hi')\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.approval_state = ChoiceOverlayState(
            deadline=0.0,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["yes", "no"],
            selected=0,
        )
        await pilot.pause()

        app.handle_file_drop([file_path])
        await pilot.pause()

        inp = app.query_one(HermesInput)
        assert inp.value == ""
        assert "file drop unavailable" in app.query_one("#hint-bar").hint


@pytest.mark.asyncio
async def test_handle_file_drop_mixed_image_and_text(tmp_path, monkeypatch) -> None:
    cli = _make_cli()
    app = HermesApp(cli=cli)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    src = tmp_path / "app.py"
    src.write_text("x = 1\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.handle_file_drop([img, src])
        await pilot.pause()

        assert app.attached_images == [img]
        inp = app.query_one(HermesInput)
        assert inp.value == "@app.py"
        hint = app.query_one("#hint-bar").hint
        assert "linked" in hint
        assert "attached" in hint


@pytest.mark.asyncio
async def test_input_paste_intercepts_dragged_file_path(tmp_path, monkeypatch) -> None:
    app = HermesApp(cli=_make_cli())
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    file_path = tmp_path / "main.py"
    file_path.write_text("print('hi')\n")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        await inp._on_paste(events.Paste(str(file_path)))
        await pilot.pause()

        assert inp.value == "@main.py"
