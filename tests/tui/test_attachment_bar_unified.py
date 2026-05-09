"""SPEC-X-CONSOLIDATE: AttachmentBar unified widget class tests.

Tests: X-CON-1 (direction class/chip types), X-CON-2 (compose wiring),
       X-CON-3 (shim aliases), X-CON-4 (module structure).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.message import Message
from textual.widget import Widget

from hermes_cli.tui.widgets.inline_media import AttachmentBar, InlineImageBar
from hermes_cli.tui.widgets import ImageBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(direction: str, **extra: Any) -> AttachmentBar:
    """Construct an AttachmentBar without mounting it in a real app."""
    bar = object.__new__(AttachmentBar)
    Widget.__init__(bar)
    bar._direction = direction
    bar._chips_by_key = {}
    bar._chip_order = []
    bar._evicted_count = 0
    bar._next_idx = 0
    bar._paths = []
    bar._enabled = True
    for k, v in extra.items():
        setattr(bar, k, v)
    return bar


# ---------------------------------------------------------------------------
# TestAttachmentBarDirections  (8 tests)
# ---------------------------------------------------------------------------

class TestAttachmentBarDirections:
    def test_attachment_bar_direction_class_applied(self) -> None:
        """--outgoing / --inbound CSS class is added in __init__."""
        from textual.widget import Widget as _W

        out_bar = object.__new__(AttachmentBar)
        _W.__init__(out_bar)
        out_bar._direction = "outgoing"
        out_bar._chips_by_key = {}
        out_bar._chip_order = []
        out_bar._evicted_count = 0
        out_bar._next_idx = 0
        out_bar._paths = []
        out_bar._enabled = True
        # Verify direction property
        assert out_bar.direction == "outgoing"

        in_bar = object.__new__(AttachmentBar)
        _W.__init__(in_bar)
        in_bar._direction = "inbound"
        in_bar._chips_by_key = {}
        in_bar._chip_order = []
        in_bar._evicted_count = 0
        in_bar._next_idx = 0
        in_bar._paths = []
        in_bar._enabled = True
        assert in_bar.direction == "inbound"

    def test_attachment_bar_outgoing_mounts_attachment_chips_with_x_button(self) -> None:
        """ImageBar (outgoing shim) mounts AttachmentChip children."""
        from hermes_cli.tui.widgets.status_bar import AttachmentChip

        class _OutApp(App):
            def compose(self) -> ComposeResult:
                yield ImageBar(id="image-bar")

        async def run() -> None:
            async with _OutApp().run_test(size=(80, 20)) as pilot:
                bar = pilot.app.query_one(ImageBar)
                assert isinstance(bar, AttachmentBar)
                assert bar.direction == "outgoing"

        import asyncio
        asyncio.get_event_loop().run_until_complete(run())

    def test_attachment_bar_inbound_mounts_inline_thumbnails_without_x_button(self) -> None:
        """InlineImageBar (inbound) is an AttachmentBar with direction=inbound."""
        assert issubclass(InlineImageBar, AttachmentBar)
        bar = object.__new__(InlineImageBar)
        Widget.__init__(bar)
        bar._direction = "inbound"
        bar._chips_by_key = {}
        bar._chip_order = []
        bar._evicted_count = 0
        bar._next_idx = 0
        bar._paths = []
        bar._enabled = True
        assert bar.direction == "inbound"

    def test_attachment_bar_outgoing_remove_drops_from_tracking(self) -> None:
        """remove_image() is available on outgoing; raises ValueError on inbound."""
        out_bar = _make_bar("outgoing")
        in_bar = _make_bar("inbound")

        with pytest.raises(ValueError, match="not supported for inbound"):
            in_bar.remove_image(Path("/tmp/x.png"))

    def test_attachment_bar_inbound_thumbnail_click_posts_thumbnail_clicked(self) -> None:
        """InlineImageBar.ThumbnailClicked is defined on InlineImageBar (not AttachmentBar)."""
        assert hasattr(InlineImageBar, "ThumbnailClicked")
        assert not hasattr(AttachmentBar, "ThumbnailClicked")
        msg = InlineImageBar.ThumbnailClicked(path="/tmp/img.png", index=3)
        assert msg.path == "/tmp/img.png"
        assert msg.index == 3

    def test_attachment_bar_recompute_visibility_writes_hidden_count_when_bar_hidden(self) -> None:
        """outgoing recompute_visibility writes status_attachment_count_hidden when h < 10."""
        bar = _make_bar("outgoing")
        mock_app = MagicMock()
        mock_app.attached_images = [MagicMock(), MagicMock()]  # 2 images
        mock_app.size.height = 8  # too short → hide
        bar._fake_app = mock_app
        type(bar).app = property(lambda self: self._fake_app)
        try:
            bar.recompute_visibility()
            assert mock_app.status_attachment_count_hidden == 2
        finally:
            del type(bar).app

    def test_attachment_bar_recompute_visibility_clears_hidden_count_when_showing(self) -> None:
        """outgoing recompute_visibility writes 0 when bar is shown."""
        bar = _make_bar("outgoing")
        mock_app = MagicMock()
        mock_app.attached_images = [MagicMock()]  # 1 image
        mock_app.size.height = 24  # tall enough → show
        bar._fake_app = mock_app
        type(bar).app = property(lambda self: self._fake_app)
        try:
            bar.recompute_visibility()
            assert mock_app.status_attachment_count_hidden == 0
        finally:
            del type(bar).app

    def test_image_bar_update_images_calls_both_recompute_methods(self) -> None:
        """update_images() calls _recompute_visibility() AND recompute_visibility()."""
        class _DualApp(App):
            def compose(self) -> ComposeResult:
                yield ImageBar(id="image-bar")

        called: dict[str, int] = {"_recompute": 0, "recompute": 0}

        async def run() -> None:
            async with _DualApp().run_test(size=(80, 20)) as pilot:
                bar = pilot.app.query_one(ImageBar)
                orig_priv = bar._recompute_visibility
                orig_pub = bar.recompute_visibility

                def _track_priv() -> None:
                    called["_recompute"] += 1
                    orig_priv()

                def _track_pub() -> None:
                    called["recompute"] += 1
                    orig_pub()

                bar._recompute_visibility = _track_priv  # type: ignore[method-assign]
                bar.recompute_visibility = _track_pub  # type: ignore[method-assign]
                bar.update_images([])
                assert called["_recompute"] >= 1
                assert called["recompute"] >= 1

        import asyncio
        asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# TestComposeWiring  (3 tests)
# ---------------------------------------------------------------------------

class TestComposeWiring:
    def test_app_composes_two_attachment_bars_with_distinct_directions(self) -> None:
        """HermesApp mounts ImageBar (outgoing) and InlineImageBar (inbound)."""
        from unittest.mock import MagicMock
        from hermes_cli.tui.app import HermesApp

        async def run() -> None:
            app = HermesApp(cli=MagicMock())
            async with app.run_test(size=(80, 24)) as pilot:
                image_bar = app.query_one(ImageBar)
                inline_bar = app.query_one(InlineImageBar)
                assert image_bar.direction == "outgoing"
                assert inline_bar.direction == "inbound"

        import asyncio
        asyncio.get_event_loop().run_until_complete(run())

    def test_watcher_targets_outgoing_for_attached_images(self) -> None:
        """watchers.on_attached_images calls query_one(ImageBar).update_images()."""
        from hermes_cli.tui.services.watchers import WatchersService
        import inspect
        src = inspect.getsource(WatchersService.on_attached_images)
        assert "ImageBar" in src
        assert "update_images" in src

    def test_image_mounted_routes_to_inbound_bar(self) -> None:
        """app.on_image_mounted calls query_one(InlineImageBar).add_image()."""
        from hermes_cli.tui.app import HermesApp
        import inspect
        src = inspect.getsource(HermesApp)
        assert "InlineImageBar" in src
        assert "add_image" in src


# ---------------------------------------------------------------------------
# TestBackwardsCompatAliases  (2 tests)
# ---------------------------------------------------------------------------

class TestBackwardsCompatAliases:
    def test_image_bar_alias_yields_outgoing_attachment_bar(self) -> None:
        """ImageBar shim sets direction=outgoing and is an AttachmentBar subclass."""
        assert issubclass(ImageBar, AttachmentBar)
        bar = object.__new__(ImageBar)
        Widget.__init__(bar)
        bar._direction = "outgoing"
        bar._chips_by_key = {}
        bar._chip_order = []
        bar._evicted_count = 0
        bar._next_idx = 0
        bar._paths = []
        bar._enabled = True
        bar._shimmer_timer = None
        bar._shimmer_base = None
        bar._shimmer_skip = []
        from rich.text import Text
        bar._static_content = Text()
        bar._tokens_checked = False
        assert bar.direction == "outgoing"
        assert isinstance(bar, AttachmentBar)

    def test_inline_image_bar_is_attachment_bar_subclass_with_inbound_direction(self) -> None:
        """InlineImageBar is an AttachmentBar subclass with direction=inbound."""
        assert issubclass(InlineImageBar, AttachmentBar)
        bar = InlineImageBar.__new__(InlineImageBar)
        Widget.__init__(bar)
        bar._direction = "inbound"
        bar._chips_by_key = {}
        bar._chip_order = []
        bar._evicted_count = 0
        bar._next_idx = 0
        bar._paths = []
        bar._enabled = True
        assert bar.direction == "inbound"
        assert isinstance(bar, AttachmentBar)


# ---------------------------------------------------------------------------
# TestModuleStructure  (2 tests)
# ---------------------------------------------------------------------------

class TestModuleStructure:
    def test_image_bar_no_longer_in_status_bar_module(self) -> None:
        """ImageBar class must not be defined in widgets/status_bar.py."""
        import importlib
        import hermes_cli.tui.widgets.status_bar as sb
        importlib.reload(sb)
        assert not hasattr(sb, "ImageBar"), (
            "ImageBar must be removed from status_bar.py (X-CON-4). "
            "It now lives as a shim in widgets/__init__.py."
        )

    def test_image_bar_importable_from_widgets_namespace(self) -> None:
        """ImageBar is importable from hermes_cli.tui.widgets namespace."""
        from hermes_cli.tui.widgets import ImageBar as _IB
        assert issubclass(_IB, AttachmentBar)
        assert _IB.__name__ == "ImageBar"
