"""R3-VOCAB: SkinColors centralization + services/tools.py exception sweep.

Covers VOCAB-1 (header hex literals → SkinColors) + VOCAB-2 (28→0 non-compliant
except blocks in services/tools.py).
"""
from __future__ import annotations

import ast
import inspect
import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text
from textual.geometry import Size
from textual.widget import Widget

from hermes_cli.tui.body_renderers._grammar import SkinColors
from hermes_cli.tui.services import tools as tools_mod
from hermes_cli.tui.services.tools import ToolRenderingService


# ============================================================================
# Helpers (mirror test_header_tail_spec_a patterns)
# ============================================================================

def _bare_header(**kwargs):
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    defaults = dict(
        _label="test", _tool_name="bash", _line_count=0, _panel=None,
        _spinner_char=None, _is_complete=True, _tool_icon_error=False,
        _primary_hero=None, _header_chips=[], _stats=None, _duration="",
        _has_affordances=False, _label_rich=None, _is_child_diff=False,
        _header_args={}, _flash_msg=None, _flash_expires=0.0, _flash_tone="success",
        _error_kind=None, _tool_icon="", _full_path=None, _path_clickable=False,
        _is_child=False, _exit_code=None, _browse_badge="", _elapsed_ms=None,
        _no_underline=False, _bold_label=False, _hidden=False, _shell_prompt=False,
        _compact_tail=False, _is_url=False, _classes=frozenset(),
        _focused_gutter_color="#5f87d7",
        _diff_add_color="#4caf50", _diff_del_color="#ef4444",
        _running_icon_color="#82aaff", _remediation_hint=None,
        _pulse_t=0.0, _pulse_tick=0,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(h, k, v)
    return h


def _render(h, *, width: int = 80, css_vars: dict | None = None,
            from_app_colors: SkinColors | None = None, accessible: bool = False):
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = css_vars or {}
    with patch.object(Widget, "size", new_callable=PropertyMock,
                      return_value=Size(width, 24)):
        with patch.object(type(h), "app", new_callable=PropertyMock,
                          return_value=mock_app):
            with patch.object(h, "_accessible_mode", return_value=accessible):
                if from_app_colors is not None:
                    with patch.object(SkinColors, "from_app", return_value=from_app_colors):
                        # Bust any cache from a prior render in the same header.
                        h._skin_colors_cache = None
                        return h._render_v4()
                return h._render_v4()


def _spans_for_substring(result: Text, substring: str):
    plain = result.plain
    pos = plain.find(substring)
    if pos == -1:
        return []
    end = pos + len(substring)
    return [s for s in result._spans if s.start < end and s.end > pos]


def _make_app(**overrides):
    """Minimal HermesApp mock for ToolRenderingService."""
    app = MagicMock()
    app.agent_running = True
    app._browse_total = 0
    app._current_turn_tool_count = 0
    app._explicit_parent_map = {}
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0
    app._active_tool_name = ""
    app._turn_start_monotonic = 0.0
    app._svc_commands = MagicMock()
    app.planned_calls = []
    for k, v in overrides.items():
        setattr(app, k, v)
    return app


# ============================================================================
# VOCAB-1
# ============================================================================

class TestSkinColorsNewFields:
    def test_skincolors_default_has_icon_dim_and_separator_dim(self):
        d = SkinColors.default()
        assert d.icon_dim == "#6e6e6e"
        assert d.separator_dim == "#555555"

    def test_skincolors_from_app_reads_new_vars(self):
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {
            "icon-dim": "#abcdef",
            "separator-dim": "#123456",
        }
        c = SkinColors.from_app(mock_app)
        assert c.icon_dim == "#abcdef"
        assert c.separator_dim == "#123456"

    def test_skincolors_from_app_invalid_hex_falls_back(self):
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {
            "icon-dim": "garbage",
            "separator-dim": "not-a-hex",
        }
        c = SkinColors.from_app(mock_app)
        d = SkinColors.default()
        assert c.icon_dim == d.icon_dim
        assert c.separator_dim == d.separator_dim


class TestToolHeaderColorsCache:
    def test_tool_header_colors_cache_lazy(self):
        h = _bare_header()
        h._skin_colors_cache = None
        sentinel = SkinColors.default()
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=MagicMock()):
            with patch.object(SkinColors, "from_app", return_value=sentinel) as mocked:
                a = h._colors()
                b = h._colors()
        assert a is sentinel
        assert b is sentinel
        assert mocked.call_count == 1

    def test_tool_header_colors_no_app_returns_default(self):
        h = _bare_header()
        h._skin_colors_cache = None
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=MagicMock()):
            with patch.object(SkinColors, "from_app", side_effect=RuntimeError("no app")):
                c = h._colors()
        assert c == SkinColors.default()


