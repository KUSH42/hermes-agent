"""Tests for SPEC-MOD: Modal/Focus Arbiter + ModalOverlayBase.

TestModalStack          (4) — MOD-1: HermesApp._modal_stack + 4 methods
TestModalMixinLifecycle (3) — MOD-2: on_mount / on_unmount lifecycle
TestFocusRestoration    (3) — MOD-3: _restore_focus_to priority chain
TestSkillPickerMigration(3) — MOD-4: SkillPickerOverlay migration
TestInterruptMigration  (3) — MOD-5: InterruptOverlay migration
TestReferenceMigration  (2) — MOD-6: ReferenceModal migration
TestToolsScreenMigration(2) — MOD-7: ToolsScreen migration
TestContextMenuMigration(1) — MOD-8: ContextMenu migration
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_widget(mounted: bool = True, name: str = "widget"):
    """Build a minimal mock widget."""
    w = MagicMock()
    w.is_mounted = mounted
    w.__class__.__name__ = name
    return w


def _make_app(modal_stack=None):
    """Build a mock HermesApp with the real arbiter method implementations."""
    app = MagicMock()
    app._modal_stack = [] if modal_stack is None else modal_stack
    app.focused = None

    def push_modal(overlay):
        if app._modal_stack:
            app._modal_stack[-1].add_class("--modal-suppressed")
        app._modal_stack.append(overlay)

    def pop_modal(overlay):
        try:
            app._modal_stack.remove(overlay)
        except ValueError:
            pass
        if app._modal_stack:
            app._modal_stack[-1].remove_class("--modal-suppressed")

    def top_modal():
        return app._modal_stack[-1] if app._modal_stack else None

    def is_modal_active():
        return bool(app._modal_stack)

    app.push_modal.side_effect = push_modal
    app.pop_modal.side_effect = pop_modal
    app.top_modal.side_effect = top_modal
    app.is_modal_active.side_effect = is_modal_active
    return app


@contextmanager
def _patch_app(instance, app_mock):
    """Patch the `app` property on a Widget subclass for a test."""
    klass = type(instance)
    with patch.object(klass, "app", new_callable=PropertyMock, return_value=app_mock):
        yield


# ---------------------------------------------------------------------------
# MOD-1: HermesApp._modal_stack + 4 methods
# ---------------------------------------------------------------------------

class TestModalStack:

    def test_push_modal_appends_overlay(self):
        from hermes_cli.tui.app import HermesApp
        app = MagicMock(spec=HermesApp)
        app._modal_stack = []
        w = _make_mock_widget()
        HermesApp.push_modal(app, w)
        assert w in app._modal_stack

    def test_push_modal_suppresses_previous_top(self):
        from hermes_cli.tui.app import HermesApp
        app = MagicMock(spec=HermesApp)
        first = _make_mock_widget()
        second = _make_mock_widget()
        app._modal_stack = [first]
        HermesApp.push_modal(app, second)
        first.add_class.assert_called_with("--modal-suppressed")
        assert app._modal_stack == [first, second]

    def test_pop_modal_removes_and_unsuppresses_top(self):
        from hermes_cli.tui.app import HermesApp
        app = MagicMock(spec=HermesApp)
        first = _make_mock_widget()
        second = _make_mock_widget()
        app._modal_stack = [first, second]
        HermesApp.pop_modal(app, second)
        assert app._modal_stack == [first]
        first.remove_class.assert_called_with("--modal-suppressed")

    def test_is_modal_active_and_top_modal(self):
        from hermes_cli.tui.app import HermesApp
        app = MagicMock(spec=HermesApp)
        app._modal_stack = []
        assert HermesApp.is_modal_active(app) is False
        assert HermesApp.top_modal(app) is None
        w = _make_mock_widget()
        app._modal_stack = [w]
        assert HermesApp.is_modal_active(app) is True
        assert HermesApp.top_modal(app) is w


# ---------------------------------------------------------------------------
# MOD-2: ModalOverlayMixin lifecycle
# (tested via a pure Python stub that doesn't inherit Widget)
# ---------------------------------------------------------------------------

class TestModalMixinLifecycle:

    def _make_stub(self):
        """Return a ModalOverlayMixin instance backed by a plain Python class (no Textual)."""
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin

        class _Stub(ModalOverlayMixin):
            def __init__(self):
                self._focus_caller = None
                self.classes = set()
                self.is_mounted = True
                self.app = None

            def add_class(self, *names):
                self.classes.update(names)

            def remove_class(self, *names):
                self.classes.difference_update(names)

            def focus(self):
                pass

            def remove(self):
                pass

        return _Stub()

    def test_on_mount_adds_modal_class(self):
        stub = self._make_stub()
        app = _make_app()
        stub.app = app
        app.focused = None
        stub.on_mount()
        assert "--modal" in stub.classes

    def test_on_mount_pushes_to_stack(self):
        stub = self._make_stub()
        app = _make_app()
        stub.app = app
        stub.on_mount()
        assert stub in app._modal_stack

    def test_on_unmount_removes_modal_class_and_pops_stack(self):
        stub = self._make_stub()
        app = _make_app()
        stub.app = app
        app._modal_stack.append(stub)
        stub.classes.add("--modal")
        stub.on_unmount()
        assert "--modal" not in stub.classes
        assert stub not in app._modal_stack


# ---------------------------------------------------------------------------
# MOD-3: Focus restoration priority chain
# (pure Python stubs — no Textual)
# ---------------------------------------------------------------------------

class TestFocusRestoration:

    def _make_stub(self):
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin

        class _Stub(ModalOverlayMixin):
            def __init__(self):
                self._focus_caller = None
                self.app = MagicMock()
            def add_class(self, *a): pass
            def remove_class(self, *a): pass
            def focus(self): pass
            def remove(self): pass

        return _Stub()

    def test_restore_focus_returns_mounted_caller(self):
        stub = self._make_stub()
        caller = _make_mock_widget(mounted=True)
        stub._focus_caller = caller
        result = stub._restore_focus_to()
        assert result is caller

    def test_restore_focus_caller_unmounted_falls_back(self):
        stub = self._make_stub()
        caller = _make_mock_widget(mounted=False)
        stub._focus_caller = caller
        fake_inp = MagicMock()
        stub.app.query_one.return_value = fake_inp
        result = stub._restore_focus_to()
        # Does not return the unmounted caller
        assert result is not caller

    def test_restore_focus_returns_none_when_all_fail(self):
        stub = self._make_stub()
        stub._focus_caller = None
        stub.app.query_one.side_effect = Exception("NoMatches")
        result = stub._restore_focus_to()
        assert result is None


# ---------------------------------------------------------------------------
# MOD-4: SkillPickerOverlay migration
# ---------------------------------------------------------------------------

class TestSkillPickerMigration:

    def test_skill_picker_inherits_mixin(self):
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(SkillPickerOverlay, ModalOverlayMixin)

    def test_skill_picker_no_duplicate_escape_binding(self):
        """SkillPickerOverlay must have exactly one escape binding across MRO (MOD-M3)."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        all_bindings = []
        for cls in SkillPickerOverlay.__mro__:
            if "BINDINGS" in cls.__dict__:
                all_bindings.extend(cls.__dict__["BINDINGS"])
        escape_bindings = [b for b in all_bindings if getattr(b, "key", None) == "escape"]
        assert len(escape_bindings) == 1, (
            f"Expected exactly 1 escape binding, found {len(escape_bindings)}: {escape_bindings}"
        )

    def test_skill_picker_dismiss_overlay_calls_remove(self):
        """dismiss_overlay() removes the widget (ephemeral pattern)."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        overlay = SkillPickerOverlay.__new__(SkillPickerOverlay)
        overlay._focus_caller = None

        removed = []
        app = _make_app()

        with _patch_app(overlay, app):
            overlay.remove = lambda: removed.append(True)
            overlay.dismiss_overlay()

        assert removed, "dismiss_overlay() should call remove()"

    def test_open_skill_picker_blocked_when_modal_active(self):
        """_open_skill_picker returns early when a non-picker modal is at top."""
        from hermes_cli.tui.app import HermesApp
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        from textual.css.query import NoMatches

        app = MagicMock(spec=HermesApp)
        existing_modal = _make_mock_widget()
        # Make it NOT a SkillPickerOverlay
        existing_modal.__class__ = _make_mock_widget.__class__

        def top_modal():
            return existing_modal

        app.top_modal.side_effect = top_modal
        app.query_one.side_effect = NoMatches()

        mounted = []
        app.mount.side_effect = lambda w: mounted.append(w)

        HermesApp._open_skill_picker(app, seed_filter="", trigger_source="prefix")
        assert not mounted, "should NOT mount when another modal is active"


# ---------------------------------------------------------------------------
# MOD-5: InterruptOverlay migration
# ---------------------------------------------------------------------------

class TestInterruptMigration:

    def test_interrupt_inherits_mixin(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(InterruptOverlay, ModalOverlayMixin)

    def test_interrupt_on_mount_does_not_push_modal(self):
        """on_mount for InterruptOverlay is a no-op (pre-mounted permanent widget)."""
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        overlay = InterruptOverlay.__new__(InterruptOverlay)

        app = _make_app()
        with _patch_app(overlay, app):
            overlay.on_mount()

        assert app._modal_stack == [], "InterruptOverlay.on_mount must not push to stack"

    def test_interrupt_dismiss_overlay_pops_stack(self):
        """dismiss_overlay removes --modal and calls app.pop_modal."""
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        overlay = InterruptOverlay.__new__(InterruptOverlay)
        overlay._focus_caller = None

        classes = {"--modal"}

        def add_class(*names):
            classes.update(names)

        def remove_class(*names):
            classes.difference_update(names)

        overlay.add_class = add_class
        overlay.remove_class = remove_class

        app = _make_app()
        app._modal_stack = [overlay]

        with _patch_app(overlay, app):
            overlay.dismiss_overlay()

        assert "--modal" not in classes
        assert overlay not in app._modal_stack

    def test_interrupt_activate_refreshes_focus_caller(self):
        """Each _activate() call must refresh _focus_caller to current focused widget (MOD-L5).

        _activate() calls _capture_focus_caller() which reads app.focused. Tests via
        _capture_focus_caller() directly since _activate() requires full Widget init
        for reactive assignments (current_kind, display) which are skipped here.
        """
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay

        overlay = InterruptOverlay.__new__(InterruptOverlay)
        overlay._focus_caller = None

        widget_a = _make_mock_widget(name="widget_a")
        widget_b = _make_mock_widget(name="widget_b")

        app = _make_app()

        # First capture — focused = widget_a
        app.focused = widget_a
        with _patch_app(overlay, app):
            overlay._capture_focus_caller()

        assert overlay._focus_caller is widget_a

        # Second capture — focused = widget_b; must overwrite first
        app.focused = widget_b
        with _patch_app(overlay, app):
            overlay._capture_focus_caller()

        assert overlay._focus_caller is widget_b, \
            "_capture_focus_caller must refresh _focus_caller on repeated calls"
        assert overlay._focus_caller is not widget_a


# ---------------------------------------------------------------------------
# MOD-6: ReferenceModal migration
# ---------------------------------------------------------------------------

class TestReferenceMigration:

    def test_reference_modal_inherits_mixin(self):
        from hermes_cli.tui.overlays.reference import ReferenceModal
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(ReferenceModal, ModalOverlayMixin)

    def test_reference_modal_no_duplicate_escape_binding(self):
        """ReferenceModal must not declare a duplicate escape binding (MOD-M4)."""
        from hermes_cli.tui.overlays.reference import ReferenceModal
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        all_bindings = []
        for cls in ReferenceModal.__mro__:
            if "BINDINGS" in cls.__dict__:
                all_bindings.extend(cls.__dict__["BINDINGS"])
        escape_bindings = [b for b in all_bindings if getattr(b, "key", None) == "escape"]
        assert len(escape_bindings) == 1, (
            f"Expected exactly 1 escape binding, found {len(escape_bindings)}: {escape_bindings}"
        )

    def test_reference_modal_show_overlay_pushes_stack(self):
        """show_overlay() registers the overlay in the arbiter stack.

        We verify the contract by calling show_overlay with all Textual widget
        methods (add_class, remove_class, is_mounted, border_title) replaced by
        lightweight stubs so we never hit the unmounted Widget internals.
        """
        from hermes_cli.tui.overlays.reference import ReferenceModal

        # Build a subclass where all Textual state is replaced with plain attrs
        class _TestModal(ReferenceModal):
            _modal_id = "test"
            _modal_title = "Test"

            # Override border_title as a plain attribute descriptor so the
            # Textual reactive setter never fires (avoids _is_mounted check).
            border_title = ""  # class-level default

            def __init__(self):  # skip Widget.__init__
                self._focus_caller = None
                self._classes: set = set()

            @property
            def is_mounted(self):
                return True

            def add_class(self, *names):
                self._classes.update(names)

            def remove_class(self, *names):
                self._classes.difference_update(names)

        overlay = _TestModal()
        app = _make_app()
        app.focused = None

        with _patch_app(overlay, app):
            overlay.show_overlay()

        assert overlay in app._modal_stack
        assert "--modal" in overlay._classes
        assert "--visible" in overlay._classes

    def test_reference_modal_dismiss_overlay_pops_stack(self):
        """dismiss_overlay() removes the overlay from the arbiter stack (MOD-M6)."""
        from hermes_cli.tui.overlays.reference import ReferenceModal

        class _TestModal(ReferenceModal):
            _modal_id = "test"
            _modal_title = "Test"
            border_title = ""

            def __init__(self):
                self._focus_caller = None
                self._classes: set = set()

            @property
            def is_mounted(self):
                return True

            def add_class(self, *names):
                self._classes.update(names)

            def remove_class(self, *names):
                self._classes.difference_update(names)

            def remove(self):
                pass

        overlay = _TestModal()
        overlay._classes = {"--modal", "--visible"}

        app = _make_app()
        app._modal_stack = [overlay]
        app.focused = None

        with _patch_app(overlay, app):
            overlay.dismiss_overlay()

        assert overlay not in app._modal_stack, "dismiss_overlay must pop from modal stack"
        assert "--modal" not in overlay._classes, "dismiss_overlay must remove --modal class"

    def test_help_overlay_on_mount_sets_border_title(self):
        """HelpOverlay.on_mount must delegate to ReferenceModal.on_mount (MOD-L2)."""
        from hermes_cli.tui.overlays.reference import HelpOverlay, ReferenceModal

        overlay = HelpOverlay.__new__(HelpOverlay)
        overlay._focus_caller = None
        overlay._refresh_commands_cache = lambda: None

        app = _make_app()
        app.focused = None

        parent_calls = []
        with _patch_app(overlay, app):
            with patch.object(ReferenceModal, "on_mount", side_effect=lambda *a: parent_calls.append(True)):
                overlay.on_mount()

        assert parent_calls, "HelpOverlay.on_mount must call super().on_mount() (ReferenceModal)"

    def test_commands_overlay_on_mount_sets_border_title(self):
        """CommandsOverlay.on_mount must delegate to ReferenceModal.on_mount (MOD-L2)."""
        from hermes_cli.tui.overlays.reference import CommandsOverlay, ReferenceModal

        overlay = CommandsOverlay.__new__(CommandsOverlay)
        overlay._focus_caller = None
        overlay._refresh_content = lambda: None

        app = _make_app()
        app.focused = None

        parent_calls = []
        with _patch_app(overlay, app):
            with patch.object(ReferenceModal, "on_mount", side_effect=lambda *a: parent_calls.append(True)):
                overlay.on_mount()

        assert parent_calls, "CommandsOverlay.on_mount must call super().on_mount() (ReferenceModal)"


# ---------------------------------------------------------------------------
# MOD-7: ToolsScreen migration
# ---------------------------------------------------------------------------

class TestToolsScreenMigration:

    def test_tools_screen_inherits_mixin(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(ToolsScreen, ModalOverlayMixin)

    def test_tools_screen_dismiss_overlay_calls_pop_screen(self):
        """dismiss_overlay() delegates to app.pop_screen()."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        screen = ToolsScreen.__new__(ToolsScreen)
        app = MagicMock()

        with _patch_app(screen, app):
            screen.dismiss_overlay()

        app.pop_screen.assert_called_once()

    def test_tools_screen_on_unmount_pops_modal_stack(self):
        """on_unmount() must pop the screen from the arbiter stack via super() (MOD-H1/M5)."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        screen = ToolsScreen.__new__(ToolsScreen)
        screen._rebuild_task = None
        screen._filter_task = None
        screen._stale_timer = None
        screen._refresh_timer = None
        screen._focus_caller = None
        # Stub Textual widget methods so mixin's remove_class/pop_modal don't crash
        screen.remove_class = lambda *a: None
        screen.add_class = lambda *a: None

        app = _make_app()
        app._modal_stack = [screen]
        app.focused = None

        with _patch_app(screen, app):
            screen.on_unmount()

        assert app._modal_stack == [], "on_unmount must pop screen from modal stack"

    def test_tools_screen_on_unmount_cancels_timers_before_super(self):
        """Timers must be cancelled before super().on_unmount() fires (MOD-H1)."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        screen = ToolsScreen.__new__(ToolsScreen)
        screen._rebuild_task = None
        screen._filter_task = None
        stale = MagicMock()
        refresh = MagicMock()
        screen._stale_timer = stale
        screen._refresh_timer = refresh
        screen._focus_caller = None

        call_order = []
        stale.stop.side_effect = lambda: call_order.append("stale")
        refresh.stop.side_effect = lambda: call_order.append("refresh")

        app = _make_app()
        app._modal_stack = [screen]
        app.focused = None

        with _patch_app(screen, app):
            # side_effect receives (self,) when called via super() on the class mock
            with patch.object(ModalOverlayMixin, "on_unmount",
                              side_effect=lambda *a: call_order.append("super")) as mock_super:
                screen.on_unmount()

        assert "stale" in call_order
        assert "refresh" in call_order
        assert call_order.index("super") > call_order.index("stale"), \
            "super().on_unmount() must fire after timer cancellation"
        assert mock_super.call_count == 1


