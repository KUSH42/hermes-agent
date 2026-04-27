"""AB-1..AB-3 — axis bus sweep follow-up to IL gates (Step 3A)."""
from __future__ import annotations

import ast
import inspect
import textwrap
import types
import typing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SRC_ROOT = Path(__file__).parent.parent.parent / "hermes_cli" / "tui"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view(**kwargs):
    defaults = dict(
        state=None,
        kind=None,
        density=None,
        streaming_kind_hint=None,
        user_kind_override=None,
        is_error=False,
        dur_ms=None,
        block=None,
        exit_code=None,
        error_category=None,
        stderr_tail=None,
        _watchers=[],
    )
    defaults.update(kwargs)
    v = types.SimpleNamespace(**defaults)
    v._watchers = list(v._watchers)  # ensure each call gets its own list
    return v


def _make_header(is_attached: bool = True):
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    # ToolHeader owns _on_axis_change + _streaming_kind_hint (not ToolCallHeader)
    header = object.__new__(ToolHeader)
    header._streaming_kind_hint = None
    type(header).is_attached = property(lambda self: is_attached)
    header.refresh = MagicMock()
    return header


# ---------------------------------------------------------------------------
# TestAB1KindAxisClearsStreamingHint
# ---------------------------------------------------------------------------

class TestAB1KindAxisClearsStreamingHint:
    def test_kind_axis_change_clears_streaming_hint(self):
        """kind axis fires → hint cleared, refresh called."""
        header = _make_header(is_attached=True)
        header._streaming_kind_hint = "json"
        view = _make_view(streaming_kind_hint="json")

        header._on_axis_change(view, "kind", None, "json")

        assert header._streaming_kind_hint is None
        header.refresh.assert_called_once()

    def test_kind_axis_when_no_hint_present_no_op(self):
        """kind axis fires when hint already None → no refresh."""
        header = _make_header(is_attached=True)
        header._streaming_kind_hint = None
        view = _make_view(streaming_kind_hint=None)

        header._on_axis_change(view, "kind", None, "log")

        assert header._streaming_kind_hint is None
        header.refresh.assert_not_called()

    def test_kind_axis_change_with_unmounted_header_does_not_refresh(self):
        """kind axis fires, is_attached=False → hint cleared but no refresh."""
        header = _make_header(is_attached=False)
        header._streaming_kind_hint = "text"
        view = _make_view(streaming_kind_hint="text")

        header._on_axis_change(view, "kind", None, "text")

        assert header._streaming_kind_hint is None
        header.refresh.assert_not_called()

    def test_force_renderer_clears_hint_before_override_write(self):
        """force_renderer calls set_axis(streaming_kind_hint, None) when hint is set."""
        from hermes_cli.tui.services import tools as tools_mod

        set_axis_calls = []
        original_set_axis = tools_mod.set_axis

        def spy_set_axis(v, axis, value):
            set_axis_calls.append((axis, value))
            original_set_axis(v, axis, value)

        view = _make_view(streaming_kind_hint="text")

        panel = MagicMock()
        panel._view_state = view
        panel._lookup_view_state = MagicMock(return_value=view)
        panel.copy_content = MagicMock(return_value="output")
        panel._tool_name = "test_tool"
        panel._category = "shell"
        panel._tool_args = {}
        panel._body_line_count = MagicMock(return_value=0)
        panel._swap_renderer = MagicMock()

        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        with patch.object(tools_mod, "set_axis", side_effect=spy_set_axis):
            # Import pick_renderer after patching so inner import in force_renderer uses spy
            with patch("hermes_cli.tui.body_renderers.pick_renderer", MagicMock(return_value=MagicMock())):
                _ToolPanelActionsMixin.force_renderer(panel, "log")

        hint_clears = [(ax, v) for ax, v in set_axis_calls if ax == "streaming_kind_hint" and v is None]
        assert hint_clears, (
            f"set_axis(streaming_kind_hint, None) not called; all set_axis calls: {set_axis_calls}"
        )

    def test_force_renderer_revert_clears_hint(self):
        """action_kind_revert clears hint via set_axis before setting user_kind_override=None."""
        from hermes_cli.tui.services import tools as tools_mod

        hint_cleared = []
        original_set_axis = tools_mod.set_axis

        def spy_set_axis(v, axis, value):
            if axis == "streaming_kind_hint" and value is None:
                hint_cleared.append(True)
            original_set_axis(v, axis, value)

        view = _make_view(streaming_kind_hint="json", user_kind_override="json")

        panel = MagicMock()
        panel._view_state = view
        panel._lookup_view_state = MagicMock(return_value=view)
        panel.force_renderer = MagicMock()
        panel._flash_header = MagicMock()

        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        with patch.object(tools_mod, "set_axis", side_effect=spy_set_axis):
            _ToolPanelActionsMixin.action_kind_revert(panel)

        assert hint_cleared, "set_axis(streaming_kind_hint, None) must be called on revert"
        assert view.user_kind_override is None


