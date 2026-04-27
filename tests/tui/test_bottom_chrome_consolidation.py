"""Tests for bottom chrome row consolidation (BD-1, BD-2).

BD-1: AssistantNameplate + HintBar merged into #nameplate-hint-row Horizontal.
BD-2: SessionBar hidden; session indicator folded into StatusBar; S key opens sessions.
"""
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_app_compose_source() -> str:
    from hermes_cli.tui.app import HermesApp
    return inspect.getsource(HermesApp.compose)


def _get_tcss() -> str:
    import pathlib
    p = pathlib.Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
    return p.read_text()


# ---------------------------------------------------------------------------
# TestNameplateHintMerge — BD-1
# ---------------------------------------------------------------------------

class TestNameplateHintMerge:

    def test_nameplate_hint_row_in_compose(self):
        """#nameplate-hint-row Horizontal wraps nameplate + hintbar; neither is a bare sibling."""
        src = _get_app_compose_source()
        assert 'Horizontal(id="nameplate-hint-row")' in src, (
            "compose() must contain Horizontal(id='nameplate-hint-row')"
        )
        # Both must be indented inside the Horizontal block — they should not appear
        # at the same indentation as the Horizontal itself.
        lines = src.splitlines()
        horizontal_indent = None
        for line in lines:
            if 'Horizontal(id="nameplate-hint-row")' in line:
                horizontal_indent = len(line) - len(line.lstrip())
                break
        assert horizontal_indent is not None, "Could not find nameplate-hint-row in compose"
        # AssistantNameplate must appear at a deeper indent than the Horizontal
        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if "AssistantNameplate(" in stripped:
                assert indent > horizontal_indent, (
                    f"AssistantNameplate indent ({indent}) must be deeper than "
                    f"Horizontal indent ({horizontal_indent})"
                )
            if 'HintBar(' in stripped and 'id="hint-bar"' in stripped:
                assert indent > horizontal_indent, (
                    f"HintBar indent ({indent}) must be deeper than Horizontal indent ({horizontal_indent})"
                )

    def test_nameplate_hint_row_height(self):
        """#nameplate-hint-row CSS sets height: 1."""
        tcss = _get_tcss()
        assert "#nameplate-hint-row" in tcss, "#nameplate-hint-row block missing from hermes.tcss"
        # Find the block and assert height: 1
        idx = tcss.index("#nameplate-hint-row")
        block = tcss[idx: idx + 200]
        assert "height: 1" in block, "#nameplate-hint-row must have height: 1"

    def test_nameplate_width_pinned(self):
        """AssistantNameplate inside #nameplate-hint-row has width: 24."""
        tcss = _get_tcss()
        assert "#nameplate-hint-row AssistantNameplate" in tcss
        idx = tcss.index("#nameplate-hint-row AssistantNameplate")
        block = tcss[idx: idx + 200]
        assert "width: 24" in block, "#nameplate-hint-row AssistantNameplate must pin width: 24"

    def test_hintbar_takes_remaining_width(self):
        """HintBar inside #nameplate-hint-row has width: 1fr."""
        tcss = _get_tcss()
        assert "#nameplate-hint-row HintBar" in tcss
        idx = tcss.index("#nameplate-hint-row HintBar")
        block = tcss[idx: idx + 100]
        assert "width: 1fr" in block, "#nameplate-hint-row HintBar must have width: 1fr"

    def test_hintbar_render_uses_own_content_width(self):
        """HintBar.render() reads self.content_size.width (not terminal width)."""
        from hermes_cli.tui.widgets.status_bar import HintBar
        src = inspect.getsource(HintBar.render)
        assert "content_size.width" in src, (
            "HintBar.render() must use self.content_size.width for variant selection"
        )

    def test_total_bottom_chrome_height_reduced(self):
        """compose() wraps nameplate+hintbar in one Horizontal — 1 fewer top-level height:1 widget."""
        src = _get_app_compose_source()
        # Before BD-1: both AssistantNameplate and HintBar were bare yields.
        # After BD-1: only one Horizontal yield at the top level. Verify they are
        # not both bare yields at the same level (i.e., they're inside with-block).
        lines = src.splitlines()
        bare_nameplate = 0
        bare_hintbar = 0
        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            # A bare yield at compose body level is at exactly 8 spaces indent.
            # Inside a with-block the indent is 12+.
            if "yield AssistantNameplate(" in stripped and indent <= 8:
                bare_nameplate += 1
            if 'yield HintBar(' in stripped and indent <= 8:
                bare_hintbar += 1
        # Both must be zero — they are inside the with Horizontal block
        assert bare_nameplate == 0, (
            "AssistantNameplate must be inside Horizontal, not a bare yield in compose()"
        )
        assert bare_hintbar == 0, (
            "HintBar must be inside Horizontal, not a bare yield in compose()"
        )


# ---------------------------------------------------------------------------
# TestSessionInlineIndicator — BD-2
# ---------------------------------------------------------------------------

