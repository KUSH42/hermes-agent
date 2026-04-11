"""Tests for hermes_cli/tui/preview_panel.py — reader + cancellation + binary sniff."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.path_search import PathCandidate
from hermes_cli.tui.preview_panel import PreviewPanel, _looks_binary


# ---------------------------------------------------------------------------
# Unit tests — _looks_binary (no Textual needed)
# ---------------------------------------------------------------------------

def test_looks_binary_with_null_byte() -> None:
    """Bytes containing a NUL → binary."""
    assert _looks_binary(b"hello\x00world")


def test_looks_binary_plain_text() -> None:
    """ASCII text without NUL → not binary."""
    assert not _looks_binary(b"def hello():\n    pass\n")


def test_looks_binary_null_outside_sniff_window() -> None:
    """NUL byte beyond 4 KiB window is ignored (treated as text)."""
    data = b"a" * 4096 + b"\x00"
    assert not _looks_binary(data)


# ---------------------------------------------------------------------------
# Integration tests (Phase 6)
# Workers require the parent CompletionOverlay to be visible (display:block)
# so Textual runs worker callbacks.
# ---------------------------------------------------------------------------

async def _show_overlay(app: HermesApp, pilot) -> None:
    """Helper: make CompletionOverlay visible so PreviewPanel workers run."""
    app.query_one(CompletionOverlay).add_class("--visible")
    await pilot.pause()


@pytest.mark.asyncio
async def test_preview_clears_on_none(tmp_path: Path) -> None:
    """candidate = None clears the log (after having a non-None candidate)."""
    py_file = tmp_path / "x.py"
    py_file.write_text("pass\n", encoding="utf-8")

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)
        # Set a real candidate first so the reactive has a non-None value
        panel.candidate = PathCandidate(display="x.py", abs_path=str(py_file))
        await asyncio.sleep(0.5)
        await pilot.pause()
        assert len(panel.lines) > 0  # sanity — file loaded
        # Now clear by setting to None (reactive fires since value changed)
        panel.candidate = None
        await pilot.pause()
        assert len(panel.lines) == 0


@pytest.mark.asyncio
async def test_preview_loads_text_file(tmp_path: Path) -> None:
    """Setting candidate with a .py path renders lines in the panel."""
    py_file = tmp_path / "hello.py"
    py_file.write_text("def hello():\n    print('hi')\n", encoding="utf-8")

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)
        panel.candidate = PathCandidate(
            display="hello.py", abs_path=str(py_file)
        )
        # Give the threaded worker time to read the file
        await asyncio.sleep(0.5)
        await pilot.pause()
        assert len(panel.lines) > 0


@pytest.mark.asyncio
async def test_preview_bails_on_large_file(tmp_path: Path) -> None:
    """File > 128 KB shows '(too large: N KB)' message."""
    large = tmp_path / "big.bin"
    large.write_bytes(b"x" * (129 * 1024))

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)
        panel.candidate = PathCandidate(
            display="big.bin", abs_path=str(large)
        )
        await asyncio.sleep(0.5)
        await pilot.pause()
        text = "".join(str(line) for line in panel.lines)
        assert "too large" in text


@pytest.mark.asyncio
async def test_preview_detects_binary(tmp_path: Path) -> None:
    """File with a NUL byte in first 4 KiB shows '(binary file: N bytes)'."""
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"hello\x00world" + b"\xff" * 10)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)
        panel.candidate = PathCandidate(
            display="blob.bin", abs_path=str(binary)
        )
        await asyncio.sleep(0.5)
        await pilot.pause()
        text = "".join(str(line) for line in panel.lines)
        assert "binary file" in text


@pytest.mark.asyncio
async def test_preview_handles_oserror() -> None:
    """Unreadable file shows '(cannot read: ...)' message."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)
        panel.candidate = PathCandidate(
            display="ghost.py",
            abs_path="/nonexistent/path/ghost.py",
        )
        await asyncio.sleep(0.5)
        await pilot.pause()
        text = "".join(str(line) for line in panel.lines)
        assert "cannot read" in text


@pytest.mark.asyncio
async def test_preview_cancellation(tmp_path: Path) -> None:
    """Rapid candidate changes only commit the last read's result."""
    files = []
    for i in range(5):
        f = tmp_path / f"file_{i}.py"
        f.write_text(f"# file {i}\n", encoding="utf-8")
        files.append(f)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _show_overlay(app, pilot)
        panel = app.query_one(PreviewPanel)

        # Assign candidates rapidly
        for f in files:
            panel.candidate = PathCandidate(display=f.name, abs_path=str(f))

        # Wait for the final worker to complete
        await asyncio.sleep(1.0)
        await pilot.pause()

        # The preview should show file_4 (last assigned)
        text = "".join(str(line) for line in panel.lines)
        assert "file 4" in text or "file_4" in text