# ---------------------------------------------------------------------------
# TestAB2NoPostStateWrites
# ---------------------------------------------------------------------------

class TestAB2NoPostStateWrites:
    def _get_terminalize_src(self) -> str:
        from hermes_cli.tui.services.tools import ToolRenderingService
        src = inspect.getsource(ToolRenderingService._terminalize_tool_view)
        return textwrap.dedent(src)

    def _find_svs_lineno(self, tree: ast.AST) -> int:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "_set_view_state"
            ):
                return node.lineno
        return -1

    def test_terminalize_writes_is_error_before_state(self):
        """view.is_error is set BEFORE _set_view_state is called."""
        from hermes_cli.tui.services.tools import ToolRenderingService

        seen_is_error_at_svs = []

        # Build a svc stub with all app-related attributes mocked out
        svc = MagicMock(spec=ToolRenderingService)
        svc._tool_views_by_id = {}
        svc._tool_views_by_gen_index = {}
        svc._open_tool_count = 1
        svc._agent_stack = []
        svc._turn_tool_calls = {}
        svc._panel_for_block = MagicMock(return_value=None)
        svc.app = MagicMock()
        svc.app._active_streaming_blocks = {"t1": MagicMock()}
        svc.app._streaming_tool_count = 1
        svc.app._active_tool_name = ""
        svc.app.agent_running = False

        # Wire the spy directly onto the instance (svc is a MagicMock; direct assignment
        # overrides the MagicMock attribute so the real method body calls the spy).
        def spy_svs(v, state):
            seen_is_error_at_svs.append(v.is_error)

        svc._set_view_state = spy_svs

        view = _make_view(gen_index=None)
        from hermes_cli.tui.services.tools import ToolCallState
        terminal_state = ToolCallState.DONE

        ToolRenderingService._terminalize_tool_view(
            svc,
            tool_call_id="t1",
            view=view,
            terminal_state=terminal_state,
            is_error=True,
        )

        assert seen_is_error_at_svs, "_set_view_state was never called"
        assert seen_is_error_at_svs[0] is True, (
            f"view.is_error was {seen_is_error_at_svs[0]} when _set_view_state fired; "
            "must be True (pre-state write)"
        )

    def test_terminalize_no_post_state_writes(self):
        """AST: zero `view.*` attribute writes after _set_view_state call."""
        src = self._get_terminalize_src()
        tree = ast.parse(src)
        svs_line = self._find_svs_lineno(tree)
        assert svs_line != -1, "Could not locate _set_view_state call in AST"

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and node.lineno > svs_line:
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "view"
                    ):
                        violations.append((node.lineno, target.attr))

        assert violations == [], (
            f"Post-state view.* mutations found (R3-AXIS-03 violation): {violations}"
        )

    def test_double_write_meta_inverse_caught(self):
        """AST walker flags synthetic function with post-state write."""
        synthetic_src = textwrap.dedent("""
        def fake_terminalize(self, view):
            view.is_error = False
            self._set_view_state(view, "done")
            view.is_error = True
        """)
        tree = ast.parse(synthetic_src)
        svs_line = -1
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "_set_view_state"
            ):
                svs_line = node.lineno
                break

        assert svs_line != -1
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and node.lineno > svs_line:
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "view"
                    ):
                        violations.append((node.lineno, target.attr))

        assert violations != [], "AST walker must catch post-state writes in synthetic source"


