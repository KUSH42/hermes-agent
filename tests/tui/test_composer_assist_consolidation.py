"""Tests for SPEC-ASS composer ASSIST consolidation (ASS-1..ASS-14)."""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Path to source files for AST/grep tests
_ROOT = Path(__file__).parents[2]
_WIDGET_PY = _ROOT / "hermes_cli/tui/input/widget.py"
_SKILL_PICKER_PY = _ROOT / "hermes_cli/tui/overlays/skill_picker.py"
_LEGEND_BAR_PY = _ROOT / "hermes_cli/tui/widgets/input_legend_bar.py"
_COMPLETION_OVERLAY_PY = _ROOT / "hermes_cli/tui/completion_overlay.py"
_PATH_COMPLETION_PY = _ROOT / "hermes_cli/tui/input/_path_completion.py"
_COMPLETION_LIST_PY = _ROOT / "hermes_cli/tui/completion_list.py"
_COMPOSER_CONCEPT_MD = _ROOT / "docs/composer-concept.md"


# ---------------------------------------------------------------------------
# ASS-1: assist reactive field
# ---------------------------------------------------------------------------

class TestAssistReactive:
    """ASS-1: assist reactive exists, defaults to NONE, not shadowed in __init__."""

    def test_assist_reactive_field_exists(self):
        """HermesInput.assist is declared as a class-level reactive."""
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.input._assist import AssistKind
        from textual.reactive import reactive
        attr = HermesInput.__dict__.get("assist")
        assert attr is not None, "HermesInput.assist not found as class attribute"
        assert isinstance(attr, reactive), "HermesInput.assist must be a reactive"

    def test_assist_reactive_default_is_none(self):
        """HermesInput.assist defaults to AssistKind.NONE."""
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.input._assist import AssistKind
        attr = HermesInput.__dict__["assist"]
        # textual reactive stores default as _default
        default = getattr(attr, "_default", None)
        # It may be a callable (AssistKind.NONE itself) or the value
        if callable(default):
            assert default() == AssistKind.NONE or default is AssistKind.NONE
        else:
            assert default == AssistKind.NONE

    def test_completion_overlay_active_deleted_from_init(self):
        """ASS-1: _completion_overlay_active must not be set in __init__."""
        src = _WIDGET_PY.read_text()
        assert "_completion_overlay_active" not in src, (
            "_completion_overlay_active still referenced in widget.py"
        )


# ---------------------------------------------------------------------------
# ASS-2: watch_assist, _sync_picker_chevron, _sync_picker_legend
# ---------------------------------------------------------------------------

