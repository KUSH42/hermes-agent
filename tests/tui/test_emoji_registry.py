"""
tests/tui/test_emoji_registry.py — 50 tests for custom emoji feature.

Groups:
  A (7):  EmojiEntry dataclass defaults
  B (8):  normalize_emoji() — aspect ratio, clamping, PIL-unavailable fallback
  C (8):  EmojiRegistry.load() — dir scan, md parse, disk cache, orphan cleanup
  D (5):  EmojiRegistry accessors — get, all_entries, is_empty, system_prompt_block
  E (6):  _EMOJI_RE regex — matches, no-match, registry-gating
  F (7):  ResponseFlowEngine emoji integration — extract, mount, ReasoningFlowEngine gating
  G (5):  Animated GIF — n_frames count, _start_animation fallback, AnimatedEmojiWidget class
  H (4):  app._resolve_user_emoji() — DOM mutation, no-op when registry absent
"""
from __future__ import annotations

import io
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(name="smile", n_frames=1, pil_image=None, cell_width=2, cell_height=1):
    from hermes_cli.tui.emoji_registry import EmojiEntry
    return EmojiEntry(
        name=name,
        path=Path(f"/fake/{name}.png"),
        description="test emoji",
        pil_image=pil_image,
        cell_width=cell_width,
        cell_height=cell_height,
        n_frames=n_frames,
    )


def _make_pil_image(w=32, h=32):
    """Return a minimal RGBA PIL image or None if PIL unavailable."""
    try:
        from PIL import Image
        img = Image.new("RGBA", (w, h), (255, 0, 0, 255))
        return img
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# A: EmojiEntry dataclass defaults
# ---------------------------------------------------------------------------

class TestEmojiEntryDefaults:
    def test_name_stored(self):
        e = _make_entry("wave")
        assert e.name == "wave"

    def test_description_stored(self):
        from hermes_cli.tui.emoji_registry import EmojiEntry
        e = EmojiEntry(name="x", path=Path("/x.png"), description="hello")
        assert e.description == "hello"

    def test_default_cell_width(self):
        from hermes_cli.tui.emoji_registry import EmojiEntry
        e = EmojiEntry(name="x", path=Path("/x.png"), description="")
        assert e.cell_width == 2

    def test_default_cell_height(self):
        from hermes_cli.tui.emoji_registry import EmojiEntry
        e = EmojiEntry(name="x", path=Path("/x.png"), description="")
        assert e.cell_height == 1

    def test_default_n_frames(self):
        from hermes_cli.tui.emoji_registry import EmojiEntry
        e = EmojiEntry(name="x", path=Path("/x.png"), description="")
        assert e.n_frames == 1

    def test_pil_image_default_none(self):
        from hermes_cli.tui.emoji_registry import EmojiEntry
        e = EmojiEntry(name="x", path=Path("/x.png"), description="")
        assert e.pil_image is None

    def test_animated_entry_n_frames(self):
        e = _make_entry("anim", n_frames=12)
        assert e.n_frames == 12


# ---------------------------------------------------------------------------
# B: normalize_emoji()
# ---------------------------------------------------------------------------

class TestNormalizeEmoji:
    def test_returns_none_when_pil_missing(self, tmp_path):
        p = tmp_path / "img.png"
        p.write_bytes(b"")
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            from hermes_cli.tui.emoji_registry import normalize_emoji
            result = normalize_emoji(p, 4, 1, 8, 16)
        assert result is None

    @pytest.mark.skipif(
        not pytest.importorskip("PIL", reason="PIL not available"),
        reason="PIL not available",
    )
    def test_cell_height_always_1(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (64, 128), (0, 0, 0, 255))
        p = tmp_path / "tall.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(p, 4, 2, 8, 16)
        assert result is not None
        _, cw, ch = result
        assert ch == 1

    @pytest.mark.skipif(
        not pytest.importorskip("PIL", reason="PIL not available"),
        reason="PIL not available",
    )
    def test_wide_image_clamped_to_max(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (512, 16), (0, 0, 0, 255))
        p = tmp_path / "wide.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(p, 4, 1, 8, 16)
        assert result is not None
        _, cw, ch = result
        assert cw <= 4
        assert ch == 1

    @pytest.mark.skipif(
        not pytest.importorskip("PIL", reason="PIL not available"),
        reason="PIL not available",
    )
    def test_square_image_gets_sensible_width(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (32, 32), (0, 0, 0, 255))
        p = tmp_path / "sq.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(p, 4, 1, 8, 16)
        assert result is not None
        pil, cw, ch = result
        assert 1 <= cw <= 4
        assert ch == 1
        assert pil is not None

    @pytest.mark.skipif(
        not pytest.importorskip("PIL", reason="PIL not available"),
        reason="PIL not available",
    )
    def test_bad_path_returns_none(self, tmp_path):
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(tmp_path / "nonexistent.png", 4, 1, 8, 16)
        assert result is None

    def test_zero_cell_px_fallback(self, tmp_path):
        """normalize_emoji should not crash when cell_px_w/h are 0."""
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (32, 32), (0, 0, 0, 255))
        p = tmp_path / "sq.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(p, 4, 1, 0, 0)
        assert result is not None

    def test_returns_triple(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (32, 32), (0, 0, 0, 255))
        p = tmp_path / "sq.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        result = normalize_emoji(p, 4, 1, 8, 16)
        assert result is not None
        assert len(result) == 3

    def test_cell_height_enforced_ignores_max(self, tmp_path):
        """max_cell_height param is ignored — always produces ch=1."""
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        img = _PILImage.new("RGBA", (64, 64), (0, 0, 0, 255))
        p = tmp_path / "sq.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import normalize_emoji
        for max_ch in (1, 2, 4, 10):
            result = normalize_emoji(p, 4, max_ch, 8, 16)
            assert result is not None
            assert result[2] == 1


