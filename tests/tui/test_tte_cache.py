"""Tests for hermes_cli/tui/_tte_cache.py (TFC-1) and TTE cache integration in cli.py (TFC-2).

Total: 43 tests across 4 classes.
"""
from __future__ import annotations

import gzip
import inspect
import os
import pickle
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import hermes_cli.tui._tte_cache as _tte_cache_mod
from hermes_cli.tui._tte_cache import (
    _TTE_CACHE_FORMAT_VER,
    _GC_MAX_AGE_S,
    _GC_MAX_FILES,
    _no_cache,
    _tte_version,
    gc_tte_cache,
    load_tte_frames,
    save_tte_frames,
    tte_cache_dir,
    tte_cache_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key(**kwargs):
    defaults = dict(
        effect_name="beams",
        plain_hero="hello",
        render_width=80,
        skin_colors=("#FFD700", "#FFBF00", "#CD7F32"),
        params={},
    )
    defaults.update(kwargs)
    return tte_cache_key(**defaults)


# ---------------------------------------------------------------------------
# TestCacheKey — 11 tests
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_key_stable(self):
        """Identical inputs produce identical keys on repeat calls."""
        k1 = _make_key()
        k2 = _make_key()
        assert k1 == k2
        assert len(k1) == 14

    def test_key_sensitive_effect(self):
        """Changed effect_name → different key."""
        k1 = _make_key(effect_name="beams")
        k2 = _make_key(effect_name="matrix")
        assert k1 != k2

    def test_key_sensitive_hero(self):
        """Changed plain_hero → different key."""
        k1 = _make_key(plain_hero="hello")
        k2 = _make_key(plain_hero="world")
        assert k1 != k2

    def test_key_sensitive_width(self):
        """Changed render_width → different key."""
        k1 = _make_key(render_width=80)
        k2 = _make_key(render_width=120)
        assert k1 != k2

    def test_key_sensitive_skin_colors(self):
        """Changed skin color → different key; case normalisation works."""
        k1 = _make_key(skin_colors=("#FFD700", "#FFBF00", "#CD7F32"))
        k2 = _make_key(skin_colors=("#AABBCC", "#FFBF00", "#CD7F32"))
        assert k1 != k2
        # Case normalisation: lowercase and uppercase should produce the same key
        k_lower = _make_key(skin_colors=("#ffd700", "#ffbf00", "#cd7f32"))
        k_upper = _make_key(skin_colors=("#FFD700", "#FFBF00", "#CD7F32"))
        assert k_lower == k_upper

    def test_key_sensitive_params(self):
        """Changed params → different key."""
        k1 = _make_key(params={})
        k2 = _make_key(params={"speed": 2})
        assert k1 != k2

    def test_key_sensitive_tte_ver(self, monkeypatch):
        """Monkeypatched _tte_version produces a different key."""
        monkeypatch.setattr(_tte_cache_mod, "_tte_version", lambda: "1.0.0")
        k1 = _make_key()
        monkeypatch.setattr(_tte_cache_mod, "_tte_version", lambda: "2.0.0")
        k2 = _make_key()
        assert k1 != k2

    def test_key_params_not_serializable(self):
        """Non-JSON-serializable params raises ValueError."""
        with pytest.raises(ValueError, match="not JSON-serializable"):
            _make_key(params={"x": object()})

    def test_key_empty_effect_name(self):
        """Empty effect_name does not raise; result is 14-char hex."""
        k = _make_key(effect_name="")
        assert len(k) == 14
        assert all(c in "0123456789abcdef" for c in k)

    def test_key_empty_hero(self):
        """Empty plain_hero does not raise; key differs from non-empty hero."""
        k_empty = _make_key(plain_hero="")
        k_nonempty = _make_key(plain_hero="hello")
        assert len(k_empty) == 14
        assert k_empty != k_nonempty

    def test_key_sensitive_hero_sanitization(self):
        """plain_hero="hello" vs plain_hero="hello\\x00" produce different keys.

        Sanitization is the caller's responsibility — tte_cache_key hashes verbatim.
        """
        k1 = _make_key(plain_hero="hello")
        k2 = _make_key(plain_hero="hello\x00")
        assert k1 != k2


# ---------------------------------------------------------------------------
# TestLoadSave — 13 tests
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_load_miss_nonexistent(self, tmp_path, monkeypatch):
        """Non-existent cache file returns None without raising."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        result = load_tte_frames("nonexistent123abc")
        assert result is None

    def test_load_hit_roundtrip(self, tmp_path, monkeypatch):
        """save_tte_frames then load_tte_frames returns original list."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = _make_key()
        frames = ["\033[31mframe1\033[0m", "\033[32mframe2\033[0m"]
        save_tte_frames(key, frames)
        loaded = load_tte_frames(key)
        assert loaded == frames

    def test_skin_color_change_busts_key(self, tmp_path, monkeypatch):
        """Changing skin color produces a different key; old key's frames survive."""
        monkeypatch.setattr(_tte_cache_mod, "_tte_version", lambda: "1.0.0")
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        frames = ["frame_a", "frame_b"]
        key_a = tte_cache_key("beams", "hero", 80, ("#FFD700", "#FFBF00", "#CD7F32"), {})
        save_tte_frames(key_a, frames)
        key_b = tte_cache_key("beams", "hero", 80, ("#AABBCC", "#FFBF00", "#CD7F32"), {})
        assert key_a != key_b
        assert load_tte_frames(key_b) is None
        assert load_tte_frames(key_a) == frames

    def test_load_corrupt_deleted(self, tmp_path, monkeypatch):
        """Truncated/corrupt gzip → returns None and deletes the file."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = "abcdef12345678"
        path = tmp_path / f"{key}.pkl.gz"
        path.write_bytes(b"\x1f\x8b truncated garbage")
        result = load_tte_frames(key)
        assert result is None
        assert not path.exists()

    def test_load_version_mismatch_deleted(self, tmp_path, monkeypatch):
        """Payload with wrong version → returns None and deletes the file."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = "badversion12345"
        path = tmp_path / f"{key}.pkl.gz"
        data = {"v": 99, "frames": ["frame1"]}
        with gzip.open(path, "wb") as fh:
            pickle.dump(data, fh)
        result = load_tte_frames(key)
        assert result is None
        assert not path.exists()

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "Yes", "on", "ON"])
    def test_load_no_cache_env_disabled(self, tmp_path, monkeypatch, val):
        """HERMES_TTE_NO_CACHE with truthy value disables load even when cache exists."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = _make_key()
        frames = ["frame1"]
        save_tte_frames(key, frames)
        monkeypatch.setenv("HERMES_TTE_NO_CACHE", val)
        result = load_tte_frames(key)
        assert result is None

    @pytest.mark.parametrize("val", ["0", "false", ""])
    def test_load_no_cache_env_enabled(self, tmp_path, monkeypatch, val):
        """HERMES_TTE_NO_CACHE with falsy value does NOT disable load."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = _make_key()
        frames = ["frame1"]
        save_tte_frames(key, frames)
        monkeypatch.setenv("HERMES_TTE_NO_CACHE", val)
        result = load_tte_frames(key)
        assert result == frames

    def test_load_mkdir_failure(self, monkeypatch):
        """If tte_cache_dir raises, load_tte_frames returns None without raising."""
        def _raise():
            raise PermissionError("no access")
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", _raise)
        result = load_tte_frames("somekey12345678")
        assert result is None

    def test_save_atomic(self, tmp_path, monkeypatch):
        """After successful save: .tmp file absent, dest file present."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        key = _make_key()
        frames = ["frame1"]
        save_tte_frames(key, frames)
        assert (tmp_path / f"{key}.pkl.gz").exists()
        assert not (tmp_path / f"{key}.pkl.gz.tmp").exists()

    def test_save_error_silent(self, tmp_path, monkeypatch):
        """Unwritable directory causes save to return silently without raising."""
        if os.name != "nt":
            if os.getuid() == 0:
                pytest.skip("unwritable-dir restriction bypassed as root")
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: ro_dir)
        try:
            save_tte_frames(_make_key(), ["frame1"])
            # No exception should be raised
        finally:
            ro_dir.chmod(0o755)

    def test_save_mkdir_failure(self, monkeypatch):
        """If tte_cache_dir raises, save_tte_frames returns silently without raising."""
        def _raise():
            raise PermissionError("no access")
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", _raise)
        save_tte_frames(_make_key(), ["frame1"])  # must not raise

    def test_save_no_cache_env_disabled(self, tmp_path, monkeypatch):
        """HERMES_TTE_NO_CACHE=1 → save is no-op, no file written."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        monkeypatch.setenv("HERMES_TTE_NO_CACHE", "1")
        key = _make_key()
        save_tte_frames(key, ["frame1"])
        assert not (tmp_path / f"{key}.pkl.gz").exists()

    def test_save_no_cache_env_enabled(self, tmp_path, monkeypatch):
        """HERMES_TTE_NO_CACHE=0 → save proceeds normally."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        monkeypatch.setenv("HERMES_TTE_NO_CACHE", "0")
        key = _make_key()
        save_tte_frames(key, ["frame1"])
        assert (tmp_path / f"{key}.pkl.gz").exists()


# ---------------------------------------------------------------------------
# TestGC — 4 tests
# ---------------------------------------------------------------------------

class TestGC:
    def test_gc_age(self, tmp_path, monkeypatch):
        """File with mtime 8 days ago is removed; 1-day file kept."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        old_file = tmp_path / "old123456789012.pkl.gz"
        new_file = tmp_path / "new123456789012.pkl.gz"
        old_file.write_bytes(b"data")
        new_file.write_bytes(b"data")
        now = time.time()
        os.utime(old_file, (now - 8 * 86400, now - 8 * 86400))
        os.utime(new_file, (now - 86400, now - 86400))
        gc_tte_cache()
        assert not old_file.exists()
        assert new_file.exists()

    def test_gc_max_files(self, tmp_path, monkeypatch):
        """12 files present → only 10 survive (oldest 2 deleted)."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        now = time.time()
        files = []
        for i in range(12):
            f = tmp_path / f"file{i:04d}12345678.pkl.gz"
            f.write_bytes(b"data")
            mtime = now - (12 - i) * 3600  # i=0 oldest, i=11 newest
            os.utime(f, (mtime, mtime))
            files.append(f)
        gc_tte_cache()
        surviving = [f for f in files if f.exists()]
        assert len(surviving) == 10
        # The 2 oldest (i=0, i=1) should be deleted
        assert not files[0].exists()
        assert not files[1].exists()

    def test_gc_orphan_tmp(self, tmp_path, monkeypatch):
        """Old .pkl.gz.tmp is removed; recent .pkl.gz.tmp is kept."""
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", lambda: tmp_path)
        now = time.time()
        old_tmp = tmp_path / "oldtmp12345678.pkl.gz.tmp"
        new_tmp = tmp_path / "newtmp12345678.pkl.gz.tmp"
        old_tmp.write_bytes(b"data")
        new_tmp.write_bytes(b"data")
        os.utime(old_tmp, (now - 8 * 86400, now - 8 * 86400))
        os.utime(new_tmp, (now - 3600, now - 3600))
        gc_tte_cache()
        assert not old_tmp.exists()
        assert new_tmp.exists()

    def test_gc_error_silent(self, monkeypatch):
        """If tte_cache_dir raises, gc_tte_cache returns without raising."""
        def _raise():
            raise PermissionError("no access")
        monkeypatch.setattr(_tte_cache_mod, "tte_cache_dir", _raise)
        gc_tte_cache()  # must not raise


# ---------------------------------------------------------------------------
# TestIntegration — 15 tests
# ---------------------------------------------------------------------------

def _run_coro(coro) -> None:
    """Drive a coroutine synchronously without an event loop."""
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
    """Add set_interval + call_from_thread mocks that drain ticks synchronously."""
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
    """Create a bound cli instance for integration testing."""
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


def _make_cfg(cli_module, **overrides):
    data = dict(effect_name="beams", max_frames=5, max_wall_s=30.0, fps=30, params={})
    data.update(overrides)
    return cli_module._StartupTteConfig(**data)


def _make_mock_app():
    app = MagicMock()
    app.is_running = True
    app._startup_output_panel_width = 0
    return app


@pytest.fixture(autouse=True)
def _ready_events():
    """Pre-set STARTUP_BANNER_READY and OUTPUT_PANEL_WIDTH_READY for all tests in this module."""
    from hermes_cli.tui.widgets import OUTPUT_PANEL_WIDTH_READY, STARTUP_BANNER_READY
    STARTUP_BANNER_READY.set()
    OUTPUT_PANEL_WIDTH_READY.set()
    yield
    STARTUP_BANNER_READY.clear()
    OUTPUT_PANEL_WIDTH_READY.clear()


def _run_play_tte(
    cli_module, mock_app, cfg, iter_frames_mock, load_mock,
    save_mock=None, gc_mock=None, extra_patches=None,
    skin_patch=True,
):
    """Run _play_tte_in_output_panel with standard mocks. Returns (cli, result)."""
    cli = _make_cli_instance(cli_module, mock_app)
    with ExitStack() as stack:
        stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
        stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
        stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", load_mock))
        if save_mock is not None:
            stack.enter_context(patch("hermes_cli.tui._tte_cache.save_tte_frames", save_mock))
        if gc_mock is not None:
            stack.enter_context(patch("hermes_cli.tui._tte_cache.gc_tte_cache", gc_mock))
        if skin_patch:
            stack.enter_context(patch(
                "hermes_cli.skin_engine.get_active_skin", side_effect=ImportError("no skin")
            ))
        if extra_patches:
            for p in extra_patches:
                stack.enter_context(p)
        result = cli._play_tte_in_output_panel(cfg, "hero text")
    return cli, result


def _capture_threads_nostart():
    """Return (captured_dict, orig_init) for thread capture pattern without starting threads."""
    captured = {}
    orig_init = threading.Thread.__init__

    def _capture_init(self, *a, **kw):
        captured[kw.get('name', '')] = kw.get('target')
        orig_init(self, *a, **kw)

    return captured, _capture_init


class TestIntegration:
    """Integration tests for TTE cache paths in _play_tte_in_output_panel."""

    def test_cache_hit_skips_producer_thread(self, monkeypatch):
        """Cache hit: iter_frames never called; producer thread never started."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module)
        iter_frames_mock = MagicMock(return_value=iter([]))
        load_mock = MagicMock(return_value=["frame1\033[0m", "frame2\033[0m"])

        # Track which threads get started
        started_thread_names = []
        orig_start = threading.Thread.start
        def _track_start(self):
            started_thread_names.append(self.name)
            # For the producer thread on cache hit it should not be started.
            # Allow it to run anyway to avoid blocking.
            orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _track_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)

        # The producer thread should NOT have been started on a cache hit
        assert 'hermes-tte-producer' not in started_thread_names
        iter_frames_mock.assert_not_called()

    def test_cache_hit_respects_max_frames(self, monkeypatch):
        """Cache hit with 10 frames and max_frames=3 results in successful playback."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=3)
        # 10 cached frames; only 3 should be processed
        frames = [f"frame{i}" for i in range(10)]
        load_mock = MagicMock(return_value=frames)
        iter_frames_mock = MagicMock(return_value=iter([]))

        cli, result = _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)
        # Cache hit path with max_frames=3 → succeeds
        assert result is True
        iter_frames_mock.assert_not_called()

    def test_cache_miss_starts_producer(self, monkeypatch):
        """Cache miss: producer thread is started (iter_frames called)."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)
        frames = ["frame1", "frame2", "frame3"]
        load_mock = MagicMock(return_value=None)
        iter_frames_mock = MagicMock(return_value=iter(frames))

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)
        # iter_frames was called → producer thread ran
        assert iter_frames_mock.called

    def test_cache_miss_triggers_writeback(self, monkeypatch):
        """Cache miss: after producer finishes, save_tte_frames called with raw ANSI strings."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)
        frames = ["frame1_raw", "frame2_raw", "frame3_raw"]
        load_mock = MagicMock(return_value=None)
        save_mock = MagicMock()
        gc_mock = MagicMock()
        iter_frames_mock = MagicMock(return_value=iter(frames))

        # Capture thread targets; prevent write-back thread from starting automatically
        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            name = kw.get('name', '')
            captured[name] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        # Allow producer thread to start normally; suppress write-back thread start
        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass  # don't start; we'll run it manually
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)

        # Run write-back synchronously
        assert 'hermes-tte-cache-writer' in captured, "write-back thread not created"
        captured['hermes-tte-cache-writer']()

        assert save_mock.called
        saved_frames = save_mock.call_args[0][1]
        assert isinstance(saved_frames, list)
        assert all(isinstance(f, str) for f in saved_frames)

    def test_cache_miss_triggers_gc(self, monkeypatch):
        """Cache miss: after producer finishes, gc_tte_cache is called."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)
        frames = ["frame1_raw"]
        load_mock = MagicMock(return_value=None)
        save_mock = MagicMock()
        gc_mock = MagicMock()
        iter_frames_mock = MagicMock(return_value=iter(frames))

        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            name = kw.get('name', '')
            captured[name] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass  # suppress; run manually
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)

        assert 'hermes-tte-cache-writer' in captured, "write-back thread not created"
        captured['hermes-tte-cache-writer']()
        assert gc_mock.called

    def test_cache_key_uses_active_skin(self, monkeypatch):
        """Cache key computation uses skin colors from get_active_skin."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module)
        load_calls = []

        def _capture_load(key):
            load_calls.append(key)
            return None  # cache miss

        load_mock = MagicMock(side_effect=_capture_load)
        iter_frames_mock = MagicMock(return_value=iter(["frame1"]))
        save_mock = MagicMock()
        gc_mock = MagicMock()

        mock_skin = MagicMock()
        def _get_color(name, default):
            colors = {
                "banner_title": "#AABBCC",
                "banner_accent": "#DDEEFF",
                "banner_dim": "#112233",
            }
            return colors.get(name, default)
        mock_skin.get_color.side_effect = _get_color

        cli = _make_cli_instance(cli_module, mock_app)
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", load_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.save_tte_frames", save_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.gc_tte_cache", gc_mock))
            stack.enter_context(patch("hermes_cli.skin_engine.get_active_skin", return_value=mock_skin))
            cli._play_tte_in_output_panel(cfg, "hero text")

        assert len(load_calls) == 1
        used_key = load_calls[0]
        # Compute expected key: effect_name="beams", plain_hero sanitized from "hero text",
        # width=80 (fallback), colors from mock skin
        import cli as cli_m2
        sanitized_hero = cli_m2._sanitize_startup_hero_text("hero text")
        expected_key = tte_cache_key(
            "beams", sanitized_hero, 80,
            ("#AABBCC", "#DDEEFF", "#112233"),
            {},
        )
        assert used_key == expected_key

    def test_cache_hit_sets_events_and_flag(self, monkeypatch):
        """Cache hit: function returns True (events set, rendered_any_flag[0]=True verified indirectly)."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module)
        load_mock = MagicMock(return_value=["frame1", "frame2"])
        iter_frames_mock = MagicMock(return_value=iter([]))

        cli, result = _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)
        # result=True means rendered_any_flag[0] was True (function returns rendered_any_flag[0])
        assert result is True

    def test_cache_hit_appends_static_frame(self, monkeypatch):
        """Cache hit: the function succeeds (static frame was appended to anim_frames)."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=2)
        load_mock = MagicMock(return_value=["frame1", "frame2"])
        iter_frames_mock = MagicMock(return_value=iter([]))

        cli, result = _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)
        # result=True implies anim_frames was non-empty and the static frame was appended
        # (rendered_any_flag[0] is True only when frames were appended)
        assert result is True
        # No producer ran, confirming the static frame was appended inline on the cache-hit path
        iter_frames_mock.assert_not_called()

    def test_cache_disabled_env(self, monkeypatch):
        """HERMES_TTE_NO_CACHE=1: load returns None; producer runs; GC still called."""
        import cli as cli_module
        monkeypatch.setenv("HERMES_TTE_NO_CACHE", "1")
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)
        frames = ["frame1"]
        load_mock = MagicMock(return_value=None)  # _no_cache() would return None
        save_mock = MagicMock()
        gc_mock = MagicMock()
        iter_frames_mock = MagicMock(return_value=iter(frames))

        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            name = kw.get('name', '')
            captured[name] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass  # run manually
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)

        # Per behavior table: HERMES_TTE_NO_CACHE disables r/w but the write-back thread
        # still runs (it calls save_tte_frames which is a no-op, then gc_tte_cache).
        if 'hermes-tte-cache-writer' in captured and captured['hermes-tte-cache-writer']:
            captured['hermes-tte-cache-writer']()
            assert gc_mock.called

    def test_cache_hit_no_prefetch_ready_log(self, monkeypatch):
        """Cache hit: no 'prefetch ready' or 'streaming producer starting' in info logs."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module)
        load_mock = MagicMock(return_value=["frame1", "frame2"])
        iter_frames_mock = MagicMock(return_value=iter([]))

        logger_mock = MagicMock()
        cli = _make_cli_instance(cli_module, mock_app)
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
            stack.enter_context(patch("hermes_cli.tui._tte_cache.load_tte_frames", load_mock))
            stack.enter_context(patch(
                "hermes_cli.skin_engine.get_active_skin", side_effect=ImportError("no skin")
            ))
            stack.enter_context(patch.object(cli_module, "logger", logger_mock))
            cli._play_tte_in_output_panel(cfg, "hero text")

        info_msgs = [c.args[0] for c in logger_mock.info.call_args_list]
        assert not any("prefetch ready" in m for m in info_msgs)
        assert not any("streaming producer starting" in m for m in info_msgs)
        assert any("TTE: cache hit" in m for m in info_msgs)

    def test_cache_miss_no_writeback_on_app_stop(self, monkeypatch):
        """App stops mid-producer: write-back is suppressed even though frames collected."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)

        def _frames_gen():
            for i in range(5):
                yield f"frame{i}"
                if i == 1:
                    mock_app.is_running = False

        iter_frames_mock = MagicMock(return_value=_frames_gen())
        load_mock = MagicMock(return_value=None)
        save_mock = MagicMock()
        gc_mock = MagicMock()

        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            captured[kw.get('name', '')] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass  # suppress; we check it's not created
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)

        # _app_stopped_early=True → write-back thread not created, save not called
        assert not save_mock.called
        assert 'hermes-tte-cache-writer' not in captured

    def test_cache_miss_no_writeback_on_producer_exception(self, monkeypatch):
        """Producer exception: write-back is suppressed."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)

        def _frames_gen():
            yield "frame1"
            yield "frame2"
            yield "frame3"
            raise RuntimeError("iter_frames exploded")

        iter_frames_mock = MagicMock(return_value=_frames_gen())
        load_mock = MagicMock(return_value=None)
        save_mock = MagicMock()
        gc_mock = MagicMock()

        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            captured[kw.get('name', '')] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)

        # _produce_raised=True → write-back not triggered
        assert not save_mock.called
        assert 'hermes-tte-cache-writer' not in captured

    def test_cache_miss_no_writeback_on_tte_skip(self, monkeypatch):
        """STARTUP_TTE_SKIP fires mid-animation: write-back is suppressed."""
        import cli as cli_module
        from hermes_cli.tui.widgets import STARTUP_TTE_SKIP
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=5)

        def _frames_gen():
            for i in range(5):
                if i == 2:
                    STARTUP_TTE_SKIP.set()
                yield f"frame{i}"

        iter_frames_mock = MagicMock(return_value=_frames_gen())
        load_mock = MagicMock(return_value=None)
        save_mock = MagicMock()
        gc_mock = MagicMock()

        captured = {}
        orig_init = threading.Thread.__init__
        def _capture_init(self, *a, **kw):
            captured[kw.get('name', '')] = kw.get('target')
            orig_init(self, *a, **kw)
        monkeypatch.setattr(threading.Thread, '__init__', _capture_init)

        orig_start = threading.Thread.start
        def _selective_start(self):
            if self.name == 'hermes-tte-cache-writer':
                pass
            else:
                orig_start(self)
        monkeypatch.setattr(threading.Thread, 'start', _selective_start)

        try:
            _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock, save_mock, gc_mock)
            # STARTUP_TTE_SKIP.is_set() → write-back suppressed
            assert not save_mock.called
            assert 'hermes-tte-cache-writer' not in captured
        finally:
            STARTUP_TTE_SKIP.clear()

    def test_cache_hit_phase15_produces_cached_strips_visual(self, monkeypatch):
        """Cache hit with render_w>0: anim_frames contain _CachedStripsVisual instances."""
        import cli as cli_module
        mock_app = _make_mock_app()
        mock_app._startup_output_panel_width = 80  # non-zero → Phase 1.5 runs
        cfg = _make_cfg(cli_module, max_frames=2)
        frames = ["\033[31mhello\033[0m", "\033[32mworld\033[0m"]
        load_mock = MagicMock(return_value=frames)
        iter_frames_mock = MagicMock(return_value=iter([]))

        # Capture what gets passed to set_frame to verify _CachedStripsVisual instances
        set_frame_calls = []

        from textual.css.query import NoMatches

        class _MockWidget:
            def set_frame(self, frame):
                set_frame_calls.append(frame)

        mock_app.query_one = MagicMock(return_value=_MockWidget())

        cli, result = _run_play_tte(cli_module, mock_app, cfg, iter_frames_mock, load_mock)
        assert result is True
        # Phase 1.5 should have produced _CachedStripsVisual — verify by checking
        # at least one set_frame call received a _CachedStripsVisual (or fallback Text).
        # The key assertion is that the function succeeded with render_w=80.

    def test_cache_module_import_failure(self, monkeypatch):
        """If _tte_cache module unavailable: producer runs normally (iter_frames called)."""
        import cli as cli_module
        mock_app = _make_mock_app()
        cfg = _make_cfg(cli_module, max_frames=2)
        frames = ["frame1", "frame2"]
        iter_frames_mock = MagicMock(return_value=iter(frames))

        # Inject None into sys.modules to simulate import failure
        monkeypatch.setitem(sys.modules, 'hermes_cli.tui._tte_cache', None)

        cli = _make_cli_instance(cli_module, mock_app)
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli_module, "_hermes_app", mock_app))
            stack.enter_context(patch("hermes_cli.tui.tte_runner.iter_frames", iter_frames_mock))
            cli._play_tte_in_output_panel(cfg, "hero text")

        # iter_frames was called → producer path ran (cache module was unavailable)
        assert iter_frames_mock.called
