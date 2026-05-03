"""Tests for BrowseMinimap lifecycle — MMP-M4..M8.

Covers:
  - MMP-M4: property shims proxy _browse_anchors/_browse_cursor to BrowseService
  - MMP-M5: toggle serialised on _browse_minimap flag (no double-mount)
  - MMP-M6: unified _mount_minimap helper; mount_minimap_default deleted
  - MMP-M7: hint flashed when toggle blocked by disabled markers
  - MMP-M8: browse help overlay gap — xfail placeholder
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs):
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.config = {}
    app = HermesApp(cli=cli)
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_anchor(anchor_type, widget=None, label="Test", turn_id=1):
    from hermes_cli.tui._browse_types import BrowseAnchor
    w = widget or MagicMock()
    w.is_mounted = True
    return BrowseAnchor(anchor_type=anchor_type, widget=w, label=label, turn_id=turn_id)


# ---------------------------------------------------------------------------
# TestStateOwnership — MMP-M4
# ---------------------------------------------------------------------------

class TestStateOwnership:
    """Property shims on HermesApp proxy to BrowseService (MMP-M4)."""

    def test_anchors_property_proxies_to_service(self):
        """Setting app._browse_anchors writes through to BrowseService._browse_anchors."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        app = _make_app()
        a1 = _make_anchor(BrowseAnchorType.TURN_START)
        app._browse_anchors = [a1]
        assert app._svc_browse._browse_anchors == [a1]

    def test_cursor_property_proxies_to_service(self):
        """Setting app._browse_cursor writes through to BrowseService._browse_cursor."""
        app = _make_app()
        app._browse_cursor = 7
        assert app._svc_browse._browse_cursor == 7

    def test_app_reset_clears_service_state(self):
        """The reset path (app._browse_anchors = []) clears the service anchor list."""
        from hermes_cli.tui._browse_types import BrowseAnchorType
        app = _make_app()
        a1 = _make_anchor(BrowseAnchorType.TURN_START)
        # Prime the service with some state
        app._svc_browse._browse_anchors = [a1]
        app._svc_browse._browse_cursor = 3
        # Simulate the reset path in handle_session_resume
        app._browse_anchors = []
        app._browse_cursor = 0
        assert app._svc_browse._browse_anchors == []
        assert app._svc_browse._browse_cursor == 0

    def test_render_reads_through_property(self):
        """app._browse_anchors property proxies correctly to BrowseService state."""
        from hermes_cli.tui._browse_types import BrowseAnchorType

        app = _make_app()
        a1 = _make_anchor(BrowseAnchorType.CODE_BLOCK)

        # Start empty
        assert app._browse_anchors == []

        # Write via service directly — property read should reflect it
        app._svc_browse._browse_anchors = [a1]
        assert app._browse_anchors is app._svc_browse._browse_anchors

        # Write via app property — service should reflect it
        a2 = _make_anchor(BrowseAnchorType.TURN_START)
        app._browse_anchors = [a2]
        assert app._svc_browse._browse_anchors == [a2]

        # Identity is preserved in both directions
        assert app._browse_anchors == app._svc_browse._browse_anchors


# ---------------------------------------------------------------------------
# TestToggleSerialization — MMP-M5
# ---------------------------------------------------------------------------

