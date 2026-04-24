"""Tests for UsageOverlay ASCII chart, copy keybinding, and sparkline.

Covers spec T1–T24.
Sparkline tests T14–T18 are implemented (tested via _build_sparkline directly).
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import UsageOverlay
from textual.widgets import Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ChartHelper:
    """Non-Textual helper for pure-function tests on chart/sparkline methods."""

    _BAR_WIDTH = 30
    _build_chart = UsageOverlay._build_chart
    _build_sparkline = UsageOverlay._build_sparkline


def _h() -> _ChartHelper:
    return _ChartHelper()


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _make_agent(**kwargs: object) -> MagicMock:
    agent = MagicMock()
    inp = int(kwargs.get("input", 0))
    out = int(kwargs.get("output", 0))
    cr = int(kwargs.get("cache_read", 0))
    cw = int(kwargs.get("cache_write", 0))
    agent.session_input_tokens = inp
    agent.session_output_tokens = out
    agent.session_cache_read_tokens = cr
    agent.session_cache_write_tokens = cw
    agent.session_total_tokens = inp + out + cr + cw
    agent.session_api_calls = int(kwargs.get("calls", 0))
    agent.model = str(kwargs.get("model", "test-model"))
    agent.provider = None
    agent.base_url = None
    agent.context_compressor = None
    agent.get_rate_limit_state.side_effect = Exception("no rl")
    return agent


def _mock_cost() -> MagicMock:
    cost = MagicMock()
    cost.amount_usd = None
    cost.status = ""
    return cost


# ---------------------------------------------------------------------------
# T1–T7: _build_chart unit tests
# ---------------------------------------------------------------------------


def test_t1_zero_total_returns_no_data_note():
    """T1: total == 0 → _build_chart returns exact no-data string with leading spaces."""
    result = _h()._build_chart(0, 0, 0, 0)
    assert result == "  (no token data yet)"


def test_t2_single_bucket_input_only_full_bar():
    """T2: input only → single Input row with 30 filled chars."""
    result = _h()._build_chart(40000, 0, 0, 0)
    data_rows = [l for l in result.split("\n") if "█" in l]
    assert len(data_rows) == 1
    assert "Input" in data_rows[0]
    assert "█" * 30 in data_rows[0]


def test_t3_two_equal_buckets_half_bars():
    """T3: 50/50 input/output split → each bar has exactly 15 filled chars."""
    result = _h()._build_chart(5000, 0, 0, 5000)
    data_rows = [l for l in result.split("\n") if "█" in l]
    assert len(data_rows) == 2
    for row in data_rows:
        assert row.count("█") == 15


def test_t4_four_buckets_correct_fill():
    """T4: four buckets → each filled == round(count/total * 30), clamped to [0,30]."""
    inp, cr, cw, out = 40000, 25000, 5000, 2700
    total = inp + cr + cw + out
    result = _h()._build_chart(inp, cr, cw, out)
    data_rows = [l for l in result.split("\n") if "█" in l]
    assert len(data_rows) == 4
    for count, label_prefix in [(inp, "Input"), (cr, "Cache"), (cw, "Cache"), (out, "Output")]:
        pct = count / total * 100
        expected = max(0, min(30, round(pct / 100 * 30)))
        matching = [r for r in data_rows if "█" * expected in r]
        assert matching, f"No row with {expected} filled chars for count={count}"


def test_t5_very_small_bucket_row_rendered_zero_filled():
    """T5: count > 0 but pct ≈ 0.3% → row rendered; filled == 0 so bar is spaces."""
    result = _h()._build_chart(99700, 300, 0, 0)
    # Cache Read row must be present
    assert "Cache Read" in result
    cr_rows = [l for l in result.split("\n") if "Cache Read" in l]
    assert cr_rows
    cr_row = cr_rows[0]
    # filled = round(0.003 * 30) = round(0.09) = 0 → no █ in bar section
    bar_start = cr_row.index(" ", cr_row.index("Cache Read") + len("Cache Read"))
    bar_section = cr_row[bar_start + 1 : bar_start + 31]
    assert "█" not in bar_section


def test_t6_all_four_buckets_nonzero_all_rows_rendered():
    """T6: all four buckets non-zero → all four label rows present."""
    result = _h()._build_chart(1000, 1000, 1000, 1000)
    assert "Input" in result
    assert "Cache Read" in result
    assert "Cache Write" in result
    assert "Output" in result
    data_rows = [l for l in result.split("\n") if "█" in l]
    assert len(data_rows) == 4


def test_t7_bar_width_never_exceeds_30():
    """T7: round() never produces filled > BAR_WIDTH (100-vector property test)."""
    h = _h()
    rng = random.Random(42)
    for _ in range(100):
        inp = rng.randint(0, 1_000_000)
        cr = rng.randint(0, 1_000_000)
        cw = rng.randint(0, 1_000_000)
        out = rng.randint(0, 1_000_000)
        if inp + cr + cw + out == 0:
            continue
        result = h._build_chart(inp, cr, cw, out)
        for line in result.split("\n"):
            filled = line.count("█")
            assert filled <= 30, f"filled={filled} > 30 in: {line!r}"


# ---------------------------------------------------------------------------
# T8–T13: Copy keybinding tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t8_c_key_hidden_no_copy():
    """T8: c key while --visible NOT set → copy not triggered, prevent_default not called."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        assert not uov.has_class("--visible")

        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            mock_copy.assert_not_called()
            event.prevent_default.assert_not_called()


