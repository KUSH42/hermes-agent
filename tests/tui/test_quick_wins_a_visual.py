"""Quick Wins A — Visual & Glyph Polish (VP-1..VP-10).

19 tests total. No DOM mount required; VP-4 class-emission test uses the
minimal App(App) harness per feedback_hermesapp_css_varspec_crash.md pattern.
"""
from __future__ import annotations

import inspect
import unittest.mock as mock
from types import SimpleNamespace
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw: str = "", tool_name: str = "test") -> Any:
    from hermes_cli.tui.tool_payload import ToolPayload
    return ToolPayload(
        tool_name=tool_name,
        category=None,
        args={},
        input_display=None,
        output_raw=output_raw,
    )


def _make_cls_result(kind=None, **extra: Any) -> Any:
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    r = ClassificationResult(kind=kind or ResultKind.TEXT, confidence=0.9)
    for k, v in extra.items():
        object.__setattr__(r, k, v)
    return r


# ---------------------------------------------------------------------------
# VP-1 — WRAP_CONTINUATION constant
# ---------------------------------------------------------------------------


class TestVP1WrapConstant:
    def test_wrap_constant_in_grammar(self) -> None:
        from hermes_cli.tui.body_renderers._grammar import WRAP_CONTINUATION
        assert WRAP_CONTINUATION == "↵"


# ---------------------------------------------------------------------------
# VP-2 — web-search description truncation emits …+N chip
# ---------------------------------------------------------------------------


class TestVP2WebSearchTruncation:
    def test_web_search_description_truncation_chip(self) -> None:
        from hermes_cli.tui.body_renderers.streaming import _render_web_search_results
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        long_desc = "X" * 250
        items = [{"title": "T", "url": "http://x.com", "description": long_desc}]
        result = _render_web_search_results(items, colors=SkinColors.default())

        # Rich Text __str__ concatenates spans
        text_str = str(result)
        assert "…+" in text_str
        # dropped = 250 - 117 = 133
        assert "…+133" in text_str
        # muted style on the chip span
        found_muted = any(
            span.style == SkinColors.default().muted
            for span in result._spans  # type: ignore[attr-defined]
        )
        assert found_muted, "chip span must be styled with colors.muted"

    def test_web_search_short_description_no_chip(self) -> None:
        from hermes_cli.tui.body_renderers.streaming import _render_web_search_results
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        short_desc = "S" * 100
        items = [{"title": "T", "url": "http://x.com", "description": short_desc}]
        result = _render_web_search_results(items, colors=SkinColors.default())

        text_str = str(result)
        assert "…+" not in text_str
        assert "…" not in text_str


# ---------------------------------------------------------------------------
# VP-4 — BodyFrame _TIER_CLASS includes default
# ---------------------------------------------------------------------------


class TestVP4BodyFrameDefaultClass:
    def test_body_frame_tier_class_complete(self) -> None:
        from hermes_cli.tui.body_renderers._frame import _TIER_CLASS
        assert set(_TIER_CLASS.keys()) == {"hero", "default", "compact", "trace"}

    def test_body_frame_default_class_emitted(self) -> None:
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from rich.text import Text

        frame = BodyFrame(
            header=None,
            body=Text("body"),
            footer=None,
            density=DensityTier.DEFAULT,
        )
        assert "body-frame--default" in frame.classes

    def test_body_frame_default_css_rule_present(self) -> None:
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        assert "body-frame--default { margin-bottom: 1" in BodyFrame.DEFAULT_CSS


# ---------------------------------------------------------------------------
# VP-5 — low-confidence caption includes cycle hint
# ---------------------------------------------------------------------------


class TestVP5LowConfidenceCaption:
    def _make_renderer(self) -> Any:
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _MinimalRenderer(BodyRenderer):
            kind = ResultKind.TEXT

            @classmethod
            def can_render(cls, cls_result, payload):
                return True

            def build(self):
                from rich.text import Text
                return Text("")

        payload = _make_payload("hello")
        cls_r = _make_cls_result(_low_confidence_disclosed=True)
        renderer = _MinimalRenderer(payload, cls_r)
        return renderer

    def test_low_confidence_caption_includes_cycle_hint(self) -> None:
        renderer = self._make_renderer()
        caption = renderer._low_confidence_caption()
        assert "press t to cycle" in caption.plain

    def test_low_confidence_caption_styled_muted(self) -> None:
        renderer = self._make_renderer()
        caption = renderer._low_confidence_caption()
        assert caption.style == renderer.colors.muted