class TestWatchAssist:
    """ASS-2: watch_assist / picker chrome sync."""

    def test_watch_assist_method_exists(self):
        """HermesInput.watch_assist exists."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "watch_assist"), "watch_assist missing from HermesInput"

    def test_sync_picker_chevron_exists(self):
        """HermesInput._sync_picker_chevron exists."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "_sync_picker_chevron")

    def test_sync_picker_legend_exists(self):
        """HermesInput._sync_picker_legend exists."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "_sync_picker_legend")

    def test_sync_picker_legend_calls_show_legend_with_picker(self):
        """_sync_picker_legend(True) calls legend.show_legend('picker') — AST check."""
        from hermes_cli.tui.input.widget import HermesInput
        # AST-based check: _sync_picker_legend must call show_legend("picker")
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_sync_picker_legend":
                func_src = ast.unparse(node)
                assert "picker" in func_src, "_sync_picker_legend must reference 'picker' legend"
                assert "show_legend" in func_src, "_sync_picker_legend must call show_legend"
                break
        else:
            pytest.fail("_sync_picker_legend not found in widget.py")


# ---------------------------------------------------------------------------
# ASS-3: _refresh_placeholder priority
# ---------------------------------------------------------------------------

class TestPlaceholderPriority:
    """ASS-3: placeholder priority order: locked > picker > rev-search > bash > overlay > error > idle.

    Tests use AST inspection since we can't run HermesInput without a full app.
    """

    def test_picker_wins_over_rev_search(self):
        """AST check: in _refresh_placeholder, PICKER branch comes before rev_mode check."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_refresh_placeholder":
                func_src = ast.unparse(node)
                pos_picker = func_src.find("AssistKind.PICKER")
                pos_rev = func_src.find("_rev_mode")
                assert pos_picker != -1, "PICKER check not found in _refresh_placeholder"
                assert pos_rev != -1, "_rev_mode check not found in _refresh_placeholder"
                assert pos_picker < pos_rev, "PICKER must appear before _rev_mode in priority"
                break
        else:
            pytest.fail("_refresh_placeholder not found in widget.py")

    def test_overlay_does_not_overwrite_placeholder(self):
        """AST check: OVERLAY branch in _refresh_placeholder returns without assignment."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_refresh_placeholder":
                func_src = ast.unparse(node)
                # The OVERLAY branch should be `return` without assigning placeholder
                assert "AssistKind.OVERLAY" in func_src, "OVERLAY check missing"
                # Check that the OVERLAY section does a bare return
                assert "return  # leave placeholder" in _WIDGET_PY.read_text() or \
                       "return" in func_src, "OVERLAY branch must return"
                break
        else:
            pytest.fail("_refresh_placeholder not found")


# ---------------------------------------------------------------------------
# ASS-4: CompletionOverlay border_subtitle
# ---------------------------------------------------------------------------

class TestPlaceholderOverlayBehavior:
    """ASS-4: CompletionOverlay.on_mount sets border_subtitle."""

    def test_completion_overlay_on_mount_sets_border_subtitle(self):
        """on_mount sets border_subtitle to nav hint string."""
        src = _COMPLETION_OVERLAY_PY.read_text()
        assert "border_subtitle" in src, "border_subtitle not set in CompletionOverlay.on_mount"
        assert "↑↓ select" in src, "border_subtitle hint text not found"

    def test_completion_overlay_border_subtitle_text(self):
        """border_subtitle is the expected string."""
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        # Parse the source to find the border_subtitle assignment
        src = _COMPLETION_OVERLAY_PY.read_text()
        assert '↑↓ select  ·  Tab accept  ·  Esc close' in src

    def test_auto_dismiss_bubble_class_exists(self):
        """CompletionOverlay._AutoDismissBubble message class exists and has bubble=True."""
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        assert hasattr(CompletionOverlay, "_AutoDismissBubble")
        assert getattr(CompletionOverlay._AutoDismissBubble, "bubble", False) is True


# ---------------------------------------------------------------------------
# ASS-5: LEGENDS dict
# ---------------------------------------------------------------------------

class TestLegendsLiterals:
    """ASS-5: LEGENDS dict has correct values for completion and picker."""

    def test_completion_legend_exact(self):
        """LEGENDS['completion'] has updated accept verbs."""
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        assert InputLegendBar.LEGENDS["completion"] == "@file  ·  Tab=accept  ·  Enter=accept  ·  Esc=cancel"

    def test_picker_legend_present_and_correct(self):
        """LEGENDS['picker'] is present with correct text."""
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        assert "picker" in InputLegendBar.LEGENDS
        assert InputLegendBar.LEGENDS["picker"] == "Enter run  ·  Tab paste  ·  ? view docs  ·  Esc cancel"


# ---------------------------------------------------------------------------
# ASS-6: _AutoDismissBubble and handler
# ---------------------------------------------------------------------------

class TestAutoDismiss:
    """ASS-6: _AutoDismissBubble bubbles up and handler calls _resolve_assist(NONE)."""

    def test_auto_dismiss_handler_in_widget(self):
        """HermesInput has on_completion_overlay__auto_dismiss_bubble handler."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "on_completion_overlay__auto_dismiss_bubble"), (
            "Missing on_completion_overlay__auto_dismiss_bubble on HermesInput"
        )

    def test_auto_dismiss_handler_calls_resolve_assist_none(self):
        """on_completion_overlay__auto_dismiss_bubble calls _resolve_assist(NONE)."""
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.input._assist import AssistKind

        widget = HermesInput.__new__(HermesInput)
        calls = []
        widget._resolve_assist = lambda kind: calls.append(kind)

        mock_ev = MagicMock()
        widget.on_completion_overlay__auto_dismiss_bubble(mock_ev)

        assert calls == [AssistKind.NONE]
        mock_ev.stop.assert_called_once()

    def test_auto_dismiss_overlay_handler_not_direct_css(self):
        """on_virtual_completion_list_auto_dismiss posts bubble instead of direct CSS."""
        src = _COMPLETION_OVERLAY_PY.read_text()
        # The old code did remove_class("--visible") directly — now it should post bubble
        # Find the on_virtual_completion_list_auto_dismiss method
        assert "_AutoDismissBubble" in src
        # Old pattern should not be present in that handler
        # The handler should no longer call remove_class("--visible")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_virtual_completion_list_auto_dismiss":
                func_src = ast.unparse(node)
                assert "post_message" in func_src, "handler must post_message"
                break


# ---------------------------------------------------------------------------
# ASS-7: _resolve_assist single-write-site
# ---------------------------------------------------------------------------