class TestToolHeaderUsesSkinColors:
    def test_chevron_slot_uses_separator_dim(self):
        custom = SkinColors.default().__class__(
            **{**SkinColors.default().__dict__, "separator_dim": "#cafe11"}
        )
        h = _bare_header(_has_affordances=False, _is_complete=False)
        result = _render(h, from_app_colors=custom, width=120)
        assert result is not None
        spans = _spans_for_substring(result, "·")
        styles = " ".join(str(s.style) for s in spans)
        assert "#cafe11" in styles
        assert "#444444" not in styles

    def test_meta_separator_uses_separator_dim(self):
        custom = SkinColors.default().__class__(
            **{**SkinColors.default().__dict__, "separator_dim": "#beadda"}
        )
        # Two tail segments → meta separator " · " painted.
        h = _bare_header(
            _tool_name="read_file",
            _primary_hero="Read 10 lines",
            _duration="1.2s",
            _is_complete=True,
        )
        result = _render(h, from_app_colors=custom, width=200)
        assert result is not None
        # Meta separator appears at " · " (3 chars). Walk every span over the plain.
        styles = " ".join(str(s.style) for s in result._spans)
        assert "#beadda" in styles
        assert "#555555" not in styles

    def test_warn_fallback_uses_skincolors_warning(self):
        # Force the stderr-warn tail segment: collapsed panel with stderr_tail.
        rs = MagicMock()
        rs.stderr_tail = "boom"
        panel = MagicMock()
        panel.collapsed = True
        panel._result_summary_v4 = rs
        custom = SkinColors.default().__class__(
            **{**SkinColors.default().__dict__, "warning": "#bada55"}
        )
        # Path 1: get_css_variables returns dict without 'status-warn-color'.
        h = _bare_header(
            _tool_name="bash", _is_complete=True, _tool_icon_error=True,
            _panel=panel, _exit_code=1,
        )
        result = _render(h, from_app_colors=custom, css_vars={}, width=200)
        assert result is not None
        styles = " ".join(str(s.style) for s in result._spans)
        assert "#bada55" in styles
        assert "#FFA726" not in styles
        # Path 2: get_css_variables raises → except branch falls back to skin.
        h2 = _bare_header(
            _tool_name="bash", _is_complete=True, _tool_icon_error=True,
            _panel=panel, _exit_code=1,
        )
        mock_app = MagicMock()
        mock_app.get_css_variables.side_effect = RuntimeError("pre-mount")
        with patch.object(Widget, "size", new_callable=PropertyMock, return_value=Size(200, 24)):
            with patch.object(type(h2), "app", new_callable=PropertyMock, return_value=mock_app):
                with patch.object(h2, "_accessible_mode", return_value=False):
                    with patch.object(SkinColors, "from_app", return_value=custom):
                        h2._skin_colors_cache = None
                        result2 = h2._render_v4()
        assert result2 is not None
        styles2 = " ".join(str(s.style) for s in result2._spans)
        assert "#bada55" in styles2

    @pytest.mark.parametrize("missing_value", [None, ""])
    def test_focus_accent_falls_back_to_skin_accent(self, missing_value):
        custom = SkinColors.default().__class__(
            **{**SkinColors.default().__dict__, "accent": "#abc123"}
        )
        # Trigger the flash branch.
        import time as _t
        h = _bare_header(
            _tool_name="bash", _is_complete=True,
            _flash_msg="ok", _flash_expires=_t.monotonic() + 60,
            _flash_tone="success",
            _focused_gutter_color=missing_value,
        )
        result = _render(h, from_app_colors=custom, width=120)
        assert result is not None
        spans = _spans_for_substring(result, "✓ ok")
        styles = " ".join(str(s.style) for s in spans)
        assert "#abc123" in styles
        assert "#5f87d7" not in styles


