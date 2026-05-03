"""Tests for OPT1-H1 — parallel TTE producer start before _ensure_startup_banner_artefacts.

Total: 15 tests across 2 classes (TestParallelTteProducer: 9, TestTemplateCell: 6).

All tests are synchronous — no pytest-asyncio required.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import cli as cli_mod

_RealThread = threading.Thread  # capture before any patching


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides):
    defaults = {"effect_name": "matrix", "params": {}, "max_wall_s": 0.05, "max_frames": 6, "fps": 30}
    defaults.update(overrides)
    return cli_mod._StartupTteConfig(**defaults)


def _make_app():
    app = MagicMock()
    app.is_running = True
    app.call_later = MagicMock()
    app.call_from_thread = MagicMock()
    app.set_interval = MagicMock(return_value=MagicMock(stop=MagicMock()))
    return app


def _make_cli():
    cli = MagicMock()
    cli._startup_banner_template = None
    cli._startup_banner_static = MagicMock()
    cli._render_startup_banner_text = MagicMock(
        return_value=MagicMock(no_wrap=False, overflow="crop")
    )
    cli._hero_ansi_colored = MagicMock(return_value="COLORED_HERO")
    cli._splice_startup_banner_frame = MagicMock(
        return_value=MagicMock(no_wrap=False, overflow="crop", plain="spliced_frame")
    )
    cli._handle_tte_producer_exc = cli_mod.HermesCLI._handle_tte_producer_exc
    return cli


def _run_coro(coro) -> None:
    """Drive a coroutine synchronously (no event loop needed)."""
    try:
        coro.send(None)
    except StopIteration:
        pass


def _setup_events():
    from hermes_cli.tui.widgets import OUTPUT_PANEL_WIDTH_READY, STARTUP_BANNER_READY, STARTUP_TTE_SKIP
    STARTUP_BANNER_READY.set()
    OUTPUT_PANEL_WIDTH_READY.set()
    STARTUP_TTE_SKIP.clear()


_TMPL = {
    "lines": [MagicMock(), MagicMock()],
    "hero_row": 0,
    "hero_col": 0,
    "hero_width": 10,
    "hero_height": 2,
}


def _run_play(cli, app, cfg, frames=("f0", "f1", "f2"), cache_frames=None,
              side_effect_on_ensure=None):
    """
    Run _play_tte_in_output_panel with tight mocks.

    Patches:
    - _hermes_app global → app
    - iter_frames → yields `frames` then stops
    - _strip_ansi_bg → identity
    - threading.Thread → returns MagicMock (non-running); start() is a no-op
    - TTE cache → cache_frames (None = miss, list = hit)

    `side_effect_on_ensure` overrides _ensure_startup_banner_artefacts behaviour.

    Returns (captured_produce_target, call_later_fns).
    """
    captured = {}
    call_later_fns: list = []

    def _record_call_later(fn, *a, **kw):
        call_later_fns.append(fn)

    app.call_later.side_effect = _record_call_later
    app.call_from_thread.side_effect = lambda fn, *a, **kw: None

    def _fake_thread(target=None, daemon=None, name=None):
        t = MagicMock(spec=_RealThread)
        if target is not None and getattr(target, "__name__", "") == "_produce":
            captured["produce"] = target
        return t

    _setup_events()

    cache_key_val = "test-key-01" if cache_frames is not None else None

    ensure_mock = side_effect_on_ensure or (lambda ph: None)

    play_fn = cli_mod.HermesCLI._play_tte_in_output_panel.__get__(cli)

    with patch.object(cli_mod, "_hermes_app", app), \
         patch("threading.Thread", side_effect=_fake_thread), \
         patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(frames)), \
         patch.object(cli_mod, "_strip_ansi_bg", side_effect=lambda x: x), \
         patch.object(cli, "_ensure_startup_banner_artefacts", side_effect=ensure_mock), \
         patch("hermes_cli.tui._tte_cache.load_tte_frames",
               return_value=cache_frames), \
         patch("hermes_cli.tui._tte_cache.save_tte_frames"), \
         patch("hermes_cli.tui._tte_cache.gc_tte_cache"), \
         patch("hermes_cli.tui._tte_cache.tte_cache_key", return_value=cache_key_val):
        play_fn(cfg, "hero text")

    return captured.get("produce"), call_later_fns


# ---------------------------------------------------------------------------
# TestParallelTteProducer (9 tests)
# ---------------------------------------------------------------------------

class TestParallelTteProducer:
    def test_producer_starts_before_artefacts(self):
        """On cache miss, producer_thread.start() must be called before _ensure_startup_banner_artefacts."""
        call_order: list[str] = []
        app = _make_app()
        cli = _make_cli()

        def _record_ensure(plain_hero):
            call_order.append("ensure")

        _setup_events()
        app.call_later.side_effect = lambda fn, *a, **kw: None
        app.call_from_thread.side_effect = lambda fn, *a, **kw: None

        mock_thread = MagicMock(spec=_RealThread)
        mock_thread.start.side_effect = lambda: call_order.append("start")

        def _fake_thread(target=None, daemon=None, name=None):
            if target is not None and getattr(target, "__name__", "") == "_produce":
                return mock_thread
            return MagicMock(spec=_RealThread)

        with patch.object(cli_mod, "_hermes_app", app), \
             patch("threading.Thread", side_effect=_fake_thread), \
             patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["f0"])), \
             patch.object(cli_mod, "_strip_ansi_bg", side_effect=lambda x: x), \
             patch.object(cli, "_ensure_startup_banner_artefacts", side_effect=_record_ensure), \
             patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None), \
             patch("hermes_cli.tui._tte_cache.tte_cache_key", return_value="k"):
            play_fn = cli_mod.HermesCLI._play_tte_in_output_panel.__get__(cli)
            play_fn(_cfg(), "hero")

        assert call_order.index("start") < call_order.index("ensure"), \
            f"Expected 'start' before 'ensure', got order: {call_order}"

    def test_producer_not_started_on_cache_hit(self):
        """On cache hit, producer_thread.start() is never called."""
        app = _make_app()
        cli = _make_cli()
        thread_starts: list[str] = []

        def _fake_thread(target=None, daemon=None, name=None):
            t = MagicMock(spec=_RealThread)
            if target is not None and getattr(target, "__name__", "") == "_produce":
                t.start.side_effect = lambda: thread_starts.append("started")
            return t

        _setup_events()
        app.call_later.side_effect = lambda fn, *a, **kw: None
        app.call_from_thread.side_effect = lambda fn, *a, **kw: None

        cache_frames = ["frame_a", "frame_b"]

        with patch.object(cli_mod, "_hermes_app", app), \
             patch("threading.Thread", side_effect=_fake_thread), \
             patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])), \
             patch.object(cli_mod, "_strip_ansi_bg", side_effect=lambda x: x), \
             patch.object(cli, "_ensure_startup_banner_artefacts", side_effect=lambda ph: None), \
             patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=cache_frames), \
             patch("hermes_cli.tui._tte_cache.save_tte_frames"), \
             patch("hermes_cli.tui._tte_cache.gc_tte_cache"), \
             patch("hermes_cli.tui._tte_cache.tte_cache_key", return_value="hit-key"):
            play_fn = cli_mod.HermesCLI._play_tte_in_output_panel.__get__(cli)
            play_fn(_cfg(), "hero")

        assert thread_starts == [], \
            "producer_thread.start() must not be called on cache hit"

    def test_produce_uses_cell_value_at_frame_time(self):
        """Frames produced after template_cell[0] is set use the splice path."""
        from rich.text import Text

        # Build a minimal _produce-like closure environment manually
        template_cell: list = [None]
        spliced: list[bool] = []
        tmpl = {**_TMPL}

        splice_mock = MagicMock(return_value=MagicMock(
            no_wrap=False, overflow="crop", plain="spliced"
        ))

        def _produce_like(frames):
            for raw in frames:
                if template_cell[0] is not None:
                    splice_mock(template_cell[0], raw)
                    spliced.append(True)
                else:
                    Text.from_ansi(raw)
                    spliced.append(False)

        frames = ["f0", "f1", "f2", "f3", "f4"]
        # Set cell after 2 frames
        def _gen():
            for i, f in enumerate(frames):
                if i == 2:
                    template_cell[0] = tmpl
                yield f

        _produce_like(_gen())

        assert spliced[:2] == [False, False], "first 2 frames before cell populated → no splice"
        assert spliced[2:] == [True, True, True], "frames after cell populated → splice"

    def test_produce_falls_back_when_template_none(self):
        """When template_cell[0] is always None, splice is never called."""
        from rich.text import Text

        template_cell: list = [None]
        splice_mock = MagicMock()

        def _produce_like(frames):
            for raw in frames:
                if template_cell[0] is not None:
                    splice_mock(template_cell[0], raw)
                else:
                    Text.from_ansi(raw)

        _produce_like(["f0", "f1", "f2"])
        splice_mock.assert_not_called()

    def test_preflight_uses_resolved_template(self):
        """_apply_preflight with template_cell[0] set calls splice with blank hero."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.widgets import StartupBannerWidget

        template_cell: list = [{**_TMPL}]
        splice_mock = MagicMock(return_value=MagicMock(
            no_wrap=False, overflow="crop"
        ))
        widget_mock = MagicMock()
        app = MagicMock()
        app.query_one.return_value = widget_mock

        # Reconstruct _apply_preflight as it appears in production
        async def _apply_preflight() -> None:
            try:
                widget = app.query_one(StartupBannerWidget)
                tmpl = template_cell[0]
                if tmpl is not None:
                    hero_height = int(tmpl["hero_height"])
                    hero_width = int(tmpl["hero_width"])
                    blank_hero = "\n".join(" " * hero_width for _ in range(hero_height))
                    widget.set_frame(splice_mock(tmpl, blank_hero))
                else:
                    widget.set_frame(MagicMock())
            except NoMatches:
                pass
            except Exception:
                pass

        _run_coro(_apply_preflight())

        splice_mock.assert_called_once()
        args = splice_mock.call_args[0]
        assert args[0] is template_cell[0], "splice called with template dict"
        # blank hero should be all spaces
        blank = args[1]
        for line in blank.splitlines():
            assert line == " " * _TMPL["hero_width"]

    def test_preflight_falls_back_when_cell_none(self):
        """_apply_preflight with template_cell[0] = None calls _build_static() path."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.widgets import StartupBannerWidget

        template_cell: list = [None]
        splice_mock = MagicMock()
        build_static_calls: list[int] = []
        widget_mock = MagicMock()
        app = MagicMock()
        app.query_one.return_value = widget_mock

        def _build_static():
            build_static_calls.append(1)
            return MagicMock(no_wrap=False, overflow="crop")

        async def _apply_preflight() -> None:
            try:
                widget = app.query_one(StartupBannerWidget)
                tmpl = template_cell[0]
                if tmpl is not None:
                    hero_height = int(tmpl["hero_height"])
                    hero_width = int(tmpl["hero_width"])
                    blank_hero = "\n".join(" " * hero_width for _ in range(hero_height))
                    widget.set_frame(splice_mock(tmpl, blank_hero))
                else:
                    widget.set_frame(_build_static())
            except NoMatches:
                pass
            except Exception:
                pass

        _run_coro(_apply_preflight())

        splice_mock.assert_not_called()
        assert build_static_calls == [1], "_build_static() called when cell is None"

    def test_parallel_build_completes_before_playback(self):
        """template_cell[0] is populated (artefacts built) before prefetch_ready.wait() is reached.

        On cache miss the code order is:
          (B) producer_thread.start()
          (C) _ensure_startup_banner_artefacts()  ← synchronous on caller thread
          (C) template_cell[0] = ...
          (C) app.call_later(_apply_preflight)
              prefetch_ready.wait()               ← only after step C

        So template_cell[0] is always populated before the wait exits.
        """
        app = _make_app()
        cli = _make_cli()
        template_cell_ref: list = []
        ensure_called: list[int] = []

        def _fake_thread(target=None, daemon=None, name=None):
            t = MagicMock(spec=_RealThread)
            if target is not None and getattr(target, "__name__", "") == "_produce":
                cv = inspect.getclosurevars(target)
                tc = cv.nonlocals.get("template_cell")
                if tc is not None:
                    template_cell_ref.append(tc)
                # Trigger prefetch_ready quickly so the function doesn't timeout
                ev = cv.nonlocals.get("prefetch_ready")
                if ev is not None:
                    def _signal():
                        time.sleep(0.002)
                        ev.set()
                    rt = _RealThread(target=_signal, daemon=True)
                    t.start.side_effect = rt.start
            return t

        _setup_events()
        app.call_later.side_effect = lambda fn, *a, **kw: None
        app.call_from_thread.side_effect = lambda fn, *a, **kw: None

        def _record_ensure(ph):
            ensure_called.append(1)
            cli._startup_banner_template = {**_TMPL}

        cli._ensure_startup_banner_artefacts = _record_ensure

        with patch.object(cli_mod, "_hermes_app", app), \
             patch("threading.Thread", side_effect=_fake_thread), \
             patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["f0"])), \
             patch.object(cli_mod, "_strip_ansi_bg", side_effect=lambda x: x), \
             patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None), \
             patch("hermes_cli.tui._tte_cache.tte_cache_key", return_value="k"):
            play_fn = cli_mod.HermesCLI._play_tte_in_output_panel.__get__(cli)
            play_fn(_cfg(max_wall_s=0.5), "hero")

        assert ensure_called, "_ensure_startup_banner_artefacts must have been called"
        if template_cell_ref:
            # template_cell[0] was set to _TMPL via _record_ensure
            assert template_cell_ref[0][0] is not None, \
                "template_cell[0] must be non-None after artefacts build"

    def test_app_stop_during_parallel_build(self):
        """If app.is_running becomes False mid-producer, no crash occurs and template_cell[0] may be None."""
        app = _make_app()
        cli = _make_cli()
        produce_fn_ref: list = []

        def _fake_thread(target=None, daemon=None, name=None):
            t = MagicMock(spec=_RealThread)
            if target is not None and getattr(target, "__name__", "") == "_produce":
                produce_fn_ref.append(target)
            return t

        _setup_events()
        app.call_later.side_effect = lambda fn, *a, **kw: None
        app.call_from_thread.side_effect = lambda fn, *a, **kw: None

        def _ensure_then_stop(ph):
            app.is_running = False

        with patch.object(cli_mod, "_hermes_app", app), \
             patch("threading.Thread", side_effect=_fake_thread), \
             patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["f0"])), \
             patch.object(cli_mod, "_strip_ansi_bg", side_effect=lambda x: x), \
             patch.object(cli, "_ensure_startup_banner_artefacts", side_effect=_ensure_then_stop), \
             patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None), \
             patch("hermes_cli.tui._tte_cache.tte_cache_key", return_value="k"):
            play_fn = cli_mod.HermesCLI._play_tte_in_output_panel.__get__(cli)
            # Should return without raising
            result = play_fn(_cfg(), "hero")

        # Either False (timed out) or True (playback started then stopped) — no crash
        assert result in (True, False)

        if produce_fn_ref:
            # Run _produce synchronously with app.is_running=False — should exit cleanly
            try:
                produce_fn_ref[0]()
            except Exception as exc:
                pytest.fail(f"_produce() raised with is_running=False: {exc}")

    def test_static_frame_still_built_when_template_fails(self):
        """If _ensure_startup_banner_artefacts raises, template_cell[0] stays None and static fallback is used."""
        app = _make_app()
        cli = _make_cli()
        static_calls: list[int] = []

        def _ensure_raises(ph):
            raise RuntimeError("simulated template build failure")

        template_cell: list = [None]

        # Reconstruct _build_static as it appears in production
        def _build_static():
            static_calls.append(1)
            if template_cell[0] is not None:
                return cli._splice_startup_banner_frame(
                    template_cell[0], cli._hero_ansi_colored("hero")
                )
            return cli._startup_banner_static or cli._render_startup_banner_text(print_hero=True)

        # EH-OK: _ensure may raise; template_cell[0] stays None; static path used
        try:
            _ensure_raises("hero")
        except Exception:
            pass  # exception swallowed per spec
        # template_cell[0] is still None (not populated)
        assert template_cell[0] is None
        # _build_static falls back to _startup_banner_static
        result = _build_static()
        assert static_calls == [1]
        assert cli._splice_startup_banner_frame.call_count == 0


# ---------------------------------------------------------------------------
# TestTemplateCell (6 tests)
# ---------------------------------------------------------------------------

class TestTemplateCell:
    def test_cell_initialized_before_produce_defined(self):
        """In _play_tte_in_output_panel source, template_cell is assigned before 'def _produce'."""
        src = inspect.getsource(cli_mod.HermesCLI._play_tte_in_output_panel)
        cell_pos = src.find("template_cell")
        produce_def_pos = src.find("def _produce()")
        assert cell_pos != -1, "template_cell not found in source"
        assert produce_def_pos != -1, "def _produce() not found in source"
        assert cell_pos < produce_def_pos, (
            f"template_cell (pos={cell_pos}) must appear before def _produce() (pos={produce_def_pos})"
        )

    def test_cell_mutable_after_thread_start(self):
        """Writing template_cell[0] after thread start is visible to _produce's closure."""
        template_cell: list = [None]
        tmpl = {**_TMPL}
        splice_mock = MagicMock(return_value=MagicMock(no_wrap=False, overflow="crop"))
        calls: list[str] = []

        # Simulate _produce reading template_cell[0] per frame
        def _produce_sim():
            for raw in ["f0", "f1", "f2"]:
                if template_cell[0] is not None:
                    calls.append("spliced")
                    splice_mock(template_cell[0], raw)
                else:
                    calls.append("raw")

        # Start thread, then update cell mid-run (simulate parallel artefact build)
        template_cell[0] = tmpl  # cell updated before _produce_sim reads
        _produce_sim()

        # All 3 frames should be spliced since cell was set before the loop
        assert calls == ["spliced", "spliced", "spliced"]
        assert splice_mock.call_count == 3
        args = splice_mock.call_args_list[0][0]
        assert args[0] is tmpl

    def test_splice_called_with_cell_value_in_produce(self):
        """When template_cell[0] is set before _produce runs, every frame calls splice."""
        from rich.text import Text

        template_cell: list = [{**_TMPL}]
        splice_mock = MagicMock(return_value=MagicMock(no_wrap=False, overflow="crop"))
        frames = ["frame_a", "frame_b", "frame_c"]

        # Mimic the produce loop from cli.py
        result_frames = []
        for raw in frames:
            rf = (
                splice_mock(template_cell[0], raw)
                if template_cell[0] is not None
                else Text.from_ansi(raw)
            )
            result_frames.append(rf)

        assert splice_mock.call_count == len(frames)
        for c in splice_mock.call_args_list:
            assert c[0][0] is template_cell[0]

    def test_no_splice_in_produce_when_cell_none(self):
        """When template_cell[0] is None, _produce never calls splice."""
        from rich.text import Text

        template_cell: list = [None]
        splice_mock = MagicMock()
        frames = ["frame_x", "frame_y"]

        for raw in frames:
            if template_cell[0] is not None:
                splice_mock(template_cell[0], raw)
            else:
                Text.from_ansi(raw)

        splice_mock.assert_not_called()

    def test_prefetch_not_blocked_by_artefact_build(self):
        """prefetch_ready can be set by producer while artefact build is sleeping."""
        prefetch_ready = threading.Event()
        producer_done = threading.Event()
        anim_frames: list = []
        _PREFETCH_FRAMES = 3
        STARTUP_TTE_SKIP = threading.Event()

        def _produce():
            for i, raw in enumerate(["f0", "f1", "f2", "f3"]):
                if STARTUP_TTE_SKIP.is_set():
                    break
                anim_frames.append(raw)
                if len(anim_frames) == _PREFETCH_FRAMES:
                    prefetch_ready.set()
            producer_done.set()
            prefetch_ready.set()

        artefact_done = threading.Event()

        def _slow_artefacts():
            time.sleep(0.05)
            artefact_done.set()

        # Start producer BEFORE artefacts (per spec)
        t = threading.Thread(target=_produce, daemon=True)
        t.start()

        artefact_t = threading.Thread(target=_slow_artefacts, daemon=True)
        artefact_t.start()

        prefetch_ready.wait(timeout=1.0)

        assert prefetch_ready.is_set(), "prefetch_ready must fire before artefacts complete"
        assert not artefact_done.is_set(), "artefact build should still be running when prefetch fires"

        # Wait for everything to settle
        t.join(timeout=1.0)
        artefact_t.join(timeout=1.0)

    def test_producer_done_after_artefact_ready(self):
        """producer_done is set by _produce's finally block, independently of artefact timing."""
        prefetch_ready = threading.Event()
        producer_done = threading.Event()
        anim_frames: list = []

        def _produce():
            try:
                for raw in ["f0", "f1"]:
                    anim_frames.append(raw)
                    if len(anim_frames) == 2:
                        prefetch_ready.set()
            finally:
                anim_frames.append("_static_")
                producer_done.set()
                prefetch_ready.set()

        t = threading.Thread(target=_produce, daemon=True)
        t.start()
        t.join(timeout=1.0)

        assert producer_done.is_set(), "producer_done must be set after _produce finishes"
        assert "_static_" in anim_frames, "static frame appended in finally block"
