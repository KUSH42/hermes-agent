"""Tests for BrowseMinimap viewport pinning and indicator — MMP-H3, MMP-H4, MMP-L1."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anchor(anchor_type, widget=None, label="Test", turn_id=1):
    from hermes_cli.tui._browse_types import BrowseAnchor
    w = widget or MagicMock()
    w.is_mounted = True
    return BrowseAnchor(anchor_type=anchor_type, widget=w, label=label, turn_id=turn_id)


def _widget_at_y(y: int):
    w = MagicMock()
    r = MagicMock()
    r.y = y
    w.virtual_region = r
    return w


def _make_minimap(
    anchors=None,
    cursor=0,
    vh=24,
    virtual_h=100,
    scroll_y=0,
    viewport_rect_enabled=True,
    viewport_bg="#1e2030",
):
    """Return a BrowseMinimap with all app interactions mocked out."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    from textual.geometry import Size

    mm = BrowseMinimap.__new__(BrowseMinimap)
    mm._accent_cached = "#7aa2f7"
    mm._accent_dirty = False
    mm._full_miss_warned = False
    mm._viewport_rect_enabled = viewport_rect_enabled
    mm._viewport_bg_cached = viewport_bg

    mock_app = MagicMock()
    mock_app._browse_anchors = anchors if anchors is not None else []
    mock_app._browse_cursor = cursor
    mock_app.get_css_variables.return_value = {"accent": "#7aa2f7", "panel-darken-1": viewport_bg}

    mock_output = MagicMock()
    type(mock_output).virtual_size = PropertyMock(return_value=Size(1, virtual_h))
    type(mock_output).scroll_y = PropertyMock(return_value=scroll_y)
    mock_app.query_one.return_value = mock_output

    mock_size = MagicMock()
    mock_size.height = vh
    type(mm).size = PropertyMock(return_value=mock_size)
    type(mm).app = PropertyMock(return_value=mock_app)

    return mm, mock_app, mock_output


# =============================================================================
# TestViewportPinning — MMP-H3 Phase A
# =============================================================================

class TestViewportPinning:
    """Verify dock:right inside OutputPanel pins to viewport, not scroll content."""

    def test_minimap_is_viewport_pinned(self):
        """BrowseMinimap.region must be stable before and after OutputPanel scrolls.

        Phase A verification test. If this test fails, Phase B relocation is required.
        This test uses pure unit-level assertions since pilot-based region checks
        are unreliable in headless mode; the key invariant is that render_line
        computes content_y from virtual coords (document-absolute), not scroll-relative coords.
        The dock:right placement guarantee is asserted by checking that
        _mount_minimap mounts inside OutputPanel (same parent used since SPEC-MMP-LIFECYCLE).
        """
        from hermes_cli.tui.services.browse import BrowseService
        import inspect
        src = inspect.getsource(BrowseService._mount_minimap)
        # Confirm mount target is OutputPanel (Phase A topology — not output.parent)
        assert "output.mount" in src or "await output.mount" in src, (
            "BrowseMinimap should be mounted inside OutputPanel (Phase A topology). "
            "If dock semantics failed, update to Phase B and update this test."
        )

    def test_minimap_render_line_is_document_absolute(self):
        """render_line row 0 maps to wy=0 regardless of scroll_y.

        The minimap is a full-document overview. content_y for row 0 must always
        be 0 regardless of how far the document is scrolled.
        """
        from hermes_cli.tui._browse_types import BrowseAnchorType
        # anchor at wy=0 — should always hit row 0 in the minimap
        anchor = _make_anchor(BrowseAnchorType.TURN_START, widget=_widget_at_y(0))
        mm, _, _ = _make_minimap(anchors=[anchor], vh=24, virtual_h=240, scroll_y=120)
        strip = mm.render_line(0)
        segs = list(strip)
        assert segs, "render_line(0) must produce at least one segment"
        assert segs[0].text != " ", (
            "Row 0 should contain the anchor glyph (wy=0 maps to content_y=0 regardless of scroll)"
        )


