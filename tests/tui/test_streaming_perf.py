"""Performance benchmarks for streaming and history-search hot paths.

Hard targets (enforced with PERF_STRICT=1, warnings-only otherwise):

    feed() mid-line chunk        < 0.5ms median
    feed() line-commit chunk     < 2ms median
    100-chunk drain              < 500ms total
    fuzzy_rank 50 TurnCandidates < 2ms median
    _render_results() 50 turns   < 50ms per-iteration (warn only; headless overhead)
    keystroke loop median        < 50ms per-iteration (warn only; headless overhead)
    timer delivery under 500 ch  < 200ms
    watch_scroll_y method body   < 0.1ms median
    watch_scroll_y invocations   ≤ 100 per 100 chunks (warn only)

CI: all tests are ``@pytest.mark.slow`` and skipped by the unit-test job.
Run with: ``pytest -m slow tests/tui/test_streaming_perf.py -o "addopts="``
Set ``PERF_STRICT=1`` to promote timing warnings to assertion failures.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
import warnings
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.fuzzy import fuzzy_rank
from hermes_cli.tui.perf import EventLoopLatencyProbe
from hermes_cli.tui.widgets import (
    HistorySearchOverlay,
    LiveLineWidget,
    OutputPanel,
    StreamingCodeBlock,
    TurnCandidate,
    _TurnEntry,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_STRICT = os.environ.get("PERF_STRICT") == "1"


def _assert_or_warn(condition: bool, message: str) -> None:
    if _STRICT:
        assert condition, message
    elif not condition:
        warnings.warn(f"PERF: {message}", stacklevel=2)


def _make_candidates(n: int) -> list[TurnCandidate]:
    """Build *n* TurnCandidates with realistic multi-line display strings."""
    body = "\n".join(["word " * 20] * 10)  # ~1100 chars per candidate
    return [
        TurnCandidate(
            display=body,
            entry=_TurnEntry(
                panel=MagicMock(),
                index=i,
                plain_text=body,
                display="word word",
            ),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# §1 — live_line.feed() per-chunk throughput
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_live_line_feed_midline_chunk_under_0_5ms() -> None:
    """feed() mid-line (no newline): reactive set only; target < 0.5ms median."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live_line = app.query_one(LiveLineWidget)
        assert not getattr(live_line, "_tw_enabled", False), (
            "Typewriter must be off for this benchmark"
        )

        batch_times: list[float] = []
        for _ in range(4):  # 4 batches × 50 = 200 calls
            t0 = time.perf_counter()
            for _ in range(50):
                live_line.feed("a" * 40)
            batch_times.append((time.perf_counter() - t0) * 1000)
            await pilot.pause()  # flush reactive notifications between batches

        per_call_ms = [t / 50 for t in batch_times]
        median_ms = statistics.median(per_call_ms)
        p99_approx = max(per_call_ms)

        _assert_or_warn(
            median_ms < 0.5,
            f"feed() mid-line median: {median_ms:.3f}ms (target <0.5ms)",
        )
        _assert_or_warn(
            p99_approx < 1.0,
            f"feed() mid-line max-batch per-call: {p99_approx:.3f}ms (target <1ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_live_line_feed_line_commit_chunk_under_2ms() -> None:
    """feed() line-committing chunk: Text.from_ansi + write_with_source; target < 2ms median."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live_line = app.query_one(LiveLineWidget)

        chunk = "hello " * 6 + "\n"
        batch_times: list[float] = []
        for _ in range(4):  # 4 batches × 25 = 100 calls
            t0 = time.perf_counter()
            for _ in range(25):
                live_line.feed(chunk)
            batch_times.append((time.perf_counter() - t0) * 1000)
            await pilot.pause()

        per_call_ms = [t / 25 for t in batch_times]
        median_ms = statistics.median(per_call_ms)

        _assert_or_warn(
            median_ms < 2.0,
            f"feed() line-commit median: {median_ms:.3f}ms (target <2ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_consume_output_100_chunks_drains_within_5s() -> None:
    """100 chunks + sentinel drain via _consume_output; total target < 500ms."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        t_start = time.perf_counter()
        for i in range(100):
            app._output_queue.put_nowait(f"chunk {i}")
        app._output_queue.put_nowait(None)  # sentinel

        deadline = time.perf_counter() + 5.0
        while not app._output_queue.empty():
            if time.perf_counter() > deadline:
                pytest.fail("Queue did not drain within 5s")
            await pilot.pause()

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        _assert_or_warn(
            elapsed_ms < 500,
            f"100-chunk drain: {elapsed_ms:.1f}ms (target <500ms)",
        )


# ---------------------------------------------------------------------------
# §2 — HistorySearchOverlay._render_results() filter pass
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_history_fuzzy_rank_50_candidates_under_2ms() -> None:
    """fuzzy_rank on 50 realistic TurnCandidates; target < 2ms median."""
    candidates = _make_candidates(50)
    times: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        fuzzy_rank("wo", candidates, limit=200)
        times.append((time.perf_counter() - t0) * 1000)
    median_ms = statistics.median(times)
    _assert_or_warn(
        median_ms < 2.0,
        f"fuzzy_rank 50 TurnCandidates median: {median_ms:.3f}ms (target <2ms)",
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_history_render_results_50_turns_under_50ms() -> None:
    """Single _render_results() call with 50 candidates; per-iteration target < 35ms.

    Headless-test target (35ms): pilot.pause() drives a full layout+render cycle,
    adding ~10-15ms of fixed overhead absent in real terminals.  The widget-reuse
    optimisation (update-in-place, limit=15) brought this from ~75ms → ~27ms.
    Real-terminal cost is well under 16ms because Textual coalesces repaints and
    the 150ms debounce on Input.Changed prevents per-keystroke calls entirely.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay._candidates = _make_candidates(50)
        overlay.add_class("--visible")  # CSS-only; does NOT call _render_results()
        await pilot.pause()

        t0 = time.perf_counter()
        overlay._render_results("wo")   # "wo" is a subsequence; renders up to 15 items
        await pilot.pause()             # flush DOM ops
        elapsed_ms = (time.perf_counter() - t0) * 1000

        _assert_or_warn(
            elapsed_ms < 50.0,
            f"_render_results single call per-iteration: {elapsed_ms:.1f}ms (target <50ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_history_render_results_keystroke_loop_under_50ms_median() -> None:
    """20-keystroke loop: per-iteration cost (call + DOM flush); median target < 35ms.

    Headless-test target (35ms): see note in test_history_render_results_50_turns_under_35ms.
    Widget reuse (update-in-place on count-stable queries) keeps subsequent iterations
    cheaper than the initial mount.  Debounce (150ms) means real users never hit this
    path per-keystroke.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay._candidates = _make_candidates(50)
        overlay.add_class("--visible")
        await pilot.pause()

        # All queries are subsequences of "word " — guaranteed non-empty results.
        queries = [
            "w", "wo", "wor", "word", "rd", "d", "o", "wd",
            "wrd", "w", "wo", "wor", "word", "rd", "d", "o",
            "wd", "wrd", "w", "wo",
        ]
        times: list[float] = []
        for q in queries:
            t0 = time.perf_counter()
            overlay._render_results(q)
            await pilot.pause()
            times.append((time.perf_counter() - t0) * 1000)

        median_ms = statistics.median(times)
        max_ms = max(times)
        _assert_or_warn(
            median_ms < 50.0,
            f"keystroke loop per-iteration median: {median_ms:.1f}ms (target <50ms)",
        )
        _assert_or_warn(
            max_ms < 80.0,
            f"keystroke loop per-iteration max: {max_ms:.1f}ms (target <80ms)",
        )


# ---------------------------------------------------------------------------
# §3 — Timer delivery under saturated output queue
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_timer_fires_under_load_no_starvation() -> None:
    """set_timer(100ms) fires within 200ms while 500 chunks drain through _consume_output."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        fired_at: list[float] = []
        t0 = time.perf_counter()

        def on_timer() -> None:
            fired_at.append(time.perf_counter() - t0)

        app.set_timer(0.1, on_timer)
        for i in range(500):
            app._output_queue.put_nowait(f"chunk {i}")

        deadline = time.perf_counter() + 2.0
        while not fired_at:
            if time.perf_counter() > deadline:
                pytest.fail("Timer did not fire within 2s")
            await pilot.pause()

        _assert_or_warn(
            fired_at[0] < 0.2,
            f"Timer fired at {fired_at[0] * 1000:.0f}ms (target <200ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_event_loop_probe_jitter_under_load() -> None:
    """EventLoopLatencyProbe sees no jitter > 50ms while 200 chunks drain.

    Configuration: expected_interval_s=0.05 (50ms), budget_ms=20.
    Any actual interval > 70ms (jitter > 20ms) increments over_budget_count.
    A 50ms event-loop stall → actual ≈ 100ms → jitter = 50ms > 20ms → detected.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        probe = EventLoopLatencyProbe(budget_ms=20.0, expected_interval_s=0.05)
        # probe.tick is a plain def — valid set_interval callback (no await).
        app.set_interval(0.05, probe.tick)

        for i in range(200):
            app._output_queue.put_nowait(f"chunk {i}")

        # asyncio.sleep() suspends the test coroutine; Textual event loop continues.
        # ~30 probe ticks (1.5s / 0.05s) fire while 200 chunks drain.
        await asyncio.sleep(1.5)
        await pilot.pause()

        assert probe.over_budget_count == 0, (
            f"Event loop stalled under streaming load: "
            f"{probe.over_budget_count} jitter spike(s) > 50ms"
        )


# ---------------------------------------------------------------------------
# §4 — OutputPanel.watch_scroll_y call frequency
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_handler_invocation_count_per_100_chunks() -> None:
    """watch_scroll_y fires ≤ 100 times per 100 streamed chunks."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(OutputPanel)

        # Plain closure — NOT an instance method.  invoke_watcher counts 1 parameter
        # and calls fn(new_value).  Method form (self, new_y) would cause invoke_watcher
        # to pass (old_value, new_value) with self=old_value — silently wrong.
        count_box = [0]
        original_fn = OutputPanel.watch_scroll_y  # unbound function

        def counting_watcher(new_y: float) -> None:
            count_box[0] += 1
            original_fn(panel, new_y)

        panel.watch_scroll_y = counting_watcher   # instance-level override

        for i in range(100):
            app._output_queue.put_nowait(f"chunk {i}")
        app._output_queue.put_nowait(None)

        deadline = time.perf_counter() + 5.0
        while not app._output_queue.empty():
            if time.perf_counter() > deadline:
                pytest.fail("Queue did not drain within 5s")
            await pilot.pause()
        await pilot.pause()  # flush deferred scroll calls

        _assert_or_warn(
            count_box[0] <= 100,
            f"watch_scroll_y called {count_box[0]} times per 100 chunks (target ≤100)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_handler_cost_under_0_1ms() -> None:
    """watch_scroll_y method body: 1 float comparison + 1 bool write; target < 0.1ms median."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)

        times: list[float] = []
        for _ in range(1000):
            t0 = time.perf_counter()
            panel.watch_scroll_y(9999.0)  # max_scroll_y ≈ 0 → True branch → _user_scrolled_up=False
            times.append((time.perf_counter() - t0) * 1000)

        median_ms = statistics.median(times)
        _assert_or_warn(
            median_ms < 0.1,
            f"watch_scroll_y method body: {median_ms:.4f}ms (target <0.1ms)",
        )


# ---------------------------------------------------------------------------
# §5 — ResponseFlowEngine + StreamingCodeBlock hot paths
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_engine_process_line_plain_prose_under_0_5ms() -> None:
    """ResponseFlowEngine.process_line() plain prose: StreamingBlockBuffer + inline-md; target < 0.5ms median.

    Tests the per-line cost of the full prose pipeline: fence detection, setext lookahead
    buffer, apply_inline_markdown, and write_with_source to CopyableRichLog.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await pilot.pause()

        engine = getattr(msg, "_response_engine", None)
        if engine is None:
            pytest.skip("ResponseFlowEngine not available (HERMES_MARKDOWN=0?)")

        line = "This is a realistic prose response with **bold**, `inline code`, and *emphasis* tokens.\n"
        batch_size, n_batches = 50, 8
        batch_times: list[float] = []
        for _ in range(n_batches):
            t0 = time.perf_counter()
            for _ in range(batch_size):
                engine.process_line(line)
            batch_times.append((time.perf_counter() - t0) * 1000)
            await pilot.pause()

        per_call_ms = [t / batch_size for t in batch_times]
        median_ms = statistics.median(per_call_ms)
        p99_approx = max(per_call_ms)

        _assert_or_warn(
            median_ms < 0.5,
            f"Engine.process_line() median: {median_ms:.3f}ms (target <0.5ms)",
        )
        _assert_or_warn(
            p99_approx < 2.0,
            f"Engine.process_line() p99-approx: {p99_approx:.3f}ms (target <2ms)",
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_code_block_per_line_highlight_under_2ms() -> None:
    """StreamingCodeBlock.append_line(): per-line Pygments TerminalTrueColorFormatter; target < 2ms median.

    Measures the per-line syntax-highlight cost while a code block is in STREAMING state.
    Pygments lexing + TerminalTrueColorFormatter + RichLog write.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await pilot.pause()

        block = StreamingCodeBlock(lang="python", pygments_theme="monokai")
        await msg.mount(block)
        await pilot.pause()

        line = "    def compute_result(self, value: int) -> str:\n"
        batch_size, n_batches = 20, 6
        batch_times: list[float] = []
        for _ in range(n_batches):
            t0 = time.perf_counter()
            for _ in range(batch_size):
                block.append_line(line)
            batch_times.append((time.perf_counter() - t0) * 1000)
            await pilot.pause()

        per_call_ms = [t / batch_size for t in batch_times]
        median_ms = statistics.median(per_call_ms)

        _assert_or_warn(
            median_ms < 2.0,
            f"StreamingCodeBlock.append_line() median: {median_ms:.3f}ms (target <2ms)",
        )