# ---------------------------------------------------------------------------
# MOD-8: ContextMenu migration
# ---------------------------------------------------------------------------

class TestContextMenuMigration:

    def test_context_menu_inherits_mixin(self):
        from hermes_cli.tui.context_menu import ContextMenu
        from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
        assert issubclass(ContextMenu, ModalOverlayMixin)

    def test_context_menu_dismiss_overlay_pops_stack(self):
        """dismiss_overlay removes --modal/--visible and calls app.pop_modal."""
        from hermes_cli.tui.context_menu import ContextMenu
        menu = ContextMenu.__new__(ContextMenu)
        menu._focus_caller = None
        menu._prev_focus = None
        menu._opener_browse_target = None

        classes = {"--modal", "--visible"}

        def add_class(*names):
            classes.update(names)

        def remove_class(*names):
            classes.difference_update(names)

        menu.add_class = add_class
        menu.remove_class = remove_class

        app = _make_app()
        app._modal_stack = [menu]
        app.focused = None

        with _patch_app(menu, app):
            menu.dismiss_overlay()

        assert "--modal" not in classes
        assert "--visible" not in classes
        assert menu not in app._modal_stack

    def test_context_menu_show_captures_browse_target(self):
        """show() must capture browse target at call time, not at on_mount (MOD-M1)."""
        import asyncio
        from hermes_cli.tui.context_menu import ContextMenu, MenuItem

        # Isolated subclass overrides the read-only Textual `children` property
        class _TestMenu(ContextMenu):
            @property
            def children(self):
                return []

            async def mount(self, *widgets, **kwargs):
                pass

        menu = _TestMenu.__new__(_TestMenu)
        menu._focus_caller = None
        menu._prev_focus = None
        menu._opener_browse_target = None
        menu._selected_index = -1
        menu._classes: set = set()
        menu.add_class = lambda *a: menu._classes.update(a)
        menu.remove_class = lambda *a: menu._classes.difference_update(a)
        menu.focus = lambda: None
        menu.styles = MagicMock()

        browse_widget = _make_mock_widget(name="browse_target")

        app = _make_app()
        app.focused = None
        app.size = MagicMock()
        app.size.width = 80
        app.size.height = 40

        # Before show(), on_mount is a no-op — browse target must be None
        with _patch_app(menu, app):
            menu.on_mount()
        assert menu._opener_browse_target is None, \
            "on_mount must not capture browse target (MOD-M1)"

        # Wire browse widget onto app.query return
        app.query.return_value = [browse_widget]

        items = [MenuItem(label="Test", shortcut="", action=lambda: None)]

        with _patch_app(menu, app):
            asyncio.get_event_loop().run_until_complete(
                menu.show(items, screen_x=10, screen_y=10)
            )

        assert menu._opener_browse_target is browse_widget, \
            "show() must capture browse target at call time"

    def test_context_menu_dismiss_overlay_captures_target_before_pop(self):
        """dismiss_overlay must capture focus target before calling pop_modal (MOD-M2)."""
        from hermes_cli.tui.context_menu import ContextMenu

        menu = ContextMenu.__new__(ContextMenu)
        menu._focus_caller = None
        menu._prev_focus = None
        menu._opener_browse_target = None
        menu._classes: set = {"--modal", "--visible"}
        menu.add_class = lambda *a: menu._classes.update(a)
        menu.remove_class = lambda *a: menu._classes.difference_update(a)

        app = _make_app()
        app._modal_stack = [menu]
        app.focused = None

        capture_stack_at_restore = []

        original_restore = type(menu)._restore_focus_to if hasattr(type(menu), "_restore_focus_to") else None

        def capturing_restore(self):
            # Record the stack state at the moment _restore_focus_to is called
            capture_stack_at_restore.append(list(app._modal_stack))
            return None

        with _patch_app(menu, app):
            with patch.object(type(menu), "_restore_focus_to", capturing_restore):
                menu.dismiss_overlay()

        assert len(capture_stack_at_restore) == 1, "_restore_focus_to should have been called once"
        assert menu in capture_stack_at_restore[0], \
            "_restore_focus_to must be called before pop_modal removes menu from stack"
