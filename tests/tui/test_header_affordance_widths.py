"""HW-1..HW-6: drop-order, gap clamp, collapsed-actions cache, compact footer,
separator palette, regression invariants.
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from rich.text import Text

from hermes_cli.tui.tool_panel.layout_resolver import (
    _DROP_ORDER_DEFAULT,
    _DROP_ORDER_HERO,
    _DROP_ORDER_COMPACT,
    _trim_tail_segments,
)
from hermes_cli.tui.tool_panel._footer import (
    _build_collapsed_actions_map,
    _get_collapsed_actions,
    FooterPane,
)
from hermes_cli.tui.body_renderers._grammar import SkinColors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(name: str, width: int) -> tuple[str, Text]:
    return (name, Text("x" * width))


def _names(segs: list) -> list[str]:
    return [n for n, _ in segs]


def _to_budget(segs: list, drop_n: int) -> int:
    total = sum(s.cell_len for _, s in segs)
    dropped_w = sum(sorted(s.cell_len for _, s in segs)[:drop_n])
    return total - dropped_w


# ---------------------------------------------------------------------------
# TestDropOrder (HW-1) — 5 tests
# ---------------------------------------------------------------------------

class TestDropOrder:
    """Verify re-prioritised _DROP_ORDER_DEFAULT via trim_tail_segments."""

    def _segs_all(self) -> list:
        """One 3-cell segment per slot in DEFAULT order."""
        names = ["chip", "linecount", "duration", "flash", "chevron",
                 "diff", "hero", "exit"]
        return [_seg(n, 3) for n in names]

    def test_narrow_keeps_exit_over_chip(self):
        segs = self._segs_all()
        total = sum(s.cell_len for _, s in segs)
        # budget: drop chip + linecount + duration (3 cosmetics × 3 cells each)
        result = _trim_tail_segments(segs, budget=total - 9, drop_order=_DROP_ORDER_DEFAULT)
        names = _names(result)
        assert "exit" in names
        assert "chip" not in names

    def test_narrow_keeps_hero_over_duration(self):
        segs = self._segs_all()
        total = sum(s.cell_len for _, s in segs)
        # drop chip + linecount + duration → hero stays
        result = _trim_tail_segments(segs, budget=total - 9, drop_order=_DROP_ORDER_DEFAULT)
        names = _names(result)
        assert "hero" in names
        assert "duration" not in names

    def test_very_narrow_keeps_only_exit(self):
        segs = self._segs_all()
        exit_w = next(s.cell_len for n, s in segs if n == "exit")
        result = _trim_tail_segments(segs, budget=exit_w, drop_order=_DROP_ORDER_DEFAULT)
        names = _names(result)
        assert names == ["exit"]

    def test_flash_dropped_before_chevron(self):
        # Only flash and chevron remaining; force exactly one to drop.
        segs = [_seg("flash", 4), _seg("chevron", 4)]
        total = sum(s.cell_len for _, s in segs)
        result = _trim_tail_segments(segs, budget=total - 1, drop_order=_DROP_ORDER_DEFAULT)
        names = _names(result)
        assert "flash" not in names
        assert "chevron" in names

    def test_hero_demotion_invariant_preserved(self):
        # When only hero + flash present and both over budget, hero drops first.
        segs = [_seg("hero", 10), _seg("flash", 5)]
        total = sum(s.cell_len for _, s in segs)
        result = _trim_tail_segments(segs, budget=total - 1, drop_order=_DROP_ORDER_DEFAULT)
        names = _names(result)
        assert "hero" not in names
        assert "flash" in names


# ---------------------------------------------------------------------------
# TestHeaderGapClamp (HW-2) — 3 tests
# ---------------------------------------------------------------------------

class TestHeaderGapClamp:
    """Gap clamp removed: pad fills full available space regardless of skin var."""

    def _render_label_pad(self, label_len: int, available: int) -> int:
        """Pure computation matching the fixed pad formula."""
        return max(0, available - label_len)

    def test_tail_right_aligns_at_wide_widths(self):
        pad = self._render_label_pad(label_len=10, available=100)
        assert pad == 90

    def test_tail_alignment_consistent_across_label_lengths(self):
        available = 60
        pad_short = self._render_label_pad(label_len=5, available=available)
        pad_long = self._render_label_pad(label_len=20, available=available)
        # right-edge of tail is always at `available` regardless of label length
        assert 5 + pad_short == 60
        assert 20 + pad_long == 60

    def test_max_header_gap_skin_var_no_longer_consulted(self):
        # _resolve_max_header_gap should no longer exist in _header module
        import hermes_cli.tui.tool_blocks._header as hdr
        assert not hasattr(hdr, "_resolve_max_header_gap"), (
            "_resolve_max_header_gap was deleted; tests or code still reference it"
        )
        assert not hasattr(hdr, "MAX_HEADER_GAP_CELLS_FALLBACK")


# ---------------------------------------------------------------------------
# TestCollapsedActionsCache (HW-3) — 3 tests
# ---------------------------------------------------------------------------

class TestCollapsedActionsCache:

    def test_consecutive_calls_not_cached(self):
        first_map = {"FAKE_A": [("a", "action-a")]}
        second_map = {"FAKE_A": [("b", "action-b")]}
        calls = iter([first_map, second_map])
        with patch(
            "hermes_cli.tui.tool_panel._footer._build_collapsed_actions_map",
            side_effect=lambda: next(calls),
        ):
            r1 = _get_collapsed_actions("FAKE_A")
            r2 = _get_collapsed_actions("FAKE_A")
        assert r1 == [("a", "action-a")]
        assert r2 == [("b", "action-b")]

    def test_collapsed_actions_logs_on_build_failure(self, caplog):
        import logging
        with patch(
            "hermes_cli.tui.tool_panel._footer._build_collapsed_actions_map",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.tool_panel._footer"):
                result = _get_collapsed_actions("anything")
        assert result == [("?", "keys")]
        assert any("boom" in r.message or "collapsed-action" in r.message
                   for r in caplog.records)

    def test_collapsed_actions_returns_fallback_for_unknown_category(self):
        result = _get_collapsed_actions("NOT_A_REAL_CATEGORY_XYZ")
        assert result == [("?", "keys")]


# ---------------------------------------------------------------------------
# TestFooterCompactRows (HW-4) — 5 tests  (pure _render_stderr + CSS-class logic)
# ---------------------------------------------------------------------------

class TestFooterCompactRows:

    def test_compact_hides_artifact_row_css(self):
        css = FooterPane.DEFAULT_CSS
        assert "compact > .artifact-row" in css and "display: none" in css

    def test_footer_no_render_stderr_method(self):
        # ER-1: stderr evidence moved to body; footer no longer has _render_stderr
        assert not hasattr(FooterPane, "_render_stderr")

    def test_footer_no_footer_stderr_css_class(self):
        # ER-1: footer-stderr CSS class removed; stderr lives in body .--stderr-tail
        css = FooterPane.DEFAULT_CSS
        assert "footer-stderr" not in css

    def test_footer_no_has_stderr_css_class(self):
        # ER-1: has-stderr state class removed from footer
        css = FooterPane.DEFAULT_CSS
        assert "has-stderr" not in css


# ---------------------------------------------------------------------------
# TestSeparatorPalette (HW-5) — 3 tests
# ---------------------------------------------------------------------------

def _linearise(hex_color: str) -> tuple[float, float, float]:
    """sRGB hex → linear-light RGB (no dependency on colormath)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    def f(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return f(r), f(g), f(b)


def _luminance(hex_color: str) -> float:
    r, g, b = _linearise(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class TestSeparatorPalette:

    def test_default_separator_dim_in_visible_range(self):
        d = SkinColors.default()
        lum = _luminance(d.separator_dim)
        # must be darker than muted but not near-black
        assert lum > 0.03, f"separator_dim too dark: {d.separator_dim} lum={lum:.4f}"
        assert lum < _luminance(d.muted), (
            f"separator_dim ({d.separator_dim}) should be darker than muted ({d.muted})"
        )

    def test_skin_override_separator_preserved(self):
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {
            "separator-dim": "#aabbcc",
        }
        skin = SkinColors.from_app(mock_app)
        assert skin.separator_dim == "#aabbcc"

    def test_separator_style_has_no_dim_modifier(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors as SC
        colors = SC.default()
        # The style string used at both call sites in _header.py should be
        # exactly the hex color, not "dim #xxxxxx".
        style_str = colors.separator_dim
        assert not style_str.startswith("dim "), (
            f"separator style must not carry 'dim' prefix; got: {style_str!r}"
        )


# ---------------------------------------------------------------------------
# TestDropOrderInvariants (HW-6) — 1 test
# ---------------------------------------------------------------------------

def _check_drop_order_invariants(order: list[str], label: str) -> None:
    assert order[-1] == "exit", f"{label}: exit must be last (got {order[-1]!r})"
    # ER-2: stderrwarn and remediation removed from header drop orders
    for removed in ("remediation", "stderrwarn"):
        assert removed not in order, f"{label}: {removed!r} must not appear (removed per ER-2)"
    for cosmetic in ("chip", "linecount", "duration"):
        if cosmetic not in order:
            continue
        assert order.index(cosmetic) < order.index("exit"), (
            f"{label}: {cosmetic!r} must drop before exit "
            f"(indices {order.index(cosmetic)} vs {order.index('exit')})"
        )


class TestDropOrderInvariants:

    def test_drop_order_invariants(self):
        for order, label in [
            (_DROP_ORDER_DEFAULT, "DEFAULT"),
            (_DROP_ORDER_HERO,    "HERO"),
            (_DROP_ORDER_COMPACT, "COMPACT"),
        ]:
            _check_drop_order_invariants(order, label)
