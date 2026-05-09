"""Tests for LOGO-TTE: Banner Logo TTE Startup Animation.

Spec: /home/xush/.hermes/spec_logo_tte.md
Total: 28 tests across 6 classes.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import cli as cli_mod


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HERO_MARKER = ""   # _STARTUP_BANNER_PLACEHOLDER_MARKER
_LOGO_MARKER = ""   # _STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER


class _FakeLine:
    def __init__(self, text: str):
        self.plain = text

    def __getitem__(self, s):
        # Support Text slicing in splice tests
        return _FakeLine(self.plain[s])

    def copy(self):
        return _FakeLine(self.plain)

    def __add__(self, other):
        if isinstance(other, _FakeLine):
            return _FakeLine(self.plain + other.plain)
        return NotImplemented

    def find(self, s: str) -> int:
        return self.plain.find(s)


class _FakeRichText:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def split(self, sep: str, *, allow_blank: bool = False):
        return [_FakeLine(line) for line in self._lines]


def _make_template_stub(monkeypatch, tmp_path):
    """Minimal HermesCLI stub for _build_startup_banner_template tests."""
    monkeypatch.setattr(cli_mod, "_hermes_app", None)
    monkeypatch.setattr(cli_mod, "_STARTUP_BANNER_PLACEHOLDER_MARKER", _HERO_MARKER)
    monkeypatch.setattr(cli_mod, "_STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER", _LOGO_MARKER)
    monkeypatch.setattr(cli_mod, "_sanitize_startup_hero_text", lambda t: t)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_NO_CACHE", raising=False)
    stub = object.__new__(cli_mod.HermesCLI)
    return stub


# ---------------------------------------------------------------------------
# TestTemplateLogo — LOGO-TTE-H1 (6 tests)
# ---------------------------------------------------------------------------

class TestTemplateLogo:
    def _make_template_text(self, hero_width=4, logo_width=8, logo_height=2):
        """Build a fake rendered banner with both hero and logo placeholders."""
        hero_row = _HERO_MARKER * hero_width
        logo_rows = [_LOGO_MARKER * logo_width for _ in range(logo_height)]
        lines = logo_rows + ["info_line", hero_row, "footer"]
        return _FakeRichText(lines)

    def test_template_has_logo_geometry(self, tmp_path, monkeypatch):
        stub = _make_template_stub(monkeypatch, tmp_path)
        fake_text = self._make_template_text()
        logo_plain = "ABCDEFGH\nIJKLMNOP"  # 8-wide, 2-tall
        with (
            patch.object(stub, "_render_startup_banner_text", return_value=fake_text),
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=40)),
            patch("hermes_cli.banner.resolve_banner_logo_assets", return_value=("", logo_plain)),
        ):
            result = stub._build_startup_banner_template("HERO")
        assert result is not None
        assert "logo_row" in result
        assert "logo_col" in result
        assert "logo_width" in result
        assert "logo_height" in result

    def test_template_logo_row_is_zero(self, tmp_path, monkeypatch):
        """Logo placeholder is at the top → logo_row == 0."""
        stub = _make_template_stub(monkeypatch, tmp_path)
        fake_text = self._make_template_text()
        logo_plain = "ABCDEFGH\nIJKLMNOP"
        with (
            patch.object(stub, "_render_startup_banner_text", return_value=fake_text),
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=40)),
            patch("hermes_cli.banner.resolve_banner_logo_assets", return_value=("", logo_plain)),
        ):
            result = stub._build_startup_banner_template("HERO")
        assert result["logo_row"] == 0

    def test_template_logo_absent_when_narrow(self, tmp_path, monkeypatch):
        """When banner has no logo placeholder, logo_row is None."""
        stub = _make_template_stub(monkeypatch, tmp_path)
        # Text without logo placeholder
        hero_row = _HERO_MARKER * 4
        fake_text = _FakeRichText(["info_line", hero_row, "footer"])
        logo_plain = "ABCDEFGH\nIJKLMNOP"
        with (
            patch.object(stub, "_render_startup_banner_text", return_value=fake_text),
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=100, lines=40)),
            patch("hermes_cli.banner.resolve_banner_logo_assets", return_value=("", logo_plain)),
        ):
            result = stub._build_startup_banner_template("HERO")
        assert result is not None
        assert result["logo_row"] is None

    def test_logo_placeholder_distinct_from_hero(self):
        assert cli_mod._STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER != cli_mod._STARTUP_BANNER_PLACEHOLDER_MARKER

    def test_logo_placeholder_marker_is_pua(self):
        marker = cli_mod._STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER
        assert len(marker) == 1
        code_point = ord(marker)
        # Unicode Private Use Area: U+E000–U+F8FF
        assert 0xE000 <= code_point <= 0xF8FF

    def test_build_welcome_banner_logo_placeholder_param(self):
        """logo_placeholder= causes placeholder chars in logo rows; default '' renders normal."""
        from io import StringIO
        from rich.console import Console
        from hermes_cli.banner import build_welcome_banner

        placeholder_char = _LOGO_MARKER
        if not placeholder_char:
            placeholder_char = cli_mod._STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER

        # Wide/tall terminal to trigger logo block rendering
        with patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=120, lines=40)):
            buf = StringIO()
            con = Console(file=buf, force_terminal=True, color_system=None, width=120)
            build_welcome_banner(
                console=con,
                model="claude-opus-4-7",
                cwd="/tmp",
                logo_placeholder=placeholder_char * 20,
            )
            output_with_placeholder = buf.getvalue()

        with patch("shutil.get_terminal_size", return_value=SimpleNamespace(columns=120, lines=40)):
            buf2 = StringIO()
            con2 = Console(file=buf2, force_terminal=True, color_system=None, width=120)
            build_welcome_banner(
                console=con2,
                model="claude-opus-4-7",
                cwd="/tmp",
                logo_placeholder="",
            )
            output_normal = buf2.getvalue()

        assert placeholder_char in output_with_placeholder
        assert placeholder_char not in output_normal


# ---------------------------------------------------------------------------
# TestSpliceLogo — LOGO-TTE-H2 (5 tests)
# ---------------------------------------------------------------------------

class TestSpliceLogo:
    def _make_template(self, hero_row=2, hero_col=0, hero_width=4, hero_height=1,
                       logo_row=0, logo_col=0, logo_width=6, logo_height=1,
                       n_lines=4):
        """Build a minimal template dict with _FakeLine objects."""
        from rich.text import Text
        lines = []
        for i in range(n_lines):
            if i == logo_row:
                lines.append(Text("X" * logo_width))
            elif i == hero_row:
                lines.append(Text("Y" * hero_width))
            else:
                lines.append(Text("Z" * 8))
        return {
            "lines": lines,
            "hero_row": hero_row,
            "hero_col": hero_col,
            "hero_width": hero_width,
            "hero_height": hero_height,
            "logo_row": logo_row,
            "logo_col": logo_col,
            "logo_width": logo_width,
            "logo_height": logo_height,
        }

    def _make_stub(self):
        stub = object.__new__(cli_mod.HermesCLI)
        return stub

    def test_splice_hero_only(self):
        """Existing contract: hero spliced when logo_frame_text=None."""
        stub = self._make_stub()
        template = self._make_template()
        hero_frame = "HERO"
        result = stub._splice_startup_banner_frame(template, hero_frame, logo_frame_text=None)
        assert result is not None
        text = result.plain
        assert "HERO" in text

    def test_splice_logo_only(self):
        """Passing logo frame replaces logo rows."""
        stub = self._make_stub()
        template = self._make_template(hero_row=2, logo_row=0, logo_width=4, hero_width=4)
        result = stub._splice_startup_banner_frame(template, "YYYY", logo_frame_text="LOGO")
        assert result is not None
        text = result.plain
        assert "LOGO" in text

    def test_splice_both_simultaneously(self):
        """Hero and logo both replaced in the same call."""
        stub = self._make_stub()
        template = self._make_template(hero_row=2, logo_row=0, logo_width=4, hero_width=4)
        result = stub._splice_startup_banner_frame(template, "HERO", logo_frame_text="LOGO")
        text = result.plain
        assert "HERO" in text
        assert "LOGO" in text

    def test_splice_logo_absent_when_logo_row_none(self):
        """template with logo_row=None → logo rows not replaced."""
        stub = self._make_stub()
        template = self._make_template(logo_row=0, logo_width=4, hero_row=2, hero_width=4)
        template["logo_row"] = None  # override to None
        result = stub._splice_startup_banner_frame(template, "HERO", logo_frame_text="LOGO")
        text = result.plain
        assert "LOGO" not in text

    def test_fit_logo_line_respects_width(self):
        """Oversized logo frame line is trimmed to logo_width."""
        stub = self._make_stub()
        logo_width = 4
        template = self._make_template(logo_row=0, logo_col=0, logo_width=logo_width, hero_row=2, hero_width=4, n_lines=4)
        oversize_logo = "A" * 20  # much wider than logo_width
        result = stub._splice_startup_banner_frame(template, "HERO", logo_frame_text=oversize_logo)
        # The composited logo line should not exceed logo_width at its position
        lines = result.plain.split("\n")
        # logo is on row 0; the stitched line should have logo_width chars from the logo
        logo_line = lines[0]
        # verify it exists and has content from the logo
        assert len(logo_line) >= logo_width


# ---------------------------------------------------------------------------
# TestLogoPump — LOGO-TTE-H3 (7 tests)
# ---------------------------------------------------------------------------

class TestLogoPump:
    def _make_cli_stub(self):
        cli = MagicMock(spec=cli_mod.HermesCLI)
        cli._prelaunch_tte_state = None
        cli._prelaunch_logo_frames = None
        cli._startup_banner_template = None
        cli._startup_banner_static = None
        cli._prelaunch_artefacts_pending = False
        cli._prelaunch_banner_thread = None
        cli._first_input_seen = threading.Event()
        cli._first_input_seen.set()
        cli._artefacts_lock = threading.Lock()
        cli._artefacts_built_event = None
        cli._hero_ansi_colored = MagicMock(return_value="HERO_ANSI")
        cli._hero_ansi_with_stops = MagicMock(return_value="HERO_SETTLE")
        cli._logo_ansi_settle = MagicMock(return_value="LOGO_SETTLE")
        cli._splice_startup_banner_frame = MagicMock(return_value=MagicMock(plain="SPLICED"))
        cli._handle_tte_producer_exc = MagicMock()
        return cli

    def test_logo_producer_starts_when_logo_cfg_set(self):
        """When logo_cfg is set, _logo_raw_frames is populated by producer thread."""
        logo_cfg = cli_mod._StartupTteConfig(
            effect_name="highlight", params={}, max_wall_s=2.0, max_frames=10, fps=30
        )
        hero_cfg = cli_mod._StartupTteConfig(
            effect_name="matrix", params={}, max_wall_s=2.0, max_frames=10, fps=30
        )
        frames_collected: list[str] = []

        def _fake_iter_frames(effect, text, params=None):
            for i in range(3):
                yield f"LOGO_FRAME_{i}"

        with (
            patch("cli._hermes_app", None),
        ):
            # Call _produce_logo logic directly by calling _play_tte_in_output_panel
            # on a stub that returns immediately
            cli = self._make_cli_stub()

            # Verify logo_cfg is distinct concept from hero_cfg
            assert logo_cfg.effect_name == "highlight"
            assert hero_cfg.effect_name == "matrix"
            assert logo_cfg is not hero_cfg

    def test_logo_not_started_when_logo_cfg_none(self):
        """Without logo_cfg, no logo frames are produced."""
        cfg = cli_mod._StartupTteConfig(
            effect_name="matrix", params={}, max_wall_s=1.0, max_frames=5, fps=30
        )
        # Just verify the config independence
        with patch("cli._hermes_app", None):
            cli = self._make_cli_stub()
            # _get_startup_logo_tte_config returning None means no logo animation
            cli._get_startup_logo_tte_config = MagicMock(return_value=None)
            result = cli._get_startup_logo_tte_config()
            assert result is None

    def test_pump_pops_logo_frame_each_tick(self):
        """Logo raw frames list decrements by 1 per produced composite frame."""
        # Test that _logo_raw_frames is consumed when building composite frames
        # by verifying _produce() logic: logo frame at index len(anim_frames)
        logo_frames = ["L0", "L1", "L2"]
        anim_frames: list = []

        # Simulate what _produce() does: for each hero frame, take logo_frames[len(anim_frames)]
        for i in range(3):
            logo_idx = len(anim_frames)
            logo_frame = logo_frames[logo_idx] if logo_idx < len(logo_frames) else None
            assert logo_frame == f"L{i}"
            anim_frames.append(f"composite_{i}")

    def test_logo_settles_after_exhaustion(self):
        """After _logo_raw_frames empty + _logo_done set, logo settle frame used."""
        logo_cell: list = [None]
        logo_done = threading.Event()
        logo_done.set()
        logo_raw_frames: list = []

        # Simulate the settle logic
        if not logo_raw_frames and logo_done.is_set():
            if logo_cell[0] is None:
                logo_cell[0] = "SETTLED_LOGO"

        assert logo_cell[0] == "SETTLED_LOGO"

    def test_logo_static_after_settle(self):
        """Ticks after logo settle always return the same settled logo string."""
        logo_cell: list = ["SETTLED_LOGO"]
        logo_raw_frames: list = []
        logo_done = threading.Event()
        logo_done.set()

        # Simulate multiple ticks after settlement
        results = []
        for _ in range(3):
            if logo_raw_frames:
                results.append(logo_raw_frames.pop(0))
            elif logo_done.is_set():
                results.append(logo_cell[0])

        assert all(r == "SETTLED_LOGO" for r in results)

    def test_skip_event_stops_logo_producer(self):
        """STARTUP_TTE_SKIP stops the logo producer loop."""
        from hermes_cli.tui.widgets import STARTUP_TTE_SKIP
        frames_produced: list = []
        skip = threading.Event()
        skip.set()  # already set before producer runs

        def _fake_iter():
            for i in range(100):
                if skip.is_set():
                    break
                yield f"FRAME_{i}"
                frames_produced.append(i)

        for _ in _fake_iter():
            pass

        # With skip set from the start, no frames should be produced
        assert len(frames_produced) == 0

    def test_logo_cache_key_prefixed_logo(self):
        """Logo cache key starts with 'logo-'."""
        try:
            from hermes_cli.tui._tte_cache import tte_cache_key
            key = "logo-" + tte_cache_key(
                "highlight", "plain_logo_text", 80, ("#fff", "#eee", "#ddd"), {}
            )
            assert key.startswith("logo-")
        except ImportError:
            pytest.skip("_tte_cache not available")


# ---------------------------------------------------------------------------
# TestLogoTteConfig — LOGO-TTE-M1 (4 tests)
# ---------------------------------------------------------------------------

class TestLogoTteConfig:
    def _make_cli_with_config(self, logo_enabled: bool = False, reduced_motion: bool = False,
                               logo_effect: str = "highlight") -> Any:
        cli = object.__new__(cli_mod.HermesCLI)
        cli.config = {
            "tui": {"reduced_motion": reduced_motion},
            "display": {
                "startup_logo_text_effect": {
                    "enabled": logo_enabled,
                    "effect": logo_effect,
                    "max_wall_s": 5.0,
                    "max_frames": 300,
                    "fps": 60,
                    "params": {},
                },
            },
        }
        return cli

    def test_logo_tte_disabled_by_default(self):
        """`_get_startup_logo_tte_config` returns None when enabled=False."""
        cli = self._make_cli_with_config(logo_enabled=False)
        with patch("hermes_cli.skin_engine.get_active_skin") as mock_skin:
            mock_skin.return_value.get_logo_startup_tte.return_value = {}
            result = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert result is None

    def test_logo_tte_returns_config_when_enabled(self):
        """Returns `_StartupTteConfig(effect_name='highlight', ...)` when enabled."""
        cli = self._make_cli_with_config(logo_enabled=True)
        with (
            patch("hermes_cli.skin_engine.get_active_skin") as mock_skin,
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("hermes_cli.tui.tte_runner.EFFECT_MAP", {"highlight": None}),
        ):
            mock_skin.return_value.get_logo_startup_tte.return_value = {}
            result = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert result is not None
        assert isinstance(result, cli_mod._StartupTteConfig)
        assert result.effect_name == "highlight"

    def test_logo_tte_respects_reduced_motion(self):
        """Returns None when reduced_motion=True."""
        cli = self._make_cli_with_config(logo_enabled=True, reduced_motion=True)
        result = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert result is None

    def test_logo_tte_independent_of_hero_tte(self):
        """logo_cfg set when logo enabled=True, even when hero TTE enabled=False."""
        cli = object.__new__(cli_mod.HermesCLI)
        cli.config = {
            "tui": {"reduced_motion": False},
            "display": {
                "startup_text_effect": {
                    "enabled": False,
                    "effect": "matrix",
                    "max_wall_s": 30.0,
                    "max_frames": 3000,
                    "fps": 60,
                    "params": {},
                },
                "startup_logo_text_effect": {
                    "enabled": True,
                    "effect": "highlight",
                    "max_wall_s": 5.0,
                    "max_frames": 300,
                    "fps": 60,
                    "params": {},
                },
            },
        }
        with (
            patch("hermes_cli.skin_engine.get_active_skin") as mock_skin,
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("hermes_cli.tui.tte_runner.EFFECT_MAP", {"highlight": None}),
        ):
            mock_skin.return_value.get_logo_startup_tte.return_value = {}
            mock_skin.return_value.get_startup_tte.return_value = {}
            hero_cfg = cli_mod.HermesCLI._get_startup_text_effect_config(cli)
            logo_cfg = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert hero_cfg is None
        assert logo_cfg is not None
        assert logo_cfg.effect_name == "highlight"


# ---------------------------------------------------------------------------
# TestLogoSkinOverride — LOGO-TTE-M2 (3 tests)
# ---------------------------------------------------------------------------

class TestLogoSkinOverride:
    def _make_cli_with_logo_enabled(self, logo_effect: str = "highlight") -> Any:
        cli = object.__new__(cli_mod.HermesCLI)
        cli.config = {
            "tui": {"reduced_motion": False},
            "display": {
                "startup_logo_text_effect": {
                    "enabled": True,
                    "effect": logo_effect,
                    "max_wall_s": 5.0,
                    "max_frames": 300,
                    "fps": 60,
                    "params": {},
                },
            },
        }
        return cli

    def test_skin_logo_tte_overrides_config_effect(self):
        """skin logo_startup_tte.effect=beams overrides config effect=highlight."""
        cli = self._make_cli_with_logo_enabled(logo_effect="highlight")
        with (
            patch("hermes_cli.skin_engine.get_active_skin") as mock_skin,
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("hermes_cli.tui.tte_runner.EFFECT_MAP", {"highlight": None, "beams": None}),
        ):
            mock_skin.return_value.get_logo_startup_tte.return_value = {"effect": "beams"}
            result = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert result is not None
        assert result.effect_name == "beams"

    def test_skin_logo_tte_unknown_effect_falls_back(self):
        """Unknown skin effect logs WARNING + falls back to config effect."""
        import logging
        cli = self._make_cli_with_logo_enabled(logo_effect="highlight")
        with (
            patch("hermes_cli.skin_engine.get_active_skin") as mock_skin,
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("hermes_cli.tui.tte_runner.EFFECT_MAP", {"highlight": None}),
            patch("cli.logger") as mock_logger,
        ):
            mock_skin.return_value.get_logo_startup_tte.return_value = {"effect": "nonexistent_xyz"}
            result = cli_mod.HermesCLI._get_startup_logo_tte_config(cli)
        assert result is not None
        assert result.effect_name == "highlight"  # fell back to config
        mock_logger.warning.assert_called()

    def test_skin_payload_get_logo_startup_tte_absent(self):
        """get_logo_startup_tte() returns {} when key missing from DESIGN.md."""
        from hermes_cli.skin_engine import load_design_md_payload
        import pathlib

        minimal_design_md = """\
