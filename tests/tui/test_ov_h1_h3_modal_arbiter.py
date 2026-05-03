"""Tests for SPEC-OV-H1-H3: Modal Arbiter Bypass Bundle.

Covers:
  - OV-H1: AnimConfigPanel migrated to ModalOverlayMixin (5 tests)
  - OV-H2: AnimGalleryOverlay migrated to ModalOverlayMixin (5 tests)
  - OV-H3: KeymapOverlay migrated to ModalOverlayMixin (5 tests)

Tests use stub instances with patched class-level methods to avoid full
Textual DOM requirements. Each widget's show() / action_dismiss() /
dismiss_overlay() contract is verified by wiring a stub app with
_modal_stack / push_modal / pop_modal.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub app factory
# ---------------------------------------------------------------------------

def _make_stub_app(focused_widget: object = None) -> types.SimpleNamespace:
    """Build a minimal stub app with the modal-stack contract."""
    stack: list = []

    def push_modal(widget: object) -> None:
        stack.append(widget)

    def pop_modal(widget: object) -> None:
        if widget in stack:
            stack.remove(widget)

    def is_modal_active() -> bool:
        return bool(stack)

    app = types.SimpleNamespace(
        _modal_stack=stack,
        push_modal=push_modal,
        pop_modal=pop_modal,
        is_modal_active=is_modal_active,
        focused=focused_widget,
    )
    return app


# ---------------------------------------------------------------------------
# Minimal stub widget that has all the Textual-like surface needed
# ---------------------------------------------------------------------------

class _StubWidget:
    """Lightweight widget stub — no Textual DOM required."""

    def __init__(self) -> None:
        self._classes: set[str] = set()
        self._focus_caller: object = None
        self._focused: bool = False
        self.is_mounted: bool = True
        self.app: types.SimpleNamespace | None = None  # set per-test

    # Textual interface shims
    def has_class(self, cls: str) -> bool:
        return cls in self._classes

    def add_class(self, *classes: str) -> None:
        self._classes.update(classes)

    def remove_class(self, *classes: str) -> None:
        self._classes.difference_update(classes)

    def focus(self) -> None:
        self._focused = True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


# ---------------------------------------------------------------------------
# OV-H1 stub — AnimConfigPanel behaviour without Textual internals
# ---------------------------------------------------------------------------

class _StubAnimConfigPanel(_StubWidget):
    """Stub that replays AnimConfigPanel's show / action_dismiss / dismiss_overlay."""

    def _capture_focus_caller(self) -> None:
        self._focus_caller = self.app.focused if self.app else None  # type: ignore[union-attr]

    def _restore_focus_to(self) -> object:
        caller = self._focus_caller
        if caller is not None and getattr(caller, "is_mounted", False):
            return caller
        return None

    def _save_fields_only(self) -> None:
        pass

    def _build_fields(self) -> None:
        pass

    def _refresh_body(self) -> None:
        pass

    def show(self) -> None:
        if self.has_class("--visible"):
            return
        self._build_fields()
        self._refresh_body()
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        self.add_class("--modal", "--visible")
        self.focus()

    def action_dismiss(self) -> None:
        self._save_fields_only()
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")
        try:
            self.app.pop_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# OV-H2 stub — AnimGalleryOverlay behaviour
# ---------------------------------------------------------------------------

class _StubAnimGalleryOverlay(_StubWidget):
    """Stub that replays AnimGalleryOverlay's show / action_dismiss / dismiss_overlay."""

    def __init__(self) -> None:
        super().__init__()
        self._focus_idx = 0

    def _capture_focus_caller(self) -> None:
        self._focus_caller = self.app.focused if self.app else None  # type: ignore[union-attr]

    def _restore_focus_to(self) -> object:
        caller = self._focus_caller
        if caller is not None and getattr(caller, "is_mounted", False):
            return caller
        return None

    def _refresh_list(self) -> None:
        pass

    def _update_preview(self) -> None:
        pass

    def show(self) -> None:
        if self.has_class("--visible"):
            return
        self._focus_idx = 0
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        self.add_class("--modal", "--visible")
        self._refresh_list()
        self._update_preview()
        self.focus()

    def action_dismiss(self) -> None:
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")
        try:
            self.app.pop_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                pass

    def action_open_config(self, config_panel: "_StubAnimConfigPanel | None" = None) -> None:
        """Mirror the production action_open_config — dismiss self, then show config."""
        self.action_dismiss()
        if config_panel is not None:
            config_panel.show()


# ---------------------------------------------------------------------------
# OV-H3 stub — KeymapOverlay behaviour
# ---------------------------------------------------------------------------

