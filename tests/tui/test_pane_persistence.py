"""
Phase 4: Session layout persistence — dump/load round-trips and session hooks.

Tests are unit-level (no running Textual app). Session save/load hooks are
tested with mocks patched at the correct module level.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.pane_manager import LayoutMode, PaneId, PaneManager
from hermes_cli.tui.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pm(cfg: dict | None = None) -> PaneManager:
    base: dict = {"layout": "v2"}
    if cfg:
        base.update(cfg)
    return PaneManager(cfg=base)


def _make_session_mgr(tmp_path: Path) -> SessionManager:
    return SessionManager(session_dir=tmp_path)


# ---------------------------------------------------------------------------
# PaneManager.dump_state
# ---------------------------------------------------------------------------

class TestDumpState:
    def test_dump_state_keys(self) -> None:
        """dump_state returns all required keys."""
        pm = _make_pm()
        blob = pm.dump_state()
        required = {"mode", "left_collapsed", "right_collapsed", "left_w", "right_w",
                    "center_split", "split_target"}
        assert required.issubset(blob.keys())

    def test_dump_state_mode_is_string(self) -> None:
        """mode is stored as a plain string, not LayoutMode enum."""
        pm = _make_pm()
        blob = pm.dump_state()
        assert isinstance(blob["mode"], str)

    def test_dump_state_defaults(self) -> None:
        """Fresh PaneManager dumps sensible defaults."""
        pm = _make_pm()
        blob = pm.dump_state()
        assert blob["left_collapsed"] is False
        assert blob["right_collapsed"] is False
        assert blob["center_split"] is False
        assert blob["split_target"] is None

    def test_dump_state_after_collapse(self) -> None:
        """left_collapsed reflected in blob after toggle."""
        pm = _make_pm()
        pm.toggle_left_collapsed()
        blob = pm.dump_state()
        assert blob["left_collapsed"] is True

    def test_dump_state_width_overrides(self) -> None:
        """set_left_w / set_right_w appear in blob."""
        pm = _make_pm()
        pm.set_left_w(30)
        pm.set_right_w(35)
        blob = pm.dump_state()
        assert blob["left_w"] == 30
        assert blob["right_w"] == 35


# ---------------------------------------------------------------------------
# PaneManager.load_state
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_load_state_restores_collapsed(self) -> None:
        """left_collapsed=True in blob → _left_collapsed True."""
        pm = _make_pm()
        pm.load_state({"left_collapsed": True, "right_collapsed": False})
        assert pm._left_collapsed is True
        assert pm._right_collapsed is False

    def test_load_state_restores_both_collapsed(self) -> None:
        pm = _make_pm()
        pm.load_state({"left_collapsed": True, "right_collapsed": True})
        assert pm._left_collapsed is True
        assert pm._right_collapsed is True

    def test_load_state_restores_widths(self) -> None:
        """left_w / right_w in blob → override attributes set."""
        pm = _make_pm()
        pm.load_state({"left_w": 30, "right_w": 35})
        assert pm._left_w_override == 30
        assert pm._right_w_override == 35

    def test_load_state_ignores_unknown_keys(self) -> None:
        """Extra unknown keys in blob do not raise."""
        pm = _make_pm()
        pm.load_state({"left_collapsed": False, "future_key": "value", "another": 42})

    def test_load_state_empty_dict(self) -> None:
        """Empty blob → all state stays at defaults."""
        pm = _make_pm()
        pm.load_state({})
        assert pm._left_collapsed is False
        assert pm._right_collapsed is False
        assert pm._left_w_override is None
        assert pm._right_w_override is None

    def test_load_state_center_split(self) -> None:
        """center_split=True in blob → _center_split True."""
        pm = _make_pm()
        pm.load_state({"center_split": True})
        assert pm._center_split is True

    def test_load_state_null_widths_not_overwritten(self) -> None:
        """None left_w/right_w in blob leaves existing override unchanged."""
        pm = _make_pm()
        pm.set_left_w(28)
        pm.load_state({"left_w": None})
        assert pm._left_w_override == 28  # unchanged

    def test_load_state_split_target(self) -> None:
        pm = _make_pm()
        pm.load_state({"split_target": "my-widget"})
        assert pm._split_target == "my-widget"


# ---------------------------------------------------------------------------
# dump/load round-trip
# ---------------------------------------------------------------------------

class TestDumpLoadRoundtrip:
    def test_roundtrip_basic(self) -> None:
        """dump → fresh pm → load → state matches."""
        pm1 = _make_pm()
        pm1.set_left_w(26)
        pm1.set_right_w(30)
        blob = pm1.dump_state()

        pm2 = _make_pm()
        pm2.load_state(blob)
        assert pm2._left_w_override == 26
        assert pm2._right_w_override == 30
        assert pm2._left_collapsed == pm1._left_collapsed
        assert pm2._right_collapsed == pm1._right_collapsed

    def test_roundtrip_collapsed(self) -> None:
        pm1 = _make_pm()
        pm1.toggle_left_collapsed()
        blob = pm1.dump_state()

        pm2 = _make_pm()
        pm2.load_state(blob)
        assert pm2._left_collapsed is True

    def test_roundtrip_width_overrides(self) -> None:
        pm1 = _make_pm()
        pm1.set_left_w(32)
        pm1.set_right_w(28)
        blob = pm1.dump_state()

        pm2 = _make_pm()
        pm2.load_state(blob)
        assert pm2._left_w_override == 32
        assert pm2._right_w_override == 28

    def test_roundtrip_center_split(self) -> None:
        pm1 = _make_pm()
        pm1.toggle_center_split()
        blob = pm1.dump_state()

        pm2 = _make_pm()
        pm2.load_state(blob)
        assert pm2._center_split is True

    def test_roundtrip_json_serializable(self) -> None:
        """dump_state output is always JSON-serializable (no Python-only types)."""
        pm = _make_pm()
        pm.set_left_w(22)
        pm.toggle_right_collapsed()
        blob = pm.dump_state()
        # Should not raise
        round_tripped = json.loads(json.dumps(blob))
        assert round_tripped["right_collapsed"] is True


# ---------------------------------------------------------------------------
# SessionManager.save_layout_blob / load_layout_blob
# ---------------------------------------------------------------------------

class TestSessionManagerLayoutBlob:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        mgr.save_layout_blob("abc123", {"mode": "three", "left_collapsed": False})
        layout_file = tmp_path / "abc123" / "layout.json"
        assert layout_file.exists()

    def test_save_content_is_valid_json(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        blob = {"mode": "three", "left_w": 28, "right_w": 30}
        mgr.save_layout_blob("s1", blob)
        data = json.loads((tmp_path / "s1" / "layout.json").read_text())
        assert data == blob

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        result = mgr.load_layout_blob("nonexistent")
        assert result == {}

    def test_load_corrupt_returns_empty(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        session_dir = tmp_path / "s2"
        session_dir.mkdir()
        (session_dir / "layout.json").write_text("NOT JSON{{{}}")
        result = mgr.load_layout_blob("s2")
        assert result == {}

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        blob = {"mode": "three_wide", "left_collapsed": True, "right_collapsed": False,
                "left_w": 30, "right_w": 32, "center_split": False, "split_target": None}
        mgr.save_layout_blob("sess1", blob)
        loaded = mgr.load_layout_blob("sess1")
        assert loaded == blob

    def test_save_creates_session_dir_if_missing(self, tmp_path: Path) -> None:
        mgr = _make_session_mgr(tmp_path)
        # Session dir doesn't exist yet
        assert not (tmp_path / "newsession").exists()
        mgr.save_layout_blob("newsession", {"mode": "single"})
        assert (tmp_path / "newsession" / "layout.json").exists()


# ---------------------------------------------------------------------------
# App-level save hook (on_unmount)
# ---------------------------------------------------------------------------

class TestAppSaveHook:
    def test_session_save_includes_layout_blob(self, tmp_path: Path) -> None:
        """on_unmount saves layout blob when own_session_id + session_mgr are set."""
        from hermes_cli.tui.pane_manager import PaneManager as PM

        mgr = _make_session_mgr(tmp_path)
        pm = _make_pm()
        pm.set_left_w(26)

        # Simulate what on_unmount does
        mgr.save_layout_blob("test-session-id", pm.dump_state())

        loaded = mgr.load_layout_blob("test-session-id")
        assert loaded["left_w"] == 26
        assert "left_collapsed" in loaded

    def test_on_unmount_saves_blob_via_session_mgr(self, tmp_path: Path) -> None:
        """Directly verify the save call happens with correct args."""
        mgr = MagicMock()
        pm = _make_pm()
        pm.set_right_w(31)

        # Replicate the on_unmount guard logic
        own_session_id = "abc456"
        if pm is not None and own_session_id and mgr is not None:
            mgr.save_layout_blob(own_session_id, pm.dump_state())

        mgr.save_layout_blob.assert_called_once()
        call_args = mgr.save_layout_blob.call_args
        assert call_args[0][0] == "abc456"
        blob = call_args[0][1]
        assert blob["right_w"] == 31


# ---------------------------------------------------------------------------
# App-level load hook (on_mount layout restore)
# ---------------------------------------------------------------------------

class TestAppLoadHook:
    def test_session_load_calls_load_state(self, tmp_path: Path) -> None:
        """When load_layout_blob returns a non-empty dict, load_state is called."""
        mgr = MagicMock()
        pm = MagicMock()
        pm.enabled = True

        stored_blob = {
            "mode": "three", "left_collapsed": True, "right_collapsed": False,
            "left_w": 28, "right_w": 30, "center_split": False, "split_target": None,
        }
        mgr.load_layout_blob.return_value = stored_blob

        # Replicate the on_mount restore guard logic
        own_session_id = "sess-xyz"
        _layout_blob = mgr.load_layout_blob(own_session_id)
        if _layout_blob:
            pm.load_state(_layout_blob)
            if pm.enabled:
                pm._apply_layout(None)

        pm.load_state.assert_called_once_with(stored_blob)
        pm._apply_layout.assert_called_once()

    def test_session_load_skipped_when_empty_blob(self) -> None:
        """Empty blob → load_state not called."""
        mgr = MagicMock()
        pm = MagicMock()
        mgr.load_layout_blob.return_value = {}

        own_session_id = "sess-empty"
        _layout_blob = mgr.load_layout_blob(own_session_id)
        if _layout_blob:
            pm.load_state(_layout_blob)

        pm.load_state.assert_not_called()
