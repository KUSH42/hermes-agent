"""SPEC-IIB-LIFECYCLE: InlineImageBar LRU cap, dedupe, clear, tooltip, click handling."""
from __future__ import annotations

import types
import unittest.mock as mock
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from hermes_cli.tui.widgets.inline_media import (
    InlineImageBar,
    InlineThumbnail,
    _OldnessChip,
    _MAX_THUMBNAILS,
)


# ---------------------------------------------------------------------------
# Minimal app fixture
# ---------------------------------------------------------------------------

class _BarApp(App):
    def compose(self) -> ComposeResult:
        yield InlineImageBar()


def _fake_stat(mtime: int):
    s = types.SimpleNamespace()
    s.st_mtime = float(mtime)
    return s


# ---------------------------------------------------------------------------
# TestInlineImageBarLRUCap (4 tests)
# ---------------------------------------------------------------------------

class TestInlineImageBarLRUCap:
    @pytest.mark.asyncio
    async def test_inline_image_bar_lru_cap_at_max_thumbnails(self, tmp_path):
        """Adding exactly _MAX_THUMBNAILS images: 40 chips, no _OldnessChip."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            for i in range(_MAX_THUMBNAILS):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            chips = list(container.query(InlineThumbnail))
            assert len(chips) == _MAX_THUMBNAILS
            assert list(container.query(_OldnessChip)) == []

    @pytest.mark.asyncio
    async def test_inline_image_bar_evict_oldest_when_cap_exceeded(self, tmp_path):
        """Adding 41 images: 40 chips remain, _evicted_count == 1, first path gone."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            paths = []
            for i in range(_MAX_THUMBNAILS + 1):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                paths.append(p)
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            chips = list(container.query(InlineThumbnail))
            assert len(chips) == _MAX_THUMBNAILS
            assert bar._evicted_count == 1
            first_key = (str(paths[0].resolve()), 0)
            assert first_key not in bar._chips_by_key

    @pytest.mark.asyncio
    async def test_inline_image_bar_oldness_chip_appears_after_first_eviction(self, tmp_path):
        """After 41 adds, exactly one _OldnessChip with text starting '+1 earlier'."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            for i in range(_MAX_THUMBNAILS + 1):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            oldness = list(container.query(_OldnessChip))
            assert len(oldness) == 1
            rendered = oldness[0].render()
            text = str(rendered)
            assert "+1 earlier" in text

    @pytest.mark.asyncio
    async def test_inline_image_bar_oldness_chip_count_grows_with_more_evictions(self, tmp_path):
        """After 50 adds (_MAX_THUMBNAILS=40), _OldnessChip shows '+10 earlier images'."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            for i in range(50):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            oldness = list(container.query(_OldnessChip))
            assert len(oldness) == 1
            rendered = oldness[0].render()
            text = str(rendered)
            assert "+10 earlier images" in text


# ---------------------------------------------------------------------------
# TestInlineImageBarDedupe (3 tests)
# ---------------------------------------------------------------------------