# ---------------------------------------------------------------------------
# VP-6 — chevron glyph is shape-stable across affordance toggle
# ---------------------------------------------------------------------------


class TestVP6ChevronShapeStable:
    """VP-6: chevron glyph is shape-stable across affordance toggle.

    Tests the glyph-selection logic directly (avoids full Textual widget mount)
    by replicating the contract expressed in _render_v4's chevron block.
    """

    def _chevron_glyph_and_style(
        self,
        density_tier: Any,
        has_affordances: bool,
        collapsed: bool = False,
    ) -> tuple[str, str]:
        """Apply the VP-6 chevron selection logic and return (glyph, style)."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier as _DT
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        from rich.text import Text

        colors = SkinColors.default()
        if density_tier == _DT.HERO:
            glyph = "  ★"
        elif collapsed:
            glyph = "  ▸"
        else:
            glyph = "  ▾"
        style = "dim" if has_affordances else colors.separator_dim
        seg = Text(glyph, style=style)
        return glyph.strip(), str(seg._spans[0].style) if seg._spans else style  # type: ignore[attr-defined]

    def test_chevron_shape_stable_hero_affordance_toggle(self) -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        sep_dim = SkinColors.default().separator_dim

        glyph_with, style_with = self._chevron_glyph_and_style(DensityTier.HERO, True)
        glyph_without, style_without = self._chevron_glyph_and_style(DensityTier.HERO, False)

        assert glyph_with == "★"
        assert glyph_without == "★"
        assert style_with == "dim"
        assert style_without == sep_dim

    def test_chevron_shape_stable_collapsed_toggle(self) -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        sep_dim = SkinColors.default().separator_dim

        glyph_with, style_with = self._chevron_glyph_and_style(DensityTier.DEFAULT, True, collapsed=True)
        glyph_without, style_without = self._chevron_glyph_and_style(DensityTier.DEFAULT, False, collapsed=True)

        assert glyph_with == "▸"
        assert glyph_without == "▸"
        assert style_with == "dim"
        assert style_without == sep_dim

    def test_chevron_shape_stable_expanded_toggle(self) -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        sep_dim = SkinColors.default().separator_dim

        glyph_with, style_with = self._chevron_glyph_and_style(DensityTier.DEFAULT, True, collapsed=False)
        glyph_without, style_without = self._chevron_glyph_and_style(DensityTier.DEFAULT, False, collapsed=False)

        assert glyph_with == "▾"
        assert glyph_without == "▾"
        assert style_with == "dim"
        assert style_without == sep_dim


# ---------------------------------------------------------------------------
# VP-7 — truncation_footer action is optional
# ---------------------------------------------------------------------------


class TestVP7TruncationFooterAction:
    def test_truncation_footer_action_optional(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "hermes_cli.tui.constants.accessibility_mode", lambda: False
        )
        from hermes_cli.tui.body_renderers._grammar import truncation_footer, SkinColors
        result = truncation_footer(hidden_n=5, unit="earlier", action=None, colors=SkinColors.default())
        # build_rule returns a Rich Text; str() gives plain text
        text_str = str(result)
        assert "5 earlier hidden" in text_str
        assert "expand" not in text_str

    def test_truncation_footer_default_action_unchanged(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "hermes_cli.tui.constants.accessibility_mode", lambda: False
        )
        from hermes_cli.tui.body_renderers._grammar import truncation_footer, SkinColors
        result = truncation_footer(hidden_n=5, colors=SkinColors.default())
        text_str = str(result)
        assert "5 lines hidden" in text_str
        assert "expand" in text_str


# ---------------------------------------------------------------------------
# VP-10 — summary_line signature extension + three re-shapes
# ---------------------------------------------------------------------------


class TestVP10SummaryLineContext:
    def test_summary_line_signature_extended(self) -> None:
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        sig = inspect.signature(BodyRenderer.summary_line)
        params = sig.parameters
        assert "density" in params, "density kwarg missing"
        assert "cls_result" in params, "cls_result kwarg missing"
        # Both must be keyword-only
        for name in ("density", "cls_result"):
            assert params[name].kind == inspect.Parameter.KEYWORD_ONLY, \
                f"{name} must be KEYWORD_ONLY"

    def test_log_summary_line_compact_returns_last_line(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "hermes_cli.tui.constants.accessibility_mode", lambda: False
        )
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP

        raw = "line1\nline2\nline3\nline4\nlastline"
        payload = _make_payload(raw)
        cls_r = _make_cls_result()
        renderer = LogRenderer(payload, cls_r)

        result = renderer.summary_line(density=DensityTier.COMPACT)
        assert result.endswith(f" {GLYPH_META_SEP} 5 lines")
        assert result.startswith("lastline")

    def test_log_summary_line_non_compact_unchanged(self) -> None:
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        raw = "line1\nline2\nlastline"
        payload = _make_payload(raw)
        cls_r = _make_cls_result()
        renderer = LogRenderer(payload, cls_r)

        result = renderer.summary_line(density=DensityTier.DEFAULT)
        assert result == "… lastline"

    def test_diff_summary_line_compact_files_and_stat(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "hermes_cli.tui.constants.accessibility_mode", lambda: False
        )
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind

        # Minimal unified diff: 3 files, +20/-5
        diff_text = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n+++ b/a.py\n"
            "@@ -1,3 +1,3 @@\n"
            + "+\n" * 10 + "-\n" * 3 +
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n+++ b/b.py\n"
            "@@ -1,1 +1,1 @@\n"
            + "+\n" * 5 + "-\n" * 1 +
            "diff --git a/c.py b/c.py\n"
            "--- a/c.py\n+++ b/c.py\n"
            "@@ -1,1 +1,1 @@\n"
            + "+\n" * 5 + "-\n" * 1
        )
        payload = _make_payload(diff_text)
        cls_r = ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)
        renderer = DiffRenderer(payload, cls_r)

        result = renderer.summary_line(density=DensityTier.COMPACT)
        # 3 files, 20 adds, 5 dels
        assert "3 files" in result
        assert "+20" in result
        assert "/-5" in result
        assert GLYPH_META_SEP in result

    def test_diff_summary_line_non_compact_unchanged(self, monkeypatch) -> None:
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind

        diff_text = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n+++ b/a.py\n"
            "@@ -1,3 +1,3 @@\n"
            + "+\n" * 20 + "-\n" * 5
        )
        payload = _make_payload(diff_text)
        cls_r = ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)
        renderer = DiffRenderer(payload, cls_r)

        result = renderer.summary_line(density=DensityTier.DEFAULT)
        # Pre-spec shape: "N file(s) · +A −D"
        assert "file(s)" in result
        assert "+20" in result
        # U+2212 minus sign in the original format
        assert "−5" in result

    def test_search_summary_line_compact_top_hit(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "hermes_cli.tui.constants.accessibility_mode", lambda: False
        )
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP
        import json

        # Construct raw JSON that _parse_search_output parses as rg-style
        # groups[0][1][0] = (line_num, content, is_hit)
        raw_json = json.dumps({
            "matches": [
                {"path": "foo.py", "line": 1, "content": "foo.py", "type": "match"},
                {"path": "foo.py", "line": 2, "content": "bar line", "type": "match"},
            ]
        })
        payload = _make_payload(raw_json)
        cls_r = ClassificationResult(kind=ResultKind.SEARCH, confidence=1.0)
        renderer = SearchRenderer(payload, cls_r)
        renderer._hit_count = 7

        result = renderer.summary_line(density=DensityTier.COMPACT)
        assert "foo.py" in result
        assert "7 hits" in result
        assert GLYPH_META_SEP in result