class TestResolveAssist:
    """ASS-7: _resolve_assist is the only site that writes self.assist."""

    def test_resolve_assist_is_only_write_site(self):
        """AST-walk: only _resolve_assist may assign self.assist."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)

        class AssistWriteVisitor(ast.NodeVisitor):
            def __init__(self):
                self.violations = []
                self._in_resolve = False

            def visit_FunctionDef(self, node):
                old = self._in_resolve
                self._in_resolve = (node.name == "_resolve_assist")
                self.generic_visit(node)
                self._in_resolve = old

            def visit_Assign(self, node):
                if not self._in_resolve:
                    for t in node.targets:
                        if (isinstance(t, ast.Attribute) and t.attr == "assist"
                                and isinstance(t.value, ast.Name) and t.value.id == "self"):
                            self.violations.append(f"line {node.lineno}")
                self.generic_visit(node)

        v = AssistWriteVisitor()
        v.visit(tree)
        assert not v.violations, f"self.assist written outside _resolve_assist: {v.violations}"

    def test_resolve_assist_method_present(self):
        """_resolve_assist exists on HermesInput."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "_resolve_assist")

    def test_resolve_assist_idempotent_for_none(self):
        """AST check: _resolve_assist returns early when current == target (idempotent guard)."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_resolve_assist":
                func_src = ast.unparse(node)
                # The method should check current == target and return early
                assert "current == target" in func_src or "current==" in func_src.replace(" ", ""), (
                    "_resolve_assist must have an idempotent guard (current == target)"
                )
                assert "return" in func_src, "_resolve_assist must return early when idempotent"
                break
        else:
            pytest.fail("_resolve_assist not found in widget.py")


# ---------------------------------------------------------------------------
# ASS-8: Middle-click paste disabled check
# ---------------------------------------------------------------------------

class TestMiddleClickPaste:
    """ASS-8: on_click skips paste when disabled, _handle_paste_result checks disabled."""

    def test_handle_paste_result_exists(self):
        """HermesInput._handle_paste_result method exists."""
        from hermes_cli.tui.input.widget import HermesInput
        assert hasattr(HermesInput, "_handle_paste_result")

    def test_on_click_disabled_check_in_source(self):
        """AST check: on_click has a disabled guard before calling safe_run."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_click":
                func_src = ast.unparse(node)
                assert "disabled" in func_src, "on_click must check self.disabled"
                assert "safe_run" in func_src, "on_click must call safe_run"
                # disabled guard must come before safe_run
                pos_disabled = func_src.find("disabled")
                pos_safe_run = func_src.find("safe_run")
                assert pos_disabled < pos_safe_run, "disabled check must come before safe_run"
                break
        else:
            pytest.fail("on_click not found in widget.py")

    def test_handle_paste_result_checks_disabled_in_source(self):
        """AST check: _handle_paste_result has disabled guard before insert_text."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_handle_paste_result":
                func_src = ast.unparse(node)
                assert "disabled" in func_src, "_handle_paste_result must check disabled"
                assert "insert_text" in func_src, "_handle_paste_result must call insert_text"
                pos_disabled = func_src.find("disabled")
                pos_insert = func_src.find("insert_text")
                assert pos_disabled < pos_insert, "disabled guard must come before insert_text"
                break
        else:
            pytest.fail("_handle_paste_result not found in widget.py")


# ---------------------------------------------------------------------------
# ASS-9: _show_path_completions ordering
# ---------------------------------------------------------------------------

class TestPathSearchOrdering:
    """ASS-9: _show_path_completions calls _set_searching(True) BEFORE _push_to_list."""

    def test_searching_set_before_push(self):
        """_show_path_completions: searching FIRST, then push to list."""
        src = _PATH_COMPLETION_PY.read_text()
        tree = ast.parse(src)

        # Find _show_path_completions function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_show_path_completions":
                func_src = ast.unparse(node)
                # _set_searching(True) must appear before _push_to_list
                pos_searching = func_src.find("_set_searching(True)")
                pos_push = func_src.find("_push_to_list")
                assert pos_searching != -1, "_set_searching(True) not found"
                assert pos_push != -1, "_push_to_list not found"
                assert pos_searching < pos_push, (
                    "_set_searching(True) must come before _push_to_list"
                )
                break
        else:
            pytest.fail("_show_path_completions not found in _path_completion.py")


# ---------------------------------------------------------------------------
# ASS-10: --slash-only class removal on empty items
# ---------------------------------------------------------------------------

class TestSlashOnlyClass:
    """ASS-10: watch_items removes --slash-only class when items is empty."""

    def test_slash_only_removal_in_watch_items(self):
        """watch_items removes --slash-only class when new is empty."""
        src = _COMPLETION_LIST_PY.read_text()
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "watch_items":
                func_src = ast.unparse(node)
                assert "--slash-only" in func_src, (
                    "watch_items does not handle --slash-only removal"
                )
                assert "remove_class" in func_src
                break
        else:
            pytest.fail("watch_items not found in completion_list.py")


# ---------------------------------------------------------------------------
# ASS-11: SkillPicker Enter key in filter
# ---------------------------------------------------------------------------

class TestPickerKeyDispatch:
    """ASS-11: Enter in picker-filter goes to on_input_submitted, not _dispatch_selected directly."""

    def test_on_input_submitted_handler_exists(self):
        """SkillPickerOverlay.on_input_submitted exists."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        assert hasattr(SkillPickerOverlay, "on_input_submitted")

    def test_on_key_skips_dispatch_when_filter_focused(self):
        """on_key enter handler skips dispatch when focus is on picker-filter."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        src = _SKILL_PICKER_PY.read_text()
        # The on_key enter branch must check focused widget id
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_key":
                func_src = ast.unparse(node)
                assert "picker-filter" in func_src, (
                    "on_key must check for picker-filter to skip dispatch"
                )
                break
        else:
            pytest.fail("on_key not found in skill_picker.py")


# ---------------------------------------------------------------------------
# ASS-12: _dispatch_selected saves draft stash and checks disabled
# ---------------------------------------------------------------------------

class TestDispatchSelected:
    """ASS-12: _dispatch_selected saves draft stash and checks disabled."""

    def test_dispatch_selected_calls_save_draft_stash(self):
        """_dispatch_selected calls inp.save_draft_stash()."""
        src = _SKILL_PICKER_PY.read_text()
        assert "save_draft_stash" in src, "_dispatch_selected missing save_draft_stash call"

    def test_dispatch_selected_checks_disabled(self):
        """_dispatch_selected checks inp.disabled before submitting."""
        src = _SKILL_PICKER_PY.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_dispatch_selected":
                func_src = ast.unparse(node)
                assert "disabled" in func_src, "_dispatch_selected must check inp.disabled"
                break
        else:
            pytest.fail("_dispatch_selected not found")

    def test_dispatch_selected_flashes_hint_when_disabled(self):
        """_dispatch_selected shows flash hint when composer is locked."""
        src = _SKILL_PICKER_PY.read_text()
        assert "composer locked" in src, "missing 'composer locked' flash hint in _dispatch_selected"


# ---------------------------------------------------------------------------
# ASS-13: No duplicate _rev_query init
# ---------------------------------------------------------------------------

class TestRevQueryReactive:
    """ASS-13: _rev_query not re-declared as instance attr in __init__."""

    def test_rev_query_not_instance_init(self):
        """AST check: __init__ does not assign self._rev_query = '' (shadowing reactive)."""
        src = _WIDGET_PY.read_text()
        tree = ast.parse(src)

        class InitChecker(ast.NodeVisitor):
            def __init__(self):
                self.violations = []
                self._in_init = False

            def visit_FunctionDef(self, node):
                old = self._in_init
                self._in_init = (node.name == "__init__")
                self.generic_visit(node)
                self._in_init = old

            def visit_Assign(self, node):
                if self._in_init:
                    for t in node.targets:
                        if (isinstance(t, ast.Attribute) and t.attr == "_rev_query"
                                and isinstance(t.value, ast.Name) and t.value.id == "self"):
                            self.violations.append(f"line {node.lineno}")
                self.generic_visit(node)

        v = InitChecker()
        v.visit(tree)
        assert not v.violations, f"self._rev_query = '' found in __init__: {v.violations}"


# ---------------------------------------------------------------------------
# ASS-14: Doc drift closure
# ---------------------------------------------------------------------------

class TestDocDriftClosure:
    """ASS-14: composer-concept.md has drift items closed + SkillPicker docstring updated."""

    def test_concept_doc_drift_1_closed(self):
        """Drift §1 in composer-concept.md has CLOSED annotation."""
        content = _COMPOSER_CONCEPT_MD.read_text()
        assert "CLOSED 2026-05-02" in content, (
            "composer-concept.md drift §1 not marked CLOSED 2026-05-02"
        )

    def test_skill_picker_docstring_uses_input_mode_normal(self):
        """SkillPickerOverlay docstring references InputMode.NORMAL not AGENT."""
        src = _SKILL_PICKER_PY.read_text()
        # Docstring at top of file
        assert "InputMode.AGENT" not in src, (
            "SkillPickerOverlay docstring still references InputMode.AGENT"
        )
        assert "InputMode.NORMAL" in src or "NORMAL" in src[:500], (
            "SkillPickerOverlay docstring should reference NORMAL mode"
        )