# ---------------------------------------------------------------------------
# TestAB3WatcherCoversAllAxes
# ---------------------------------------------------------------------------

class TestAB3WatcherCoversAllAxes:
    def _get_axis_names(self) -> list[str]:
        from hermes_cli.tui.services.tools import AxisName
        return list(typing.get_args(AxisName))

    def _find_watcher_names(self) -> list[tuple[str, str]]:
        """Return (file_path, watcher_name) for every add_axis_watcher call site."""
        results = []
        for py in SRC_ROOT.rglob("*.py"):
            src = py.read_text()
            if "add_axis_watcher" not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # Match both `add_axis_watcher(...)` and `mod.add_axis_watcher(...)`
                func = node.func
                is_match = (
                    (isinstance(func, ast.Name) and func.id == "add_axis_watcher")
                    or (isinstance(func, ast.Attribute) and func.attr == "add_axis_watcher")
                )
                if not is_match or len(node.args) != 2:
                    continue
                arg = node.args[1]
                if isinstance(arg, ast.Attribute):
                    name = arg.attr
                elif isinstance(arg, ast.Name):
                    name = arg.id
                else:
                    name = ast.unparse(arg)
                results.append((str(py), name))
        return results

    def _get_watcher_src(self, watcher_name: str) -> str | None:
        for py in SRC_ROOT.rglob("*.py"):
            src = py.read_text()
            if watcher_name not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == watcher_name:
                        return ast.unparse(node)
        return None

    def _axes_handled(self, watcher_src: str) -> set[str]:
        tree = ast.parse(watcher_src)
        handled = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                left = node.left
                # axis == "x"
                if (
                    isinstance(left, ast.Name) and left.id == "axis"
                    and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
                    and isinstance(node.comparators[0], ast.Constant)
                ):
                    handled.add(node.comparators[0].value)
                # axis in ("a", "b")
                if (
                    isinstance(left, ast.Name) and left.id == "axis"
                    and len(node.ops) == 1 and isinstance(node.ops[0], ast.In)
                    and isinstance(node.comparators[0], (ast.Tuple, ast.List))
                ):
                    for elt in node.comparators[0].elts:
                        if isinstance(elt, ast.Constant):
                            handled.add(elt.value)
        return handled

    def _opt_out_axes(self, watcher_name: str) -> set[str]:
        """Return axis names opted-out via `# AB-3: <axis> not relevant` comment."""
        opted_out = set()
        for py in SRC_ROOT.rglob("*.py"):
            src = py.read_text()
            if watcher_name not in src and "AB-3:" not in src:
                continue
            in_watcher = False
            for line in src.splitlines():
                if f"def {watcher_name}" in line:
                    in_watcher = True
                if in_watcher and "AB-3:" in line and "not relevant" in line:
                    after = line.split("AB-3:")[1].strip()
                    axis = after.split()[0].rstrip(":")
                    opted_out.add(axis)
        return opted_out

    def test_axis_watchers_handle_all_view_axes(self):
        """Every registered watcher handles all AxisName axes or opts out explicitly."""
        axis_names = self._get_axis_names()
        assert axis_names, "AxisName must enumerate at least one axis"

        watcher_sites = self._find_watcher_names()
        assert watcher_sites, (
            "No add_axis_watcher call sites found — test guards against vacuous pass"
        )

        for site, watcher_name in watcher_sites:
            watcher_src = self._get_watcher_src(watcher_name)
            assert watcher_src is not None, (
                f"Could not locate source for watcher '{watcher_name}' (at {site})"
            )
            handled = self._axes_handled(watcher_src)
            opted_out = self._opt_out_axes(watcher_name)
            accounted = handled | opted_out
            missing = set(axis_names) - accounted
            assert not missing, (
                f"Watcher '{watcher_name}' does not account for axes: {sorted(missing)}. "
                f"Add a branch or '# AB-3: <axis> not relevant: <reason>' annotation."
            )