# ============================================================================
# VOCAB-2 — Pattern A bare swallows
# ============================================================================

def _trigger_l201(svc, app):
    """L201: open_reasoning DrawbrailleOverlay signal."""
    svc.current_message_panel = MagicMock(return_value=None)
    app.query_one = MagicMock(side_effect=RuntimeError("simulated"))
    svc.open_reasoning("title")


def _trigger_l219(svc, app):
    """L219: close_reasoning DrawbrailleOverlay signal."""
    svc.current_message_panel = MagicMock(return_value=None)
    app.agent_running = True
    app.query_one = MagicMock(side_effect=RuntimeError("simulated"))
    svc.close_reasoning()


def _trigger_l392(svc, app):
    """L389/L392: depth-warning Static mount on ancestor panel."""
    parent_id = "parent"
    tool_call_id = "child"
    parent_rec = tools_mod._ToolCallRecord(
        tool_call_id=parent_id,
        parent_tool_call_id=None,
        label="L", tool_name="agent",
        category="agent", depth=3,
        start_s=0.0, dur_ms=None,
        is_error=False, error_kind=None, mcp_server=None,
    )
    svc._turn_tool_calls[parent_id] = parent_rec
    app._explicit_parent_map = {tool_call_id: parent_id}
    output = MagicMock()
    output._user_scrolled_up = True
    msg = MagicMock()
    msg._subagent_panels = {parent_id: MagicMock()}
    msg._subagent_panels[parent_id]._body.mount.side_effect = RuntimeError("mount-fail")
    output.current_message = msg
    output.is_mounted = True
    app._cached_output_panel = output
    # Stub query_one for panel_id collision check (NoMatches branch).
    from textual.css.query import NoMatches
    app.query_one = MagicMock(side_effect=NoMatches("free"))
    svc.open_streaming_tool_block(tool_call_id, label="lbl", tool_name="bash")


def _trigger_l409(svc, app):
    """L406/L409: panel.add_class('--streaming') failure."""
    output = MagicMock()
    output._user_scrolled_up = True
    msg = MagicMock()
    msg._subagent_panels = {}
    output.current_message = msg
    output.is_mounted = True
    app._cached_output_panel = output
    from textual.css.query import NoMatches
    app.query_one = MagicMock(side_effect=NoMatches("free"))
    block = MagicMock()
    block._tool_panel = MagicMock()
    block._tool_panel.add_class.side_effect = RuntimeError("css-fail")
    msg.open_streaming_tool_block.return_value = block
    svc.open_streaming_tool_block("tcid", label="lbl", tool_name="bash")


def _trigger_l418(svc, app):
    """L415/L418: DrawbrailleOverlay tool signal (inside open_streaming_tool_block)."""
    output = MagicMock()
    output._user_scrolled_up = True
    msg = MagicMock()
    msg._subagent_panels = {}
    output.current_message = msg
    output.is_mounted = True
    app._cached_output_panel = output
    from textual.css.query import NoMatches

    def _query_side(arg):
        # First call: panel_id collision check → NoMatches (free).
        # Subsequent (DrawbrailleOverlay): raise RuntimeError to trigger L418.
        if isinstance(arg, str):
            raise NoMatches("free")
        raise RuntimeError("overlay-fail")
    app.query_one.side_effect = _query_side
    block = MagicMock()
    block._tool_panel = MagicMock()
    msg.open_streaming_tool_block.return_value = block
    svc.open_streaming_tool_block("tcid", label="lbl", tool_name="bash")


def _trigger_l777(svc, app):
    """L774/L777: header.refresh() post-arg-wire."""
    from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
    block = MagicMock()
    block._tool_input = {}
    header = MagicMock()
    header.refresh.side_effect = RuntimeError("refresh-fail")
    block._header = header
    panel = MagicMock(spec=["set_tool_args"])
    view = ToolCallViewState(
        tool_call_id="tcid", gen_index=0, tool_name="bash",
        label="L", args={}, state=ToolCallState.STARTED,
        block=block, panel=panel,
        parent_tool_call_id=None, category="shell", depth=0,
        start_s=0.0,
    )
    svc._wire_args(view, {"a": 1})


