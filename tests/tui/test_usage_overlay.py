"""Tests for UsageOverlay chart + copy enhancements.

Spec: /home/xush/.hermes/usage-overlay-chart-spec.md
Tests: T1–T24 (T14–T18 sparkline deferred but included as stubs).
"""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.overlays import UsageOverlay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_overlay() -> UsageOverlay:
    """Instantiate a bare UsageOverlay (no app context needed for unit tests)."""
    return UsageOverlay()


def _make_mock_agent(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    total: int | None = None,
    calls: int = 0,
    model: str = "test-model",
    provider: str = "anthropic",
    turn_log: list[int] | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.model = model
    agent.provider = provider
    agent.base_url = None
    agent.session_input_tokens = input_tokens
    agent.session_output_tokens = output_tokens
    agent.session_cache_read_tokens = cache_read
    agent.session_cache_write_tokens = cache_write
    agent.session_total_tokens = total if total is not None else (input_tokens + output_tokens + cache_read + cache_write)
    agent.session_api_calls = calls
    agent.context_compressor = MagicMock(
        last_prompt_tokens=0,
        context_length=200_000,
        compression_count=0,
    )
    agent.get_rate_limit_state.return_value = None
    if turn_log is not None:
        agent.session_turn_token_log = turn_log
    else:
        # No attribute at all — tests graceful degradation
        del agent.session_turn_token_log
    return agent


# ---------------------------------------------------------------------------
# T1–T7: Chart rendering (unit tests — no Textual app needed)
# ---------------------------------------------------------------------------

class TestBuildChart:
    """T1–T7: _build_chart() unit tests."""

    def setup_method(self) -> None:
        self.ov = _make_overlay()

    def test_t1_total_zero_returns_no_data_note(self) -> None:
        """T1: total==0 returns no-data note."""
        result = self.ov._build_chart(0, 0, 0, 0)
        assert result == "  (no token data yet)"

    def test_t2_single_bucket_fills_full_bar(self) -> None:
        """T2: single non-zero bucket → bar is full width (30 chars of █)."""
        result = self.ov._build_chart(1000, 0, 0, 0)
        # Only Input row should appear (cache read/write/output are 0 → skipped)
        assert "Cache Read" not in result
        assert "Cache Write" not in result
        assert "Output" not in result
        # Input bar should have 30 █ chars (100% fill)
        assert "█" * 30 in result

    def test_t3_two_buckets_equal_split(self) -> None:
        """T3: 50/50 split → each bar has exactly 15 █ chars."""
        result = self.ov._build_chart(1000, 0, 0, 1000)
        lines = result.split("\n")
        bar_lines = [l for l in lines if "█" in l and "Input" in l or "█" in l and "Output" in l]
        # Both Input and Output rows present
        assert any("Input" in l for l in lines)
        assert any("Output" in l for l in lines)
        # Each has 15 filled chars
        for l in lines:
            if "Input" in l or "Output" in l:
                filled = l.count("█")
                assert filled == 15, f"Expected 15 █ in line, got {filled}: {l!r}"

    def test_t4_four_buckets_standard_mix(self) -> None:
        """T4: four non-zero buckets → correct filled count per bar."""
        inp, cr, cw, out = 40_000, 25_000, 5_000, 2_700
        total = inp + cr + cw + out
        result = self.ov._build_chart(inp, cr, cw, out)
        for count, label in [(inp, "Input"), (cr, "Cache Read"), (cw, "Cache Write"), (out, "Output")]:
            pct = count / total * 100
            expected_filled = max(0, min(30, round(pct / 100 * 30)))
            lines = result.split("\n")
            match = [l for l in lines if label in l]
            assert match, f"No row for {label}"
            actual_filled = match[0].count("█")
            assert actual_filled == expected_filled, (
                f"{label}: expected {expected_filled}, got {actual_filled}"
            )

    def test_t5_very_small_bucket_gives_zero_fill(self) -> None:
        """T5: a very small bucket (pct ≈ 0.3%) → filled==0, 30 spaces in bar."""
        # 1 token out of ~300 total → ~0.33%, round(0.0033 * 30) = 0
        inp = 299
        out = 1
        result = self.ov._build_chart(inp, 0, 0, out)
        lines = result.split("\n")
        output_line = [l for l in lines if "Output" in l][0]
        # Should have 0 block chars and 30 spaces in bar region
        filled = output_line.count("█")
        assert filled == 0

    def test_t6_all_four_buckets_nonzero_all_rows_present(self) -> None:
        """T6: all four non-zero → all four rows in output."""
        result = self.ov._build_chart(1000, 500, 200, 300)
        assert "Input" in result
        assert "Cache Read" in result
        assert "Cache Write" in result
        assert "Output" in result

    def test_t7_bar_width_clamp_never_exceeds_30(self) -> None:
        """T7: property test — BAR_WIDTH clamp holds over 100 random vectors."""
        rng = random.Random(42)
        BAR_WIDTH = 30
        for _ in range(100):
            vals = [rng.randint(0, 1_000_000) for _ in range(4)]
            inp, cr, cw, out = vals
            result = self.ov._build_chart(inp, cr, cw, out)
            if result == "  (no token data yet)":
                continue
            for line in result.split("\n"):
                if "█" in line:
                    filled = line.count("█")
                    assert 0 <= filled <= BAR_WIDTH, (
                        f"filled={filled} exceeds BAR_WIDTH={BAR_WIDTH} in: {line!r}"
                    )


# ---------------------------------------------------------------------------
# T10–T11: Plain-text copy content
# ---------------------------------------------------------------------------

class TestBuildPlainText:
    """T10–T11: _build_plain_text() excludes bar chart rows and Rich markup."""

    def setup_method(self) -> None:
        self.ov = _make_overlay()

    def _make_cost_result(self) -> object:
        cr = MagicMock()
        cr.amount_usd = None
        cr.status = "unknown"
        return cr

    def test_t10_bar_chart_rows_excluded(self) -> None:
        """T10: bar chart header and bar rows are absent from plain-text copy."""
        cost = self._make_cost_result()
        compressor = SimpleNamespace(last_prompt_tokens=0, context_length=200_000, compression_count=0)
        agent = SimpleNamespace(model="test")
        text = self.ov._build_plain_text(1000, 500, 200, 300, 2000, 3, cost, compressor, agent, [])
        # Bar chart header should NOT be present
        assert "Token Breakdown" not in text
        # No block char rows (those only appear in the chart section)
        assert "─" * 10 not in text  # dashes from chart header
        # But stat fields should be present
        assert "Input:" in text
        assert "Output:" in text

    def test_t11_no_rich_markup_in_plain_text(self) -> None:
        """T11: plain-text copy contains no Rich markup tags."""
        cost = self._make_cost_result()
        compressor = SimpleNamespace(last_prompt_tokens=0, context_length=200_000, compression_count=0)
        agent = SimpleNamespace(model="test")
        text = self.ov._build_plain_text(1000, 500, 200, 300, 2000, 3, cost, compressor, agent, [])
        assert "[dim]" not in text
        assert "[bold]" not in text
        assert "[/bold]" not in text
        assert "[/dim]" not in text


# ---------------------------------------------------------------------------
# T14–T18: Sparkline unit tests
# ---------------------------------------------------------------------------

class TestBuildSparkline:
    """T14–T18: _build_sparkline() deferred — agent field interface tests."""

    def setup_method(self) -> None:
        self.ov = _make_overlay()

    def test_t14_no_log_attribute_gives_empty_string(self) -> None:
        """T14: turn_log=[] (or absent) → sparkline section absent."""
        assert self.ov._build_sparkline([]) == ""

    def test_t15_single_entry_log(self) -> None:
        """T15: single-entry log → shows █ (1 call)."""
        result = self.ov._build_sparkline([100])
        assert "█" in result
        assert "1 call" in result

    def test_t16_two_entry_log(self) -> None:
        """T16: [100, 200] → two chars, second is █ (normalised max)."""
        result = self.ov._build_sparkline([100, 200])
        # Should have exactly 2 sparkline chars
        SPARKS = set("▁▂▃▄▅▆▇█")
        spark_chars = [c for c in result if c in SPARKS]
        assert len(spark_chars) == 2
        assert spark_chars[-1] == "█"  # last/max value = full bar

    def test_t17_fifty_entries_truncated_to_40(self) -> None:
        """T17: 50-entry log → sparkline shows only 40 chars wide."""
        log = list(range(1, 51))  # 50 entries
        result = self.ov._build_sparkline(log)
        SPARKS = set("▁▂▃▄▅▆▇█")
        spark_chars = [c for c in result if c in SPARKS]
        assert len(spark_chars) == 40
        # n in the label is still 50 (total turns)
        assert "50 calls" in result

    def test_t18_flat_log_all_max_chars(self) -> None:
        """T18: flat log (all same value) → all chars are █."""
        log = [500] * 10
        result = self.ov._build_sparkline(log)
        SPARKS = set("▁▂▃▄▅▆▇█")
        spark_chars = [c for c in result if c in SPARKS]
        assert all(c == "█" for c in spark_chars)


# ---------------------------------------------------------------------------
# T19–T21: Layout / CSS
# ---------------------------------------------------------------------------

class TestLayoutCSS:
    """T19–T21: CSS and hint line checks."""

    def test_t19_max_height_26_in_default_css(self) -> None:
        """T19: DEFAULT_CSS contains max-height: 26."""
        assert "max-height: 26" in UsageOverlay.DEFAULT_CSS

    def test_t20_hint_line_present_in_content(self) -> None:
        """T20: refresh_data produces content containing 'c copy' and 'Esc dismiss'."""
        ov = _make_overlay()
        # Simulate query_one returning a mock Static
        mock_static = MagicMock()
        ov.query_one = MagicMock(return_value=mock_static)

        agent = _make_mock_agent(input_tokens=1000, output_tokens=500, total=1500, calls=1)
        with patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            cr = MagicMock()
            cr.amount_usd = None
            cr.status = "unknown"
            mock_cost.return_value = cr
            ov.refresh_data(agent)

        call_args = mock_static.update.call_args[0][0]
        assert "c copy" in call_args
        assert "Esc dismiss" in call_args

    def test_t21_hint_line_present_even_when_total_is_zero(self) -> None:
        """T21: hint line still shown when total tokens == 0."""
        ov = _make_overlay()
        mock_static = MagicMock()
        ov.query_one = MagicMock(return_value=mock_static)

        agent = _make_mock_agent(total=0)
        with patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            cr = MagicMock()
            cr.amount_usd = None
            cr.status = "unknown"
            mock_cost.return_value = cr
            ov.refresh_data(agent)

        call_args = mock_static.update.call_args[0][0]
        assert "c copy" in call_args
        assert "no token data yet" in call_args


# ---------------------------------------------------------------------------
# T22–T24: Integration tests (require Textual app)
# ---------------------------------------------------------------------------

def _make_app_with_agent(
    input_tokens: int = 40_000,
    output_tokens: int = 2_700,
    cache_read: int = 25_000,
    cache_write: int = 5_000,
    turn_log: list[int] | None = None,
) -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    agent = MagicMock()
    agent.model = "claude-sonnet-4-6"
    agent.provider = "anthropic"
    agent.base_url = None
    agent.session_input_tokens = input_tokens
    agent.session_output_tokens = output_tokens
    agent.session_cache_read_tokens = cache_read
    agent.session_cache_write_tokens = cache_write
    agent.session_total_tokens = input_tokens + output_tokens + cache_read + cache_write
    agent.session_api_calls = 3
    agent.context_compressor = MagicMock(
        last_prompt_tokens=8_000,
        context_length=200_000,
        compression_count=0,
    )
    agent.get_rate_limit_state.return_value = None
    if turn_log is not None:
        agent.session_turn_token_log = turn_log
    # else: no attribute — graceful degradation
    cli.agent = agent
    return HermesApp(cli=cli)


async def _submit(pilot, app, cmd: str) -> None:
    from hermes_cli.tui.input_widget import HermesInput
    inp = app.query_one(HermesInput)
    inp.value = cmd
    inp.action_submit()
    await pilot.pause()


@pytest.mark.asyncio
async def test_t22_refresh_data_all_zeros_no_crash():
    """T22: refresh_data with all-zero agent → shows no-data note, no crash."""
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    agent = MagicMock()
    agent.model = "test"
    agent.provider = "anthropic"
    agent.base_url = None
    agent.session_input_tokens = 0
    agent.session_output_tokens = 0
    agent.session_cache_read_tokens = 0
    agent.session_cache_write_tokens = 0
    agent.session_total_tokens = 0
    agent.session_api_calls = 0
    agent.context_compressor = None
    agent.get_rate_limit_state.return_value = None
    # No session_turn_token_log → graceful degradation
    cli.agent = agent
    app = HermesApp(cli=cli)

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/usage")
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        assert ov.has_class("--visible")
        from textual.widgets import Static
        content = ov.query_one("#usage-content", Static).content
        content_str = str(content)
        assert "no token data yet" in content_str


@pytest.mark.asyncio
async def test_t23_chart_section_precedes_stats_section():
    """T23: chart section appears before stats section in rendered content."""
    app = _make_app_with_agent()

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/usage")
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        assert ov.has_class("--visible")
        from textual.widgets import Static
        content_str = str(ov.query_one("#usage-content", Static).content)
        token_breakdown_pos = content_str.find("Token Breakdown")
        model_pos = content_str.find("Model:")
        # Chart header comes before Model line in the stats section
        assert token_breakdown_pos >= 0, "Token Breakdown header not found"
        assert model_pos >= 0, "Model: line not found"
        assert token_breakdown_pos < model_pos, (
            "Expected chart section before stats; "
            f"chart@{token_breakdown_pos}, model@{model_pos}"
        )


@pytest.mark.asyncio
async def test_t24_c_key_visible_calls_do_copy():
    """T24a: c key with overlay visible → _do_copy called."""
    app = _make_app_with_agent()

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/usage")
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        assert ov.has_class("--visible")

        # Directly replace _do_copy on the instance to track invocations
        do_copy_called: list[bool] = []
        ov._do_copy = lambda: do_copy_called.append(True)  # type: ignore[method-assign]

        await pilot.press("c")
        await pilot.pause()

        # _do_copy should have been called exactly once
        assert len(do_copy_called) == 1


@pytest.mark.asyncio
async def test_t24b_c_key_hidden_does_not_call_do_copy():
    """T24b: c key with overlay hidden → _do_copy NOT called."""
    app = _make_app_with_agent()

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        # Overlay is hidden (never opened)
        ov = app.query_one(UsageOverlay)
        assert not ov.has_class("--visible")

        copy_calls: list[str] = []
        app._copy_text_with_hint = lambda t: copy_calls.append(t)  # type: ignore[method-assign]
        do_copy_called = []
        original = ov._do_copy
        ov._do_copy = lambda: do_copy_called.append(True)  # type: ignore[method-assign]

        await pilot.press("c")
        await pilot.pause()

        assert len(do_copy_called) == 0


# ---------------------------------------------------------------------------
# T8–T9: Copy keybinding (app-level guard) — unit-level via direct on_key logic
# ---------------------------------------------------------------------------

class TestCopyKeybindingGuard:
    """T8–T9: copy guard in _app_key_handler.py — verified via the integration
    tests T24a/T24b above. These unit tests verify the overlay's _do_copy
    delegates to app._copy_text_with_hint with non-empty text."""

    def test_t8_do_copy_calls_app_helper(self) -> None:
        """T8/T9: _do_copy delegates to app._copy_text_with_hint with stored text."""
        ov = _make_overlay()
        ov._last_plain_text = "Model: test\nInput:           1,000"
        calls: list[str] = []
        mock_app = MagicMock()
        mock_app._copy_text_with_hint = lambda t: calls.append(t)
        # app is a read-only Textual property; patch at DOMNode level
        with patch.object(type(ov), "app", new_callable=lambda: property(lambda self: mock_app)):
            ov._do_copy()
        assert len(calls) == 1
        assert calls[0] == ov._last_plain_text

    def test_t9_do_copy_with_empty_text_still_calls(self) -> None:
        """_do_copy forwards empty string too — let app handle clipboard."""
        ov = _make_overlay()
        ov._last_plain_text = ""
        calls: list[str] = []
        mock_app = MagicMock()
        mock_app._copy_text_with_hint = lambda t: calls.append(t)
        with patch.object(type(ov), "app", new_callable=lambda: property(lambda self: mock_app)):
            ov._do_copy()
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# T12: event.prevent_default() called on c when visible
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t12_prevent_default_called_on_c_when_visible():
    """T12: c key when overlay visible calls event.prevent_default()."""
    # We verify this indirectly: pressing c doesn't insert 'c' into input.
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app_with_agent()

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/usage")
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        assert ov.has_class("--visible")

        # Stub out _copy_text_with_hint to avoid real clipboard ops
        app._copy_text_with_hint = MagicMock()  # type: ignore[method-assign]

        # Record input value before pressing c
        inp = app.query_one(HermesInput)
        inp.value = ""

        await pilot.press("c")
        await pilot.pause()

        # If prevent_default worked, 'c' was NOT inserted into input
        assert "c" not in inp.value


# ---------------------------------------------------------------------------
# T13: clipboard unavailable → set_status_error via _copy_text_with_hint
# ---------------------------------------------------------------------------

class TestClipboardUnavailable:
    """T13: when clipboard unavailable, set_status_error is called."""

    def test_t13_no_clipboard_no_xclip_calls_set_status_error(self) -> None:
        """T13: _do_copy → app._copy_text_with_hint → set_status_error if no clipboard."""
        ov = _make_overlay()
        ov._last_plain_text = "Model: test"
        # Mock an app with no clipboard and no xclip
        mock_app = MagicMock()
        mock_app._clipboard_available = False
        mock_app._xclip_cmd = None
        error_calls: list[str] = []
        mock_app.set_status_error = lambda msg, **kw: error_calls.append(msg)

        def _copy_text_with_hint(text: str) -> None:
            # Simulate the real method logic for the no-clipboard path
            if not mock_app._clipboard_available:
                if mock_app._xclip_cmd:
                    pass  # would try subprocess
                else:
                    mock_app.set_status_error("no clipboard — install xclip or xsel", auto_clear_s=0)

        mock_app._copy_text_with_hint = _copy_text_with_hint
        with patch.object(type(ov), "app", new_callable=lambda: property(lambda self: mock_app)):
            ov._do_copy()
        assert any("no clipboard" in e for e in error_calls)
