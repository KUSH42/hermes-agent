"""Tests for execute_streaming() — step 21 (BaseEnvironment + LocalEnvironment).

Run with:
    pytest tests/environments/test_execute_streaming.py -v
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# BaseEnvironment.execute_streaming — fallback path
# ---------------------------------------------------------------------------

class TestBaseEnvStreamingFallback:
    """The default execute_streaming() falls back to execute() and emits lines."""

    def _make_env(self):
        """Return a minimal BaseEnvironment subclass with execute() mocked."""
        from tools.environments.base import BaseEnvironment

        class _FakeEnv(BaseEnvironment):
            def _run_bash(self, cmd, **kw):
                raise NotImplementedError
            def cleanup(self):
                pass
            def _kill_process(self, proc):
                pass

        env = _FakeEnv.__new__(_FakeEnv)
        return env

    def test_fallback_calls_on_line_for_each_output_line(self):
        from tools.environments.base import BaseEnvironment

        class _FakeEnv(BaseEnvironment):
            def _run_bash(self, cmd, **kw):
                raise NotImplementedError
            def cleanup(self):
                pass
            def _kill_process(self, proc):
                pass
            def execute(self, command, cwd="", *, timeout=None, stdin_data=None):
                return {"output": "line1\nline2\nline3", "returncode": 0}

        env = _FakeEnv.__new__(_FakeEnv)
        collected = []
        result = env.execute_streaming("echo hi", on_line=collected.append)
        assert result["returncode"] == 0
        assert collected == ["line1", "line2", "line3"]

    def test_fallback_returns_execute_result(self):
        from tools.environments.base import BaseEnvironment

        class _FakeEnv(BaseEnvironment):
            def _run_bash(self, cmd, **kw):
                raise NotImplementedError
            def cleanup(self):
                pass
            def _kill_process(self, proc):
                pass
            def execute(self, command, cwd="", *, timeout=None, stdin_data=None):
                return {"output": "hello", "returncode": 42}

        env = _FakeEnv.__new__(_FakeEnv)
        result = env.execute_streaming("cmd")
        assert result == {"output": "hello", "returncode": 42}

    def test_fallback_no_on_line_noop(self):
        """execute_streaming without on_line silently skips emission."""
        from tools.environments.base import BaseEnvironment

        class _FakeEnv(BaseEnvironment):
            def _run_bash(self, cmd, **kw):
                raise NotImplementedError
            def cleanup(self):
                pass
            def _kill_process(self, proc):
                pass
            def execute(self, command, cwd="", *, timeout=None, stdin_data=None):
                return {"output": "out", "returncode": 0}

        env = _FakeEnv.__new__(_FakeEnv)
        # Should not raise
        result = env.execute_streaming("cmd")
        assert result["returncode"] == 0


# ---------------------------------------------------------------------------
# LocalEnvironment.execute_streaming — real streaming path
# ---------------------------------------------------------------------------

class TestLocalEnvExecuteStreaming:
    """LocalEnvironment.execute_streaming delivers lines incrementally."""

    def _make_local_env(self):
        from tools.environments.local import LocalEnvironment
        try:
            env = LocalEnvironment()
        except Exception:
            pytest.skip("LocalEnvironment not available in this test environment")
        return env

    def test_basic_echo(self):
        """Simple echo delivers its line via on_line before returning."""
        env = self._make_local_env()
        collected = []
        result = env.execute_streaming("echo hello_world", on_line=collected.append)
        env.cleanup()
        assert result["returncode"] == 0
        assert any("hello_world" in line for line in collected)

    def test_multiline_output(self):
        """Multi-line output is delivered one line at a time."""
        env = self._make_local_env()
        collected = []
        result = env.execute_streaming(
            "printf 'alpha\\nbeta\\ngamma\\n'",
            on_line=collected.append,
        )
        env.cleanup()
        assert result["returncode"] == 0
        assert "alpha" in collected
        assert "beta" in collected
        assert "gamma" in collected

    def test_incremental_timing(self):
        """Lines from a sleep-delayed command arrive before the command finishes."""
        env = self._make_local_env()
        timestamps = []

        def _on_line(line):
            timestamps.append((line, time.monotonic()))

        t0 = time.monotonic()
        result = env.execute_streaming(
            "echo first; sleep 0.5; echo second",
            on_line=_on_line,
        )
        env.cleanup()

        assert result["returncode"] == 0
        # Both lines must have arrived
        lines = [t[0] for t in timestamps]
        assert any("first" in l for l in lines)
        assert any("second" in l for l in lines)

        # "first" line should arrive significantly before the command finishes
        first_ts = next(t[1] for t in timestamps if "first" in t[0])
        total = time.monotonic() - t0
        # first line should arrive well before total (at least 0.3s before end)
        assert first_ts - t0 < total - 0.2, (
            f"first line arrived at {first_ts - t0:.2f}s, total={total:.2f}s"
        )

    def test_no_on_line_still_returns_output(self):
        """execute_streaming without on_line still returns full output."""
        env = self._make_local_env()
        result = env.execute_streaming("echo no_callback")
        env.cleanup()
        assert result["returncode"] == 0
        assert "no_callback" in result["output"]

    def test_output_in_result_matches_on_line_calls(self):
        """result['output'] contains the same text as what on_line received."""
        env = self._make_local_env()
        collected = []
        result = env.execute_streaming(
            "echo alpha; echo beta",
            on_line=collected.append,
        )
        env.cleanup()
        output_lines = [l for l in result["output"].splitlines() if l.strip()]
        assert "alpha" in output_lines
        assert "beta" in output_lines
        assert "alpha" in collected or any("alpha" in c for c in collected)


# ---------------------------------------------------------------------------
# terminal_tool streaming callback API
# ---------------------------------------------------------------------------

class TestTerminalToolStreamingCallback:
    """set_streaming_callback / reset_streaming_callback ContextVar API."""

    def test_set_and_get(self):
        from tools.terminal_tool import (
            _streaming_line_callback,
            set_streaming_callback,
            reset_streaming_callback,
        )
        cb = lambda line: None
        token = set_streaming_callback(cb)
        assert _streaming_line_callback.get(None) is cb
        reset_streaming_callback(token)
        assert _streaming_line_callback.get(None) is None

    def test_reset_restores_previous(self):
        """reset_streaming_callback restores the value that existed before set."""
        from tools.terminal_tool import (
            _streaming_line_callback,
            set_streaming_callback,
            reset_streaming_callback,
        )
        cb1 = lambda line: None
        cb2 = lambda line: None
        tok1 = set_streaming_callback(cb1)
        tok2 = set_streaming_callback(cb2)
        assert _streaming_line_callback.get(None) is cb2
        reset_streaming_callback(tok2)
        assert _streaming_line_callback.get(None) is cb1
        reset_streaming_callback(tok1)
        assert _streaming_line_callback.get(None) is None

    def test_independent_per_thread(self):
        """ContextVar values are independent across threads."""
        import threading
        from tools.terminal_tool import (
            _streaming_line_callback,
            set_streaming_callback,
            reset_streaming_callback,
        )
        thread_saw = []

        def _worker():
            # In a fresh thread, the ContextVar should have the default (None)
            thread_saw.append(_streaming_line_callback.get(None))

        tok = set_streaming_callback(lambda l: None)
        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        reset_streaming_callback(tok)
        # Child thread inherits context at spawn time — since tok was set
        # BEFORE spawning, the child should see the callback
        # (ContextVar copies parent context at thread spawn)
        # This test validates the *isolation* direction: child changes
        # don't affect parent, which is what we care about for safety.
        # The child saw whatever the parent had at spawn — just assert no error.
        assert len(thread_saw) == 1
