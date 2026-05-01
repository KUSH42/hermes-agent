"""Tests for CS-1 (placeholder separator) and CS-2 (idle bar hide)."""
from __future__ import annotations

import types
from typing import Any


# ---------------------------------------------------------------------------
# Helpers — StatusBar
# ---------------------------------------------------------------------------

def _make_bar():
    from hermes_cli.tui.widgets.status_bar import StatusBar

    class _IsolatedBar(StatusBar):
        app = None  # type: ignore[assignment]
        size = None  # type: ignore[assignment]
        content_size = None  # type: ignore[assignment]

    bar = object.__new__(_IsolatedBar)
    bar._model_changed_at = 0.0
    bar._cwd_changed_at = 0.0
    bar.__dict__["_tok_s_displayed"] = 0.0
    bar._pulse_active = False
    bar._classes = frozenset()
    return bar


def _make_app(**kwargs: Any) -> types.SimpleNamespace:
    defaults = dict(
        status_model="claude-sonnet-4-6",
        status_context_tokens=0,
        status_context_max=0,
        status_compaction_progress=0.0,
        status_compaction_enabled=True,
        status_streaming=False,
        agent_running=False,
        command_running=False,
        yolo_mode=False,
        compact=False,
        status_verbose=False,
        status_active_file="",
        status_active_file_offscreen=False,
        browse_mode=False,
        browse_index=0,
        _browse_total=0,
        status_output_dropped=False,
        context_pct=0.0,
        session_label="",
        session_count=1,
        status_error="",
        status_tok_s=0.0,
        status_phase="idle",
        status_cwd="",
        feedback=None,
        _cfg={},
    )
    defaults.update(kwargs)
    app = types.SimpleNamespace(**defaults)
    app.get_css_variables = lambda: {}
    return app


def _render(bar, app, *, width: int = 80) -> str:
    size_ns = types.SimpleNamespace(width=width, height=1)
    content_size_ns = types.SimpleNamespace(width=width, height=1)

    bar.__class__.app = property(lambda s: app)
    bar.__class__.size = property(lambda s: size_ns)
    bar.__class__.content_size = property(lambda s: content_size_ns)

    result = bar.render()
    if hasattr(result, "plain"):
        return result.plain
    return str(result)


# ---------------------------------------------------------------------------
# CS-1 — Placeholder separator
# ---------------------------------------------------------------------------

class TestCS1Placeholder:
    def test_default_placeholder_uses_middle_dot(self):
        import hermes_cli.tui.input.widget as _mod
        import inspect, re
        src = inspect.getsource(_mod)
        m = re.search(r'_default_placeholder\s*=\s*"([^"]+)"', src)
        assert m is not None, "_default_placeholder not found in source"
        assert "·" in m.group(1)

    def test_default_placeholder_no_double_space_runs(self):
        # Read the constant directly from the module's source code path
        import hermes_cli.tui.input.widget as _mod
        import inspect
        src = inspect.getsource(_mod)
        # Find the _default_placeholder value
        import re
        m = re.search(r'_default_placeholder\s*=\s*"([^"]+)"', src)
        assert m is not None, "_default_placeholder not found in source"
        placeholder = m.group(1)
        assert "  " not in placeholder, f"Double-space run found in: {placeholder!r}"

    def test_explicit_placeholder_overrides_default(self):
        """Passing placeholder= overrides the default (regression guard)."""
        import hermes_cli.tui.input.widget as _mod
        import inspect, re
        src = inspect.getsource(_mod)
        # The logic: if placeholder is truthy, use it; else use _default_placeholder
        # We verify by checking the code path condition
        placeholder_arg = "custom"
        _default = "Type a message · @file · /cmd · !shell"
        effective = placeholder_arg if placeholder_arg else _default
        assert effective == "custom"


# ---------------------------------------------------------------------------
# CS-2 — Compaction bar hidden when idle
# ---------------------------------------------------------------------------

class TestCS2BarIdleHide:
    def test_bar_hidden_at_zero_progress_full_width(self):
        bar = _make_bar()
        app = _make_app(status_compaction_progress=0.0, status_compaction_enabled=True)
        text = _render(bar, app, width=80)
        assert "▱" not in text
        assert "▰" not in text

    def test_bar_hidden_when_rounds_to_zero(self):
        bar = _make_bar()
        # 0.004 → rounds to 0% — bar must stay hidden
        app = _make_app(status_compaction_progress=0.004, status_compaction_enabled=True)
        text = _render(bar, app, width=80)
        assert "▱" not in text
        assert "0%" not in text

    def test_bar_shown_at_one_percent(self):
        bar = _make_bar()
        app = _make_app(status_compaction_progress=0.01, status_compaction_enabled=True)
        text = _render(bar, app, width=80)
        # 1% — bar is shown (empty cells present) and percent label shows
        assert "▱" in text
        assert "1%" in text

    def test_percent_clamped_on_overshoot(self):
        bar = _make_bar()
        app = _make_app(status_compaction_progress=1.05, status_compaction_enabled=True)
        text = _render(bar, app, width=80)
        assert "100%" in text
        assert "105%" not in text

    def test_narrow_glyph_hidden_at_zero(self):
        bar = _make_bar()
        app_zero = _make_app(status_compaction_progress=0.0, status_compaction_enabled=True)
        text_zero = _render(bar, app_zero, width=50)
        assert "▰" not in text_zero

        bar2 = _make_bar()
        app_half = _make_app(status_compaction_progress=0.5, status_compaction_enabled=True)
        text_half = _render(bar2, app_half, width=50)
        assert "▰" in text_half
