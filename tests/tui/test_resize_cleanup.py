"""Tests for RZ-CL-M1, RZ-CL-M2, RZ-CL-M8, RZ-CL-L2, RZ-CL-L5.

Spec: /home/xush/.hermes/spec_rz_cleanup.md
"""

from __future__ import annotations

import ast
import glob
import inspect
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TUI_DIR = Path(__file__).parent.parent.parent / "hermes_cli" / "tui"


def _collect_on_resize_nodes(exclude_files: "list[str] | None" = None) -> "list[tuple[str, ast.FunctionDef]]":
    """Walk hermes_cli/tui/**/*.py and return (filepath, node) for each on_resize FunctionDef."""
    exclude_files = exclude_files or []
    results = []
    pattern = str(TUI_DIR / "**" / "*.py")
    for filepath in glob.glob(pattern, recursive=True):
        fname = os.path.basename(filepath)
        if fname in exclude_files:
            continue
        try:
            source = Path(filepath).read_text()
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_resize":
                results.append((filepath, node))
    return results


# ---------------------------------------------------------------------------
# TestSizeSourceUnified (RZ-CL-M1)
# ---------------------------------------------------------------------------


class TestSizeSourceUnified:
    """M1: tools_overlay.py on_resize reads event.size.width, not self.app.size.width."""

    def test_tools_overlay_signature_takes_event(self) -> None:
        """on_resize must accept a positional `event` parameter."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        sig = inspect.signature(ToolsScreen.on_resize)
        params = [p for p in sig.parameters if p != "self"]
        assert len(params) == 1, f"Expected 1 non-self param, got {params}"
        assert params[0] == "event", f"Expected param named 'event', got {params[0]}"

    def test_tools_overlay_uses_event_size(self) -> None:
        """Dismiss triggers when event.size.width is narrow, even if app.size.width is wide."""
        from hermes_cli.tui.tools_overlay import ToolsScreen

        # Build a minimal mock instance — bypass the property descriptor by using __dict__
        instance = MagicMock(spec=ToolsScreen)
        instance._last_resize_w = 200
        instance._term_w = 200

        dismissed = []
        instance.dismiss_overlay.side_effect = lambda: dismissed.append(True)

        mock_app = MagicMock()
        mock_app.size.width = 200  # wide — should NOT influence the decision
        instance.app = mock_app

        # Fire a resize event with a narrow width
        mock_event = MagicMock()
        mock_event.size.width = 50  # narrow — should trigger dismiss

        ToolsScreen.on_resize(instance, mock_event)

        assert dismissed, "dismiss_overlay should have been called when event.size.width=50 < THRESHOLD_NARROW"


# ---------------------------------------------------------------------------
# TestNameplateDeltaConstant (RZ-CL-M2)
# ---------------------------------------------------------------------------


class TestNameplateDeltaConstant:
    """M2: NAMEPLATE_REFRESH_DELTA constant in resize_utils, used by nameplate."""

    def test_constant_in_resize_utils(self) -> None:
        from hermes_cli.tui.resize_utils import NAMEPLATE_REFRESH_DELTA
        assert NAMEPLATE_REFRESH_DELTA == 4

    def test_delta_below_constant_no_refresh(self) -> None:
        """Delta of 2 (<4) must not trigger refresh."""
        from hermes_cli.tui.widgets.nameplate import AssistantNameplate

        instance = object.__new__(AssistantNameplate)
        instance._canvas_width = 80  # type: ignore[attr-defined]
        instance._last_nameplate_w = 80  # type: ignore[attr-defined]

        refreshed = []
        instance.refresh = lambda: refreshed.append(True)  # type: ignore[attr-defined]

        mock_event = MagicMock()
        mock_event.size.width = 82  # delta == 2

        AssistantNameplate.on_resize(instance, mock_event)

        assert not refreshed, "refresh should NOT be called when delta < NAMEPLATE_REFRESH_DELTA"
        assert instance._last_nameplate_w == 82

    def test_delta_at_or_above_constant_refreshes(self) -> None:
        """Delta of exactly 4 (== NAMEPLATE_REFRESH_DELTA) must trigger refresh."""
        from hermes_cli.tui.widgets.nameplate import AssistantNameplate

        instance = object.__new__(AssistantNameplate)
        instance._canvas_width = 80  # type: ignore[attr-defined]
        instance._last_nameplate_w = 80  # type: ignore[attr-defined]

        refreshed = []
        instance.refresh = lambda: refreshed.append(True)  # type: ignore[attr-defined]

        mock_event = MagicMock()
        mock_event.size.width = 84  # delta == 4

        AssistantNameplate.on_resize(instance, mock_event)

        assert refreshed, "refresh should be called when delta >= NAMEPLATE_REFRESH_DELTA"
        assert instance._canvas_width == 84


# ---------------------------------------------------------------------------
# TestPaneManagerRename (RZ-CL-M8)
# ---------------------------------------------------------------------------


class TestPaneManagerRename:
    """M8: PaneManager.on_resize renamed to update_for_size."""

    def test_pane_manager_method_renamed(self) -> None:
        from hermes_cli.tui.pane_manager import PaneManager
        assert hasattr(PaneManager, "update_for_size"), "update_for_size must exist"
        assert not hasattr(PaneManager, "on_resize"), "on_resize must not exist"

    def test_app_calls_renamed_method(self) -> None:
        """app._flush_resize must call update_for_size, not pane_manager.on_resize."""
        from hermes_cli.tui import app as app_mod

        # The actual call to update_for_size is inside _flush_resize (debounce target)
        src = inspect.getsource(app_mod.HermesApp._flush_resize)
        assert "update_for_size" in src, "HermesApp._flush_resize must call update_for_size"
        # Confirm the old name is gone from _flush_resize
        # Strip the def line itself, then check no remaining "on_resize" call
        lines = src.splitlines()
        body = "\n".join(lines[1:])  # drop the def line
        assert "_pane_manager.on_resize" not in body, (
            "HermesApp._flush_resize must not call the old _pane_manager.on_resize"
        )


# ---------------------------------------------------------------------------
# TestInitialStateContract (RZ-CL-L2)
# ---------------------------------------------------------------------------


class TestInitialStateContract:
    """L2: initial_resize_state helper + crosses_threshold first-run guarantee."""

    def test_initial_state_helper_returns_zero(self) -> None:
        from hermes_cli.tui.resize_utils import initial_resize_state
        assert initial_resize_state() == 0

    def test_crosses_threshold_first_run_contract(self) -> None:
        """old=0 must trigger for each canonical threshold."""
        from hermes_cli.tui.resize_utils import crosses_threshold, HYSTERESIS
        canonical_thresholds = [40, 60, 80]
        for threshold in canonical_thresholds:
            result = crosses_threshold(0, threshold + HYSTERESIS, threshold)
            assert result is True, (
                f"crosses_threshold(0, {threshold + HYSTERESIS}, {threshold}) "
                f"should be True (first-run contract), got False"
            )


# ---------------------------------------------------------------------------
# TestEventTypeAnnotations (RZ-CL-L5) — AST lint gate
# ---------------------------------------------------------------------------

# Files excluded from the L5 gate (renamed by M8; deferred to RZ-OV-M4/M5)
_L5_EXCLUDE_FILES = {
    "pane_manager.py",   # non-handler renamed by M8
    "overlays.py",       # KeymapOverlay and HistorySearchOverlay deferred → RZ-OV-M4/M5
}


class TestEventTypeAnnotations:
    """L5: All on_resize handlers in hermes_cli/tui/**/*.py must use events.Resize annotation."""

    def test_no_handler_uses_any_or_object(self) -> None:
        """No on_resize handler may annotate its event param as Any or object (bare Name node)."""
        violations = []
        for filepath, node in _collect_on_resize_nodes(exclude_files=list(_L5_EXCLUDE_FILES)):
            # Get parameters other than self
            params = node.args.args[1:]  # skip self
            if not params:
                continue  # handled by next test
            first_param = params[0]
            ann = first_param.annotation
            if ann is None:
                continue  # unannotated — not a violation for this test
            # Check if annotation is a bare Name("Any") or Name("object")
            if isinstance(ann, ast.Name) and ann.id in ("Any", "object"):
                rel = os.path.relpath(filepath, TUI_DIR)
                violations.append(f"{rel}:{node.lineno} param '{first_param.arg}': {ann.id}")
        assert not violations, (
            "on_resize handlers must not use Any/object annotation:\n"
            + "\n".join(violations)
        )

    def test_no_handler_missing_event_param(self) -> None:
        """Every on_resize handler must have at least one param besides self, named event or _event."""
        violations = []
        for filepath, node in _collect_on_resize_nodes(exclude_files=list(_L5_EXCLUDE_FILES)):
            params = node.args.args[1:]  # skip self
            if not params:
                rel = os.path.relpath(filepath, TUI_DIR)
                violations.append(f"{rel}:{node.lineno} — no event parameter")
                continue
            first_name = params[0].arg
            if first_name not in ("event", "_event"):
                rel = os.path.relpath(filepath, TUI_DIR)
                violations.append(
                    f"{rel}:{node.lineno} — first param is '{first_name}', expected 'event' or '_event'"
                )
        assert not violations, (
            "on_resize handlers must have event/_event param:\n"
            + "\n".join(violations)
        )
