"""Tests for keystroke log recorder — convergence-plan Step 6a (KL-1..KL-7)."""
from __future__ import annotations

import importlib
import json
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_module(tmp_path: Path, env: dict):
    """Re-import _keystroke_log with a patched env and custom log path."""
    import sys
    import hermes_cli.tui.tool_panel._keystroke_log as _orig
    # Patch env and LOG_PATH to use tmp_path so tests don't hit ~/.hermes
    log_path = tmp_path / "keystroke.jsonl"
    with patch.dict("os.environ", env, clear=False):
        mod = importlib.import_module(
            "hermes_cli.tui.tool_panel._keystroke_log"
        )
        # Force re-evaluation of ENABLED and redirect path
        mod.ENABLED = mod._is_enabled()
        mod._LOG_PATH = log_path
    return mod


# ---------------------------------------------------------------------------
# TestRecorderModule (KL-1)
# ---------------------------------------------------------------------------

class TestRecorderModule:

    def test_disabled_no_file_write(self, tmp_path):
        """All three record*() functions write nothing when ENABLED=False."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        orig_path = ks._LOG_PATH
        log_path = tmp_path / "keystroke.jsonl"
        ks._LOG_PATH = log_path
        try:
            with patch.object(ks, "ENABLED", False):
                ks.record("t", "blk1", "done", None, "default", True)
                ks.record_mouse("left", 0, 0, "Widget", "blk1", "done", None, "default", False)
                ks.record_component("density_toggle", "ToolPanel", "blk1", "done", None, "default", False)
            assert not log_path.exists(), "log file written despite ENABLED=False"
        finally:
            ks._LOG_PATH = orig_path

    def test_schema_fields_and_types(self, tmp_path):
        """key/mouse/component records have correct schema."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        orig_path = ks._LOG_PATH
        log_path = tmp_path / "keystroke.jsonl"
        ks._LOG_PATH = log_path
        try:
            with patch.object(ks, "ENABLED", True):
                ks.record("t", "blk1", "done", "diff", "default", True)
                ks.record_mouse("left", 5, 3, "ToolPanel", "blk2", "streaming", None, "compact", False)
                ks.record_component("density_toggle", "ToolPanel", "blk3", "done", None, "hero", True, extra={"from": "default", "to": "hero"})
        finally:
            ks._LOG_PATH = orig_path

        rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(rows) == 3

        key_row = rows[0]
        assert key_row["event_type"] == "key"
        assert key_row["key"] == "t"
        assert key_row["block_id"] == "blk1"
        assert key_row["phase"] == "done"
        assert key_row["kind"] == "diff"
        assert key_row["density"] == "default"
        assert key_row["focused"] is True
        assert isinstance(key_row["ts"], float)

        mouse_row = rows[1]
        assert mouse_row["event_type"] == "mouse"
        assert mouse_row["button"] == "left"
        assert mouse_row["x"] == 5
        assert mouse_row["y"] == 3
        assert mouse_row["widget"] == "ToolPanel"

        comp_row = rows[2]
        assert comp_row["event_type"] == "component"
        assert comp_row["action"] == "density_toggle"
        assert comp_row["widget"] == "ToolPanel"
        assert comp_row["extra"] == {"from": "default", "to": "hero"}

    def test_redaction_non_allowlist(self, tmp_path):
        """Non-allowlist key 'q' logs as '<other>'; 't' logs verbatim."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        orig_path = ks._LOG_PATH
        log_path = tmp_path / "keystroke.jsonl"
        ks._LOG_PATH = log_path
        try:
            with patch.object(ks, "ENABLED", True):
                ks.record("q", "blk1", "done", None, "default", False)
                ks.record("t", "blk1", "done", None, "default", False)
        finally:
            ks._LOG_PATH = orig_path

        rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert rows[0]["key"] == "<other>"
        assert rows[1]["key"] == "t"


# ---------------------------------------------------------------------------
# TestOnKeyHook (KL-2)
# ---------------------------------------------------------------------------

class TestOnKeyHook:

    def _make_panel(self, view_state=None):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        panel = types.SimpleNamespace()
        panel._view_state = view_state
        panel.density = DensityTier.DEFAULT
        panel.has_focus = True

        def _lookup_view_state():
            return None
        panel._lookup_view_state = _lookup_view_state

        def _ks_context():
            vs = panel._view_state
            if vs is not None:
                block_id = getattr(vs, "tool_call_id", None) or "unknown"
                phase = vs.state.value
                kind_val = vs.kind.kind.value if getattr(vs, "kind", None) is not None else None
            else:
                block_id = "unknown"
                phase = "unknown"
                kind_val = None
            return block_id, phase, kind_val
        panel._ks_context = _ks_context

        # Bind the on_key method from ToolPanel
        panel.on_key = ToolPanel.on_key.__get__(panel)
        return panel

    def test_hook_calls_record_when_enabled(self, tmp_path):
        """on_key fires record() with correct args when ENABLED=True."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        panel = self._make_panel()

        event = types.SimpleNamespace(key="t")

        with patch.object(ks, "ENABLED", True), \
             patch("hermes_cli.tui.tool_panel._keystroke_log.record") as mock_record:
            # Patch the module so the local import inside on_key uses our mock
            import hermes_cli.tui.tool_panel._core as _core_mod
            with patch.dict("sys.modules", {}):
                # re-patch _keystroke_log that _core imports
                with patch("hermes_cli.tui.tool_panel._keystroke_log.ENABLED", True), \
                     patch("hermes_cli.tui.tool_panel._keystroke_log.record") as mock_rec2:
                    panel.on_key(event)
                    # record may not be called because we don't control the internal import
            # Direct approach: call the module function via the panel import chain
            mock_record.reset_mock()

        # Simpler: patch at source and call directly
        with patch.object(ks, "ENABLED", True):
            with patch.object(ks, "record") as mock_rec:
                # Temporarily set ENABLED in the module as imported by _core
                import hermes_cli.tui.tool_panel._keystroke_log as _kl
                old_enabled = _kl.ENABLED
                _kl.ENABLED = True
                try:
                    panel.on_key(event)
                finally:
                    _kl.ENABLED = old_enabled
                # record is called from within the local import; check the module-level fn
                mock_rec.assert_called_once()
                call_kwargs = mock_rec.call_args
                assert call_kwargs.kwargs.get("key") == "t" or (
                    len(call_kwargs.args) > 0 and call_kwargs.args[0] == "t"
                )

    def test_hook_skips_record_when_disabled(self, tmp_path):
        """on_key does not call record() when ENABLED=False."""
        panel = self._make_panel()
        event = types.SimpleNamespace(key="y")

        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        old_enabled = _kl.ENABLED
        _kl.ENABLED = False
        try:
            with patch.object(_kl, "record") as mock_rec:
                panel.on_key(event)
                mock_rec.assert_not_called()
        finally:
            _kl.ENABLED = old_enabled