class TestInlineImageBarDedupe:
    @pytest.mark.asyncio
    async def test_inline_image_bar_dedupe_on_realpath(self, tmp_path):
        """Adding the same path twice mounts only one InlineThumbnail."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            p = tmp_path / "img.png"
            p.write_bytes(b"")
            with patch.object(Path, "stat", return_value=_fake_stat(100)):
                bar.add_image(str(p))
                bar.add_image(str(p))
            await pilot.pause()
            chips = list(container.query(InlineThumbnail))
            assert len(chips) == 1

    @pytest.mark.asyncio
    async def test_inline_image_bar_dedupe_uses_mtime_to_distinguish_overwritten_files(self, tmp_path):
        """Same path, different mtimes → two InlineThumbnail widgets."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            p = tmp_path / "img.png"
            p.write_bytes(b"")
            with patch.object(Path, "stat", return_value=_fake_stat(100)):
                bar.add_image(str(p))
            with patch.object(Path, "stat", return_value=_fake_stat(200)):
                bar.add_image(str(p))
            await pilot.pause()
            chips = list(container.query(InlineThumbnail))
            assert len(chips) == 2

    @pytest.mark.asyncio
    async def test_inline_image_bar_dedupe_highlight_pulses_existing_chip(self, tmp_path):
        """Second add of same path adds --highlight-pulse class; removed after 0.6s."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            p = tmp_path / "img.png"
            p.write_bytes(b"")
            with patch.object(Path, "stat", return_value=_fake_stat(100)):
                bar.add_image(str(p))
                bar.add_image(str(p))
            await pilot.pause()
            chips = list(container.query(InlineThumbnail))
            assert len(chips) == 1
            assert chips[0].has_class("--highlight-pulse")
            # Advance timers past 0.6s to verify removal
            await pilot.pause(delay=0.7)
            assert not chips[0].has_class("--highlight-pulse")


# ---------------------------------------------------------------------------
# TestInlineImageBarClear (3 tests)
# ---------------------------------------------------------------------------

class TestInlineImageBarClear:
    @pytest.mark.asyncio
    async def test_inline_image_bar_clear_removes_all_thumbnails(self, tmp_path):
        """After adding 5 images then calling clear(), no InlineThumbnail remains."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            for i in range(5):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            bar.clear()
            await pilot.pause()
            assert list(container.query(InlineThumbnail)) == []

    @pytest.mark.asyncio
    async def test_inline_image_bar_clear_removes_oldness_chip_and_resets_counter(self, tmp_path):
        """After 45 images then clear(): no _OldnessChip and _evicted_count == 0."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            container = bar.query_one(Horizontal)
            for i in range(45):
                p = tmp_path / f"img_{i}.png"
                p.write_bytes(b"")
                with patch.object(Path, "stat", return_value=_fake_stat(i)):
                    bar.add_image(str(p))
            await pilot.pause()
            assert bar._evicted_count == 5
            bar.clear()
            await pilot.pause()
            assert list(container.query(_OldnessChip)) == []
            assert bar._evicted_count == 0

    def test_clear_conversation_hook_invokes_inline_image_bar_clear(self):
        """handle_clear_tui calls InlineImageBar.clear() exactly once."""
        from hermes_cli.tui.services.commands import CommandsService
        from hermes_cli.tui.widgets.inline_media import InlineImageBar as _IIB

        cleared = []
        fake_bar = MagicMock()
        fake_bar.clear = MagicMock(side_effect=lambda: cleared.append(1))

        fake_op = MagicMock()
        fake_op.remove_children = MagicMock()
        fake_op.mount = MagicMock()

        fake_input = MagicMock()

        def _query_one(klass):
            if klass is _IIB or klass.__name__ == "InlineImageBar":
                return fake_bar
            from textual.css.query import NoMatches
            raise NoMatches()

        app = MagicMock()
        app._clear_animation_in_progress = False
        app.query_one = MagicMock(side_effect=_query_one)
        app.query = MagicMock(return_value=[])
        app.cli = MagicMock()
        app.cli.new_session = MagicMock()
        app._flash_hint = MagicMock()

        svc = CommandsService.__new__(CommandsService)
        svc.app = app

        import asyncio

        async def _run():
            # Patch op and input query_one so handle_clear_tui works end-to-end
            from textual.css.query import NoMatches as _NM
            from hermes_cli.tui.widgets import OutputPanel as _OP

            def _q1(klass):
                if klass is _IIB:
                    return fake_bar
                if klass is _OP or (hasattr(klass, "__name__") and klass.__name__ == "OutputPanel"):
                    return fake_op
                raise _NM()

            app.query_one = MagicMock(side_effect=_q1)
            await svc.handle_clear_tui()

        asyncio.run(_run())
        assert len(cleared) == 1


# ---------------------------------------------------------------------------
# TestInlineThumbnailTooltip (2 tests)
# ---------------------------------------------------------------------------

class TestInlineThumbnailTooltip:
    @pytest.mark.asyncio
    async def test_inline_thumbnail_tooltip_relative_when_under_cwd(self, tmp_path):
        """Tooltip is relative path when image is under the working directory."""
        img_dir = tmp_path / "img"
        img_dir.mkdir()
        img_path = img_dir / "foo.png"
        img_path.write_bytes(b"")

        class _TipApp(App):
            def compose(self) -> ComposeResult:
                yield InlineThumbnail(path=str(img_path), index=0)

            def get_working_directory(self) -> Path:
                return tmp_path

        async with _TipApp().run_test() as pilot:
            await pilot.pause()
            thumb = pilot.app.query_one(InlineThumbnail)
            assert thumb._tooltip_text == "img/foo.png"

    @pytest.mark.asyncio
    async def test_inline_thumbnail_tooltip_absolute_when_outside_cwd(self, tmp_path):
        """Tooltip falls back to absolute path when image is outside cwd."""
        outside = tmp_path / "other" / "bar.png"
        outside.parent.mkdir()
        outside.write_bytes(b"")
        cwd_dir = tmp_path / "cwd"
        cwd_dir.mkdir()

        class _TipApp(App):
            def compose(self) -> ComposeResult:
                yield InlineThumbnail(path=str(outside), index=0)

            def get_working_directory(self) -> Path:
                return cwd_dir

        async with _TipApp().run_test() as pilot:
            await pilot.pause()
            thumb = pilot.app.query_one(InlineThumbnail)
            assert thumb._tooltip_text == str(outside)


# ---------------------------------------------------------------------------
# Minimal click handler (mirrors app.py handler for testing without HermesApp)
# ---------------------------------------------------------------------------

async def _invoke_thumbnail_clicked(app: App, event: Any) -> None:
    """Call the same logic as app.py on_inline_image_bar_thumbnail_clicked."""
    from hermes_cli.tui.widgets.inline_media import InlineImage
    from hermes_cli.tui.services import feedback as _fb
    from hermes_cli.tui.widgets import OutputPanel
    from textual.css.query import NoMatches
    for widget in app.query(InlineImage):
        if getattr(widget, "_src_path", "") == event.path:
            try:
                app.query_one(OutputPanel).scroll_to_widget(widget, animate=True)
            except NoMatches:
                pass
            widget.add_class("--highlight-pulse")
            app.set_timer(0.6, lambda w=widget: w.remove_class("--highlight-pulse"))
            return
    app._flash_hint(
        "image no longer in view — scroll back to find it",
        1.5,
        key=_fb.HINT_KEY_IMAGE_NOT_IN_VIEW,
    )


# ---------------------------------------------------------------------------
# TestThumbClickNoMatch (2 tests)
# ---------------------------------------------------------------------------

class TestThumbClickNoMatch:
    @pytest.mark.asyncio
    async def test_thumb_click_match_scrolls_and_pulses(self):
        """When a matching InlineImage is mounted, scroll + --highlight-pulse fires."""
        from hermes_cli.tui.widgets.inline_media import InlineImage

        class _ClickApp(App):
            def compose(self) -> ComposeResult:
                yield InlineImageBar()
                img = InlineImage()
                img._src_path = "/tmp/a.png"
                yield img

        async with _ClickApp().run_test() as pilot:
            from hermes_cli.tui.widgets import OutputPanel
            from textual.css.query import NoMatches

            app = pilot.app
            img_widget = app.query_one(InlineImage)

            scrolled = []

            original_q1 = app.query_one

            def _patched_q1(klass):
                if klass is OutputPanel:
                    panel = MagicMock()
                    panel.scroll_to_widget = lambda w, animate=False: scrolled.append(w)
                    return panel
                return original_q1(klass)

            app.query_one = _patched_q1
            app._flash_hint = MagicMock()

            event = types.SimpleNamespace(path="/tmp/a.png", index=0)
            await _invoke_thumbnail_clicked(app, event)
            await pilot.pause()

            assert len(scrolled) == 1
            assert img_widget.has_class("--highlight-pulse")
            await pilot.pause(delay=0.7)
            assert not img_widget.has_class("--highlight-pulse")

    @pytest.mark.asyncio
    async def test_thumb_click_no_match_flashes_hint(self):
        """When no InlineImage matches the path, _flash_hint called with correct args."""
        from hermes_cli.tui.services.feedback import HINT_KEY_IMAGE_NOT_IN_VIEW

        class _NoMatchApp(App):
            def compose(self) -> ComposeResult:
                yield InlineImageBar()

        async with _NoMatchApp().run_test() as pilot:
            app = pilot.app
            flash_calls = []
            app._flash_hint = lambda msg, dur, **kw: flash_calls.append((msg, dur, kw))

            event = types.SimpleNamespace(path="/tmp/nonexistent.png", index=0)
            await _invoke_thumbnail_clicked(app, event)
            await pilot.pause()

            assert len(flash_calls) == 1
            msg, dur, kw = flash_calls[0]
            assert "no longer in view" in msg
            assert kw.get("key") == HINT_KEY_IMAGE_NOT_IN_VIEW


# ---------------------------------------------------------------------------
# TestInlineImageBarVisibility (2 tests)
# ---------------------------------------------------------------------------

class TestInlineImageBarVisibility:
    @pytest.mark.asyncio
    async def test_inline_image_bar_visible_class_added_on_add(self, tmp_path):
        """Adding one image adds --visible class."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            p = tmp_path / "img.png"
            p.write_bytes(b"")
            with patch.object(Path, "stat", return_value=_fake_stat(1)):
                bar.add_image(str(p))
            await pilot.pause()
            assert bar.has_class("--visible")

    @pytest.mark.asyncio
    async def test_inline_image_bar_visible_class_removed_on_clear(self, tmp_path):
        """After adding one image then calling clear(), --visible is removed."""
        async with _BarApp().run_test() as pilot:
            bar = pilot.app.query_one(InlineImageBar)
            p = tmp_path / "img.png"
            p.write_bytes(b"")
            with patch.object(Path, "stat", return_value=_fake_stat(1)):
                bar.add_image(str(p))
            await pilot.pause()
            assert bar.has_class("--visible")
            bar.clear()
            await pilot.pause()
            assert not bar.has_class("--visible")