SITE_TRIGGERS = [
    ("l201", _trigger_l201, "DrawbrailleOverlay.signal('reasoning') failed"),
    ("l219", _trigger_l219, "DrawbrailleOverlay.signal('thinking') failed"),
    ("l392", _trigger_l392, "depth-warning _Static mount on ancestor panel failed"),
    ("l409", _trigger_l409, "panel.add_class('--streaming') failed"),
    ("l418", _trigger_l418, "DrawbrailleOverlay.signal('tool') failed"),
    ("l777", _trigger_l777, "header.refresh() post-arg-wire failed"),
]


class TestExceptionSweepBareSwallows:
    @pytest.mark.parametrize("site,trigger,msg", SITE_TRIGGERS, ids=[s[0] for s in SITE_TRIGGERS])
    def test_pattern_a_logs_debug_for_each_site(self, site, trigger, msg):
        app = _make_app()
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc.app = app
        svc._streaming_map = {}
        svc._turn_tool_calls = {}
        svc._agent_stack = []
        svc._subagent_panels = {}
        svc._open_tool_count = 0
        svc._tool_views_by_id = {}
        svc._tool_views_by_gen_index = {}
        svc._pending_gen_arg_deltas = {}
        with patch.object(tools_mod.logger, "debug") as mock_dbg:
            trigger(svc, app)
        msgs = [str(c.args[0]) if c.args else "" for c in mock_dbg.call_args_list]
        assert any(msg in m for m in msgs), f"site={site} expected log {msg!r}, got {msgs}"
        target_calls = [c for c in mock_dbg.call_args_list if c.args and msg in str(c.args[0])]
        assert all(c.kwargs.get("exc_info") is True for c in target_calls), \
            f"site={site}: exc_info=True missing in {target_calls}"


# ============================================================================
# VOCAB-2 — Pattern B narrowed except blocks
# ============================================================================

class TestExceptionSweepClassifyToolDead:
    def test_no_try_except_wraps_classify_tool_or_ct(self):
        src = inspect.getsource(tools_mod)
        tree = ast.parse(src)

        def _is_target(node):
            if not isinstance(node, ast.Call):
                return False
            f = node.func
            if isinstance(f, ast.Name) and f.id in ("classify_tool", "_ct"):
                return True
            if isinstance(f, ast.Attribute) and f.attr == "classify_tool":
                return True
            return False

        offenders = []
        # Walk every Try; for each handler that catches bare Exception, scan body for target.
        for try_node in ast.walk(tree):
            if not isinstance(try_node, ast.Try):
                continue
            catches_exception = any(
                (isinstance(h.type, ast.Name) and h.type.id == "Exception")
                for h in try_node.handlers
            )
            if not catches_exception:
                continue
            for stmt in try_node.body:
                for sub in ast.walk(stmt):
                    if _is_target(sub):
                        offenders.append((sub.lineno, ast.dump(sub.func)))
        assert not offenders, f"classify_tool/_ct still wrapped in try/except Exception: {offenders}"