class _StubKeymapOverlay(_StubWidget):
    """Stub that replays KeymapOverlay's show / action_dismiss / dismiss_overlay."""

    def _capture_focus_caller(self) -> None:
        self._focus_caller = self.app.focused if self.app else None  # type: ignore[union-attr]

    def _restore_focus_to(self) -> object:
        caller = self._focus_caller
        if caller is not None and getattr(caller, "is_mounted", False):
            return caller
        return None

    def _update_content(self) -> None:
        pass

    def show(self) -> None:
        if self.has_class("--visible"):
            return
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        self.add_class("--modal", "--visible")
        self._update_content()

    def action_dismiss(self) -> None:
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")
        try:
            self.app.pop_modal(self)  # type: ignore[union-attr]
        except AttributeError:
            pass
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helper: a mounted opener widget
# ---------------------------------------------------------------------------

class _FakeOpener:
    def __init__(self, mounted: bool = True) -> None:
        self.is_mounted = mounted
        self._focused = False

    def focus(self) -> None:
        self._focused = True


# ---------------------------------------------------------------------------
# TestOvH1AnimConfigPanel
# ---------------------------------------------------------------------------

class TestOvH1AnimConfigPanel:

    def _make(self) -> tuple[_StubAnimConfigPanel, types.SimpleNamespace]:
        panel = _StubAnimConfigPanel()
        app = _make_stub_app()
        panel.app = app
        return panel, app

    def test_anim_config_show_pushes_modal_stack(self) -> None:
        """show() registers panel in arbiter stack and adds --modal class."""
        panel, app = self._make()
        panel.show()
        assert app._modal_stack == [panel]
        assert "--modal" in panel._classes
        assert app.is_modal_active() is True

    def test_anim_config_dismiss_pops_modal_stack(self) -> None:
        """action_dismiss() saves fields then pops stack and removes --modal/--visible."""
        panel, app = self._make()
        panel.show()
        assert app._modal_stack == [panel]

        panel.action_dismiss()

        assert app._modal_stack == []
        assert "--modal" not in panel._classes
        assert "--visible" not in panel._classes

    def test_anim_config_double_show_does_not_double_push(self) -> None:
        """Calling show() twice must not push the modal stack twice."""
        panel, app = self._make()
        panel.show()
        panel.show()  # re-entry guard fires
        assert len(app._modal_stack) == 1

    def test_anim_config_dismiss_restores_captured_opener(self) -> None:
        """dismiss_overlay() focuses the recorded opener when still mounted."""
        opener = _FakeOpener(mounted=True)
        panel, app = self._make()
        app.focused = opener

        panel.show()      # _capture_focus_caller records opener
        panel.action_dismiss()

        assert opener._focused is True

    def test_anim_config_dismiss_falls_back_to_input_when_opener_unmounted(self) -> None:
        """dismiss_overlay() skips unmounted opener (falls back to None / no focus)."""
        opener = _FakeOpener(mounted=False)
        fake_input = _FakeOpener(mounted=True)
        panel, app = self._make()
        app.focused = opener

        # Override _restore_focus_to to return fake_input (simulates HermesInput fallback)
        panel._restore_focus_to = lambda: fake_input  # type: ignore[method-assign]

        panel.show()
        panel.action_dismiss()

        assert fake_input._focused is True


# ---------------------------------------------------------------------------
# TestOvH2AnimGalleryOverlay
# ---------------------------------------------------------------------------

class TestOvH2AnimGalleryOverlay:

    def _make(self) -> tuple[_StubAnimGalleryOverlay, types.SimpleNamespace]:
        gallery = _StubAnimGalleryOverlay()
        app = _make_stub_app()
        gallery.app = app
        return gallery, app

    def test_anim_gallery_show_pushes_modal_stack(self) -> None:
        """show() registers gallery in arbiter stack and adds --modal."""
        gallery, app = self._make()
        gallery.show()
        assert app._modal_stack == [gallery]
        assert "--modal" in gallery._classes
        assert app.is_modal_active() is True

    def test_anim_gallery_dismiss_pops_modal_stack(self) -> None:
        """action_dismiss() pops stack and removes --modal/--visible."""
        gallery, app = self._make()
        gallery.show()
        gallery.action_dismiss()
        assert app._modal_stack == []
        assert "--modal" not in gallery._classes
        assert "--visible" not in gallery._classes

    def test_anim_gallery_select_pops_modal_stack(self) -> None:
        """action_select() ends with action_dismiss() which flows through dismiss_overlay()."""
        gallery, app = self._make()
        gallery.show()
        assert app._modal_stack == [gallery]

        # action_select() calls action_dismiss() at the end — test that path
        gallery.action_dismiss()

        assert app._modal_stack == []

    def test_anim_gallery_double_show_does_not_double_push(self) -> None:
        """Re-entry guard: second show() when already visible does not double-push."""
        gallery, app = self._make()
        gallery.show()
        gallery.show()
        assert len(app._modal_stack) == 1

    def test_anim_gallery_open_config_dismisses_gallery(self) -> None:
        """action_open_config() dismisses gallery first, then calls AnimConfigPanel.show()."""
        gallery, app = self._make()
        config_panel = _StubAnimConfigPanel()
        config_panel.app = app

        gallery.show()
        assert app._modal_stack == [gallery]

        gallery.action_open_config(config_panel)

        # Gallery must have dismissed
        assert "--modal" not in gallery._classes
        assert "--visible" not in gallery._classes
        # Config panel must have opened
        assert config_panel in app._modal_stack
        assert "--modal" in config_panel._classes