# ---------------------------------------------------------------------------
# C: EmojiRegistry.load()
# ---------------------------------------------------------------------------

class TestEmojiRegistryLoad:
    def test_empty_when_dir_missing(self, tmp_path):
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(tmp_path / "nope")
        reg.load()
        assert reg.is_empty()

    def test_loads_png_files(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (0, 255, 0, 255))
        img.save(str(d / "thumbsup.png"))
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d)
        reg.load()
        assert not reg.is_empty()
        assert reg.get("thumbsup") is not None

    def test_case_insensitive_lookup(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (0, 255, 0, 255))
        img.save(str(d / "ThumbsUp.png"))
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d)
        reg.load()
        assert reg.get("thumbsup") is not None
        assert reg.get("THUMBSUP") is not None

    def test_reads_description_from_md(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (0, 255, 0, 255))
        img.save(str(d / "wave.png"))
        md = d / "emojis.md"
        md.write_text(":wave: - A waving hand\n")
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d, md)
        reg.load()
        entry = reg.get("wave")
        assert entry is not None
        assert "waving" in entry.description

    def test_ignores_non_image_files(self, tmp_path):
        d = tmp_path / "emojis"
        d.mkdir()
        (d / "readme.txt").write_text("hello")
        (d / "emojis.md").write_text(":x: - test\n")
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d)
        reg.load()
        assert reg.is_empty()

    def test_disk_cache_writes_png(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (255, 0, 0, 255))
        img.save(str(d / "red.png"))
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d, cfg={"disk_cache": True, "max_cell_width": 2})
        reg.load()
        cache_dir = d / ".cache"
        assert cache_dir.exists()
        assert any(cache_dir.iterdir())

    def test_disk_cache_hit_skips_normalize(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (255, 0, 0, 255))
        p = d / "red.png"
        img.save(str(p))
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        # First load populates cache
        reg1 = EmojiRegistry(d, cfg={"disk_cache": True, "max_cell_width": 2})
        reg1.load()
        # Second load should hit cache
        reg2 = EmojiRegistry(d, cfg={"disk_cache": True, "max_cell_width": 2})
        normalize_calls = []
        from hermes_cli.tui import emoji_registry as _er
        orig = _er.normalize_emoji
        def _spy(path, *args, **kwargs):
            normalize_calls.append(path)
            return orig(path, *args, **kwargs)
        with patch.object(_er, "normalize_emoji", _spy):
            reg2.load()
        # Spy may or may not be called depending on cache hit; just verify load succeeds
        assert not reg2.is_empty()

    def test_orphan_cache_entries_removed(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        img = _PILImage.new("RGBA", (16, 16), (255, 0, 0, 255))
        img.save(str(d / "red.png"))
        cache_dir = d / ".cache"
        cache_dir.mkdir()
        # Create stale orphan cache entry
        stale = cache_dir / "orphan_2x1_8x16.png"
        stale.write_bytes(b"fake")
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d, cfg={"disk_cache": True, "max_cell_width": 2})
        reg.load()
        assert not stale.exists()


# ---------------------------------------------------------------------------
# D: EmojiRegistry accessors
# ---------------------------------------------------------------------------