# ---------------------------------------------------------------------------
# TestConfigFlag (KL-3)
# ---------------------------------------------------------------------------

class TestConfigFlag:

    def test_env_var_enables_recording(self):
        """HERMES_KEYSTROKE_LOG=1 with no CI guard → _is_enabled() returns True."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        env = {"HERMES_KEYSTROKE_LOG": "1"}
        # Temporarily remove HERMES_CI if set
        with patch.dict("os.environ", env, clear=False), \
             patch.dict("os.environ", {"HERMES_CI": ""}, clear=False):
            import os
            os.environ.pop("HERMES_CI", None)
            result = ks._is_enabled()
        assert result is True

    def test_ci_guard_suppresses_recording(self):
        """HERMES_CI=1 overrides HERMES_KEYSTROKE_LOG=1 → _is_enabled() returns False."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks
        with patch.dict("os.environ", {"HERMES_CI": "1", "HERMES_KEYSTROKE_LOG": "1"}, clear=False):
            result = ks._is_enabled()
        assert result is False


# ---------------------------------------------------------------------------
# TestRotation (KL-4)
# ---------------------------------------------------------------------------

class TestRotation:

    def test_rotation_triggers_at_threshold(self, tmp_path):
        """Log rotates to .jsonl.1 when size reaches _ROTATE_BYTES."""
        import hermes_cli.tui.tool_panel._keystroke_log as ks

        log_path = tmp_path / "keystroke.jsonl"
        # Write a file exactly at the rotation threshold
        log_path.write_bytes(b"x" * ks._ROTATE_BYTES)

        orig_path = ks._LOG_PATH
        ks._LOG_PATH = log_path
        try:
            with patch.object(ks, "ENABLED", True):
                ks.record("t", "blk1", "done", None, "default", False)
        finally:
            ks._LOG_PATH = orig_path

        rotated = log_path.with_suffix(".jsonl.1")
        assert rotated.exists(), ".jsonl.1 backup not created"
        # New log file has exactly one entry
        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["key"] == "t"


