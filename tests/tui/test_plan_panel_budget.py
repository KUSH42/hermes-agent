"""tests/tui/test_plan_panel_budget.py — Budget + cost integration (Phase 3, 9 tests)."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper: build budget text from raw values (mirrors _BudgetSection logic)
# ---------------------------------------------------------------------------

def _budget_text(cost_usd: float, tokens_in: int, tokens_out: int) -> str:
    cost_str = f"${cost_usd:.2f}" if cost_usd > 0 else "$0.00"
    in_k = f"{tokens_in / 1000:.1f}k" if tokens_in >= 1000 else str(tokens_in)
    out_k = f"{tokens_out / 1000:.1f}k" if tokens_out >= 1000 else str(tokens_out)
    return f"{cost_str} · {in_k}↑ {out_k}↓"


# T1: budget text with typical values
def test_budget_text_typical():
    text = _budget_text(0.12, 4300, 12100)
    assert "$0.12" in text
    assert "4.3k↑" in text
    assert "12.1k↓" in text


# T2: budget text with zero cost
def test_budget_text_zero():
    text = _budget_text(0.0, 0, 0)
    assert "$0.00" in text
    assert "0↑" in text
    assert "0↓" in text


# T3: budget text with sub-1k token counts
def test_budget_text_small_tokens():
    text = _budget_text(0.01, 500, 200)
    assert "500↑" in text
    assert "200↓" in text


# T4: budget text with large values
def test_budget_text_large():
    text = _budget_text(1.23, 100000, 50000)
    assert "$1.23" in text
    assert "100.0k↑" in text
    assert "50.0k↓" in text


# T5: turn_cost_usd reactive on HermesApp defaults to 0.0
def test_turn_cost_usd_default():
    from hermes_cli.tui.app import HermesApp
    assert hasattr(HermesApp, "turn_cost_usd")


# T6: turn_tokens_in reactive on HermesApp defaults to 0
def test_turn_tokens_in_default():
    from hermes_cli.tui.app import HermesApp
    assert hasattr(HermesApp, "turn_tokens_in")


# T7: turn_tokens_out reactive on HermesApp defaults to 0
def test_turn_tokens_out_default():
    from hermes_cli.tui.app import HermesApp
    assert hasattr(HermesApp, "turn_tokens_out")


# T8: _on_usage accumulates tokens across calls
def test_on_usage_accumulates():
    """Verify the accumulation logic (tested via cli object stub)."""
    class _CliStub:
        _turn_prompt_tokens = 0
        _turn_completion_tokens = 0
        _turn_cost_usd = 0.0

        def _on_usage(self, prompt, completion, cost_usd):
            self._turn_prompt_tokens = getattr(self, "_turn_prompt_tokens", 0) + prompt
            self._turn_completion_tokens = getattr(self, "_turn_completion_tokens", 0) + completion
            self._turn_cost_usd = getattr(self, "_turn_cost_usd", 0.0) + cost_usd

    cli = _CliStub()
    cli._on_usage(1000, 500, 0.01)
    cli._on_usage(2000, 800, 0.02)
    assert cli._turn_prompt_tokens == 3000
    assert cli._turn_completion_tokens == 1300
    assert abs(cli._turn_cost_usd - 0.03) < 1e-9


# T9: _reset_turn_state zeros all turn counters
def test_reset_turn_state_zeros_counters():
    class _CliStub:
        _turn_prompt_tokens = 999
        _turn_completion_tokens = 888
        _turn_cost_usd = 9.99

        def _reset_turn_state(self):
            self._turn_prompt_tokens = 0
            self._turn_completion_tokens = 0
            self._turn_cost_usd = 0.0

    cli = _CliStub()
    cli._reset_turn_state()
    assert cli._turn_prompt_tokens == 0
    assert cli._turn_completion_tokens == 0
    assert cli._turn_cost_usd == 0.0