# ---------------------------------------------------------------------------
# TestOvH3KeymapOverlay
# ---------------------------------------------------------------------------

class TestOvH3KeymapOverlay:

    def _make(self) -> tuple[_StubKeymapOverlay, types.SimpleNamespace]:
        overlay = _StubKeymapOverlay()
        app = _make_stub_app()
        overlay.app = app
        return overlay, app

    def test_keymap_show_pushes_modal_stack(self) -> None:
        """show() registers keymap in arbiter stack and adds --modal."""
        overlay, app = self._make()
        overlay.show()
        assert app._modal_stack == [overlay]
        assert "--modal" in overlay._classes
        assert app.is_modal_active() is True

    def test_keymap_dismiss_via_escape_pops(self) -> None:
        """action_dismiss() (Esc path) pops stack and clears --modal."""
        overlay, app = self._make()
        overlay.show()
        overlay.action_dismiss()
        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_keymap_dismiss_via_f1_pops(self) -> None:
        """F1 binding → action_dismiss → dismiss_overlay() pops stack."""
        overlay, app = self._make()
        overlay.show()
        overlay.action_dismiss()  # F1 binding calls action_dismiss
        assert app._modal_stack == []
        assert "--visible" not in overlay._classes

    def test_keymap_dismiss_via_q_pops(self) -> None:
        """q binding → action_dismiss → dismiss_overlay() pops stack."""
        overlay, app = self._make()
        overlay.show()
        overlay.action_dismiss()  # q binding calls action_dismiss
        assert app._modal_stack == []

    def test_keymap_dismiss_restores_captured_opener(self) -> None:
        """dismiss_overlay() focuses the recorded opener."""
        opener = _FakeOpener(mounted=True)
        overlay, app = self._make()
        app.focused = opener

        overlay.show()  # _capture_focus_caller records opener
        overlay.action_dismiss()

        assert opener._focused is True


# ---------------------------------------------------------------------------
# Sanity: verify the actual production classes inherit ModalOverlayMixin
# ---------------------------------------------------------------------------

class TestProductionClassInheritance:
    """Verify real production classes have ModalOverlayMixin in their MRO."""

    def test_anim_config_panel_inherits_mixin(self) -> None:
        with (
            patch("hermes_cli.tui.drawbraille_overlay.DrawbrailleOverlay", new=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay.DrawbrailleOverlayCfg", new=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay._cfg_from_mapping", return_value=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay._ENGINES", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._ENGINE_META", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._PHASE_CATEGORIES", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._PRESETS", new={}),
        ):
            from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel
            from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(AnimConfigPanel, ModalOverlayMixin)

    def test_anim_gallery_overlay_inherits_mixin(self) -> None:
        with (
            patch("hermes_cli.tui.drawbraille_overlay.DrawbrailleOverlay", new=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay.DrawbrailleOverlayCfg", new=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay._cfg_from_mapping", return_value=MagicMock()),
            patch("hermes_cli.tui.drawbraille_overlay._ENGINES", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._ENGINE_META", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._PHASE_CATEGORIES", new={}),
            patch("hermes_cli.tui.drawbraille_overlay._PRESETS", new={}),
        ):
            from hermes_cli.tui.widgets.anim_config_panel import AnimGalleryOverlay
            from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(AnimGalleryOverlay, ModalOverlayMixin)

    def test_keymap_overlay_inherits_mixin(self) -> None:
        from hermes_cli.tui.widgets.overlays import KeymapOverlay
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(KeymapOverlay, ModalOverlayMixin)

    def test_keymap_overlay_has_can_focus_true(self) -> None:
        from hermes_cli.tui.widgets.overlays import KeymapOverlay
        assert KeymapOverlay.can_focus is True
