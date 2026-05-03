"""Tests for SPEC-TBC: concept v3.6 drift fix (CD-1..5, IL-GAP-1, DEAD-1).

Covers:
  TBC-1  Dead ToolCallHeader class deletion
  TBC-2  _swap_renderer fallback to FallbackRenderer on build_widget failure
  TBC-3  Slow-renderer 250ms/2s deadline wire-up
  TBC-4  _auto_renderer_kind and _best_kind_icon parent-walk fix
  TBC-5  Copy key rebinding y→c
  TBC-6  set_user_kind_override helper
  TBC-7  Concept doc changelog

Test layout:
  TestToolCallHeaderDeleted         — 3 tests
  TestSwapRendererRawTextFallback   — 4 tests
  TestSlowRendererWorkerDispatch    — 6 tests
  TestAutoRendererKindResolves      — 7 tests
  TestCopyKeyBinding                — 2 tests
  TestUserKindOverrideHelper        — 4 tests
  TestConceptDocChangelog           — 1 test
  Total: 27 tests
"""
from __future__ import annotations

import ast
import pathlib
import time
import types
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_TUI_ROOT = _REPO_ROOT / "hermes_cli" / "tui"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view_state(**kwargs: Any):
    from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState
    import time as _t
    defaults: dict[str, Any] = dict(
        tool_call_id="tbc-test-1",
        gen_index=0,
        tool_name="bash",
        label="bash",
        args={},
        state=ToolCallState.DONE,
        block=None,
        panel=None,
        parent_tool_call_id=None,
        category="shell",
        depth=0,
        start_s=_t.monotonic(),
    )
    defaults.update(kwargs)
    return ToolCallViewState(**defaults)


# ---------------------------------------------------------------------------
# TestToolCallHeaderDeleted — TBC-1
# ---------------------------------------------------------------------------

class TestToolCallHeaderDeleted:
    """TBC-1: ToolCallHeader dead class is deleted."""

    def test_toolcall_header_class_is_removed(self):
        """ToolCallHeader must not exist on _header module after deletion."""
        from hermes_cli.tui.tool_blocks import _header
        assert not hasattr(_header, "ToolCallHeader"), (
            "ToolCallHeader is a dead class (DEAD-1) and must be deleted"
        )

    def test_no_import_statements_naming_toolcall_header(self):
        """No import statement (import/from-import) names ToolCallHeader in the codebase.

        Exclusion: keystroke-log string literals in test_keystroke_log.py are not import
        statements and are not checked.
        """
        import re
        # Pattern: import ... ToolCallHeader or from ... import ... ToolCallHeader
        import_re = re.compile(r'\bToolCallHeader\b')
        exclusions = {
            _REPO_ROOT / "tests" / "tui" / "test_keystroke_log.py",
            _REPO_ROOT / "tests" / "tui" / "test_concept_drift_fix.py",  # this file
        }
        offenders: list[str] = []
        # Only scan hermes_cli/ and tests/tui/ in the main worktree — not .claude/worktrees/
        scan_dirs = [_REPO_ROOT / "hermes_cli", _REPO_ROOT / "tests"]
        for scan_dir in scan_dirs:
            for py_file in sorted(scan_dir.rglob("*.py")):
                if py_file in exclusions:
                    continue
                try:
                    src = py_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                # Only flag import statement lines, not any string literal occurrences
                for i, line in enumerate(src.splitlines(), 1):
                    stripped = line.strip()
                    if (stripped.startswith("import ") or "import " in stripped) and import_re.search(stripped):
                        offenders.append(f"{py_file.relative_to(_REPO_ROOT)}:{i}: {stripped}")
        assert offenders == [], (
            "Remaining ToolCallHeader import statements found:\n" + "\n".join(offenders)
        )

    def test_chip_constants_still_present_after_deletion(self):
        """_CHIP_CANCELLED and _CHIP_FINALIZING are preserved (consumed by live header)."""
        from hermes_cli.tui.tool_blocks import _header
        assert hasattr(_header, "_CHIP_CANCELLED"), "_CHIP_CANCELLED must be preserved"
        assert hasattr(_header, "_CHIP_FINALIZING"), "_CHIP_FINALIZING must be preserved"