@pytest.mark.asyncio
async def test_t9_c_key_visible_triggers_copy():
    """T9: c key while --visible set → _copy_text_with_hint called with plain text."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        uov.add_class("--visible")
        uov._last_plain_text = "token stats here"

        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            mock_copy.assert_called_once_with("token stats here")


@pytest.mark.asyncio
async def test_t10_plain_text_excludes_bar_chart_rows():
    """T10: plain-text copy excludes bar chart rows; sparkline chars permitted."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent(input=40000, output=2700, cache_read=25000, cache_write=5000)

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        plain = uov._last_plain_text
        assert "─" not in plain  # rule chars from chart section header
        assert "Token Breakdown" not in plain
        assert "[dim]" not in plain
        assert "█" not in plain  # bar chart ASCII art excluded from copy


@pytest.mark.asyncio
async def test_t11_plain_text_excludes_rich_markup():
    """T11: plain-text copy contains no Rich markup tags."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent(input=1000, output=500)

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        plain = uov._last_plain_text
        assert "[dim]" not in plain
        assert "[bold]" not in plain
        assert "[/bold]" not in plain


@pytest.mark.asyncio
async def test_t12_prevent_default_called_when_visible():
    """T12: event.prevent_default() called on c key when overlay visible."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        uov.add_class("--visible")
        uov._last_plain_text = "stats"

        with patch.object(app, "_copy_text_with_hint"):
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            event.prevent_default.assert_called()


@pytest.mark.asyncio
async def test_t13_clipboard_unavailable_calls_status_error():
    """T13: when clipboard unavailable, _copy_text_with_hint propagates to set_status_error."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        uov.add_class("--visible")
        uov._last_plain_text = "stats"

        def _no_clip(text: str) -> None:
            app.set_status_error("no clipboard — install xclip or xsel")

        with (
            patch.object(app, "_copy_text_with_hint", side_effect=_no_clip),
            patch.object(app, "set_status_error") as mock_err,
        ):
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# T14–T18: Sparkline tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t14_no_turn_log_attribute_sparkline_absent():
    """T14: agent has no session_turn_token_log → sparkline section absent from rendered content."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent(input=1000, output=500)
        # Explicitly ensure the attribute is absent (MagicMock would otherwise auto-create it)
        del agent.session_turn_token_log

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        content = str(uov.query_one("#usage-content", Static).content)
        assert "Context growth" not in content