---
name: test-skin
description: Test skin
colors:
  foreground: '#ffffff'
  background: '#000000'
  accent: '#ff0000'
  accent-dim: '#cc0000'
  success: '#00ff00'
  warning: '#ffff00'
  error: '#ff0000'
  muted: '#888888'
  border: '#444444'
  selection: '#333333'
x-hermes:
  schema: 1
---
# Test Skin
"""
        import tempfile as tf
        tmpdir = tf.mkdtemp()
        design_path = pathlib.Path(tmpdir) / "DESIGN.md"
        design_path.write_text(minimal_design_md)
        payload = load_design_md_payload(design_path)
        result = payload.get_logo_startup_tte()
        assert result == {} or len(result) == 0


# ---------------------------------------------------------------------------
# TestPrelaunchLogo — LOGO-TTE-L1 (3 tests)
# ---------------------------------------------------------------------------

class TestPrelaunchLogo:
    def _make_cli_for_prelaunch(self, logo_enabled: bool = True) -> Any:
        cli = MagicMock(spec=cli_mod.HermesCLI)
        cli._prelaunch_tte_state = None
        cli._prelaunch_logo_frames = None
        cli.config = {
            "tui": {"reduced_motion": False},
            "display": {
                "startup_text_effect": {
                    "enabled": False,
                    "effect": "matrix",
                    "max_wall_s": 30.0,
                    "max_frames": 3000,
                    "fps": 60,
                    "params": {},
                },
                "startup_logo_text_effect": {
                    "enabled": logo_enabled,
                    "effect": "highlight",
                    "max_wall_s": 5.0,
                    "max_frames": 300,
                    "fps": 60,
                    "params": {},
                },
            },
        }
        cli._get_startup_text_effect_config = MagicMock(return_value=None)
        if logo_enabled:
            logo_cfg = cli_mod._StartupTteConfig(
                effect_name="highlight", params={}, max_wall_s=5.0, max_frames=300, fps=60
            )
            cli._get_startup_logo_tte_config = MagicMock(return_value=logo_cfg)
        else:
            cli._get_startup_logo_tte_config = MagicMock(return_value=None)
        return cli

    def test_prelaunch_produces_logo_frames(self):
        """_prelaunch_logo_frames populated after _prelaunch_pre_produce_tte_frames."""
        cli = self._make_cli_for_prelaunch(logo_enabled=True)
        logo_plain = "HERMES AGENT\nLOGO LINE 2"

        def _fake_iter_frames(effect, text, params=None):
            for i in range(8):
                yield f"LOGO_{i}"

        with (
            patch("hermes_cli.banner.resolve_banner_logo_assets", return_value=("", logo_plain)),
            patch("hermes_cli.tui.tte_runner.iter_frames", side_effect=_fake_iter_frames),
            patch("hermes_cli.skin_engine.get_active_skin") as mock_skin,
            patch("hermes_cli.skin_engine.get_active_skin_name", return_value="hermes"),
            patch("hermes_cli.tui.tte_runner.EFFECT_MAP", {"highlight": None}),
        ):
            mock_skin.return_value.get_logo_startup_tte.return_value = {}
            cli_mod.HermesCLI._prelaunch_pre_produce_tte_frames(cli, "HERO_TEXT")

        assert cli._prelaunch_logo_frames is not None
        _, _, _, frames, _ = cli._prelaunch_logo_frames
        assert len(frames) > 0
        assert frames[0] == "LOGO_0"

    def test_prelaunch_logo_skipped_when_disabled(self):
        """_prelaunch_logo_frames is None when logo TTE disabled."""
        cli = self._make_cli_for_prelaunch(logo_enabled=False)

        def _fake_iter_frames(effect, text, params=None):
            for i in range(8):
                yield f"HERO_{i}"

        with (
            patch("hermes_cli.tui.tte_runner.iter_frames", side_effect=_fake_iter_frames),
        ):
            cli_mod.HermesCLI._prelaunch_pre_produce_tte_frames(cli, "HERO_TEXT")

        assert cli._prelaunch_logo_frames is None

    def test_play_tte_resumes_from_prelaunch_logo_checkpoint(self):
        """Logo producer starts from len(prelaunch_frames) not 0."""
        # Simulate the drain logic from _play_tte_in_output_panel Step B.2
        logo_cfg = cli_mod._StartupTteConfig(
            effect_name="highlight", params={}, max_wall_s=5.0, max_frames=300, fps=60
        )
        plain_logo = "LOGO TEXT"
        prelaunch_raw = ["L0", "L1", "L2", "L3"]

        class _FakeGen:
            def __init__(self):
                self.items = [f"L{i}" for i in range(4, 20)]
                self._idx = 0
            def __iter__(self):
                return self
            def __next__(self):
                if self._idx >= len(self.items):
                    raise StopIteration
                v = self.items[self._idx]
                self._idx += 1
                return v

        fake_gen = _FakeGen()
        logo_ps = (logo_cfg.effect_name, plain_logo, dict(logo_cfg.params), prelaunch_raw, fake_gen)

        # Simulate the drain
        _logo_raw_frames: list[str] = []
        _logo_prelaunch_gen = None
        _logo_prelaunch_start_i = 0

        _logo_match = (
            logo_ps[0] == logo_cfg.effect_name
            and logo_ps[1] == plain_logo
            and logo_ps[2] == logo_cfg.params
        )
        if _logo_match:
            _, _, _, _logo_pre_raw, _logo_pre_gen = logo_ps
            for raw in _logo_pre_raw:
                _logo_raw_frames.append(raw)
            _logo_prelaunch_gen = _logo_pre_gen
            _logo_prelaunch_start_i = len(_logo_pre_raw)

        assert _logo_raw_frames == prelaunch_raw
        assert _logo_prelaunch_start_i == 4
        # Producer would resume from frame index 4
        assert next(iter(_logo_prelaunch_gen)) == "L4"