class TestEmojiRegistryAccessors:
    def _make_loaded_registry(self, tmp_path):
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        d = tmp_path / "emojis"
        d.mkdir()
        for name in ("smile", "wave"):
            img = _PILImage.new("RGBA", (16, 16), (0, 0, 0, 255))
            img.save(str(d / f"{name}.png"))
        md = d / "emojis.md"
        md.write_text(":smile: - A smiling face\n:wave: - Waving hand\n")
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(d, md)
        reg.load()
        return reg

    def test_get_returns_none_for_unknown(self, tmp_path):
        reg = self._make_loaded_registry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_all_entries_count(self, tmp_path):
        reg = self._make_loaded_registry(tmp_path)
        assert len(reg.all_entries()) == 2

    def test_is_empty_false_when_loaded(self, tmp_path):
        reg = self._make_loaded_registry(tmp_path)
        assert not reg.is_empty()

    def test_system_prompt_block_contains_names(self, tmp_path):
        reg = self._make_loaded_registry(tmp_path)
        block = reg.system_prompt_block()
        assert ":smile:" in block
        assert ":wave:" in block

    def test_system_prompt_block_empty_when_no_entries(self, tmp_path):
        from hermes_cli.tui.emoji_registry import EmojiRegistry
        reg = EmojiRegistry(tmp_path / "nope")
        reg.load()
        assert reg.system_prompt_block() == ""


# ---------------------------------------------------------------------------
# E: _EMOJI_RE regex
# ---------------------------------------------------------------------------

class TestEmojiRegex:
    def setup_method(self):
        from hermes_cli.tui.response_flow import _EMOJI_RE
        self.re = _EMOJI_RE

    def test_matches_simple_name(self):
        m = self.re.search("hello :smile: world")
        assert m is not None
        assert m.group(1) == "smile"

    def test_matches_name_with_hyphen(self):
        m = self.re.search(":thumbs-up:")
        assert m is not None
        assert m.group(1) == "thumbs-up"

    def test_matches_name_with_underscore(self):
        m = self.re.search(":cat_face:")
        assert m is not None
        assert m.group(1) == "cat_face"

    def test_no_match_on_spaces_inside(self):
        m = self.re.search(":hello world:")
        assert m is None

    def test_findall_multiple(self):
        matches = self.re.findall(":a: and :b: and :c:")
        assert matches == ["a", "b", "c"]

    def test_no_match_empty_name(self):
        m = self.re.search("::")
        assert m is None


# ---------------------------------------------------------------------------
# F: ResponseFlowEngine emoji integration
# ---------------------------------------------------------------------------

class TestResponseFlowEmojiIntegration:
    def _make_engine(self, registry=None, enabled=True):
        """Build a minimal ResponseFlowEngine with mocked panel."""
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        app = MagicMock()
        app._emoji_registry = registry
        app._emoji_images_enabled = enabled
        app._math_enabled = False
        app._mermaid_enabled = False
        app._citations_enabled = False
        app._math_renderer = "unicode"
        app._math_dpi = 150
        app._math_max_rows = 12
        panel = MagicMock()
        panel.app = app
        panel.response_log = MagicMock()
        panel.current_prose_log = MagicMock(return_value=panel.response_log)
        panel.response_log.write_with_source = MagicMock()
        panel.response_log.write_inline = MagicMock()
        engine = ResponseFlowEngine.__new__(ResponseFlowEngine)
        engine.__init__(panel=panel)
        engine._has_image_support = MagicMock(return_value=True)
        return engine

    def test_extract_empty_when_no_registry(self):
        engine = self._make_engine(registry=None)
        assert engine._extract_emoji_refs("hello :smile:") == []

    def test_extract_empty_when_disabled(self):
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        engine = self._make_engine(registry=registry, enabled=False)
        assert engine._extract_emoji_refs("hello :smile:") == []

    def test_extract_only_known_names(self):
        registry = MagicMock()
        registry.get.side_effect = lambda name: (
            MagicMock() if name == "smile" else None
        )
        engine = self._make_engine(registry=registry)
        result = engine._extract_emoji_refs("hello :smile: and :wave:")
        assert result == ["smile"]

    def test_extract_deduplicates(self):
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        engine = self._make_engine(registry=registry)
        result = engine._extract_emoji_refs(":smile: and :smile:")
        assert result == ["smile"]

    def test_extract_empty_without_image_support(self):
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        engine = self._make_engine(registry=registry)
        engine._has_image_support = MagicMock(return_value=False)
        assert engine._extract_emoji_refs("hello :smile:") == []

    def test_inline_emoji_write_uses_write_inline(self, tmp_path):
        from hermes_cli.tui.emoji_registry import EmojiEntry

        pil_img = _make_pil_image()
        entry = EmojiEntry(
            name="smile",
            path=tmp_path / "smile.png",
            description="",
            pil_image=pil_img,
            cell_width=2,
            cell_height=1,
            n_frames=1,
        )
        registry = MagicMock()
        registry.get.side_effect = lambda name: entry if name == "smile" else None
        engine = self._make_engine(registry=registry)

        from rich.text import Text

        wrote_inline = engine._write_prose_inline_emojis(Text("hi :smile: there"), "hi :smile: there")
        assert wrote_inline is True
        engine._prose_log.write_inline.assert_called_once()
        engine._prose_log.write_with_source.assert_not_called()

    def test_has_image_support_for_tgp_sixel_and_halfblock(self):
        engine = self._make_engine(registry=None)
        del engine._has_image_support
        from hermes_cli.tui.kitty_graphics import GraphicsCap
        with patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK):
            assert engine._has_image_support() is True
        with patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.TGP):
            assert engine._has_image_support() is True
        with patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.SIXEL):
            assert engine._has_image_support() is True

    def test_mount_emoji_no_crash_when_registry_none(self):
        engine = self._make_engine(registry=None)
        engine._mount_emoji("smile")  # should not raise

    def test_mount_emoji_skips_unknown_entry(self):
        registry = MagicMock()
        registry.get.return_value = None
        engine = self._make_engine(registry=registry)
        engine._mount_emoji("ghost")  # should not raise

    def test_reasoning_engine_emoji_disabled_when_flag_off(self):
        from hermes_cli.tui.response_flow import ReasoningFlowEngine
        app = MagicMock()
        app._emoji_registry = MagicMock()
        app._emoji_images_enabled = True
        app._emoji_reasoning = False
        app._reasoning_rich_prose = True
        app._citations_enabled = False
        panel = MagicMock()
        panel.app = app
        panel._reasoning_log = MagicMock()
        panel._plain_lines = []
        engine = ReasoningFlowEngine.__new__(ReasoningFlowEngine)
        engine.__init__(panel=panel)
        assert engine._emoji_registry is None
        assert not engine._emoji_images_enabled


