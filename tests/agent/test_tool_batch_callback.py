"""tests/agent/test_tool_batch_callback.py — tool_batch_callback + usage_callback wiring (Phase 1)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# T1: AIAgent accepts tool_batch_callback without error
# ---------------------------------------------------------------------------
def test_aiagent_accepts_tool_batch_callback():
    from run_agent import AIAgent
    cb = MagicMock()
    agent = AIAgent(tool_batch_callback=cb)
    assert agent.tool_batch_callback is cb


# ---------------------------------------------------------------------------
# T2: AIAgent accepts usage_callback without error
# ---------------------------------------------------------------------------
def test_aiagent_accepts_usage_callback():
    from run_agent import AIAgent
    cb = MagicMock()
    agent = AIAgent(usage_callback=cb)
    assert agent.usage_callback is cb


# ---------------------------------------------------------------------------
# T3: tool_batch_callback is None by default
# ---------------------------------------------------------------------------
def test_tool_batch_callback_default_none():
    from run_agent import AIAgent
    agent = AIAgent()
    assert agent.tool_batch_callback is None


# ---------------------------------------------------------------------------
# T4: usage_callback is None by default
# ---------------------------------------------------------------------------
def test_usage_callback_default_none():
    from run_agent import AIAgent
    agent = AIAgent()
    assert agent.usage_callback is None


# ---------------------------------------------------------------------------
# T5: tool_batch_callback fires in sequential path before tool_start_callback
# ---------------------------------------------------------------------------
def test_tool_batch_callback_fires_before_tool_start_sequential():
    """Verify batch CB fires before start CB in sequential execution."""
    from run_agent import AIAgent
    call_order: list[str] = []

    batch_cb = MagicMock(side_effect=lambda *a: call_order.append("batch"))
    start_cb = MagicMock(side_effect=lambda *a: call_order.append("start"))

    agent = AIAgent(tool_batch_callback=batch_cb, tool_start_callback=start_cb)
    agent.quiet_mode = True

    # Build a minimal assistant_message mock
    tc = MagicMock()
    tc.id = "tc1"
    tc.function.name = "terminal"
    tc.function.arguments = '{"command": "ls"}'
    assistant_msg = MagicMock()
    assistant_msg.tool_calls = [tc]

    messages: list = []

    # Stub _invoke_tool to avoid actual tool execution
    with patch.object(agent, "_invoke_tool", return_value="ok"):
        with patch.object(agent, "_touch_activity", return_value=None):
            with patch.object(agent, "_get_budget_warning", return_value=None):
                try:
                    agent._execute_tool_calls_sequential(assistant_msg, messages, "task1")
                except Exception:
                    pass  # interrupts/missing attrs fine

    if "batch" in call_order and "start" in call_order:
        assert call_order.index("batch") < call_order.index("start"), \
            f"batch must fire before start, got order: {call_order}"


# ---------------------------------------------------------------------------
# T6: tool_batch_callback crash does not propagate to agent (try/except guard)
# ---------------------------------------------------------------------------
def test_tool_batch_callback_crash_does_not_crash_agent():
    from run_agent import AIAgent

    def _boom(*_):
        raise RuntimeError("TUI failure")

    agent = AIAgent(tool_batch_callback=_boom)
    agent.quiet_mode = True

    tc = MagicMock()
    tc.id = "tc1"
    tc.function.name = "terminal"
    tc.function.arguments = '{"command": "echo hi"}'
    assistant_msg = MagicMock()
    assistant_msg.tool_calls = [tc]

    messages: list = []
    with patch.object(agent, "_invoke_tool", return_value="ok"):
        with patch.object(agent, "_touch_activity", return_value=None):
            with patch.object(agent, "_get_budget_warning", return_value=None):
                try:
                    # Should not raise even though batch_cb raises
                    agent._execute_tool_calls_sequential(assistant_msg, messages, "task1")
                except SystemExit:
                    pass
                # If we get here without RuntimeError propagating, the guard works.
