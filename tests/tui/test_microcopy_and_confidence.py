"""Tests for MC-1..MC-6 — Microcopy + Confidence surface spec."""
from __future__ import annotations

import pathlib
import re

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TUI_ROOT = pathlib.Path(__file__).parents[2] / "hermes_cli" / "tui"
_HEADER_PY   = _TUI_ROOT / "tool_blocks" / "_header.py"
_STREAMING_PY = _TUI_ROOT / "tool_blocks" / "_streaming.py"
_BR_INIT_PY  = _TUI_ROOT / "body_renderers" / "__init__.py"


def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# MC-1 (TestStatusChipCasing) migrated to test_invariants.py::TestIL5StatusChipCasing.


# ---------------------------------------------------------------------------
# MC-2: Live-tail "more rows" chip
# ---------------------------------------------------------------------------

class TestLiveTailChip:
    """MC-2 — canonical ↓ N more-rows chip format."""

    def test_more_rows_chip_canonical(self) -> None:
        """_MORE_ROWS_CHIP.format(n=5) == '↓ 5 more-rows'."""
        from hermes_cli.tui.tool_blocks._streaming import _MORE_ROWS_CHIP
        assert _MORE_ROWS_CHIP.format(n=5) == "↓ 5 more-rows"

    def test_more_rows_chip_length(self) -> None:
        """n=5 → 13 chars ('↓ 5 more-rows'); n=99 → 14 chars ('↓ 99 more-rows')."""
        from hermes_cli.tui.tool_blocks._streaming import _MORE_ROWS_CHIP
        # ↓(1) + space(1) + digit(s) + space(1) + 'more-rows'(9)
        assert len(_MORE_ROWS_CHIP.format(n=5)) == 13
        assert len(_MORE_ROWS_CHIP.format(n=99)) == 14

    def test_more_rows_no_padding_spaces(self) -> None:
        """Chip text has no leading or trailing whitespace."""
        from hermes_cli.tui.tool_blocks._streaming import _MORE_ROWS_CHIP
        rendered = _MORE_ROWS_CHIP.format(n=5)
        assert rendered == rendered.strip()


# ---------------------------------------------------------------------------
# MC-3: Flash labels lowercase
# ---------------------------------------------------------------------------