def test_t15_single_entry_log_flat_baseline():
    """T15: single-entry log → 'Context growth: █ (1 call)'."""
    result = _h()._build_sparkline([100])
    assert result == "Context growth: █ (1 call)"


def test_t16_two_entry_log_second_is_max():
    """T16: log [100, 200] → 2 chars, second is █ (normalised max)."""
    result = _h()._build_sparkline([100, 200])
    assert "Context growth:" in result
    chars = result.split(": ")[1].split(" (")[0]
    assert len(chars) == 2
    assert chars[1] == "█"


def test_t17_long_log_capped_at_40_chars():
    """T17: 50-entry log → sparkline shows 40 chars; label shows (50 calls)."""
    log = list(range(1, 51))
    result = _h()._build_sparkline(log)
    chars = result.split(": ")[1].split(" (")[0]
    assert len(chars) == 40
    assert "(50 calls)" in result


def test_t18_flat_log_all_full_blocks():
    """T18: all-same-value log → all chars are █ (min==max → always max index)."""
    log = [1000] * 5
    result = _h()._build_sparkline(log)
    chars = result.split(": ")[1].split(" (")[0]
    assert all(c == "█" for c in chars)


# ---------------------------------------------------------------------------
# T19–T21: Layout / CSS tests
# ---------------------------------------------------------------------------


def test_t19_max_height_26_in_css():
    """T19: DEFAULT_CSS specifies max-height: 26."""
    assert "max-height: 26" in UsageOverlay.DEFAULT_CSS


@pytest.mark.asyncio
async def test_t20_hint_line_present_in_content():
    """T20: rendered content contains 'c copy' and 'Esc dismiss'."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent(input=1000, output=500)

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        content = str(uov.query_one("#usage-content", Static).content)
        assert "c copy" in content
        assert "Esc dismiss" in content


@pytest.mark.asyncio
async def test_t21_hint_line_present_when_zero_total():
    """T21: zero total → hint line still shown alongside no-data note."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent()  # all zeros

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        content = str(uov.query_one("#usage-content", Static).content)
        assert "c copy" in content


# ---------------------------------------------------------------------------
# T22–T24: Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t22_refresh_data_all_zeros_no_crash():
    """T22: refresh_data with all-zero agent → no crash, shows no-data note."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent()

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        content = str(uov.query_one("#usage-content", Static).content)
        assert "no token data yet" in content.lower()


@pytest.mark.asyncio
async def test_t23_chart_precedes_stats_in_content():
    """T23: chart section (Token Breakdown) appears before stats section (Model:)."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        agent = _make_agent(input=40000, output=2700, cache_read=25000, cache_write=5000)

        with (
            patch("agent.usage_pricing.estimate_usage_cost", return_value=_mock_cost()),
            patch("agent.usage_pricing.CanonicalUsage"),
        ):
            uov.refresh_data(agent)

        content = str(uov.query_one("#usage-content", Static).content)
        chart_pos = content.find("Token Breakdown")
        model_pos = content.find("Model:")
        assert chart_pos != -1, "chart section not found"
        assert model_pos != -1, "stats section not found"
        assert chart_pos < model_pos


@pytest.mark.asyncio
async def test_t24_c_key_visible_vs_hidden():
    """T24: c key — visible calls _do_copy; hidden does not."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        uov = app.query_one(UsageOverlay)
        uov._last_plain_text = "test stats"

        # Hidden: _do_copy NOT called
        with patch.object(uov, "_do_copy") as mock_copy:
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            mock_copy.assert_not_called()

        # Visible: _do_copy IS called
        uov.add_class("--visible")
        with patch.object(uov, "_do_copy") as mock_copy:
            event = MagicMock()
            event.key = "c"
            app.on_key(event)
            await pilot.pause()
            mock_copy.assert_called_once()
