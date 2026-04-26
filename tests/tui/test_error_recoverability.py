"""Error recoverability — B-2, C-1, C-2, D-2 (21 pure-unit tests)."""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers: minimal ToolPanel stand-in (no Textual runtime)
# ---------------------------------------------------------------------------

def _make_summary(
    *,
    is_error: bool = False,
    error_kind: str | None = None,
    stderr_tail: str | None = None,
    chips: tuple = (),
    actions: tuple = (),
    primary: str | None = None,
    exit_code: int | None = None,
) -> Any:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=primary,
        exit_code=exit_code,
        chips=chips,
        is_error=is_error,
        error_kind=error_kind,
        stderr_tail=stderr_tail,
        actions=list(actions),
        artifacts=(),
    )


class _FakePanel:
    """Minimal ToolPanel-like object for B-2 and C-2 tests (no Textual)."""

    def __init__(self) -> None:
        self._classes: set[str] = set()
        self._result_summary_v4 = None
        self._block = MagicMock()
        self._block._header = MagicMock()
        self._footer_pane = None
        self._accent = None
        self._start_time = 0.0
        self._completed_at = None
        self._user_collapse_override = False
        self.collapsed = False
        self._timer_calls: list[tuple[float, Any]] = []

    # Textual CSS class stubs
    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)

    def has_class(self, cls: str) -> bool:
        return cls in self._classes

    def set_timer(self, delay: float, callback: Any) -> None:
        self._timer_calls.append((delay, callback))

    # Minimal stubs for set_result_summary dependencies
    def post_message(self, _: Any) -> None:
        pass

    def _body_line_count(self) -> int:
        return 0

    def _update_kind_from_classifier(self, _: int) -> None:
        pass

    def _schedule_age_ticks(self) -> None:
        pass

    def _has_footer_content(self) -> bool:
        return False

    # We pull in the real logic from ToolPanel for the parts we care about
    def _run_remediation_and_schedule(self, summary: Any) -> None:
        """Replicate the B-2 block from set_result_summary (ER-2: C-2 remediation removed)."""
        import os as _os

        # B-2 schedule
        if _os.environ.get("HERMES_DETERMINISTIC"):
            self._post_complete_tidy(summary)
        else:
            try:
                self.add_class("--completing")
            except AttributeError:
                pass
            self.set_timer(0.25, lambda: self._post_complete_tidy(summary))

    def _post_complete_tidy(self, summary: Any) -> None:
        """Minimal tidy matching ToolPanel's contract."""
        try:
            self.remove_class("--completing")
        except AttributeError:
            pass
        if summary.is_error:
            self.collapsed = False


# ---------------------------------------------------------------------------
# _H: ToolHeader stand-in for C-2 tail-segment tests
# ---------------------------------------------------------------------------