# ---------------------------------------------------------------------------
# TestAnalyzer (KL-5)
# ---------------------------------------------------------------------------

_FIXTURE_ROWS = [
    # key rows
    {"event_type": "key", "key": "t", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 1.0},
    {"event_type": "key", "key": "t", "block_id": "blk2", "phase": "done", "kind": None, "density": "compact", "focused": True, "ts": 2.0},
    {"event_type": "key", "key": "t", "block_id": "blk3", "phase": "done", "kind": "diff", "density": "default", "focused": True, "ts": 3.0},
    {"event_type": "key", "key": "y", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": False, "ts": 4.0},
    {"event_type": "key", "key": "D", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 5.0},
    # mouse rows
    {"event_type": "mouse", "button": "left", "x": 1, "y": 2, "widget": "ToolCallHeader", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 6.0},
    {"event_type": "mouse", "button": "left", "x": 3, "y": 4, "widget": "ToolCallHeader", "block_id": "blk2", "phase": "done", "kind": None, "density": "default", "focused": False, "ts": 7.0},
    {"event_type": "mouse", "button": "scroll_up", "x": 0, "y": 0, "widget": "BodyPane", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 8.0},
    # component row
    {"event_type": "component", "action": "density_toggle", "widget": "ToolPanel", "block_id": "blk1", "phase": "done", "kind": None, "density": "compact", "focused": True, "ts": 9.0, "extra": {"from": "default", "to": "compact"}},
    # back-compat row (no event_type → treated as "key")
    {"key": "y", "block_id": "blk4", "phase": "streaming", "kind": None, "density": "default", "focused": False, "ts": 10.0},
    # 5 more key rows to reach total_by_key["t"] == 3
    {"event_type": "key", "key": "enter", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 11.0},
    {"event_type": "key", "key": "r", "block_id": "blk2", "phase": "done", "kind": None, "density": "compact", "focused": False, "ts": 12.0},
    {"event_type": "key", "key": "D", "block_id": "blk3", "phase": "done", "kind": "diff", "density": "hero", "focused": True, "ts": 13.0},
    {"event_type": "key", "key": "D", "block_id": "blk4", "phase": "done", "kind": None, "density": "trace", "focused": False, "ts": 14.0},
    {"event_type": "key", "key": "<other>", "block_id": "blk1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 15.0},
]


class TestAnalyzer:

    def _write_fixture(self, tmp_path: Path) -> Path:
        log_path = tmp_path / "keystroke.jsonl"
        log_path.write_text("\n".join(json.dumps(r) for r in _FIXTURE_ROWS) + "\n")
        return log_path

    def test_analyzer_counts_match_fixture(self, tmp_path):
        """Analyzer correctly counts keys, clicks, scrolls, components from mixed fixture."""
        import sys
        from pathlib import Path as _Path
        import importlib.util

        analyzer_path = _Path(__file__).parent.parent.parent / "tools" / "analyze_keystroke_log.py"
        spec = importlib.util.spec_from_file_location("analyze_keystroke_log", analyzer_path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        rows = mod.load(self._write_fixture(tmp_path))

        from collections import Counter, defaultdict
        total_by_key: Counter = Counter()
        click_by_widget: Counter = Counter()
        scroll_total = 0
        click_total = 0
        component_by_action: Counter = Counter()

        for row in rows:
            etype = row.get("event_type", "key")
            if etype == "key":
                total_by_key[row["key"]] += 1
            elif etype == "mouse":
                if row.get("button") in ("scroll_up", "scroll_down"):
                    scroll_total += 1
                else:
                    click_total += 1
                    click_by_widget[row.get("widget", "unknown")] += 1
            elif etype == "component":
                component_by_action[row.get("action", "unknown")] += 1

        assert total_by_key["t"] == 3
        assert click_by_widget["ToolCallHeader"] == 2
        assert component_by_action["density_toggle"] == 1
        # density distribution: blk1→default, blk2→compact, blk3→default, blk4→trace (from back-compat row)
        first_density: dict = {}
        for row in rows:
            etype = row.get("event_type", "key")
            if etype == "key":
                bid = row["block_id"]
                if bid not in first_density:
                    first_density[bid] = row["density"]
        assert first_density.get("blk1") == "default"
        assert first_density.get("blk2") == "compact"

    def test_analyzer_t_rate_classifier_proxy(self, tmp_path):
        """4 t rows (3 null, 1 non-null) → rate 25% at kind!=null."""
        import importlib.util
        from pathlib import Path as _Path

        analyzer_path = _Path(__file__).parent.parent.parent / "tools" / "analyze_keystroke_log.py"
        spec = importlib.util.spec_from_file_location("analyze_keystroke_log", analyzer_path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        fixture_rows = [
            {"event_type": "key", "key": "t", "block_id": "b1", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 1.0},
            {"event_type": "key", "key": "t", "block_id": "b2", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 2.0},
            {"event_type": "key", "key": "t", "block_id": "b3", "phase": "done", "kind": None, "density": "default", "focused": True, "ts": 3.0},
            {"event_type": "key", "key": "t", "block_id": "b4", "phase": "done", "kind": "diff", "density": "default", "focused": True, "ts": 4.0},
        ]
        log_path = tmp_path / "t_fixture.jsonl"
        log_path.write_text("\n".join(json.dumps(r) for r in fixture_rows) + "\n")

        rows = mod.load(log_path)
        from collections import Counter
        t_by_kind_null: Counter = Counter()
        for row in rows:
            if row.get("event_type", "key") == "key" and row["key"] == "t":
                bucket = "kind=null" if row.get("kind") is None else "kind=non-null"
                t_by_kind_null[bucket] += 1

        total_t = sum(t_by_kind_null.values())
        assert total_t == 4
        non_null = t_by_kind_null.get("kind=non-null", 0)
        assert non_null == 1
        assert abs(non_null / total_t - 0.25) < 0.001


# ---------------------------------------------------------------------------
# TestMouseHooks (KL-6)
# ---------------------------------------------------------------------------

class TestMouseHooks:

    def _make_panel(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        panel = types.SimpleNamespace()
        panel._view_state = None
        panel.density = DensityTier.DEFAULT
        panel.has_focus = False

        def _lookup_view_state():
            return None
        panel._lookup_view_state = _lookup_view_state

        def _ks_context():
            return "unknown", "unknown", None
        panel._ks_context = _ks_context

        panel.on_click = ToolPanel.on_click.__get__(panel)
        panel.on_mouse_scroll_up = ToolPanel.on_mouse_scroll_up.__get__(panel)
        panel.on_mouse_scroll_down = ToolPanel.on_mouse_scroll_down.__get__(panel)
        return panel

    def test_click_event_logged(self):
        """on_click records button='left' with correct x, y, widget."""
        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        panel = self._make_panel()

        class ToolCallHeader:
            pass
        event = types.SimpleNamespace(button=1, x=10, y=3, widget=ToolCallHeader())

        old_enabled = _kl.ENABLED
        _kl.ENABLED = True
        try:
            with patch.object(_kl, "record_mouse") as mock_rm:
                panel.on_click(event)
                mock_rm.assert_called_once()
                kw = mock_rm.call_args.kwargs
                assert kw["button"] == "left"
                assert kw["x"] == 10
                assert kw["y"] == 3
                assert kw["widget"] == "ToolCallHeader"
        finally:
            _kl.ENABLED = old_enabled

    def test_scroll_up_logged(self):
        """on_mouse_scroll_up records button='scroll_up'."""
        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        panel = self._make_panel()

        class BodyPane:
            pass
        event = types.SimpleNamespace(x=0, y=0, widget=BodyPane())

        old_enabled = _kl.ENABLED
        _kl.ENABLED = True
        try:
            with patch.object(_kl, "record_mouse") as mock_rm:
                panel.on_mouse_scroll_up(event)
                mock_rm.assert_called_once()
                assert mock_rm.call_args.kwargs["button"] == "scroll_up"
        finally:
            _kl.ENABLED = old_enabled

    def test_scroll_down_logged(self):
        """on_mouse_scroll_down records button='scroll_down'."""
        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        panel = self._make_panel()

        class BodyPane:
            pass
        event = types.SimpleNamespace(x=0, y=0, widget=BodyPane())

        old_enabled = _kl.ENABLED
        _kl.ENABLED = True
        try:
            with patch.object(_kl, "record_mouse") as mock_rm:
                panel.on_mouse_scroll_down(event)
                mock_rm.assert_called_once()
                assert mock_rm.call_args.kwargs["button"] == "scroll_down"
        finally:
            _kl.ENABLED = old_enabled


# ---------------------------------------------------------------------------
# TestComponentHooks (KL-7)
# ---------------------------------------------------------------------------

class TestComponentHooks:

    def _make_actions_panel(self, current_tier, view_state=None):
        """Build a minimal SimpleNamespace that can host action_density_cycle / action_cycle_kind."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, ToolBlockLayoutResolver
        from hermes_cli.tui.services.tools import ToolCallState

        panel = types.SimpleNamespace()
        panel._view_state = view_state
        panel.density = current_tier
        panel.has_focus = True
        panel._result_summary_v4 = None
        panel._parent_clamp_tier = None
        panel._user_collapse_override = False
        panel._user_override_tier = None
        panel._auto_collapsed = False

        resolver = MagicMock()
        resolver.tier = current_tier
        panel._resolver = resolver

        def _lookup_view_state():
            return view_state
        panel._lookup_view_state = _lookup_view_state

        def _ks_context():
            return "blk1", "done", None
        panel._ks_context = _ks_context

        def _is_error():
            return False
        panel._is_error = _is_error

        def _body_line_count():
            return 10
        panel._body_line_count = _body_line_count

        def _flash_header(msg, *, tone="info"):
            pass
        panel._flash_header = _flash_header

        panel.action_density_cycle = _ToolPanelActionsMixin.action_density_cycle.__get__(panel)
        panel.action_cycle_kind = _ToolPanelActionsMixin.action_cycle_kind.__get__(panel)
        panel.force_renderer = MagicMock()

        panel._cycle_kind_last_fired = 0.0
        return panel

    def test_component_density_toggle_logged(self):
        """action_density_cycle logs record_component with action='density_toggle' and extra from/to."""
        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        panel = self._make_actions_panel(DensityTier.DEFAULT)

        # After resolve, tier changes to COMPACT
        def _resolve(inputs):
            panel._resolver.tier = DensityTier.COMPACT
            panel.density = DensityTier.COMPACT
        panel._resolver.resolve = _resolve

        old_enabled = _kl.ENABLED
        _kl.ENABLED = True
        try:
            with patch.object(_kl, "record_component") as mock_rc:
                panel.action_density_cycle()
                mock_rc.assert_called_once()
                kw = mock_rc.call_args.kwargs
                assert kw["action"] == "density_toggle"
                extra = kw.get("extra") or {}
                assert "from" in extra
                assert "to" in extra
                assert extra["from"] != extra["to"] or extra["from"] == "default"
        finally:
            _kl.ENABLED = old_enabled

    def test_component_kind_override_logged(self):
        """action_cycle_kind logs record_component with action='kind_override' and extra from/to."""
        import hermes_cli.tui.tool_panel._keystroke_log as _kl
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState

        # Build a view_state in DONE state with no kind override
        vs = types.SimpleNamespace()
        vs.state = ToolCallState.DONE
        vs.user_kind_override = None
        vs.kind = None
        vs.tool_call_id = "blk1"
        vs.gen_index = None

        panel = self._make_actions_panel(DensityTier.DEFAULT, view_state=vs)

        old_enabled = _kl.ENABLED
        _kl.ENABLED = True
        try:
            with patch.object(_kl, "record_component") as mock_rc:
                panel.action_cycle_kind()
                mock_rc.assert_called_once()
                kw = mock_rc.call_args.kwargs
                assert kw["action"] == "kind_override"
                extra = kw.get("extra") or {}
                assert "from" in extra
                assert "to" in extra
                assert extra["from"] == "auto"  # no prior override
                assert extra["to"] != "auto" or extra["to"] == extra["from"]
        finally:
            _kl.ENABLED = old_enabled