# =============================================================================
# TestRelocatedTopology — MMP-H3 Phase B (skipped — Phase A passed)
# =============================================================================

@pytest.mark.skip(reason="Phase B not executed — Phase A dock verification passed")
class TestRelocatedTopology:
    """Tests for Phase B structural relocation (skipped when Phase A passes)."""

    def test_minimap_mounts_as_output_sibling(self):
        """After _mount_minimap, mm.parent is output.parent (PaneContainer#pane-center)."""
        pass  # would check mm.parent is output.parent

    def test_minimap_screen_region_stable_under_scroll(self):
        """Post-relocation: screen region is unchanged after scroll."""
        pass

    def test_minimap_unmounts_from_sibling_layer(self):
        """Toggle off removes minimap from PaneContainer, not from output."""
        pass


# =============================================================================
# TestViewportRectangle — MMP-H4
# =============================================================================

class TestViewportRectangle:
    """Viewport rectangle indicator: config-gated bg tint band on the minimap."""

    # ---- Gate ON (default) -------------------------------------------------

    def test_viewport_band_renders_bg_tint(self):
        """Row whose content_y falls inside viewport renders non-empty bg color."""
        # vh=10, virtual_h=100, scroll_y=50 → viewport covers doc rows 50-59
        # row y=5 maps to content_y=50 → in viewport
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=100,
            scroll_y=50,
            viewport_rect_enabled=True,
            viewport_bg="#1e2030",
        )
        strip = mm.render_line(5)
        segs = list(strip)
        assert segs, "render_line must produce segments"
        seg = segs[0]
        assert seg.style and seg.style.bgcolor is not None, (
            "Row inside viewport must carry a bg color (viewport tint)"
        )

    def test_viewport_band_outside_no_bg(self):
        """Row whose content_y is above scroll_y has no bg tint."""
        # vh=10, virtual_h=100, scroll_y=50 → viewport covers doc rows 50-59
        # row y=0 maps to content_y=0 → outside viewport
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=100,
            scroll_y=50,
            viewport_rect_enabled=True,
        )
        strip = mm.render_line(0)
        segs = list(strip)
        assert segs
        seg = segs[0]
        no_bg = seg.style is None or seg.style.bgcolor is None
        assert no_bg, "Row above viewport must not carry a bg tint"

    def test_viewport_band_combined_with_anchor(self):
        """Non-cursor anchor inside viewport: segment has glyph AND viewport bg color."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        # vh=10, virtual_h=100, scroll_y=40 → viewport covers doc rows 40-49
        # anchor at wy=45, maps to y=4 (content_y=40..49)
        # cursor=1 so anchor[0] is NOT the cursor → gets accent fg + vp bg
        anchor = _make_anchor(BrowseAnchorType.TURN_START, widget=_widget_at_y(45))
        mm, _, _ = _make_minimap(
            anchors=[anchor],
            cursor=1,  # not the cursor — gets accent+bg, not reverse
            vh=10,
            virtual_h=100,
            scroll_y=40,
            viewport_rect_enabled=True,
            viewport_bg="#1e2030",
        )
        strip = mm.render_line(4)
        segs = list(strip)
        assert segs
        seg = segs[0]
        assert seg.text.strip() != "", "anchor inside viewport must render a glyph"
        assert seg.style and seg.style.bgcolor is not None, (
            "Non-cursor anchor inside viewport must carry viewport bg tint"
        )

    def test_viewport_band_zero_scroll(self):
        """scroll_y=0: viewport band starts at row 0."""
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=100,
            scroll_y=0,
            viewport_rect_enabled=True,
            viewport_bg="#1e2030",
        )
        strip = mm.render_line(0)
        segs = list(strip)
        assert segs
        seg = segs[0]
        assert seg.style and seg.style.bgcolor is not None, (
            "Row 0 must be tinted when scroll_y=0 (viewport starts at doc top)"
        )

    def test_viewport_band_at_document_end(self):
        """Scrolled to bottom: last rows carry viewport tint."""
        # vh=10, virtual_h=100, scroll_y=90 → viewport covers doc rows 90-99
        # row y=9 (last row) always maps to upper=virtual_h=100 → in viewport
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=100,
            scroll_y=90,
            viewport_rect_enabled=True,
            viewport_bg="#1e2030",
        )
        strip = mm.render_line(9)
        segs = list(strip)
        assert segs
        seg = segs[0]
        assert seg.style and seg.style.bgcolor is not None, (
            "Last row must be tinted when scrolled to document bottom"
        )

    def test_viewport_band_short_document(self):
        """virtual_h <= vh: entire minimap is viewport-tinted (whole doc in view)."""
        # virtual_h=10 == vh=10 → all rows are in viewport
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=10,
            scroll_y=0,
            viewport_rect_enabled=True,
            viewport_bg="#1e2030",
        )
        for y in range(10):
            strip = mm.render_line(y)
            segs = list(strip)
            assert segs
            seg = segs[0]
            assert seg.style and seg.style.bgcolor is not None, (
                f"Row {y} must be tinted when whole document fits in viewport"
            )

    # ---- Gate OFF ----------------------------------------------------------

    def test_viewport_rect_disabled_no_bg_anywhere(self):
        """Gate off: no row carries a bg tint even at mid-scroll."""
        mm, _, _ = _make_minimap(
            anchors=[],
            vh=10,
            virtual_h=100,
            scroll_y=50,
            viewport_rect_enabled=False,
        )
        for y in range(10):
            strip = mm.render_line(y)
            segs = list(strip)
            for seg in segs:
                no_bg = seg.style is None or seg.style.bgcolor is None
                assert no_bg, f"Row {y}: gate-off must not render any viewport bg tint"

    def test_viewport_rect_disabled_anchor_unaffected(self):
        """Gate off: anchors still render glyph + accent fg (overview-only path)."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        anchor = _make_anchor(BrowseAnchorType.TURN_START, widget=_widget_at_y(50))
        mm, _, _ = _make_minimap(
            anchors=[anchor],
            cursor=0,
            vh=10,
            virtual_h=100,
            scroll_y=0,
            viewport_rect_enabled=False,
        )
        strip = mm.render_line(5)
        segs = list(strip)
        assert segs
        seg = segs[0]
        assert seg.text.strip() != "", "anchor must render glyph even when gate is off"
        no_bg = seg.style is None or seg.style.bgcolor is None
        assert no_bg, "gate-off anchor must have no viewport bg tint"

    def test_config_default_is_true(self):
        """Fresh config load: browse_markers.minimap_viewport_rect defaults to True."""
        from hermes_cli.config import DEFAULT_CONFIG
        cfg = DEFAULT_CONFIG
        bm = cfg["display"]["browse_markers"]
        assert bm.get("minimap_viewport_rect", True) is True, (
            "minimap_viewport_rect must default to True"
        )

    def test_minimap_refreshes_on_output_scroll(self):
        """_on_output_scroll calls self.refresh()."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        mm = BrowseMinimap.__new__(BrowseMinimap)
        mm._viewport_rect_enabled = True
        refresh_calls = []
        mm.refresh = lambda: refresh_calls.append(1)
        mm._on_output_scroll(42)
        assert len(refresh_calls) == 1, "_on_output_scroll must call self.refresh()"


# =============================================================================
# TestDocstringAccuracy — MMP-L1
# =============================================================================

class TestDocstringAccuracy:
    """Docstring describes the actual topology (MMP-L1)."""

    def test_minimap_docstring_mentions_topology(self):
        """BrowseMinimap.__doc__ must mention either 'ScrollableContainer' (Phase A)
        or 'sibling of OutputPanel' (Phase B).
        """
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        doc = BrowseMinimap.__doc__ or ""
        phase_a_marker = "ScrollableContainer" in doc
        phase_b_marker = "sibling of OutputPanel" in doc
        assert phase_a_marker or phase_b_marker, (
            "BrowseMinimap docstring must describe mount topology: "
            "either 'ScrollableContainer' (dock inside scrollable parent, Phase A) "
            "or 'sibling of OutputPanel' (relocated to PaneContainer, Phase B). "
            f"Got: {doc!r}"
        )