class TestSessionInlineIndicator:

    def _make_service(self, records=None, active_id="sess-1"):
        """Build a SessionsService stub with mock app."""
        from hermes_cli.tui.services.sessions import SessionsService
        svc = object.__new__(SessionsService)
        records = records or []
        app = SimpleNamespace(
            _session_records_cache=records,
            _session_active_id=active_id,
            session_label="",
            session_count=len(records),
            _session_mgr=None,
            _sessions_enabled_override=True,
        )
        svc.app = app
        return svc, app

    def test_session_label_empty_when_single_session(self):
        """session_label is empty when only 1 session."""
        svc, app = self._make_service(
            records=[SimpleNamespace(id="sess-1", title="main")],
            active_id="sess-1",
        )
        svc._update_session_label()
        assert app.session_label == "", f"Expected '' but got {app.session_label!r}"

    def test_session_label_set_when_multiple(self):
        """session_label is '[2/3]' when active=2, count=3."""
        records = [
            SimpleNamespace(id="s1", title="first"),
            SimpleNamespace(id="s2", title="second"),
            SimpleNamespace(id="s3", title="third"),
        ]
        svc, app = self._make_service(records=records, active_id="s2")
        svc._update_session_label()
        assert app.session_label == "[2/3]", (
            f"Expected '[2/3]' but got {app.session_label!r}"
        )

    def test_session_indicator_in_statusbar_render(self):
        """When session_label='[1/2]' and session_count=2, StatusBar render includes '[1/2]'."""
        from hermes_cli.tui.widgets.status_bar import StatusBar
        bar = object.__new__(StatusBar)
        app = SimpleNamespace(
            session_label="[1/2]",
            session_count=2,
            status_model="claude-sonnet",
            status_streaming=False,
            status_phase="idle",
            status_error="",
            agent_running=False,
            command_running=False,
            status_voice_mode="",
            status_active_file="",
            status_active_file_offscreen=False,
            plan_panel_collapsed=True,
            turn_cost_usd=0.0,
            turn_tokens_in=0,
            turn_tokens_out=0,
            status_context_tokens=0,
            status_context_max=0,
            status_compaction_progress=0.0,
            status_compaction_enabled=False,
            status_verbose=False,
            yolo_mode=False,
            compact=False,
            browse_mode=False,
            cli=None,
            feedback=None,
            get_css_variables=lambda: {},
            has_class=lambda *a: False,
        )
        from unittest.mock import PropertyMock
        # Patch app, size, and content_size so render() can run without DOM
        with patch.object(type(bar), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(type(bar), "size", new_callable=PropertyMock,
                              return_value=SimpleNamespace(width=80, height=1)):
                with patch.object(type(bar), "content_size", new_callable=PropertyMock,
                                  return_value=SimpleNamespace(width=80)):
                    result = bar.render()
        rendered = str(result) if hasattr(result, "__str__") else ""
        # StatusBar render returns a Rich Text or str; get plain text
        try:
            plain = result.plain
        except AttributeError:
            plain = str(result)
        assert "[1/2]" in plain, f"StatusBar render must include '[1/2]', got: {plain!r}"

    def test_session_bar_css_hidden(self):
        """SessionBar CSS has display: none !important so it is always hidden."""
        tcss = _get_tcss()
        # Find the actual CSS rule (not a comment line)
        rule_found = False
        for line in tcss.splitlines():
            stripped = line.strip()
            if stripped.startswith("SessionBar") and "{" in stripped:
                assert "display: none" in stripped, (
                    f"SessionBar rule must have 'display: none', got: {stripped!r}"
                )
                assert "!important" in stripped, (
                    f"SessionBar display: none must use !important, got: {stripped!r}"
                )
                rule_found = True
                break
        assert rule_found, "SessionBar { display: none !important; } rule not found in hermes.tcss"

    def test_s_key_opens_sessions_overlay(self):
        """'S' key binding exists in HermesApp BINDINGS pointing to open_sessions."""
        from hermes_cli.tui.app import HermesApp
        bindings = HermesApp.BINDINGS
        s_bindings = [b for b in bindings if getattr(b, "key", None) == "S"]
        assert len(s_bindings) >= 1, "HermesApp.BINDINGS must include a binding for 'S'"
        action = getattr(s_bindings[0], "action", "")
        assert "open_sessions" in action, (
            f"'S' binding action must be 'open_sessions', got {action!r}"
        )

    def test_total_bottom_chrome_height_reduced_session_case(self):
        """With BD-2, SessionBar is hidden unconditionally; no extra row when sessions > 1."""
        tcss = _get_tcss()
        # The !important rule on SessionBar means --sessions-enabled cannot reveal it
        rule_found = False
        for line in tcss.splitlines():
            stripped = line.strip()
            if stripped.startswith("SessionBar") and "{" in stripped and "!important" in stripped:
                rule_found = True
                break
        assert rule_found, (
            "SessionBar must use display: none !important to prevent --sessions-enabled from adding a row"
        )