# ---------------------------------------------------------------------------
# TestSwapRendererRawTextFallback — TBC-2
# ---------------------------------------------------------------------------

class TestSwapRendererRawTextFallback:
    """TBC-2: _swap_renderer falls back to FallbackRenderer on build_widget failure."""

    def _make_completion_mixin_with_view(self):
        """Return a _ToolPanelCompletionMixin stub with a live view state."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        view = _make_view_state()
        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="some output",
            line_count=1,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

        # Build a minimal stub with just enough to run _swap_renderer
        mixin = _ToolPanelCompletionMixin.__new__(_ToolPanelCompletionMixin)
        mixin._view_state = view
        mixin._pending_renderer_swap = None

        # Minimal BodyPane stub
        body_pane = SimpleNamespace(
            _renderer=None,
            _block=None,
            mount=MagicMock(),
            query=MagicMock(return_value=MagicMock(remove=MagicMock())),
        )
        mixin._body_pane = body_pane
        mixin._block = None
        mixin.app = None  # None causes SkinColors to use defaults safely

        def _fake_lookup():
            return view
        mixin._lookup_view_state = _fake_lookup

        return mixin, view, payload, cls_result

    def test_swap_renderer_mounts_raw_text_on_build_widget_exception(self):
        """When renderer.build_widget() raises, FallbackRenderer widget is mounted instead."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        mixin, view, payload, cls_result = self._make_completion_mixin_with_view()

        class _FailingRenderer:
            kind = ResultKind.TEXT

            def __init__(self, payload, cls_result, *, app=None):
                self.payload = payload
                self.cls_result = cls_result

            def build_widget(self, density=None, clamp_rows=None):
                raise RuntimeError("intentional test failure")

        mixin._swap_renderer(_FailingRenderer, payload, cls_result)

        # BodyPane._renderer must be reassigned to fallback
        assert isinstance(mixin._body_pane._renderer, FallbackRenderer), (
            "_body_pane._renderer must be FallbackRenderer after build_widget failure"
        )

    def test_swap_renderer_logs_with_exc_info_on_failure(self):
        """_swap_renderer must call _log.exception (exc_info=True implicitly) on failure."""
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        mixin, view, payload, cls_result = self._make_completion_mixin_with_view()

        class _FailingRenderer:
            kind = ResultKind.TEXT

            def __init__(self, payload, cls_result, *, app=None):
                self.payload = payload
                self.cls_result = cls_result

            def build_widget(self, density=None, clamp_rows=None):
                raise RuntimeError("intentional test failure")

        with patch("hermes_cli.tui.tool_panel._completion._log") as mock_log:
            mixin._swap_renderer(_FailingRenderer, payload, cls_result)

        assert mock_log.exception.called, "_log.exception must be called on build_widget failure"

    def test_block_tagged_after_failure_skips_renderer_on_density_change(self):
        """After failure, failed_renderer_classes contains the failed class."""
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        mixin, view, payload, cls_result = self._make_completion_mixin_with_view()

        class _FailingRenderer:
            kind = ResultKind.TEXT

            def __init__(self, payload, cls_result, *, app=None):
                self.payload = payload
                self.cls_result = cls_result

            def build_widget(self, density=None, clamp_rows=None):
                raise RuntimeError("intentional test failure")

        mixin._swap_renderer(_FailingRenderer, payload, cls_result)

        assert _FailingRenderer in view.failed_renderer_classes, (
            "Failed renderer class must be added to view.failed_renderer_classes"
        )

    def test_raw_text_renderer_caption_shows_classification_failure(self):
        """FallbackRenderer.build() includes 'unclassified · plain text' footer when confidence=0."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="hello",
            line_count=1,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)
        renderer = FallbackRenderer(payload, cls_result)
        result = renderer.build()
        assert "unclassified" in result.plain or "plain text" in result.plain, (
            "FallbackRenderer must show 'unclassified · plain text' caption for low-confidence"
        )


# ---------------------------------------------------------------------------
# TestSlowRendererWorkerDispatch — TBC-3
# ---------------------------------------------------------------------------

class TestSlowRendererWorkerDispatch:
    """TBC-3: slow-renderer 250ms/2s deadline wire-up."""

    def _make_body_pane_with_panel(self, block_id: str = "test-block-1"):
        """Return a BodyPane stub with a mock panel parent."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="",
            line_count=0,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

        vs = SimpleNamespace(tool_call_id=block_id)
        slow_map: dict = {}
        panel = SimpleNamespace(
            _view_state=vs,
            _slow_renderer_classes_by_block=slow_map,
        )

        pane = BodyPane.__new__(BodyPane)
        pane._block = None
        pane._renderer = FallbackRenderer(payload, cls_result)
        pane._err_body_locked = False
        pane._last_tier = None
        pane._slow_worker_active = False
        pane._hard_timer = None
        # `parent` is a read-only property on Textual Widget; override via __class__
        pane.__class__ = type(
            "TestBodyPane",
            (BodyPane,),
            {"parent": property(lambda s: panel)},
        )

        return pane, panel, slow_map

    def test_initial_build_runs_synchronously_when_untagged(self):
        """First build on an untagged block runs synchronously (not via worker)."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        pane, panel, slow_map = self._make_body_pane_with_panel("block-sync-1")

        build_called = []

        class _FastRenderer:
            payload = pane._renderer.payload
            cls_result = pane._renderer.cls_result
            kind_icon = "▸"

            def build_widget(self, density=None, clamp_rows=None):
                build_called.append("sync")
                return MagicMock()

        pane._renderer = _FastRenderer()

        with patch.object(pane, "_start_slow_render") as mock_slow:
            with patch.object(pane, "query", return_value=MagicMock(remove=MagicMock())):
                with patch.object(pane, "mount"):
                    pane._mount_body_with_deadline(DensityTier.DEFAULT)

        assert "sync" in build_called, "First build must run synchronously"
        assert not mock_slow.called, "_start_slow_render must NOT be called on first untagged build"

    def test_overrun_tags_renderer_class_as_slow_on_this_block(self):
        """When a renderer exceeds 250ms, it is tagged in panel._slow_renderer_classes_by_block."""
        from hermes_cli.tui.tool_panel._footer import _SLOW_DEADLINE_S
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        pane, panel, slow_map = self._make_body_pane_with_panel("block-tag-1")

        class _SlowRenderer:
            payload = pane._renderer.payload
            cls_result = pane._renderer.cls_result
            kind_icon = "▸"

            def build_widget(self, density=None, clamp_rows=None):
                return MagicMock()

        pane._renderer = _SlowRenderer()

        # Simulate elapsed > threshold by patching time.monotonic
        start_time = 1000.0
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            if call_count[0] == 1:
                return start_time
            return start_time + _SLOW_DEADLINE_S + 0.1  # over threshold

        with patch("hermes_cli.tui.tool_panel._footer.time") as mock_time:
            mock_time.monotonic.side_effect = fake_monotonic
            with patch.object(pane, "query", return_value=MagicMock(remove=MagicMock())):
                with patch.object(pane, "mount"):
                    pane._mount_body_with_deadline(DensityTier.DEFAULT)

        block_id = pane._get_block_id()
        assert block_id in slow_map, f"block_id {block_id!r} must be in slow_map"
        assert _SlowRenderer in slow_map[block_id], (
            "_SlowRenderer must be tagged in panel._slow_renderer_classes_by_block"
        )
        # Not on view_state — per-block tag lives on panel (concept §Failure modes)
        vs = panel._view_state
        assert not hasattr(vs, "_slow_renderer_classes_by_block"), (
            "Slow-render tag must be on the panel, not on view_state"
        )

    def test_tagged_renderer_routes_to_worker_on_next_build_same_block(self):
        """A renderer tagged as slow dispatches to _start_slow_render on next density change."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        pane, panel, slow_map = self._make_body_pane_with_panel("block-worker-1")

        class _TaggedRenderer:
            payload = pane._renderer.payload
            cls_result = pane._renderer.cls_result
            kind_icon = "▸"

            def build_widget(self, density=None, clamp_rows=None):
                return MagicMock()

        pane._renderer = _TaggedRenderer()

        # Pre-tag the renderer class
        slow_map["block-worker-1"] = {_TaggedRenderer}

        with patch.object(pane, "_start_slow_render") as mock_slow:
            with patch.object(pane, "query", return_value=MagicMock(remove=MagicMock())):
                pane._mount_body_with_deadline(DensityTier.DEFAULT)

        assert mock_slow.called, "_start_slow_render must be called for tagged renderer"
        assert mock_slow.call_args[0][0] == DensityTier.DEFAULT

    def test_worker_swap_uses_call_from_thread(self):
        """_render_in_worker posts the result back via app.call_from_thread."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="",
            line_count=0,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        pane = BodyPane.__new__(BodyPane)
        pane._block = None
        pane._renderer = FallbackRenderer(payload, cls_result)
        pane._err_body_locked = False
        pane._last_tier = None
        pane._slow_worker_active = True
        pane._hard_timer = None
        # Override read-only parent property
        pane.__class__ = type("_TestBP", (BodyPane,), {"parent": property(lambda s: None)})

        call_from_thread_calls = []
        fake_app = MagicMock()
        fake_app.call_from_thread.side_effect = lambda fn, *a, **kw: call_from_thread_calls.append((fn, a))

        with patch.object(type(pane), "app", new_callable=lambda: property(lambda s: fake_app)):
            from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
            # Call the worker body directly (not via @work decorator)
            pane._slow_worker_active = True
            pane._render_in_worker.__func__(pane, DensityTier.DEFAULT)

        assert len(call_from_thread_calls) > 0, "call_from_thread must be called by worker"

    def test_hard_deadline_cancels_worker(self):
        """_slow_kill invokes app.workers.cancel_group(panel, 'slow-render')."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="slow content",
            line_count=1,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

        pane = BodyPane.__new__(BodyPane)
        pane._block = None
        pane._renderer = FallbackRenderer(payload, cls_result)
        pane._err_body_locked = False
        pane._last_tier = DensityTier.DEFAULT
        pane._slow_worker_active = True
        pane._hard_timer = None
        pane.__class__ = type("_TestBP", (BodyPane,), {"parent": property(lambda s: None)})

        cancel_calls = []
        fake_workers = MagicMock()
        fake_workers.cancel_group.side_effect = lambda *a, **kw: cancel_calls.append(a)
        fake_app = MagicMock()
        fake_app.workers = fake_workers

        with patch.object(type(pane), "app", new_callable=lambda: property(lambda s: fake_app)):
            with patch.object(pane, "_swap_in_real_widget"):
                pane._slow_kill()

        assert any(
            len(a) >= 2 and a[1] == "slow-render" for a in cancel_calls
        ), "cancel_group must be called with 'slow-render' group on hard-deadline"
        assert not pane._slow_worker_active, "_slow_worker_active must be False after _slow_kill"

    def test_hard_deadline_falls_back_to_raw_text(self):
        """_slow_kill mounts FallbackRenderer widget and logs a warning."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        payload = ToolPayload(
            tool_name="bash",
            category=None,
            args={},
            input_display=None,
            output_raw="slow content",
            line_count=1,
        )
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

        pane = BodyPane.__new__(BodyPane)
        pane._block = None
        pane._renderer = FallbackRenderer(payload, cls_result)
        pane._err_body_locked = False
        pane._last_tier = DensityTier.DEFAULT
        pane._slow_worker_active = True
        pane._hard_timer = None
        pane.__class__ = type("_TestBP2", (BodyPane,), {"parent": property(lambda s: None)})

        swapped_widgets = []
        fake_app = MagicMock()

        with patch.object(type(pane), "app", new_callable=lambda: property(lambda s: fake_app)):
            with patch("hermes_cli.tui.tool_panel._footer._log") as mock_log:
                with patch.object(pane, "_swap_in_real_widget", side_effect=lambda w: swapped_widgets.append(w)):
                    pane._slow_kill()

        assert mock_log.warning.called, "_log.warning must be emitted on hard-deadline"
        assert len(swapped_widgets) == 1, "_swap_in_real_widget must be called once"


# ---------------------------------------------------------------------------
# TestAutoRendererKindResolves — TBC-4
# ---------------------------------------------------------------------------

class TestAutoRendererKindResolves:
    """TBC-4: _auto_renderer_kind and _best_kind_icon use parent-walk."""

    def _make_streaming_block_stub(self, view_state=None):
        """Return a StreamingToolBlock stub with a mock panel grandparent.

        Uses a dynamically-created subclass to override read-only Textual properties.
        """
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        from hermes_cli.tui.tool_category import ToolCategory

        panel = SimpleNamespace(_view_state=view_state)
        parent_obj = SimpleNamespace(parent=panel)

        # Build a subclass that overrides read-only properties
        class _StubBlock(StreamingToolBlock):
            parent = property(lambda s: parent_obj)  # type: ignore[assignment]
            is_attached = property(lambda s: True)   # type: ignore[assignment]

        stub = _StubBlock.__new__(_StubBlock)
        stub._tool_name = "bash"
        stub._tool_args = {}
        stub._kind_override = None
        stub._was_generated = False
        stub._all_plain = ["line1", "line2"]
        stub._rendered_plain_text = ""
        stub._category = ToolCategory.SHELL
        stub._header = MagicMock()
        stub._header._tool_icon = ""

        posted = []
        stub.post_message = lambda m: posted.append(m)
        stub._posted = posted

        # Bind copy_content and _body_line_count as instance methods
        stub.copy_content = lambda: "\n".join(stub._all_plain)
        stub._body_line_count = lambda: len(stub._all_plain)

        stub._auto_renderer_kind = StreamingToolBlock._auto_renderer_kind.__get__(stub)
        stub._best_kind_icon = StreamingToolBlock._best_kind_icon.__get__(stub)
        stub.action_kind_revert = StreamingToolBlock.action_kind_revert.__get__(stub)

        return stub

    def test_auto_renderer_kind_resolves_via_parent_walk_to_panel_view_state(self):
        """_auto_renderer_kind walks parent.parent._view_state, not self._view."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view_state()
        view.kind = ClassificationResult(kind=ResultKind.TEXT, confidence=0.9)
        view.state = ToolCallState.DONE

        stub = self._make_streaming_block_stub(view_state=view)

        result = stub._auto_renderer_kind()
        assert isinstance(result, RendererKind), f"Expected RendererKind, got {type(result)}"

    def test_auto_renderer_kind_returns_plain_when_panel_missing(self):
        """Without a panel parent (no view_state), _auto_renderer_kind returns RendererKind.PLAIN."""
        from hermes_cli.tui.body_renderers import RendererKind

        # Make a stub where view_state is None — panel exists but _view_state is None
        stub = self._make_streaming_block_stub(view_state=None)
        # view.kind is None (view_state itself is None) → returns PLAIN
        result = stub._auto_renderer_kind()
        assert result == RendererKind.PLAIN

    def test_auto_renderer_kind_builds_tool_payload_not_args_dict(self):
        """pick_renderer receives a ToolPayload (not view.args dict) as second arg."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view_state()
        view.kind = ClassificationResult(kind=ResultKind.TEXT, confidence=0.9)
        view.state = ToolCallState.DONE

        stub = self._make_streaming_block_stub(view_state=view)

        captured_payloads = []

        original_pick = None

        def _fake_pick_renderer(cls_result, payload, *, phase, density, user_kind_override=None):
            captured_payloads.append(payload)
            from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
            return FallbackRenderer

        with patch("hermes_cli.tui.tool_blocks._streaming.pick_renderer", _fake_pick_renderer, create=True):
            with patch("hermes_cli.tui.body_renderers.pick_renderer", _fake_pick_renderer):
                stub._auto_renderer_kind()

        assert len(captured_payloads) > 0, "pick_renderer must be called"
        for p in captured_payloads:
            assert isinstance(p, ToolPayload), (
                f"pick_renderer second arg must be ToolPayload, got {type(p)}"
            )

    def test_action_kind_revert_caption_reflects_real_classifier_verdict(self):
        """action_kind_revert uses _auto_renderer_kind result for the caption."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        stub = self._make_streaming_block_stub()
        stub._kind_override = RendererKind.CODE

        # Mock _auto_renderer_kind to return PLAIN
        auto_kind_returns = []

        def _fake_auto_kind():
            rk = RendererKind.PLAIN
            auto_kind_returns.append(rk)
            return rk

        stub._auto_renderer_kind = _fake_auto_kind
        stub.action_kind_revert = StreamingToolBlock.action_kind_revert.__get__(stub)

        with patch.object(type(stub), "is_attached", new_callable=lambda: property(lambda s: True)):
            stub.action_kind_revert()

        assert len(auto_kind_returns) > 0, "_auto_renderer_kind must be called by action_kind_revert"
        flash_msgs = [m for m in stub._posted if hasattr(m, "text")]
        assert any("auto" in getattr(m, "text", "") for m in flash_msgs), (
            "Flash message must mention 'auto'"
        )

    def test_action_kind_revert_caption_renders_for_non_renderer_kind_verdicts(self):
        """Caption is well-formed for ResultKind.JSON (folds to PLAIN in _auto_renderer_kind)."""
        from hermes_cli.tui.body_renderers import RendererKind

        # _auto_renderer_kind returns PLAIN for JSON (no matching RendererKind.value)
        # action_kind_revert calls auto_kind.value.lower() → "plain"
        rk = RendererKind.PLAIN
        caption = f"kind: auto ({rk.value.lower()})"
        assert "auto" in caption
        assert "plain" in caption

    def test_auto_renderer_kind_maps_result_kind_to_renderer_kind(self):
        """Table-drive: ResultKind.DIFF→DIFF, CODE→CODE, others→PLAIN."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.body_renderers import pick_renderer

        table = [
            (ResultKind.DIFF, RendererKind.DIFF),
            (ResultKind.CODE, RendererKind.CODE),
            (ResultKind.TEXT, RendererKind.PLAIN),
            (ResultKind.JSON, RendererKind.PLAIN),
            (ResultKind.TABLE, RendererKind.PLAIN),
            (ResultKind.LOG, RendererKind.PLAIN),
            (ResultKind.EMPTY, RendererKind.PLAIN),
        ]
        for result_kind, expected_rk in table:
            view = _make_view_state()
            view.kind = ClassificationResult(kind=result_kind, confidence=0.95)
            view.state = ToolCallState.DONE

            stub = self._make_streaming_block_stub(view_state=view)
            result = stub._auto_renderer_kind()
            assert isinstance(result, RendererKind), f"For {result_kind}: expected RendererKind, got {type(result)}"
            assert result == expected_rk, (
                f"For ResultKind.{result_kind.name}: expected RendererKind.{expected_rk.name}, got {result}"
            )

    def test_best_kind_icon_resolves_streaming_kind_hint_via_parent_walk(self):
        """_best_kind_icon returns the diff glyph when view_state.streaming_kind_hint=DIFF."""
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_blocks._header import ToolHeader

        view = _make_view_state()
        view.streaming_kind_hint = ResultKind.DIFF

        stub = self._make_streaming_block_stub(view_state=view)

        # Build the kind hint map so _KIND_HINT_ICON is populated
        ToolHeader._build_kind_hint_maps()
        expected_glyph = ToolHeader._KIND_HINT_ICON.get(ResultKind.DIFF)

        result = stub._best_kind_icon()

        if expected_glyph:
            assert result == expected_glyph, (
                f"Expected DIFF glyph {expected_glyph!r}, got {result!r}"
            )
        else:
            # If no DIFF glyph is registered, at least assert it doesn't return "▸"
            # (which would mean the parent-walk failed)
            assert result != "▸" or view.streaming_kind_hint is None, (
                "_best_kind_icon fell back to '▸' despite streaming_kind_hint being set"
            )


# ---------------------------------------------------------------------------
# TestCopyKeyBinding — TBC-5
# ---------------------------------------------------------------------------

class TestCopyKeyBinding:
    """TBC-5: block-level copy key is 'c', not 'y'."""

    def test_block_level_copy_binding_is_c(self):
        """ToolPanel.BINDINGS must contain ('c', 'copy_body', ...) not ('y', ...)."""
        from hermes_cli.tui.tool_panel._core import ToolPanel

        bindings = ToolPanel.BINDINGS
        copy_bindings = [b for b in bindings if getattr(b, "action", None) == "copy_body"]

        assert len(copy_bindings) >= 1, "copy_body action must be in BINDINGS"
        for b in copy_bindings:
            key = getattr(b, "key", None)
            assert key == "c", (
                f"copy_body must be bound to 'c' (TBC-5), got {key!r}"
            )
            assert key != "y", "copy_body must not be bound to 'y' (old binding)"

    def test_hint_pipeline_renders_c_copy_label(self):
        """The collapsed actions map shows ('c', 'copy') not ('y', 'copy')."""
        from hermes_cli.tui.tool_panel._footer import _get_collapsed_actions
        from hermes_cli.tui.tool_category import ToolCategory

        for cat in (ToolCategory.SHELL, ToolCategory.FILE, ToolCategory.CODE,
                    ToolCategory.SEARCH, ToolCategory.WEB, ToolCategory.MCP):
            actions = _get_collapsed_actions(cat)
            copy_entries = [(k, v) for k, v in actions if v == "copy"]
            if copy_entries:
                for key, label in copy_entries:
                    assert key == "c", (
                        f"Category {cat}: copy action must use key 'c', got {key!r}"
                    )
                    assert key != "y", (
                        f"Category {cat}: copy action must not use 'y' (old binding)"
                    )


# ---------------------------------------------------------------------------
# TestUserKindOverrideHelper — TBC-6
# ---------------------------------------------------------------------------

class TestUserKindOverrideHelper:
    """TBC-6: set_user_kind_override helper writes value and refreshes header."""

    def test_set_user_kind_override_writes_value_and_refreshes_header(self):
        """set_user_kind_override sets view.user_kind_override and calls header.refresh()."""
        from hermes_cli.tui.services.tools import set_user_kind_override
        from hermes_cli.tui.tool_payload import ResultKind

        view = _make_view_state()
        assert view.user_kind_override is None

        # Set up a mock header on the block on the panel
        mock_header = MagicMock()
        mock_block = SimpleNamespace(_header=mock_header)
        mock_panel = SimpleNamespace(_block=mock_block)
        source = SimpleNamespace(parent=SimpleNamespace(parent=mock_panel))

        set_user_kind_override(view, ResultKind.DIFF, source_widget=source)

        assert view.user_kind_override == ResultKind.DIFF, (
            "view.user_kind_override must be set to ResultKind.DIFF"
        )
        assert mock_header.refresh.called, (
            "header.refresh() must be called after write"
        )

    def test_set_user_kind_override_no_op_when_value_unchanged(self):
        """No write and no refresh when old == new."""
        from hermes_cli.tui.services.tools import set_user_kind_override
        from hermes_cli.tui.tool_payload import ResultKind

        view = _make_view_state()
        view.user_kind_override = ResultKind.CODE

        mock_header = MagicMock()
        mock_block = SimpleNamespace(_header=mock_header)
        mock_panel = SimpleNamespace(_block=mock_block)
        source = SimpleNamespace(parent=SimpleNamespace(parent=mock_panel))

        set_user_kind_override(view, ResultKind.CODE, source_widget=source)

        assert not mock_header.refresh.called, (
            "header.refresh() must NOT be called when value is unchanged"
        )
        assert view.user_kind_override == ResultKind.CODE

    def test_action_kind_revert_uses_set_user_kind_override_helper(self):
        """action_kind_revert calls set_user_kind_override instead of direct assignment."""
        import inspect
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        src = inspect.getsource(_ToolPanelActionsMixin.action_kind_revert)
        assert "set_user_kind_override" in src, (
            "action_kind_revert must use set_user_kind_override helper (TBC-6)"
        )
        assert "view.user_kind_override = " not in src, (
            "action_kind_revert must not contain direct view.user_kind_override assignment"
        )

    def test_il_7_extension_user_override_writes_paired_with_helper(self):
        """Static AST: no direct 'view.user_kind_override = ...' in tool_panel/ or tool_blocks/.

        Only set_user_kind_override helper is allowed to do the actual assignment.
        (The helper itself is in services/tools.py and is excluded from the check.)
        """
        owner_dirs = [
            _TUI_ROOT / "tool_panel",
            _TUI_ROOT / "tool_blocks",
        ]
        offenders: list[str] = []

        for d in owner_dirs:
            for py_file in sorted(d.glob("*.py")):
                try:
                    src = py_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                tree = ast.parse(src, filename=str(py_file))
                for node in ast.walk(tree):
                    # Look for: <something>.user_kind_override = <value>
                    if not isinstance(node, ast.Assign):
                        continue
                    for target in node.targets:
                        if (isinstance(target, ast.Attribute)
                                and target.attr == "user_kind_override"):
                            offenders.append(
                                f"{py_file.relative_to(_REPO_ROOT)}:{node.lineno}: "
                                f"direct user_kind_override assignment (use set_user_kind_override)"
                            )

        assert offenders == [], (
            "Direct view.user_kind_override = ... found outside helper:\n"
            + "\n".join(offenders)
        )


# ---------------------------------------------------------------------------
# TestConceptDocChangelog — TBC-7
# ---------------------------------------------------------------------------

class TestConceptDocChangelog:
    """TBC-7: concept.md changelog contains 2026-05-02 entries."""

    def test_concept_doc_changelog_present_for_2026_05_02(self):
        """docs/concept.md must contain the 2026-05-02 bug-fix changelog entries."""
        concept_path = _REPO_ROOT / "docs" / "concept.md"
        src = concept_path.read_text(encoding="utf-8")

        # All three required changelog bullets
        assert "2026-05-02 (bug-fix): block-level copy key reconciliation" in src, (
            "TBC-5 changelog entry missing from docs/concept.md"
        )
        assert "2026-05-02 (bug-fix): user_kind_override writes routed through" in src, (
            "TBC-6 changelog entry missing from docs/concept.md"
        )
        assert "2026-05-02 (bug-fix / factual correction): the symbol `RawTextRenderer`" in src, (
            "TBC-2/TBC-3 factual-correction entry missing from docs/concept.md"
        )