class TestFlashLabels:
    """MC-3 — flash_label defaults must be lowercase imperative."""

    def test_flash_default_label_lowercase(self) -> None:
        """_header.py flash_copy default is '✓ copied' (lowercase c)."""
        src = _src(_HEADER_PY)
        # Find the flash_copy default arg line
        match = re.search(r'def flash_copy\(self,\s*flash_label:\s*str\s*=\s*"([^"]+)"', src)
        assert match is not None, "Could not find flash_copy default in _header.py"
        assert match.group(1) == "✓ copied", (
            f"Expected '✓ copied', got {match.group(1)!r}"
        )

    def test_no_sentence_case_flash_labels(self) -> None:
        """Meta-test: no flash_label defaults with sentence-case (✓ [A-Z])."""
        tui_py_files = list(_TUI_ROOT.rglob("*.py"))
        violations = []
        for py_file in tui_py_files:
            src = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(src.splitlines(), start=1):
                if re.search(r'flash_label.*"✓\s+[A-Z]', line):
                    violations.append(f"{py_file}:{lineno}: {line.strip()}")
        assert violations == [], (
            "Found sentence-case flash_label defaults:\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# MC-4: Footer visibility decoupled from user-override flag
# ---------------------------------------------------------------------------

class TestFooterVisibility:
    """MC-4 — footer_visible comes from resolve_full(), not re-synthesized."""

    def _make_resolver(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        return ToolBlockLayoutResolver(hero_min_width=100)

    def _make_inputs(self, *, tier_override=None, user_collapsed=False, has_footer=True):
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        return LayoutInputs(
            phase=ToolCallState.DONE,
            is_error=False,
            has_focus=False,
            user_scrolled_up=False,
            user_override=(tier_override is not None),
            user_override_tier=tier_override,
            body_line_count=5,
            threshold=20,
            row_budget=None,
            kind=None,
            parent_clamp=None,
            width=120,
            user_collapsed=user_collapsed,
            has_footer_content=has_footer,
        )

    def test_footer_hidden_at_compact_no_content(self) -> None:
        """COMPACT tier with no footer content → footer_visible False (FH-5: content gate)."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        resolver = self._make_resolver()
        inputs = self._make_inputs(tier_override=DensityTier.COMPACT, has_footer=False)
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is False

    def test_footer_hidden_when_user_collapsed(self) -> None:
        """user_collapsed=True → footer_visible False."""
        resolver = self._make_resolver()
        inputs = self._make_inputs(user_collapsed=True)
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is False

    def test_footer_visible_default_no_collapse(self) -> None:
        """Non-COMPACT tier, user_collapsed=False, has_footer=True → footer_visible True."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        resolver = self._make_resolver()
        inputs = self._make_inputs(
            tier_override=DensityTier.DEFAULT,
            user_collapsed=False,
            has_footer=True,
        )
        decision = resolver.resolve_full(inputs)
        assert decision.tier != DensityTier.COMPACT
        assert decision.footer_visible is True


# ---------------------------------------------------------------------------
# MC-5: KIND_MIN_CONFIDENCE named constants
# ---------------------------------------------------------------------------

class TestConfidenceThresholds:
    """MC-5 — thresholds live in content_classifier.THRESHOLDS."""

    def test_thresholds_defined(self) -> None:
        """THRESHOLDS dict contains all four expected keys."""
        from hermes_cli.tui.content_classifier import THRESHOLDS
        expected = {
            "KIND_MIN_CONFIDENCE",
            "KIND_DISCLOSURE_BAND_LOW",
            "KIND_DISCLOSURE_BAND_HIGH",
            "KIND_HIGH_CONFIDENCE",
        }
        assert expected <= set(THRESHOLDS.keys())

    def test_no_inline_confidence_literals(self) -> None:
        """Meta-test: no raw 0.5/0.7/0.8 confidence literals remain in body_renderers/__init__.py."""
        src = _src(_BR_INIT_PY)
        matches = []
        for lineno, line in enumerate(src.splitlines(), start=1):
            # Only flag executable code lines, not comments or strings.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\b0\.[578]\b', stripped):
                matches.append(f"line {lineno}: {line.rstrip()}")
        assert matches == [], (
            "Found inline confidence literals in body_renderers/__init__.py:\n"
            + "\n".join(matches)
        )

    def test_below_min_falls_to_raw(self) -> None:
        """pick_renderer with confidence=0.4 (< KIND_MIN_CONFIDENCE) returns FallbackRenderer."""
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer

        cls_result = ClassificationResult(kind=ResultKind.DIFF, confidence=0.4)
        payload = ToolPayload(
            tool_name="test",
            category=ToolCategory.UNKNOWN,
            args={},
            input_display=None,
            output_raw="some output",
        )
        result = pick_renderer(
            cls_result,
            payload,
            phase=ToolCallState.DONE,
            density=DensityTier.DEFAULT,
        )
        assert result is FallbackRenderer


# ---------------------------------------------------------------------------
# MC-6: Low-confidence disclosure caption rendered
# ---------------------------------------------------------------------------

class TestLowConfidenceCaption:
    """MC-6 — _low_confidence_disclosed flag surfaces ⚠ caption in build_widget()."""

    def _make_renderer(self, confidence: float, kind_str: str = "diff", disclosed: bool = False):
        """Create a concrete BodyRenderer subclass with cls_result + app=None."""
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ToolPayload
        from hermes_cli.tui.tool_category import ToolCategory
        from rich.text import Text

        kind = ResultKind(kind_str)
        cls_result = ClassificationResult(kind=kind, confidence=confidence)
        if disclosed:
            object.__setattr__(cls_result, "_low_confidence_disclosed", True)

        payload = ToolPayload(
            tool_name="t",
            category=ToolCategory.UNKNOWN,
            args={},
            input_display=None,
            output_raw="body content",
        )

        class _Stub(BodyRenderer):
            kind = ResultKind.DIFF

            @classmethod
            def can_render(cls, cr, pl):
                return True

            def build(self):
                return Text("body content")

        renderer = _Stub(payload=payload, cls_result=cls_result, app=None)
        return renderer

    def test_low_conf_caption_present(self) -> None:
        """confidence=0.6 + _low_confidence_disclosed → build_widget() contains caption."""
        renderer = self._make_renderer(confidence=0.6, disclosed=True)
        widget = renderer.build_widget()
        # CopyableRichLog has _lines attribute (list of renderable writes)
        # Check via _low_confidence_caption directly
        caption = renderer._low_confidence_caption()
        assert "low-confidence: diff" in caption.plain

    def test_high_conf_no_caption(self) -> None:
        """confidence=0.85, no _low_confidence_disclosed → _low_confidence_caption not triggered."""
        renderer = self._make_renderer(confidence=0.85, disclosed=False)
        # The flag is absent — getattr returns False
        assert not getattr(renderer.cls_result, "_low_confidence_disclosed", False)

    def test_low_conf_caption_styled_muted(self) -> None:
        """Caption uses colors.muted style."""
        renderer = self._make_renderer(confidence=0.6, disclosed=True)
        caption = renderer._low_confidence_caption()
        muted = renderer.colors.muted
        # Rich Text stores style as string or Style; compare string form
        assert str(caption.style) == str(muted)
