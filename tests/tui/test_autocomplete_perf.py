"""Performance tests — frame-time microbench (competitive claim enforcement).

Hard targets:
- 10k items mount + virtual_size in <150ms
- 200 render_line calls in <200ms (<1ms/row amortized)
- 200 arrow-key highlight moves: median per-move <16.67ms (60fps budget)
- fuzzy_rank on 10k candidates in <5ms
- First batch from walker on 1k-file tree in <50ms

CI: these are marked ``@pytest.mark.slow`` and skipped by the unit-test job.
Run with ``pytest -m slow tests/tui/test_autocomplete_perf.py``.
A ``PERF_STRICT=1`` env var promotes timing warnings to assertion failures.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.fuzzy import fuzzy_rank
from hermes_cli.tui.path_search import PathCandidate, PathSearchProvider

_STRICT = os.environ.get("PERF_STRICT") == "1"


def _assert_or_warn(condition: bool, message: str) -> None:
    if _STRICT:
        assert condition, message
    elif not condition:
        import warnings
        warnings.warn(f"PERF: {message}", stacklevel=2)


def _pc(name: str) -> PathCandidate:
    return PathCandidate(display=name, abs_path=f"/tmp/{name}")


def _make_items(n: int) -> tuple[PathCandidate, ...]:
    return tuple(_pc(f"file_{i:06d}.txt") for i in range(n))


def _make_tree(root: Path, n: int) -> None:
    (root / "src").mkdir()
    for i in range(n):
        (root / "src" / f"f_{i:04d}.py").write_text("x", encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 3 perf tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.asyncio
async def test_10k_items_mount_under_150ms() -> None:
    """Building + assigning 10k candidates + reading virtual_size in <150ms."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        items = _make_items(10_000)

        start = time.perf_counter()
        clist.items = items
        await pilot.pause()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert clist.virtual_size.height == 10_000
        _assert_or_warn(
            elapsed_ms < 150,
            f"10k mount took {elapsed_ms:.1f}ms (target <150ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_render_line_under_1ms_per_row() -> None:
    """200 render_line calls complete in <200ms (<1ms/row amortized)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.items = _make_items(10_000)
        await pilot.pause()

        start = time.perf_counter()
        for y in range(200):
            clist.render_line(y % 24)  # stay in viewport range
        elapsed_ms = (time.perf_counter() - start) * 1000

        _assert_or_warn(
            elapsed_ms < 200,
            f"200 render_line calls took {elapsed_ms:.1f}ms (target <200ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_arrow_key_loop_under_16ms_median() -> None:
    """200 highlight moves: median per-move <16.67ms (60fps budget)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        clist = app.query_one(VirtualCompletionList)
        clist.items = _make_items(10_000)
        clist.highlighted = 0
        await pilot.pause()

        times: list[float] = []
        for _ in range(200):
            t0 = time.perf_counter()
            clist.highlighted = (clist.highlighted + 1) % len(clist.items)
            await pilot.pause()
            times.append((time.perf_counter() - t0) * 1000)

        median_ms = statistics.median(times)
        _assert_or_warn(
            median_ms < 16.67,
            f"Arrow-key loop median: {median_ms:.2f}ms (target <16.67ms)",
        )


@pytest.mark.slow
def test_fuzzy_rank_under_5ms() -> None:
    """fuzzy_rank('abc', 10k candidates) completes in <5ms."""
    items = _make_items(10_000)
    start = time.perf_counter()
    fuzzy_rank("abc", items, limit=200)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _assert_or_warn(
        elapsed_ms < 5,
        f"fuzzy_rank on 10k took {elapsed_ms:.2f}ms (target <5ms)",
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_path_walker_first_batch_under_50ms(tmp_path: Path) -> None:
    """First Batch arrives within 50ms of search() call on a 1k-file tree."""
    _make_tree(tmp_path, 1000)

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)

        first_batch_time: list[float] = []
        original_post = provider.post_message
        t_start = time.perf_counter()

        def capture(msg):
            if isinstance(msg, PathSearchProvider.Batch) and not first_batch_time:
                first_batch_time.append((time.perf_counter() - t_start) * 1000)
            original_post(msg)

        provider.post_message = capture  # type: ignore[method-assign]
        provider.search("", tmp_path)
        await asyncio.sleep(1.0)
        await pilot.pause()

    assert first_batch_time, "No batch arrived within 1s"
    _assert_or_warn(
        first_batch_time[0] < 50,
        f"First batch arrived in {first_batch_time[0]:.1f}ms (target <50ms)",
    )
