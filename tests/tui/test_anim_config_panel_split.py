"""Tests for Phase 1 split: AnimConfigPanel, AnimGalleryOverlay, _GalleryPreview.

S-01 through S-10 — import verification + smoke tests.
"""
from __future__ import annotations

import importlib

import pytest


# S-01: AnimConfigPanel importable from drawbraille_overlay
def test_s01_anim_config_panel_from_overlay() -> None:
    from hermes_cli.tui.drawbraille_overlay import AnimConfigPanel  # noqa: F401
    assert AnimConfigPanel is not None


# S-02: AnimGalleryOverlay importable from drawbraille_overlay
def test_s02_anim_gallery_overlay_from_overlay() -> None:
    from hermes_cli.tui.drawbraille_overlay import AnimGalleryOverlay  # noqa: F401
    assert AnimGalleryOverlay is not None


# S-03: ANIMATION_KEYS importable, non-empty list
def test_s03_animation_keys_non_empty() -> None:
    from hermes_cli.tui.drawbraille_overlay import ANIMATION_KEYS
    assert isinstance(ANIMATION_KEYS, list)
    assert len(ANIMATION_KEYS) > 0
    assert "dna" in ANIMATION_KEYS
    assert "sdf_morph" in ANIMATION_KEYS


# S-04: ANIMATION_LABELS importable, non-empty dict
def test_s04_animation_labels_non_empty() -> None:
    from hermes_cli.tui.drawbraille_overlay import ANIMATION_LABELS
    assert isinstance(ANIMATION_LABELS, dict)
    assert len(ANIMATION_LABELS) > 0


# S-05: AnimConfigPanel importable from widgets.anim_config_panel
def test_s05_anim_config_panel_from_widgets() -> None:
    from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel  # noqa: F401
    assert AnimConfigPanel is not None


# S-06: Same class object from both import paths
def test_s06_same_class_object() -> None:
    from hermes_cli.tui.drawbraille_overlay import AnimConfigPanel as ACP1
    from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel as ACP2
    assert ACP1 is ACP2


# S-07: DrawbrailleOverlay constructor works (on_mount is Textual lifecycle, skip)
def test_s07_drawbraille_overlay_class_importable() -> None:
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
    # Just verify class is importable and is a class
    assert isinstance(DrawbrailleOverlay, type)


# S-08: _renderer attr will exist — verify class has no pre-Phase2 blocker
def test_s08_drawbraille_overlay_importable() -> None:
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
    # Verify it's a widget subclass
    from textual.widget import Widget
    assert issubclass(DrawbrailleOverlay, Widget)


# S-09: Module-level constants still in drawbraille_overlay namespace
def test_s09_module_level_constants() -> None:
    import hermes_cli.tui.drawbraille_overlay as dbo
    assert hasattr(dbo, "_PRESETS"), "_PRESETS missing"
    assert hasattr(dbo, "_POS_GRID"), "_POS_GRID missing"
    assert hasattr(dbo, "_ENGINE_META"), "_ENGINE_META missing"
    assert hasattr(dbo, "ANIMATION_LABELS"), "ANIMATION_LABELS missing"
    # Verify they have expected content
    assert isinstance(dbo._PRESETS, dict)
    assert len(dbo._POS_GRID) == 3  # 3 rows of position grid
    assert isinstance(dbo._ENGINE_META, dict)
    assert isinstance(dbo.ANIMATION_LABELS, dict)


# S-10: _GalleryPreview importable from drawbraille_overlay (regression guard)
def test_s10_gallery_preview_from_overlay() -> None:
    from hermes_cli.tui.drawbraille_overlay import _GalleryPreview  # noqa: F401
    assert _GalleryPreview is not None
    # Also verify it's a Widget subclass
    from textual.widget import Widget
    assert issubclass(_GalleryPreview, Widget)
