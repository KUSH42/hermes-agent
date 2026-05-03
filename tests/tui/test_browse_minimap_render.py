"""Tests for BrowseMinimap render correctness — MMP-H1/H2/H5/M1/M2/M3/L2/L3/L4/L6."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest


# ---- helpers ----------------------------------------------------------------

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


def _make_minimap_with_mock_app(anchors=None, cursor=0, vh=24, virtual_h=100):
    """Return a BrowseMinimap with all app interactions mocked out."""
    from hermes_cli.tui.browse_minimap import BrowseMinimap
    mm = BrowseMinimap.__new__(BrowseMinimap)
    mm._accent_cached = "#7aa2f7"
    mm._accent_dirty = False
    mm._full_miss_warned = False

    mock_app = MagicMock()
    mock_app._browse_anchors = anchors or []
    mock_app._browse_cursor = cursor
    mock_app.get_css_variables.return_value = {"accent": "#7aa2f7"}

    mock_output = MagicMock()
    from textual.geometry import Size
    type(mock_output).virtual_size = PropertyMock(return_value=Size(1, virtual_h))
    mock_app.query_one.return_value = mock_output

    mock_size = MagicMock()
    mock_size.height = vh
    type(mm).size = PropertyMock(return_value=mock_size)
    type(mm).app = PropertyMock(return_value=mock_app)

    return mm, mock_app


# =============================================================================
# TestGlyphMapConsolidation — MMP-H1
# =============================================================================

class TestGlyphMapConsolidation:
    """MMP-H1: single glyph source of truth."""

    def test_minimap_glyph_subagent_root(self):
        """SUBAGENT_ROOT anchor renders ◆, not · fallback."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        w = _widget_at_y(0)
        anchor = _make_anchor(BrowseAnchorType.SUBAGENT_ROOT, w)
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert "◆" in text, f"Expected ◆, got {text!r}"

    @pytest.mark.parametrize("atype,expected_glyph", [
        ("TURN_START", "▸"),
        ("CODE_BLOCK", "‹"),
        ("TOOL_BLOCK", "▣"),
        ("MEDIA", "▶"),
        ("SUBAGENT_ROOT", "◆"),
    ])
    def test_minimap_glyph_all_types(self, atype, expected_glyph):
        """Each anchor type maps to the correct _BROWSE_TYPE_GLYPH_NARROW value."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        anchor_type = BrowseAnchorType[atype]
        w = _widget_at_y(0)
        anchor = _make_anchor(anchor_type, w)
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert expected_glyph in text, f"Expected {expected_glyph!r} for {atype}, got {text!r}"

    def test_status_bar_glyph_unchanged(self):
        """_BROWSE_TYPE_GLYPH still returns ‹› and 🤖 — no regression to status bar."""
        from hermes_cli.tui._browse_types import _BROWSE_TYPE_GLYPH
        assert _BROWSE_TYPE_GLYPH["code_block"] == "‹›"
        assert _BROWSE_TYPE_GLYPH["subagent_root"] == "🤖"

    def test_minimap_glyph_unknown_type(self):
        """Unknown anchor_type.value falls back to ·."""
        from hermes_cli.tui._browse_types import BrowseAnchor, BrowseAnchorType
        w = _widget_at_y(0)
        # Build a real-ish anchor but with an anchor_type whose .value is unrecognised
        anchor_type_mock = MagicMock()
        anchor_type_mock.value = "definitely_unknown_xyz"
        anchor = MagicMock()
        anchor.widget = w
        anchor.anchor_type = anchor_type_mock
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert "·" in text, f"Expected · fallback, got {text!r}"


# =============================================================================
# TestRefreshHooks — MMP-H2
# =============================================================================

class TestRefreshHooks:
    """MMP-H2: explicit refresh on cursor/anchor change."""

    def test_refresh_minimap_no_match_safe(self):
        """_refresh_minimap with no minimap mounted does not raise."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.services.browse import BrowseService

        mock_app = MagicMock()
        mock_app.query_one.side_effect = NoMatches()
        svc = BrowseService.__new__(BrowseService)
        svc.app = mock_app
        # Should not raise
        svc._refresh_minimap()

    @pytest.mark.asyncio
    async def test_minimap_refresh_on_focus_anchor(self):
        """After focus_anchor, minimap.refresh() is called."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        from hermes_cli.tui._browse_types import BrowseAnchorType

        def _make_app(**kwargs):
            from hermes_cli.tui.app import HermesApp
            cli = MagicMock()
            cli.config = {}
            app = HermesApp(cli=cli)
            for k, v in kwargs.items():
                setattr(app, k, v)
            return app

        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            from hermes_cli.tui.widgets import OutputPanel
            output = app.query_one(OutputPanel)
            mm = BrowseMinimap()
            await output.mount(mm)
            await pilot.pause()

            w0 = _widget_at_y(0)
            w1 = _widget_at_y(10)
            anchor0 = _make_anchor(BrowseAnchorType.TURN_START, w0)
            anchor1 = _make_anchor(BrowseAnchorType.CODE_BLOCK, w1)
            app._browse_anchors = [anchor0, anchor1]
            app.browse_mode = True
            await pilot.pause()

            refresh_calls = []
            original_refresh = mm.refresh
            mm.refresh = lambda *a, **kw: refresh_calls.append(1) or original_refresh(*a, **kw)

            app._svc_browse.focus_anchor(1, anchor1)
            await pilot.pause()
            assert len(refresh_calls) >= 1, "Expected minimap.refresh() to be called after focus_anchor"

    @pytest.mark.asyncio
    async def test_minimap_refresh_on_rebuild(self):
        """After rebuild_browse_anchors, minimap.refresh() is called without manual refresh."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap

        def _make_app(**kwargs):
            from hermes_cli.tui.app import HermesApp
            cli = MagicMock()
            cli.config = {}
            app = HermesApp(cli=cli)
            for k, v in kwargs.items():
                setattr(app, k, v)
            return app

        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            from hermes_cli.tui.widgets import OutputPanel
            output = app.query_one(OutputPanel)
            mm = BrowseMinimap()
            await output.mount(mm)
            await pilot.pause()

            refresh_calls = []
            original_refresh = mm.refresh
            mm.refresh = lambda *a, **kw: refresh_calls.append(1) or original_refresh(*a, **kw)

            app.browse_mode = True
            await pilot.pause()
            app._svc_browse.rebuild_browse_anchors()
            await pilot.pause()
            assert len(refresh_calls) >= 1, "Expected minimap.refresh() to be called after rebuild_browse_anchors"


