"""Tests for hermes_cli/tui/path_search.py — threaded walker + cancellation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.path_search import PathCandidate, PathSearchProvider


def _make_tree(root: Path, n: int) -> None:
    """Create *n* text files spread across a few subdirectories."""
    (root / "a").mkdir()
    (root / "b").mkdir()
    for i in range(n):
        subdir = root / ("a" if i % 2 == 0 else "b")
        (subdir / f"file_{i:04d}.txt").write_text("x", encoding="utf-8")


@pytest.mark.asyncio
async def test_walker_finds_known_files(tmp_path: Path) -> None:
    """All files in a tmp tree appear in the batches."""
    _make_tree(tmp_path, 50)

    collected: list[PathCandidate] = []
    final_seen = False

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        # Intercept Batch messages
        received: list[PathSearchProvider.Batch] = []

        original_post = provider.post_message

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch):
                received.append(msg)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]

        provider.search("", tmp_path)
        # Give the threaded worker time to complete
        await asyncio.sleep(1.0)
        await pilot.pause()

        for batch in received:
            collected.extend(batch.batch)
            if batch.final:
                final_seen = True

    assert final_seen, "final=True batch never arrived"
    names = {c.display for c in collected}
    assert len(names) == 50


@pytest.mark.asyncio
async def test_ignore_dirs_skipped(tmp_path: Path) -> None:
    """Ignored directories (.git, node_modules, etc.) are not walked."""
    # Create files in an ignored dir and a normal dir
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass", encoding="utf-8")

    collected: list[PathCandidate] = []

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        received: list[PathSearchProvider.Batch] = []
        original_post = provider.post_message

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch):
                received.append(msg)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]

        provider.search("", tmp_path)
        await asyncio.sleep(0.5)
        await pilot.pause()

        for batch in received:
            collected.extend(batch.batch)

    abs_paths = {c.abs_path for c in collected}
    assert not any(".git" in p for p in abs_paths), ".git dir was not ignored"
    assert any("main.py" in p for p in abs_paths), "src/main.py not found"


@pytest.mark.asyncio
async def test_batch_size_bounded(tmp_path: Path) -> None:
    """No single batch exceeds 512 items."""
    _make_tree(tmp_path, 100)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        received: list[PathSearchProvider.Batch] = []
        original_post = provider.post_message

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch):
                received.append(msg)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]

        provider.search("", tmp_path)
        await asyncio.sleep(0.5)
        await pilot.pause()

    for batch in received:
        assert len(batch.batch) <= 512


@pytest.mark.asyncio
async def test_final_flag_set_once(tmp_path: Path) -> None:
    """Exactly one Batch with final=True per search."""
    _make_tree(tmp_path, 20)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        received: list[PathSearchProvider.Batch] = []
        original_post = provider.post_message

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch):
                received.append(msg)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]

        provider.search("", tmp_path)
        await asyncio.sleep(0.5)
        await pilot.pause()

    finals = [b for b in received if b.final]
    assert len(finals) == 1


@pytest.mark.asyncio
async def test_cancellation_on_new_query(tmp_path: Path) -> None:
    """Starting a second search cancels the first; combined output is consistent."""
    _make_tree(tmp_path, 60)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        received: list[PathSearchProvider.Batch] = []
        original_post = provider.post_message

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch):
                received.append(msg)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]

        provider.search("file_0", tmp_path)
        # Immediately start a second search to cancel the first
        await asyncio.sleep(0.05)
        provider.search("file_1", tmp_path)
        await asyncio.sleep(1.0)
        await pilot.pause()

    # Second search must complete (has a final=True with query="file_1")
    second_finals = [b for b in received if b.final and b.query == "file_1"]
    assert len(second_finals) == 1