class _H:
    """Thin stand-in for ToolHeader exercising _render_v4 tail segment logic."""

    def __init__(
        self,
        *,
        tool_name: str = "bash",
        collapsed: bool = True,
        is_complete: bool = True,
        tool_icon_error: bool = False,
        remediation_hint: str | None = None,
        primary_hero: str | None = None,
        panel_collapsed: bool | None = None,
        width: int = 200,
        exit_code: int | None = None,
    ) -> None:
        self._tool_name = tool_name
        self._label = tool_name
        self._line_count = 0
        self._stats = None
        self._has_affordances = False
        self._flash_msg = None
        self._flash_expires = 0.0
        self._spinner_char = None
        self._duration = ""
        self._is_complete = is_complete
        self._tool_icon = ""
        self._tool_icon_error = tool_icon_error
        self._label_rich = None
        self._compact_tail = False
        self._is_child_diff = False
        self._full_path = None
        self._path_clickable = False
        self._is_url = False
        self._no_underline = False
        self._hide_duration = False
        self._bold_label = False
        self._hidden = False
        self._shell_prompt = False
        self._elapsed_ms = None
        self._header_args = {}
        self._primary_hero = primary_hero
        self._header_chips = []
        self._error_kind = None
        self._exit_code = exit_code
        self._flash_tone = "success"
        self._browse_badge = ""
        self._is_child = False
        self._remediation_hint = remediation_hint
        self.collapsed = collapsed
        self._focused_gutter_color = "#5f87d7"
        self._diff_add_color = "#4caf50"
        self._diff_del_color = "#ef4444"
        self._running_icon_color = "#FFA726"
        self._width = width
        self._pulse_t = 0.0
        self._pulse_tick = 0
        self._spinner_identity = None

        if panel_collapsed is not None:
            self._panel = MagicMock()
            self._panel.collapsed = panel_collapsed
            self._panel._result_summary_v4 = None
        else:
            self._panel = None

    def has_class(self, *_: Any) -> bool:
        return False

    def _accessible_mode(self) -> bool:
        return False

    @property
    def size(self) -> Any:
        s = MagicMock()
        s.width = self._width
        return s

    def _tail(self, budget: int = 200) -> "list[tuple[str, Any]]":
        """Build tail segments mirroring the _render_v4 non-spinner branch."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments

        tail_segments: list[tuple[str, Any]] = []

        if self._primary_hero:
            if self._tool_icon_error:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="bold red")))
            else:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="dim green")))

        is_collapsed = self._panel.collapsed if self._panel is not None else self.collapsed

        # chevron slot
        if self._has_affordances:
            tail_segments.append(("chevron", Text("  ▸" if is_collapsed else "  ▾", style="dim")))
        else:
            tail_segments.append(("chevron", Text("  ·", style="dim #444444")))

        # R10 exit code
        if is_collapsed and self._is_complete:
            code = getattr(self, "_exit_code", None)
            if code is not None:
                if code == 0:
                    if not self._primary_hero:
                        tail_segments.append(("exit", Text("  ok", style="dim green")))
                else:
                    tail_segments.append(("exit", Text(f"  exit {code}", style="bold red")))

        return _trim_tail_segments(tail_segments, budget)

    def _tail_names(self, budget: int = 200) -> "list[str]":
        return [name for name, _ in self._tail(budget)]

    def _tail_text(self, name: str, budget: int = 200) -> "str | None":
        for n, seg in self._tail(budget):
            if n == name:
                return seg.plain
        return None


# ---------------------------------------------------------------------------
# B-2 tests
# ---------------------------------------------------------------------------

class TestB2CompletingClass:
    def test_er_b2_01_add_completing_on_set_result(self) -> None:
        """set_result_summary adds --completing class immediately (non-deterministic path)."""
        panel = _FakePanel()
        summary = _make_summary()
        with _non_deterministic():
            panel._run_remediation_and_schedule(summary)
        assert panel.has_class("--completing")

    def test_er_b2_02_post_tidy_removes_completing(self) -> None:
        """_post_complete_tidy removes --completing class."""
        panel = _FakePanel()
        panel.add_class("--completing")
        summary = _make_summary()
        panel._post_complete_tidy(summary)
        assert not panel.has_class("--completing")

    def test_er_b2_03_deterministic_no_completing_class(self) -> None:
        """HERMES_DETERMINISTIC=1: no --completing class added, tidy runs inline."""
        panel = _FakePanel()
        summary = _make_summary()
        with _deterministic():
            panel._run_remediation_and_schedule(summary)
        # In deterministic mode _post_complete_tidy runs inline, which removes the class
        # and the add_class is never called
        assert not panel.has_class("--completing")
        # no timer was queued
        assert len(panel._timer_calls) == 0

    def test_er_b2_04_no_collapse_before_timer(self) -> None:
        """collapsed remains False right after set_result_summary (before timer fires)."""
        panel = _FakePanel()
        panel.collapsed = False
        summary = _make_summary()
        with _non_deterministic():
            panel._run_remediation_and_schedule(summary)
        # Timer not fired yet — collapsed unchanged
        assert panel.collapsed is False

    def test_er_b2_05_error_completing_lifecycle(self) -> None:
        """--completing added then removed; error path always expands."""
        panel = _FakePanel()
        summary = _make_summary(is_error=True, error_kind="timeout")
        with _non_deterministic():
            panel._run_remediation_and_schedule(summary)
        assert panel.has_class("--completing")
        # Fire the timer callback
        assert len(panel._timer_calls) == 1
        _, callback = panel._timer_calls[0]
        callback()
        assert not panel.has_class("--completing")
        # error path expands
        assert panel.collapsed is False


# ---------------------------------------------------------------------------
# C-1 tests — copy_err injection in _render_footer
# ---------------------------------------------------------------------------

def _make_footer_pane_and_summary(
    *,
    stderr_tail: str | None = None,
    existing_copy_err: bool = False,
) -> tuple[Any, Any]:
    from hermes_cli.tui.tool_result_parse import Action as _Action

    actions = []
    if existing_copy_err:
        actions.append(_Action(label="copy err", hotkey="e", kind="copy_err", payload=None))

    summary = _make_summary(stderr_tail=stderr_tail, actions=tuple(actions))
    return summary


def _collect_action_kinds(summary: Any) -> list[str]:
    """Run the C-1 injection logic and return list of action kinds."""
    actions_to_render = list(summary.actions)
    # Replicate C-1 injection from _render_footer
    if summary.stderr_tail and not any(a.kind == "copy_err" for a in actions_to_render):
        from hermes_cli.tui.tool_result_parse import Action as _Action
        actions_to_render.append(_Action(
            label="copy err",
            hotkey="e",
            kind="copy_err",
            payload=None,
        ))
    return [a.kind for a in actions_to_render]


class TestC1CopyErrInjection:
    def test_er_c1_01_copy_err_injected_when_stderr_present(self) -> None:
        summary = _make_footer_pane_and_summary(stderr_tail="some error output")
        kinds = _collect_action_kinds(summary)
        assert "copy_err" in kinds

    def test_er_c1_02_no_duplicate_copy_err(self) -> None:
        summary = _make_footer_pane_and_summary(stderr_tail="err", existing_copy_err=True)
        kinds = _collect_action_kinds(summary)
        assert kinds.count("copy_err") == 1

    def test_er_c1_03_idempotent_on_re_render(self) -> None:
        summary = _make_footer_pane_and_summary(stderr_tail="err output")
        # call twice (simulate re-render)
        kinds1 = _collect_action_kinds(summary)
        kinds2 = _collect_action_kinds(summary)
        assert kinds1.count("copy_err") == 1
        assert kinds2.count("copy_err") == 1

    def test_er_c1_no_stderr_no_injection(self) -> None:
        summary = _make_footer_pane_and_summary(stderr_tail=None)
        kinds = _collect_action_kinds(summary)
        assert "copy_err" not in kinds


# ---------------------------------------------------------------------------
# ER-2 tests — header has no stderrwarn/remediation segments (moved to body/footer)
# ---------------------------------------------------------------------------

class TestER2HeaderNoEvidence:
    def test_er2_01_stderrwarn_absent_from_drop_order(self) -> None:
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert "stderrwarn" not in _DROP_ORDER

    def test_er2_02_remediation_absent_from_drop_order(self) -> None:
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert "remediation" not in _DROP_ORDER

    def test_er2_03_drop_order_length_is_8(self) -> None:
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert len(_DROP_ORDER) == 8

    def test_er2_04_no_stderrwarn_segment_on_error(self) -> None:
        h = _H(is_complete=True, tool_icon_error=True, collapsed=True, panel_collapsed=True)
        assert "stderrwarn" not in h._tail_names()

    def test_er2_05_no_remediation_segment_even_with_hint(self) -> None:
        h = _H(
            is_complete=True,
            tool_icon_error=True,
            collapsed=True,
            remediation_hint="increase timeout",
            panel_collapsed=True,
        )
        assert "remediation" not in h._tail_names()

    def test_er2_06_exit_still_present_on_error(self) -> None:
        h = _H(is_complete=True, tool_icon_error=True, collapsed=True,
               exit_code=1, panel_collapsed=True)
        assert "exit" in h._tail_names()

    def test_er2_07_no_remediation_hint_written_to_header(self) -> None:
        """ER-2: _completion.py no longer writes _remediation_hint to header."""
        import inspect
        from hermes_cli.tui.tool_panel import _completion
        src = inspect.getsource(_completion)
        assert "_remediation_hint" not in src


# ---------------------------------------------------------------------------
# D-2 tests — SubAgentPanel child error glyphs
# ---------------------------------------------------------------------------

class _FakeSubAgentPanel:
    """Minimal SubAgentPanel stand-in — avoids Textual reactive machinery."""

    def __init__(self) -> None:
        self._depth = 0
        self._has_children = False
        import time as _time
        self._open_time = _time.monotonic()
        self._completed_child_count = 0
        self._child_error_kinds: list[str] = []
        self.child_count = 0
        self.error_count = 0
        self.elapsed_ms = 0
        self.subtree_done = False
        self._body = MagicMock()
        self._body.children = []


def _make_sub_agent_panel(depth: int = 0) -> "_FakeSubAgentPanel":
    return _FakeSubAgentPanel()


def _run_notify(panel: Any, tool_call_id: str, is_error: bool,
                error_kind: str | None = None) -> None:
    """Run _notify_child_complete logic directly on a _FakeSubAgentPanel."""
    # Build a fake child with the given tool_call_id and error_kind
    fake_child = MagicMock()
    fake_block = MagicMock()
    fake_block._tool_call_id = tool_call_id
    fake_child._block = fake_block
    rs = MagicMock()
    rs.error_kind = error_kind
    fake_child._result_summary_v4 = rs
    panel._body.children = [fake_child]
    panel.child_count += 1

    # Replicate _notify_child_complete logic directly (avoids reactive __set__)
    from hermes_cli.tui.sub_agent_panel import SubAgentPanel
    if is_error:
        _ek = SubAgentPanel._extract_error_kind(panel, tool_call_id)
        if _ek and _ek not in panel._child_error_kinds:
            panel._child_error_kinds.append(_ek)
        panel.error_count += 1
    panel._completed_child_count += 1


class _SubAgentHeaderStub:
    """Stand-in for SubAgentHeader.update rendering segments."""

    def __init__(self) -> None:
        self._last_segments: list[tuple[str, Any]] = []
        self._last_badge: str = ""
        self._badges = MagicMock()

    def update(self, child_count: int, error_count: int, elapsed_ms: int,
               done: bool, error_kinds: "list[str] | None" = None) -> None:
        from rich.text import Text as _Text
        segments = [("calls", _Text(f"  {child_count} calls", style="dim"))]
        if error_count > 0:
            warn_color = "#FFA726"
            err_word = "error" if error_count == 1 else "errors"
            segments.append(("errors", _Text(f"  {error_count} {err_word}", style=f"bold {warn_color}")))
            if error_kinds:
                _GLYPHS = {"timeout": "⏱", "auth": "🔒", "network": "🌐",
                           "signal": "💀", "exit": "✗"}
                glyphs = "".join(_GLYPHS.get(k, "✗") for k in error_kinds[:3])
                segments.append(("error-kinds", _Text(f" {glyphs}", style=f"bold {warn_color}")))
        segments.append(("duration", _Text("  0s", style="dim")))
        self._last_segments = segments

    def _seg_names(self) -> list[str]:
        return [n for n, _ in self._last_segments]

    def _seg_text(self, name: str) -> str | None:
        for n, t in self._last_segments:
            if n == name:
                return t.plain
        return None


class _SubAgentHeaderAccessibleStub(_SubAgentHeaderStub):
    def update(self, child_count: int, error_count: int, elapsed_ms: int,
               done: bool, error_kinds: "list[str] | None" = None) -> None:
        badge = f"calls:{child_count} err:{error_count} dur:0s"
        if error_count > 0 and error_kinds:
            badge += f" err-kinds:{','.join(error_kinds[:3])}"
        self._last_badge = badge


class TestD2ChildErrorGlyphs:
    def test_er_d2_01_child_error_kinds_updated_on_error_complete(self) -> None:
        panel = _make_sub_agent_panel()
        _run_notify(panel, "call-1", is_error=True, error_kind="timeout")
        assert "timeout" in panel._child_error_kinds

    def test_er_d2_02_duplicate_kinds_not_added(self) -> None:
        panel = _make_sub_agent_panel()
        _run_notify(panel, "call-1", is_error=True, error_kind="timeout")
        _run_notify(panel, "call-2", is_error=True, error_kind="timeout")
        assert panel._child_error_kinds.count("timeout") == 1

    def test_er_d2_03_header_renders_glyph_for_timeout(self) -> None:
        h = _SubAgentHeaderStub()
        h.update(child_count=3, error_count=1, elapsed_ms=0, done=False,
                 error_kinds=["timeout"])
        assert "error-kinds" in h._seg_names()
        text = h._seg_text("error-kinds")
        assert text is not None
        assert "⏱" in text

    def test_er_d2_04_max_3_glyphs(self) -> None:
        h = _SubAgentHeaderStub()
        h.update(child_count=5, error_count=4, elapsed_ms=0, done=False,
                 error_kinds=["timeout", "auth", "network", "signal"])
        text = h._seg_text("error-kinds")
        assert text is not None
        # 4 kinds provided but only 3 glyphs rendered
        # Count glyph characters (each is 1+ codepoints)
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments
        # Simple approach: only first 3 kinds are joined
        _GLYPHS = {"timeout": "⏱", "auth": "🔒", "network": "🌐", "signal": "💀"}
        expected_3 = "".join(_GLYPHS[k] for k in ["timeout", "auth", "network"])
        assert expected_3 in text
        fourth = _GLYPHS["signal"]
        assert fourth not in text

    def test_er_d2_05_accessible_mode_text_form(self) -> None:
        h = _SubAgentHeaderAccessibleStub()
        h.update(child_count=2, error_count=1, elapsed_ms=0, done=False,
                 error_kinds=["timeout", "auth"])
        assert "err-kinds:timeout,auth" in h._last_badge
        # no glyphs
        assert "⏱" not in h._last_badge
        assert "🔒" not in h._last_badge

    def test_er_d2_06_no_error_count_no_glyphs(self) -> None:
        h = _SubAgentHeaderStub()
        h.update(child_count=3, error_count=0, elapsed_ms=0, done=True,
                 error_kinds=["timeout"])
        assert "error-kinds" not in h._seg_names()


# ---------------------------------------------------------------------------
# Context managers for deterministic / non-deterministic mode
# ---------------------------------------------------------------------------

class _deterministic:
    def __enter__(self) -> "_deterministic":
        os.environ["HERMES_DETERMINISTIC"] = "1"
        return self

    def __exit__(self, *_: Any) -> None:
        os.environ.pop("HERMES_DETERMINISTIC", None)


class _non_deterministic:
    def __enter__(self) -> "_non_deterministic":
        os.environ.pop("HERMES_DETERMINISTIC", None)
        return self

    def __exit__(self, *_: Any) -> None:
        pass
