"""Tests for hermes_cli/tui/_banner_geo_cache.py (TestGeoCacheModule) and
cli.py _build_startup_banner_template geo-cache integration (TestGeoCacheIntegration).

Total: 18 tests across 2 classes.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from hermes_cli.tui._banner_geo_cache import (
    _GEO_CACHE_FORMAT_VER,
    gc_geo_cache,
    geo_cache_dir,
    geo_cache_key,
    is_cache_disabled,
    load_geo,
    save_geo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key(**kwargs):
    defaults = dict(
        panel_width=100,
        skin_name="hermes",
        wide_layout=True,
        tall_layout=True,
    )
    defaults.update(kwargs)
    return geo_cache_key(**defaults)


# ---------------------------------------------------------------------------
# TestGeoCacheModule — 9 pure unit tests
# ---------------------------------------------------------------------------

class TestGeoCacheModule:
    def test_geo_cache_key_deterministic(self, tmp_path, monkeypatch):
        """Same inputs always produce the same key."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        k1 = _make_key()
        k2 = _make_key()
        assert k1 == k2
        assert len(k1) == 12

    def test_geo_cache_key_differs_on_width(self, tmp_path, monkeypatch):
        """Different panel_width → different key."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        k1 = _make_key(panel_width=100)
        k2 = _make_key(panel_width=120)
        assert k1 != k2

    def test_geo_cache_key_differs_on_skin(self, tmp_path, monkeypatch):
        """Different skin_name → different key."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        k1 = _make_key(skin_name="hermes")
        k2 = _make_key(skin_name="matrix")
        assert k1 != k2

    def test_geo_cache_key_differs_on_wide_layout(self, tmp_path, monkeypatch):
        """Different wide_layout flag → different key."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        k1 = _make_key(wide_layout=True)
        k2 = _make_key(wide_layout=False)
        assert k1 != k2

    def test_geo_cache_key_differs_on_tall_layout(self, tmp_path, monkeypatch):
        """Different tall_layout flag → different key."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        k1 = _make_key(tall_layout=True)
        k2 = _make_key(tall_layout=False)
        assert k1 != k2

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """save_geo then load_geo returns the original hero_row/hero_col."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_NO_CACHE", raising=False)
        key = _make_key()
        geo = {"hero_row": 5, "hero_col": 12}
        save_geo(key, geo)
        result = load_geo(key)
        assert result == geo

    def test_load_returns_none_on_missing(self, tmp_path, monkeypatch):
        """No file on disk → load_geo returns None."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_NO_CACHE", raising=False)
        result = load_geo("nonexistentkey123")
        assert result is None

    def test_load_returns_none_on_wrong_version(self, tmp_path, monkeypatch):
        """Wrong _v field in cached file → load_geo returns None."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_NO_CACHE", raising=False)
        key = _make_key()
        # Write a file with a wrong version.
        p = tmp_path / "hermes" / "banner_geo" / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"hero_row": 1, "hero_col": 2, "_v": 999}))
        result = load_geo(key)
        assert result is None

    def test_gc_removes_oldest_beyond_cap(self, tmp_path, monkeypatch):
        """gc_geo_cache(cap=20) removes oldest files when > 20 exist."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_NO_CACHE", raising=False)
        cache_dir = tmp_path / "hermes" / "banner_geo"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Create 25 files with distinct mtime.
        for i in range(25):
            p = cache_dir / f"file{i:03d}.json"
            p.write_text("{}")
            # Stagger mtime so sort order is stable.
            os.utime(p, (time.time() + i, time.time() + i))
        gc_geo_cache(cap=20)
        remaining = list(cache_dir.glob("*.json"))
        assert len(remaining) == 20


# ---------------------------------------------------------------------------
# Helpers for integration tests
# ---------------------------------------------------------------------------

# Minimal stub of a cli.py Text-like object that supports .plain and .find.
class _FakeLine:
    def __init__(self, text: str):
        self.plain = text

    def find(self, s: str) -> int:
        return self.plain.find(s)