class TestExceptionSweepValueCoalesce:
    def _fresh_svc(self, app):
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc.app = app
        svc._streaming_map = {}
        svc._turn_tool_calls = {}
        svc._agent_stack = []
        svc._subagent_panels = {}
        svc._open_tool_count = 0
        svc._tool_views_by_id = {}
        svc._tool_views_by_gen_index = {}
        svc._pending_gen_arg_deltas = {}
        return svc

    def test_query_one_panel_id_collision(self):
        from textual.css.query import NoMatches
        app = _make_app()
        svc = self._fresh_svc(app)
        output = MagicMock()
        output._user_scrolled_up = True
        msg = MagicMock()
        msg._subagent_panels = {}
        output.current_message = msg
        output.is_mounted = True
        app._cached_output_panel = output
        block = MagicMock()
        block._tool_panel = MagicMock()
        msg.open_streaming_tool_block.return_value = block

        # Case A: query_one returns existing widget → panel_id is None.
        app.query_one = MagicMock(return_value=MagicMock())
        svc.open_streaming_tool_block("a1", label="L", tool_name="bash")
        kwargs_a = msg.open_streaming_tool_block.call_args.kwargs
        assert kwargs_a["panel_id"] is None

        # Case B: query_one raises NoMatches → panel_id = base.
        msg.open_streaming_tool_block.reset_mock()
        app.query_one = MagicMock(side_effect=NoMatches("free"))
        svc.open_streaming_tool_block("b2", label="L", tool_name="bash")
        kwargs_b = msg.open_streaming_tool_block.call_args.kwargs
        assert kwargs_b["panel_id"] == "tool-b2"

        # Case C: query_one raises RuntimeError → propagates.
        msg.open_streaming_tool_block.reset_mock()
        app.query_one = MagicMock(side_effect=RuntimeError("dom-broken"))
        with pytest.raises(RuntimeError, match="dom-broken"):
            svc.open_streaming_tool_block("c3", label="L", tool_name="bash")

    def test_json_dumps_preview_unserializable_returns_empty(self):
        app = _make_app()
        svc = self._fresh_svc(app)
        # Non-serializable args (set is not JSON-able).
        svc.set_plan_batch([("tcid", "bash", "label", {"x": {1, 2}})])
        assert len(app.planned_calls) == 1
        assert app.planned_calls[0].args_preview == ""

        # RuntimeError from json.dumps must propagate (not in narrowed catch).
        app2 = _make_app()
        svc2 = self._fresh_svc(app2)
        with patch.object(json, "dumps", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                svc2.set_plan_batch([("tcid", "bash", "label", {"a": 1})])

    def test_partial_json_stream_skipped_logs_debug(self):
        app = _make_app()
        svc = self._fresh_svc(app)
        block = MagicMock(spec=["feed_delta", "update_progress"])
        # Case 1: partial JSON.
        with patch.object(tools_mod.logger, "debug") as mock_dbg:
            svc._apply_gen_arg_delta(block, "write_file", delta="{", accumulated='{"total_size":')
        msgs = [str(c.args[0]) for c in mock_dbg.call_args_list if c.args]
        assert any("partial JSON during stream" in m for m in msgs), msgs
        partial_calls = [c for c in mock_dbg.call_args_list
                         if c.args and "partial JSON" in str(c.args[0])]
        assert all(c.kwargs.get("exc_info") is True for c in partial_calls)
        # update_progress called; total stays 0.
        assert block.update_progress.called
        last_call = block.update_progress.call_args
        assert last_call.args[1] == 0  # total

        # Case 2: valid JSON but non-numeric total_size.
        block2 = MagicMock(spec=["feed_delta", "update_progress"])
        with patch.object(tools_mod.logger, "debug") as mock_dbg2:
            svc._apply_gen_arg_delta(
                block2, "write_file", delta="x",
                accumulated='{"total_size":"garbage"}',
            )
        msgs2 = [str(c.args[0]) for c in mock_dbg2.call_args_list if c.args]
        assert any("non-numeric total" in m for m in msgs2), msgs2
        nn_calls = [c for c in mock_dbg2.call_args_list
                    if c.args and "non-numeric total" in str(c.args[0])]
        assert all(c.kwargs.get("exc_info") is True for c in nn_calls)
        assert block2.update_progress.call_args.args[1] == 0


# ============================================================================
# VOCAB-2 — Logger contract guard (every Pattern A site uses exc_info=True)
# ============================================================================

class TestExceptionSweepLoggerContract:
    def test_pattern_a_loggers_use_exc_info_true(self):
        for site, trigger, expected_msg in SITE_TRIGGERS:
            app = _make_app()
            svc = ToolRenderingService.__new__(ToolRenderingService)
            svc.app = app
            svc._streaming_map = {}
            svc._turn_tool_calls = {}
            svc._agent_stack = []
            svc._subagent_panels = {}
            svc._open_tool_count = 0
            svc._tool_views_by_id = {}
            svc._tool_views_by_gen_index = {}
            svc._pending_gen_arg_deltas = {}
            with patch.object(tools_mod.logger, "debug") as mock_dbg:
                trigger(svc, app)
            target_calls = [
                c for c in mock_dbg.call_args_list
                if c.args and expected_msg in str(c.args[0])
            ]
            assert target_calls, f"site={site}: no matching debug call for {expected_msg!r}"
            for c in target_calls:
                assert c.kwargs.get("exc_info") is True, \
                    f"site={site}: exc_info missing on call {c}"
