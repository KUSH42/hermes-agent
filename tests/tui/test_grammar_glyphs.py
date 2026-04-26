"""CU-2 — accessibility glyph fallbacks for gutter glyphs added in GV-1."""
from __future__ import annotations


class TestAsciiGlyphFallback:
    def test_glyph_fallback_focused_gutter(self, monkeypatch):
        from hermes_cli.tui.body_renderers._grammar import glyph, GLYPH_GUTTER_FOCUSED
        monkeypatch.setattr("hermes_cli.tui.constants.accessibility_mode", lambda: True)
        assert glyph(GLYPH_GUTTER_FOCUSED) == "|"

    def test_glyph_fallback_group_gutter(self, monkeypatch):
        from hermes_cli.tui.body_renderers._grammar import glyph, GLYPH_GUTTER_GROUP
        monkeypatch.setattr("hermes_cli.tui.constants.accessibility_mode", lambda: True)
        assert glyph(GLYPH_GUTTER_GROUP) == ":"

    def test_glyph_fallback_child_diff_gutter(self, monkeypatch):
        from hermes_cli.tui.body_renderers._grammar import glyph, GLYPH_GUTTER_CHILD_DIFF
        monkeypatch.setattr("hermes_cli.tui.constants.accessibility_mode", lambda: True)
        assert glyph(GLYPH_GUTTER_CHILD_DIFF) == "\\-"

    def test_glyph_unchanged_when_accessibility_off(self, monkeypatch):
        from hermes_cli.tui.body_renderers._grammar import glyph, GLYPH_GUTTER_FOCUSED
        monkeypatch.setattr("hermes_cli.tui.constants.accessibility_mode", lambda: False)
        assert glyph(GLYPH_GUTTER_FOCUSED) == GLYPH_GUTTER_FOCUSED