class _FakeRichText:
    """Simulates the Rich Text object returned by _render_startup_banner_text."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def split(self, sep: str, *, allow_blank: bool = False):
        return [_FakeLine(line) for line in self._lines]


_PLACEHOLDER = ""  # matches _STARTUP_BANNER_PLACEHOLDER_MARKER in cli.py


def _make_stub_class(monkeypatch, tmp_path, *, render_lines: list[str] | None = None):
    """Return a minimal instance that exposes _build_startup_banner_template.

    Patches all module-level names the method depends on.
    """
    import cli as cli_mod  # noqa: PLC0415 – intentional late import

    monkeypatch.setattr(cli_mod, "_hermes_app", None)
    monkeypatch.setattr(cli_mod, "_STARTUP_BANNER_PLACEHOLDER_MARKER", _PLACEHOLDER)
    monkeypatch.setattr(cli_mod, "_sanitize_startup_hero_text", lambda t: t)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_NO_CACHE", raising=False)

    # Default render_lines: one line whose content matches the placeholder.
    plain_hero = "HERO"
    hero_width = len(plain_hero)
    hero_height = 2  # len(hero_lines)+1 = 1+1
    if render_lines is None:
        placeholder_row = _PLACEHOLDER * hero_width
        render_lines = ["preamble", placeholder_row, "postamble"]

    fake_text = _FakeRichText(render_lines)

    stub = object.__new__(cli_mod.HermesCLI)

    return stub, fake_text, plain_hero


# ---------------------------------------------------------------------------
# TestGeoCacheIntegration — 9 tests
# ---------------------------------------------------------------------------

class TestGeoCacheIntegration:
    def test_cache_miss_runs_full_scan(self, tmp_path, monkeypatch):
        """On a fresh cache the scan for-loop runs and finds hero_row/hero_col."""
        stub, fake_text, plain_hero = _make_stub_class(monkeypatch, tmp_path)
        with patch.object(stub, "_render_startup_banner_text", return_value=fake_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            result = stub._build_startup_banner_template(plain_hero)
        assert result is not None
        assert result["hero_row"] == 1
        assert result["hero_col"] == 0

    def test_cache_miss_saves_geo(self, tmp_path, monkeypatch):
        """After a cache miss the geo file is written to disk."""
        stub, fake_text, plain_hero = _make_stub_class(monkeypatch, tmp_path)
        with patch.object(stub, "_render_startup_banner_text", return_value=fake_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)), \
             patch("threading.Thread"):
            result = stub._build_startup_banner_template(plain_hero)
        assert result is not None
        # The geo cache dir should contain exactly one .json file.
        cache_dir = tmp_path / "hermes" / "banner_geo"
        json_files = list(cache_dir.glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data["hero_row"] == result["hero_row"]
        assert data["hero_col"] == result["hero_col"]

    def test_cache_hit_skips_scan_loop(self, tmp_path, monkeypatch):
        """Pre-populated cache → method returns without scanning placeholder."""
        stub, _, plain_hero = _make_stub_class(monkeypatch, tmp_path)
        # Render returns text with NO placeholder — if scan ran, start_row stays None → None returned.
        no_placeholder_text = _FakeRichText(["line_a", "line_b", "line_c"])
        with patch.object(stub, "_render_startup_banner_text", return_value=no_placeholder_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            # Prime the cache by doing a real scan first with text that has the placeholder.
            hero_width = len(plain_hero)
            placeholder_row = _PLACEHOLDER * hero_width
            priming_text = _FakeRichText(["preamble", placeholder_row, "end"])
            with patch.object(stub, "_render_startup_banner_text", return_value=priming_text), \
                 patch("threading.Thread"):
                stub._build_startup_banner_template(plain_hero)
            # Now re-run with no_placeholder_text; should hit cache and succeed.
            with patch.object(stub, "_render_startup_banner_text", return_value=no_placeholder_text):
                result = stub._build_startup_banner_template(plain_hero)
        assert result is not None

    def test_cache_hit_uses_cached_position(self, tmp_path, monkeypatch):
        """Cache hit returns cached hero_row/col, not what scan would find."""
        import cli as cli_mod
        stub, _, plain_hero = _make_stub_class(monkeypatch, tmp_path)

        # Pre-populate cache with specific values.
        with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            from hermes_cli.tui._banner_geo_cache import geo_cache_key, save_geo
            key = geo_cache_key(100, "hermes", True, True)
            save_geo(key, {"hero_row": 7, "hero_col": 3})

        # Render returns text that would give row=99 if scanned.
        hero_width = len(plain_hero)
        placeholder_row = _PLACEHOLDER * hero_width
        scan_would_give_99 = ["x"] * 99 + [placeholder_row]
        scan_text = _FakeRichText(scan_would_give_99)

        with patch.object(stub, "_render_startup_banner_text", return_value=scan_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            result = stub._build_startup_banner_template(plain_hero)

        assert result is not None
        assert result["hero_row"] == 7
        assert result["hero_col"] == 3

    def test_cache_hit_render_still_called(self, tmp_path, monkeypatch):
        """_render_startup_banner_text is called even on a cache hit."""
        stub, _, plain_hero = _make_stub_class(monkeypatch, tmp_path)

        with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            from hermes_cli.tui._banner_geo_cache import geo_cache_key, save_geo
            key = geo_cache_key(100, "hermes", True, True)
            save_geo(key, {"hero_row": 2, "hero_col": 0})

        hero_width = len(plain_hero)
        placeholder_row = _PLACEHOLDER * hero_width
        fake_text = _FakeRichText(["preamble", placeholder_row])
        render_mock = MagicMock(return_value=fake_text)

        with patch.object(stub, "_render_startup_banner_text", render_mock), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            stub._build_startup_banner_template(plain_hero)

        render_mock.assert_called_once()

    def test_cache_hit_lines_populated(self, tmp_path, monkeypatch):
        """On cache hit, result['lines'] is non-empty."""
        stub, _, plain_hero = _make_stub_class(monkeypatch, tmp_path)

        with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            from hermes_cli.tui._banner_geo_cache import geo_cache_key, save_geo
            key = geo_cache_key(100, "hermes", True, True)
            save_geo(key, {"hero_row": 1, "hero_col": 0})

        hero_width = len(plain_hero)
        placeholder_row = _PLACEHOLDER * hero_width
        fake_text = _FakeRichText(["preamble", placeholder_row, "end"])

        with patch.object(stub, "_render_startup_banner_text", return_value=fake_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            result = stub._build_startup_banner_template(plain_hero)

        assert result is not None
        assert len(result["lines"]) > 0

    def test_no_cache_env_disables_geo_cache(self, tmp_path, monkeypatch):
        """HERMES_NO_CACHE=1 → load_geo returns None, save_geo is no-op."""
        monkeypatch.setenv("HERMES_NO_CACHE", "1")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = _make_key()
        # save_geo should write nothing.
        save_geo(key, {"hero_row": 5, "hero_col": 2})
        cache_dir = tmp_path / "hermes" / "banner_geo"
        assert not cache_dir.exists() or len(list(cache_dir.glob("*.json"))) == 0
        # load_geo should return None even if file somehow exists.
        assert load_geo(key) is None

    def test_gc_thread_started_after_write(self, tmp_path, monkeypatch):
        """threading.Thread(target=gc_geo_cache, daemon=True) is started on miss+write."""
        stub, fake_text, plain_hero = _make_stub_class(monkeypatch, tmp_path)
        thread_mock = MagicMock()

        with patch.object(stub, "_render_startup_banner_text", return_value=fake_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)), \
             patch("threading.Thread", return_value=thread_mock) as thread_cls:
            stub._build_startup_banner_template(plain_hero)

        from hermes_cli.tui._banner_geo_cache import gc_geo_cache as _gc
        thread_cls.assert_called_once_with(target=_gc, daemon=True)
        thread_mock.start.assert_called_once()

    def test_hero_width_height_from_plain_hero(self, tmp_path, monkeypatch):
        """hero_width/hero_height are always derived from plain_hero, not from cache."""
        stub, _, _ = _make_stub_class(monkeypatch, tmp_path)

        # Pre-populate cache so we hit the cache-hit path.
        with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            from hermes_cli.tui._banner_geo_cache import geo_cache_key, save_geo
            key = geo_cache_key(100, "hermes", True, True)
            save_geo(key, {"hero_row": 0, "hero_col": 0})

        plain_hero = "ABCDE"  # 5 chars wide, 1 line → height = 1+1 = 2
        hero_width = len(plain_hero)
        placeholder_row = _PLACEHOLDER * hero_width
        fake_text = _FakeRichText(["preamble", placeholder_row])

        with patch.object(stub, "_render_startup_banner_text", return_value=fake_text), \
             patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"), \
             patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=25)):
            result = stub._build_startup_banner_template(plain_hero)

        assert result is not None
        assert result["hero_width"] == 5
        assert result["hero_height"] == 2
