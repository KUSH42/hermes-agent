"""Tests for TTE-SETTLE-M1 / H1 / H2 — settle frame gradient direction fix.

Classes:
    TestGetEffectGradientDirection  (5 tests)  tte_runner helper
    TestHeroAnsiWithStopsDirection  (7 tests)  _hero_ansi_with_stops branches
    TestSettleDirectionWiring       (3 tests)  _play_tte_in_output_panel wires direction
Total: 15 tests
"""
from __future__ import annotations

import inspect
import re
import sys
import threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

tte = pytest.importorskip("terminaltexteffects", reason="terminaltexteffects not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ansi_rows(ansi: str) -> list[list[tuple[int, int, int]]]:
    """Parse ANSI truecolor output into rows of (r,g,b) per visible char."""
    rows: list[list[tuple[int, int, int]]] = []
    cur_rgb: tuple[int, int, int] = (255, 215, 0)
    current_row: list[tuple[int, int, int]] = []
    # Strip escape sequences but extract RGB colors
    # Pattern: ESC[38;2;R;G;Bm or ESC[0m etc.
    i = 0
    text = ansi
    while i < len(text):
        if text[i] == "\033" and i + 1 < len(text) and text[i + 1] == "[":
            j = i + 2
            while j < len(text) and text[j] not in ("m", "M"):
                j += 1
            seq = text[i + 2:j]
            parts = seq.split(";")
            if len(parts) >= 5 and parts[0] == "38" and parts[1] == "2":
                try:
                    cur_rgb = (int(parts[2]), int(parts[3]), int(parts[4]))
                except ValueError:
                    pass
            i = j + 1
        elif text[i] == "\n":
            rows.append(current_row)
            current_row = []
            i += 1
        else:
            current_row.append(cur_rgb)
            i += 1
    if current_row:
        rows.append(current_row)
    return rows


def _make_cli_hero_ansi(stops, direction, hero):
    """Call _hero_ansi_with_stops via a minimal mock cli bound method."""
    import cli as cli_module
    cli = MagicMock()
    cli._hero_ansi_colored = MagicMock(return_value="")
    method = cli_module.HermesCLI._hero_ansi_with_stops.__get__(cli)
    return method(hero, stops, direction)


# ---------------------------------------------------------------------------
# TestGetEffectGradientDirection
# ---------------------------------------------------------------------------

class TestGetEffectGradientDirection:
    """TTE-SETTLE-M1: get_effect_gradient_direction API."""

    def test_vhstape_returns_vertical(self):
        from hermes_cli.tui.tte_runner import get_effect_gradient_direction
        assert get_effect_gradient_direction("vhstape") == "VERTICAL"

    def test_fireworks_returns_horizontal(self):
        from hermes_cli.tui.tte_runner import get_effect_gradient_direction
        assert get_effect_gradient_direction("fireworks") == "HORIZONTAL"

    def test_bouncyballs_returns_diagonal(self):
        from hermes_cli.tui.tte_runner import get_effect_gradient_direction
        assert get_effect_gradient_direction("bouncyballs") == "DIAGONAL"

    def test_unknown_effect_returns_diagonal(self):
        from hermes_cli.tui.tte_runner import get_effect_gradient_direction
        assert get_effect_gradient_direction("totally_unknown_fx_xyz") == "DIAGONAL"

    def test_no_direction_attr_returns_diagonal(self, monkeypatch):
        from hermes_cli.tui import tte_runner
        from hermes_cli.tui.tte_runner import get_effect_gradient_direction

        # Patch resolve_effect to return a fake spec; patch importlib to
        # return a fake class whose effect_config has no final_gradient_direction.
        import importlib as _importlib

        fake_cfg = SimpleNamespace()  # no final_gradient_direction attribute
        fake_effect = SimpleNamespace(effect_config=fake_cfg)

        class FakeCls:
            def __init__(self, text):
                pass
            effect_config = fake_cfg

        monkeypatch.setattr(tte_runner, "resolve_effect", lambda name: ("fake.mod", "FakeCls"))
        monkeypatch.setattr(tte_runner, "_apply_effect_params", lambda *a, **kw: False)

        orig_import = _importlib.import_module
        def _mock_import(name):
            if name == "fake.mod":
                mod = SimpleNamespace(FakeCls=FakeCls)
                return mod
            return orig_import(name)

        monkeypatch.setattr(_importlib, "import_module", _mock_import)

        result = get_effect_gradient_direction("whatever")
        assert result == "DIAGONAL"


# ---------------------------------------------------------------------------
# TestHeroAnsiWithStopsDirection
# ---------------------------------------------------------------------------

class TestHeroAnsiWithStopsDirection:
    """TTE-SETTLE-H1: direction-aware _hero_ansi_with_stops."""

    STOPS = ["#000000", "#FF0000", "#FFFFFF"]

    def test_vertical_rows_uniform_color(self):
        hero = "AAAAA\nBBBBB\nCCCCC"
        out = _make_cli_hero_ansi(self.STOPS, "VERTICAL", hero)
        rows = _parse_ansi_rows(out)
        assert len(rows) == 3
        # All chars in each row share the same color
        for row in rows:
            assert len(set(row)) == 1, f"row not uniform: {row}"
        # Row 0 and row 2 have different colors
        assert rows[0][0] != rows[2][0]

    def test_vertical_single_row(self):
        hero = "HELLO"
        out = _make_cli_hero_ansi(self.STOPS, "VERTICAL", hero)
        rows = _parse_ansi_rows(out)
        assert len(rows) == 1
        # Single row → t=0.0 → all chars = stops[0] color (black = 0,0,0)
        assert all(r == (0, 0, 0) for r in rows[0])

    def test_horizontal_cols_uniform_color(self):
        hero = "ABCD\nABCD\nABCD"
        out = _make_cli_hero_ansi(self.STOPS, "HORIZONTAL", hero)
        rows = _parse_ansi_rows(out)
        assert len(rows) == 3
        # All chars in the same column share the same color
        for col in range(4):
            col_colors = [rows[row][col] for row in range(3)]
            assert len(set(col_colors)) == 1, f"col {col} not uniform: {col_colors}"
        # First and last column differ
        assert rows[0][0] != rows[0][3]

    def test_horizontal_single_char_line(self):
        hero = "X\nX\nX"
        out = _make_cli_hero_ansi(self.STOPS, "HORIZONTAL", hero)
        rows = _parse_ansi_rows(out)
        # max_col=1 → t=0.0 → all chars = stops[0] color
        assert all(row[0] == (0, 0, 0) for row in rows)

    def test_diagonal_unchanged(self):
        hero = "AB\nCD"
        # DIAGONAL should match the char-count original impl
        out_diag = _make_cli_hero_ansi(self.STOPS, "DIAGONAL", hero)
        # Also run as default (no direction arg)
        import cli as cli_module
        cli = MagicMock()
        cli._hero_ansi_colored = MagicMock(return_value="")
        method = cli_module.HermesCLI._hero_ansi_with_stops.__get__(cli)
        out_default = method(hero, self.STOPS)
        assert out_diag == out_default

    def test_radial_falls_through_to_diagonal(self):
        hero = "AB\nCD"
        out_radial = _make_cli_hero_ansi(self.STOPS, "RADIAL", hero)
        out_diag = _make_cli_hero_ansi(self.STOPS, "DIAGONAL", hero)
        assert out_radial == out_diag

    def test_single_stop_delegates(self):
        import cli as cli_module
        cli = MagicMock()
        sentinel = "SENTINEL_RESULT"
        cli._hero_ansi_colored = MagicMock(return_value=sentinel)
        method = cli_module.HermesCLI._hero_ansi_with_stops.__get__(cli)
        result = method("HELLO", ["#FFD700"], "VERTICAL")
        cli._hero_ansi_colored.assert_called_once_with("HELLO")
        assert result == sentinel

    def test_vertical_trailing_newline_safe(self):
        # The phantom empty line from split("\n") changes t-values and thus colors,
        # but must NOT raise and downstream .splitlines() must have the same number
        # of non-blank lines (the phantom row is empty and contributes at most one
        # extra blank/ANSI-only line that downstream _splice_startup_banner_frame
        # ignores via its frame_lines[rel] access pattern).
        hero_with_nl = "abc\ndef\n"
        hero_without_nl = "abc\ndef"
        out_with = _make_cli_hero_ansi(self.STOPS, "VERTICAL", hero_with_nl)
        out_without = _make_cli_hero_ansi(self.STOPS, "VERTICAL", hero_without_nl)
        # Both must not raise; non-blank line count must match (≤1 phantom extra line).
        non_blank_with = [l for l in out_with.splitlines() if l.strip()]
        non_blank_without = [l for l in out_without.splitlines() if l.strip()]
        assert len(non_blank_with) == len(non_blank_without)


# ---------------------------------------------------------------------------
# TestSettleDirectionWiring
# ---------------------------------------------------------------------------

def _make_mock_app():
    app = MagicMock()
    app.is_running = True
    app._startup_output_panel_width = 0
    return app


def _make_cfg(cli_module, **overrides):
    data = dict(effect_name="vhstape", max_frames=5, max_wall_s=30.0, fps=30, params={})
    data.update(overrides)
    return cli_module._StartupTteConfig(**data)


def _run_coro(coro) -> None:
    try:
        coro.send(None)
    except StopIteration:
        pass


def _sync_call_from_thread(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        _run_coro(result)
    return result


def _install_draining_set_interval(mock_app):
    """set_interval + call_from_thread that drain ticks synchronously (mirrors test_tte_cache)."""
    _tick_fn: list = []
    _stop: list[bool] = [False]

    class _MockTimer:
        def stop(self) -> None:
            _stop[0] = True

    def _set_interval_side_effect(interval, fn):
        _tick_fn.append(fn)
        return _MockTimer()

    mock_app.set_interval.side_effect = _set_interval_side_effect

    def _call_from_thread_side_effect(fn, *a, **kw):
        r = fn(*a, **kw)
        if inspect.isawaitable(r):
            _run_coro(r)
        while _tick_fn and not _stop[0]:
            tick_r = _tick_fn[0]()
            if inspect.isawaitable(tick_r):
                _run_coro(tick_r)
        return r

    mock_app.call_from_thread.side_effect = _call_from_thread_side_effect


def _make_cli_instance(cli_module, mock_app):
    cli = MagicMock()
    cli._play_tte_in_output_panel = cli_module.HermesCLI._play_tte_in_output_panel.__get__(cli)
    cli._ensure_startup_banner_artefacts = (
        cli_module.HermesCLI._ensure_startup_banner_artefacts.__get__(cli)
    )
    cli._render_startup_banner_text = MagicMock(return_value=MagicMock())
    cli._startup_banner_template = None
    cli._startup_banner_static = None
    cli._build_startup_banner_template = MagicMock(return_value={
        "lines": [], "hero_row": 0, "hero_col": 0, "hero_width": 10, "hero_height": 5
    })
    cli._splice_startup_banner_frame = MagicMock(return_value=MagicMock())
    mock_app.call_later = MagicMock(side_effect=_sync_call_from_thread)
    _install_draining_set_interval(mock_app)
    return cli


class TestSettleDirectionWiring:
    """TTE-SETTLE-H2: _play_tte_in_output_panel passes direction to settle frame."""

    @pytest.fixture(autouse=True)
    def _ready(self):
        from hermes_cli.tui.widgets import OUTPUT_PANEL_WIDTH_READY, STARTUP_BANNER_READY
        STARTUP_BANNER_READY.set()
        OUTPUT_PANEL_WIDTH_READY.set()
        yield
        STARTUP_BANNER_READY.clear()
        OUTPUT_PANEL_WIDTH_READY.clear()

    def test_settle_direction_extracted_for_vhstape(self, monkeypatch):
        """Cache-miss path passes direction='VERTICAL' to _hero_ansi_with_stops."""
        import cli as cli_module

        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, effect_name="vhstape")
        cli = _make_cli_instance(cli_module, mock_app)

        calls: list = []

        def _mock_ansi_with_stops(plain_hero, stops, direction="DIAGONAL"):
            calls.append(direction)
            return "\033[0mhero\033[0m"

        cli._hero_ansi_with_stops = _mock_ansi_with_stops
        cli._hero_ansi_colored = MagicMock(return_value="\033[0mhero\033[0m")

        iter_frames_mock = MagicMock(return_value=iter(["\033[0mfr\033[0m"]))

        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None))
            stack.enter_context(patch(
                "hermes_cli.skin_engine.get_active_skin", side_effect=ImportError("no skin")
            ))
            cli._play_tte_in_output_panel(cfg, "hero text")

        assert calls, "settle frame never generated"
        assert calls[-1] == "VERTICAL", f"expected VERTICAL, got {calls[-1]}"

    def test_settle_direction_extracted_cache_hit_path(self, monkeypatch):
        """Cache-hit path passes direction='VERTICAL' to _hero_ansi_with_stops."""
        import cli as cli_module

        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, effect_name="vhstape")
        cli = _make_cli_instance(cli_module, mock_app)

        calls: list = []

        def _mock_ansi_with_stops(plain_hero, stops, direction="DIAGONAL"):
            calls.append(direction)
            return "\033[0mhero\033[0m"

        cli._hero_ansi_with_stops = _mock_ansi_with_stops
        cli._hero_ansi_colored = MagicMock(return_value="\033[0mhero\033[0m")

        cached = ["\033[0mfr1\033[0m", "\033[0mfr2\033[0m"]
        load_mock = MagicMock(return_value=cached)

        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", MagicMock(return_value=iter([]))))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", load_mock))
            stack.enter_context(patch(
                "hermes_cli.skin_engine.get_active_skin", side_effect=ImportError("no skin")
            ))
            cli._play_tte_in_output_panel(cfg, "hero text")

        assert calls, "settle frame never generated on cache-hit path"
        assert calls[-1] == "VERTICAL", f"expected VERTICAL, got {calls[-1]}"

    def test_settle_direction_falls_back_on_exception(self, monkeypatch):
        """If get_effect_gradient_direction raises, settle frame uses DIAGONAL (no crash)."""
        import cli as cli_module

        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, effect_name="vhstape")
        cli = _make_cli_instance(cli_module, mock_app)

        calls: list = []

        def _mock_ansi_with_stops(plain_hero, stops, direction="DIAGONAL"):
            calls.append(direction)
            return "\033[0mhero\033[0m"

        cli._hero_ansi_with_stops = _mock_ansi_with_stops
        cli._hero_ansi_colored = MagicMock(return_value="\033[0mhero\033[0m")

        iter_frames_mock = MagicMock(return_value=iter(["\033[0mfr\033[0m"]))

        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None))
            stack.enter_context(patch(
                "hermes_cli.skin_engine.get_active_skin", side_effect=ImportError("no skin")
            ))
            stack.enter_context(patch(
                "hermes_cli.tui.tte_runner.get_effect_gradient_direction",
                side_effect=RuntimeError("boom"),
            ))
            cli._play_tte_in_output_panel(cfg, "hero text")

        assert calls, "settle frame never generated"
        assert calls[-1] == "DIAGONAL", f"expected DIAGONAL fallback, got {calls[-1]}"