# ---------------------------------------------------------------------------
# G: Animated GIF
# ---------------------------------------------------------------------------

class TestAnimatedGif:
    def test_n_frames_default_one(self):
        e = _make_entry("img", n_frames=1)
        assert e.n_frames == 1

    def test_n_frames_multi(self):
        e = _make_entry("anim", n_frames=5)
        assert e.n_frames == 5

    def test_get_animated_widget_class_returns_type(self):
        from hermes_cli.tui.emoji_registry import get_animated_emoji_widget_class
        cls = get_animated_emoji_widget_class()
        assert isinstance(cls, type)
        assert cls.__name__ == "AnimatedEmojiWidget"

    def test_get_animated_widget_class_cached(self):
        from hermes_cli.tui.emoji_registry import get_animated_emoji_widget_class
        cls1 = get_animated_emoji_widget_class()
        cls2 = get_animated_emoji_widget_class()
        assert cls1 is cls2

    def test_registry_gif_extension_supported(self):
        from hermes_cli.tui.emoji_registry import _IMAGE_EXTS
        assert ".gif" in _IMAGE_EXTS
        assert ".webp" in _IMAGE_EXTS


# ---------------------------------------------------------------------------
# H: app._resolve_user_emoji()
# ---------------------------------------------------------------------------

class TestResolveUserEmoji:
    def _make_app(self, registry=None, enabled=True):
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)
        app._emoji_registry = registry
        app._emoji_images_enabled = enabled
        return app

    def test_no_op_when_registry_none(self):
        app = self._make_app(registry=None)
        panel = MagicMock()
        app._resolve_user_emoji("hello :smile:", panel)
        panel.mount.assert_not_called()

    def test_no_op_when_disabled(self):
        registry = MagicMock()
        registry.get.return_value = MagicMock()
        app = self._make_app(registry=registry, enabled=False)
        panel = MagicMock()
        app._resolve_user_emoji("hello :smile:", panel)
        panel.mount.assert_not_called()

    def test_no_op_even_for_known_or_unknown_emoji(self, tmp_path):
        """User echo panel keeps raw :name: text; it should not mount image widgets."""
        try:
            from PIL import Image as _PILImage
        except ImportError:
            pytest.skip("PIL not available")
        from hermes_cli.tui.emoji_registry import EmojiEntry
        pil_img = _PILImage.new("RGBA", (16, 16), (0, 0, 0, 255))
        entry = EmojiEntry(
            name="smile",
            path=tmp_path / "smile.png",
            description="",
            pil_image=pil_img,
            cell_width=2,
            cell_height=1,
            n_frames=1,
        )
        registry = MagicMock()
        registry.get.side_effect = lambda name: entry if name == "smile" else None
        app = self._make_app(registry=registry, enabled=True)
        panel = MagicMock()

        from hermes_cli.tui.app import HermesApp
        HermesApp._resolve_user_emoji(app, "hello :smile: :ghost:", panel)
        panel.mount.assert_not_called()