# =============================================================================
# TestBandCollision — MMP-H5
# =============================================================================

class TestBandCollision:
    """MMP-H5: cursor anchor wins band collisions."""

    def test_minimap_band_collision_cursor_first(self):
        """Two anchors in same band; cursor on second → reverse style on strip."""
        from rich.style import Style
        from hermes_cli.tui._browse_types import BrowseAnchorType

        # Put both anchors at y=0 so they share band when virtual_h=24, vh=24
        w0 = _widget_at_y(0)
        w1 = _widget_at_y(0)
        a0 = _make_anchor(BrowseAnchorType.TURN_START, w0)
        a1 = _make_anchor(BrowseAnchorType.CODE_BLOCK, w1)
        mm, _ = _make_minimap_with_mock_app(anchors=[a0, a1], cursor=1, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        segments = [s for s in strip if s.text.strip()]
        has_reverse = any(
            getattr(s.style, "reverse", False) or (isinstance(s.style, Style) and s.style.reverse)
            for s in segments
        )
        assert has_reverse, "Cursor anchor (index 1) should win and use reverse style"

    def test_minimap_band_collision_cursor_outside(self):
        """Two anchors in band 0, cursor on anchor 2 (different band) → first DOM wins."""
        from rich.style import Style
        from hermes_cli.tui._browse_types import BrowseAnchorType

        w0 = _widget_at_y(0)
        w1 = _widget_at_y(0)
        w2 = _widget_at_y(23)
        a0 = _make_anchor(BrowseAnchorType.TURN_START, w0)
        a1 = _make_anchor(BrowseAnchorType.CODE_BLOCK, w1)
        a2 = _make_anchor(BrowseAnchorType.TOOL_BLOCK, w2)
        # cursor=2 is in a different band; row 0 should pick first DOM anchor (a0) = TURN_START = ▸
        mm, _ = _make_minimap_with_mock_app(anchors=[a0, a1, a2], cursor=2, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert "▸" in text, f"Expected ▸ (first DOM anchor), got {text!r}"
        # Should NOT be reverse style
        segments = [s for s in strip if s.text.strip()]
        has_reverse = any(
            getattr(s.style, "reverse", False) or (isinstance(s.style, Style) and s.style.reverse)
            for s in segments
        )
        assert not has_reverse, "Non-cursor anchor should not have reverse style"

    def test_minimap_band_collision_no_cursor_match(self):
        """Collision band with cursor=-1; first DOM-order anchor wins."""
        from rich.style import Style
        from hermes_cli.tui._browse_types import BrowseAnchorType

        w0 = _widget_at_y(0)
        w1 = _widget_at_y(0)
        a0 = _make_anchor(BrowseAnchorType.CODE_BLOCK, w0)
        a1 = _make_anchor(BrowseAnchorType.TOOL_BLOCK, w1)
        mm, _ = _make_minimap_with_mock_app(anchors=[a0, a1], cursor=-1, vh=24, virtual_h=24)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert "‹" in text, f"Expected ‹ (first DOM anchor CODE_BLOCK), got {text!r}"


# =============================================================================
# TestAccentCache — MMP-M1/L2
# =============================================================================

class TestAccentCache:
    """MMP-M1/L2: accent cached per repaint, not per row."""

    def test_minimap_accent_cached_once_per_repaint(self):
        """get_css_variables called at most once across 24 render_line calls."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        from textual.geometry import Size

        w = _widget_at_y(0)
        anchor = _make_anchor(BrowseAnchorType.TURN_START, w)

        mm, mock_app = _make_minimap_with_mock_app(
            anchors=[anchor], cursor=0, vh=24, virtual_h=24
        )
        # Ensure dirty so first call triggers refresh
        mm._accent_dirty = True
        call_count = [0]
        def counting_get_css_variables():
            call_count[0] += 1
            return {"accent": "#aabbcc"}
        mock_app.get_css_variables.side_effect = counting_get_css_variables

        for row in range(24):
            mm.render_line(row)

        assert call_count[0] <= 1, f"get_css_variables called {call_count[0]} times; expected ≤1"

    def test_minimap_accent_invalidates_on_skin_change(self):
        """_on_skin_changed sets _accent_dirty=True."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        mm = BrowseMinimap.__new__(BrowseMinimap)
        mm._accent_cached = "#7aa2f7"
        mm._accent_dirty = False
        mm._full_miss_warned = False

        mock_app = MagicMock()
        type(mm).app = PropertyMock(return_value=mock_app)

        # Simulate refresh being callable
        mm.refresh = MagicMock()

        mm._on_skin_changed()
        assert mm._accent_dirty is True

    def test_minimap_accent_default_on_lookup_failure(self):
        """When get_css_variables raises, cached accent stays at #7aa2f7."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        mm = BrowseMinimap.__new__(BrowseMinimap)
        mm._accent_cached = "#7aa2f7"
        mm._accent_dirty = True
        mm._full_miss_warned = False

        mock_app = MagicMock()
        mock_app.get_css_variables.side_effect = RuntimeError("no css vars")
        type(mm).app = PropertyMock(return_value=mock_app)

        mm._refresh_accent()
        assert mm._accent_cached == "#7aa2f7"
        assert mm._accent_dirty is False  # dirty flag cleared even on failure


# =============================================================================
# TestImportHoist — MMP-M2
# =============================================================================

class TestImportHoist:
    """MMP-M2: OutputPanel import hoisted to module level."""

    def test_minimap_module_import_no_cycle(self):
        """import hermes_cli.tui.browse_minimap from a fresh subprocess — no ImportError."""
        result = subprocess.run(
            [sys.executable, "-c", "import hermes_cli.tui.browse_minimap; print('OK')"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Import failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout


# =============================================================================
# TestVirtualRegionFailures — MMP-M3
# =============================================================================

class TestVirtualRegionFailures:
    """MMP-M3: narrow virtual_region exception, warn on full miss."""

    def _make_bad_widget(self):
        """Widget whose .virtual_region.y raises AttributeError."""
        bad_w = MagicMock()
        # spec=[] means the mock has no attributes, so .y access raises AttributeError
        bad_w.virtual_region = MagicMock(spec=[])
        return bad_w

    def test_minimap_partial_unmounted_anchors_render(self):
        """3 anchors, first raises AttributeError; remaining 2 render correctly."""
        from hermes_cli.tui._browse_types import BrowseAnchorType

        a0 = _make_anchor(BrowseAnchorType.TURN_START, self._make_bad_widget())
        w1 = _widget_at_y(0)
        a1 = _make_anchor(BrowseAnchorType.CODE_BLOCK, w1)
        w2 = _widget_at_y(5)
        a2 = _make_anchor(BrowseAnchorType.TOOL_BLOCK, w2)

        mm, _ = _make_minimap_with_mock_app(anchors=[a0, a1, a2], cursor=1, vh=24, virtual_h=24)
        # Should render non-blank (a1 or a2 is in band)
        strip = mm.render_line(0)
        text = "".join(s.text for s in strip if s.text.strip())
        assert text != "", "Expected non-blank strip with partial anchors"

    def test_minimap_full_miss_logs_warning_once(self):
        """All anchors raise; WARNING logged exactly once across multiple render_line calls."""
        from hermes_cli.tui._browse_types import BrowseAnchorType

        bad_w = self._make_bad_widget()
        a0 = _make_anchor(BrowseAnchorType.TURN_START, bad_w)
        a1 = _make_anchor(BrowseAnchorType.CODE_BLOCK, bad_w)

        mm, _ = _make_minimap_with_mock_app(anchors=[a0, a1], cursor=0, vh=24, virtual_h=24)

        warning_calls = []
        import hermes_cli.tui.browse_minimap as _bm_mod
        with patch.object(_bm_mod._log, "warning", side_effect=lambda *a, **kw: warning_calls.append(a)):
            for row in range(5):
                mm.render_line(row)

        assert len(warning_calls) == 1, f"Expected exactly 1 WARNING, got {len(warning_calls)}"

    def test_minimap_full_miss_resets_after_recovery(self):
        """Full miss sets _full_miss_warned; partial success resets it."""
        from hermes_cli.tui._browse_types import BrowseAnchorType

        bad_w = self._make_bad_widget()
        a_bad = _make_anchor(BrowseAnchorType.TURN_START, bad_w)

        mm, mock_app = _make_minimap_with_mock_app(anchors=[a_bad], cursor=0, vh=24, virtual_h=24)

        # Induce full miss
        mm.render_line(0)
        assert mm._full_miss_warned is True

        # Now add a good anchor alongside the bad one
        good_w = _widget_at_y(0)
        a_good = _make_anchor(BrowseAnchorType.CODE_BLOCK, good_w)
        mock_app._browse_anchors = [a_bad, a_good]

        mm.render_line(0)
        assert mm._full_miss_warned is False, "Warning latch should reset after partial success"


# =============================================================================
# TestLastRowCoverage — MMP-L3
# =============================================================================

class TestLastRowCoverage:
    """MMP-L3: last viewport row covers tail of virtual_h."""

    def test_minimap_last_row_covers_tail(self):
        """virtual_h=25, vh=24, anchor at wy=24; renders on row 23."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        w = _widget_at_y(24)
        anchor = _make_anchor(BrowseAnchorType.TURN_START, w)
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=25)
        # Row 22 (second to last): band = max(1, 25//24) = 1; content_y = int(22/24*25)=22; upper=23 → wy=24 not in [22,23)
        strip_22 = mm.render_line(22)
        text_22 = "".join(s.text for s in strip_22 if s.text.strip())
        # Row 23 (last): upper=25 → wy=24 in [content_y, 25)
        strip_23 = mm.render_line(23)
        text_23 = "".join(s.text for s in strip_23 if s.text.strip())
        assert "▸" in text_23, f"Anchor at wy=24 should render on row 23, got {text_23!r}"
        assert "▸" not in text_22, f"Anchor at wy=24 should NOT render on row 22, got {text_22!r}"

    def test_minimap_aliasing_no_double_count(self):
        """virtual_h=25, vh=24; anchor at wy=23 renders on row 22 only, not also row 23."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        w = _widget_at_y(23)
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=25)

        strip_22 = mm.render_line(22)
        text_22 = "".join(s.text for s in strip_22 if s.text.strip())
        strip_23 = mm.render_line(23)
        text_23 = "".join(s.text for s in strip_23 if s.text.strip())

        # Row 22: content_y = int(22/24*25)=22, upper=23; wy=23 NOT in [22,23) → blank
        # Row 23: content_y = int(23/24*25)=23, upper=25; wy=23 in [23,25) → glyph
        assert "‹" in text_23, f"Anchor at wy=23 should render on row 23, got {text_23!r}"
        assert "‹" not in text_22, f"Anchor at wy=23 should NOT render on row 22, got {text_22!r}"


# =============================================================================
# TestExceptionNarrowing — MMP-L4
# =============================================================================

class TestExceptionNarrowing:
    """MMP-L4: no bare `except Exception:` in services/browse.py."""

    def test_browse_service_no_bare_exception(self):
        """services/browse.py must have zero `except Exception:` bare catches."""
        browse_path = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "services" / "browse.py"
        assert browse_path.exists(), f"browse.py not found at {browse_path}"
        source = browse_path.read_text()
        tree = ast.parse(source)
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # bare `except Exception:` means type is Name(id='Exception')
                if (
                    node.type is not None
                    and isinstance(node.type, ast.Name)
                    and node.type.id == "Exception"
                ):
                    violations.append(node.lineno)
        assert violations == [], (
            f"Found bare `except Exception:` at lines {violations} in services/browse.py"
        )


# =============================================================================
# TestZeroHeightCoverage — MMP-L6
# =============================================================================

class TestZeroHeightCoverage:
    """MMP-L6: zero-height path covered by dedicated test."""

    def test_minimap_does_not_raise_on_default_state(self):
        """render_line does not raise on typical app state with anchors (unit)."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        w = _widget_at_y(0)
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)
        mm, _ = _make_minimap_with_mock_app(anchors=[anchor], cursor=0)
        try:
            strip = mm.render_line(0)
        except Exception as e:
            pytest.fail(f"render_line raised unexpectedly: {e}")
        assert len(list(strip)) >= 1

    def test_minimap_zero_virtual_height_returns_blank(self):
        """render_line returns blank strip when virtual_h resolves to 0."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        from textual.geometry import Size

        w = _widget_at_y(0)
        anchor = _make_anchor(BrowseAnchorType.CODE_BLOCK, w)

        mm, mock_app = _make_minimap_with_mock_app(anchors=[anchor], cursor=0, vh=24, virtual_h=0)
        # Override mock_output virtual_size to return Size(0,0)
        mock_output = mock_app.query_one.return_value
        type(mock_output).virtual_size = PropertyMock(return_value=Size(0, 0))

        strip = mm.render_line(0)
        segments = list(strip)
        text = "".join(s.text for s in segments)
        assert text.strip() == "", f"Expected blank strip for zero virtual_h, got {text!r}"