class TestToggleSerialization:
    """Toggle serialised on _browse_minimap flag (MMP-M5)."""

    @pytest.mark.asyncio
    async def test_toggle_double_press_no_double_mount(self):
        """Two rapid toggle calls result in unmounted state with no duplicate mounts."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        from textual.css.query import NoMatches

        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()

            # First toggle: mount
            await app.action_toggle_minimap()
            await pilot.pause()
            assert app._browse_minimap is True

            # Second toggle: unmount (no pause between — rapid double press)
            await app.action_toggle_minimap()
            await pilot.pause()
            assert app._browse_minimap is False

            # No BrowseMinimap should remain in DOM
            try:
                app.query_one(BrowseMinimap)
                found = True
            except NoMatches:
                found = False
            assert not found

    @pytest.mark.asyncio
    async def test_toggle_mount_failure_reverts_flag(self):
        """If mount raises, _browse_minimap stays False."""
        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()

            # Patch _mount_minimap to simulate failure
            with patch.object(
                app._svc_browse,
                "_mount_minimap",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_mount:
                await app.action_toggle_minimap()
                await pilot.pause()
                mock_mount.assert_awaited_once()
            # Flag should reflect the failed-mount outcome (False returned)
            assert app._browse_minimap is False

    @pytest.mark.asyncio
    async def test_toggle_unmount_when_query_fails(self):
        """Flag True but no widget in DOM: toggle clears flag without raising."""
        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()

            # Force flag to True without actually mounting
            app._browse_minimap = True
            # Now toggle: should detect NoMatches and clear flag cleanly
            await app.action_toggle_minimap()
            await pilot.pause()
            assert app._browse_minimap is False


# ---------------------------------------------------------------------------
# TestUnifiedMountPath — MMP-M6
# ---------------------------------------------------------------------------

class TestUnifiedMountPath:
    """Unified _mount_minimap helper; mount_minimap_default deleted (MMP-M6)."""

    @pytest.mark.asyncio
    async def test_default_mount_uses_unified_path(self):
        """minimap_default=True enters browse mode and mounts via _mount_minimap."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap

        app = _make_app(_browse_markers_enabled=True, _browse_minimap_default=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause(0.2)
            assert app._browse_minimap is True
            # Exactly one BrowseMinimap
            mms = list(app.query(BrowseMinimap))
            assert len(mms) == 1

    @pytest.mark.asyncio
    async def test_default_mount_failure_resets_flag(self):
        """If _mount_minimap fails during auto-mount, _browse_minimap stays False."""
        app = _make_app(_browse_markers_enabled=True, _browse_minimap_default=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            # Patch before browse mode triggers the call
            with patch.object(
                app._svc_browse,
                "_mount_minimap",
                new_callable=AsyncMock,
                return_value=False,
            ):
                app.browse_mode = True
                await pilot.pause(0.2)
            # Flag must be False because mock returned False
            assert app._browse_minimap is False

    def test_mount_minimap_default_symbol_removed(self):
        """mount_minimap_default no longer exists on BrowseService (MMP-M6 deletion)."""
        from hermes_cli.tui.services.browse import BrowseService
        assert getattr(BrowseService, "mount_minimap_default", None) is None


# ---------------------------------------------------------------------------
# TestBlockedToggleHint — MMP-M7
# ---------------------------------------------------------------------------

class TestBlockedToggleHint:
    """Flash hint when toggle blocked by disabled markers (MMP-M7)."""

    @pytest.mark.asyncio
    async def test_blocked_toggle_flashes_hint(self):
        """_flash_hint called with expected message when markers disabled."""
        app = _make_app(_browse_markers_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()

            flash_calls: list = []
            original = app._flash_hint

            def _capture(msg, *args, **kwargs):
                flash_calls.append(msg)
                return original(msg, *args, **kwargs)

            with patch.object(app, "_flash_hint", side_effect=_capture):
                await app.action_toggle_minimap()
                await pilot.pause()

            assert any(
                "Anchor markers disabled" in m for m in flash_calls
            ), f"Expected hint not found in: {flash_calls}"

    @pytest.mark.asyncio
    async def test_blocked_toggle_does_not_mount(self):
        """No BrowseMinimap mounts when markers are disabled."""
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        from textual.css.query import NoMatches

        app = _make_app(_browse_markers_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()
            await app.action_toggle_minimap()
            await pilot.pause()

            try:
                app.query_one(BrowseMinimap)
                found = True
            except NoMatches:
                found = False
            assert not found
            assert app._browse_minimap is False

    @pytest.mark.asyncio
    async def test_unblocked_toggle_no_hint(self):
        """_flash_hint is NOT called when markers are enabled and toggle proceeds."""
        app = _make_app(_browse_markers_enabled=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.browse_mode = True
            await pilot.pause()

            flash_calls: list = []

            def _capture(msg, *args, **kwargs):
                flash_calls.append(msg)

            with patch.object(app, "_flash_hint", side_effect=_capture):
                await app.action_toggle_minimap()
                await pilot.pause()

            marker_hints = [m for m in flash_calls if "Anchor markers disabled" in m]
            assert not marker_hints, f"Unexpected hint fired: {marker_hints}"


# ---------------------------------------------------------------------------
# TestHelpOverlay — MMP-M8 (xfail — no browse help overlay yet)
# ---------------------------------------------------------------------------

class TestHelpOverlay:
    """MMP-M8: browse help overlay showing \\ binding — DEFERRED (BHO spec)."""

    @pytest.mark.xfail(
        reason="MMP-M8 DEFERRED: no browse-mode-specific help overlay exists yet; "
               "tracked for BHO spec implementation",
        strict=True,
    )
    def test_browse_help_overlay_exists_or_documented(self):
        """A browse-mode help overlay class should be importable and list the \\ binding."""
        # This will fail until the BHO spec is implemented.
        from hermes_cli.tui.overlays import BrowseHelpOverlay  # noqa: F401 — expected ImportError
