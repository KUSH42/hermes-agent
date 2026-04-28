"""Tests for UX Audit C — Affordance / Discoverability (Spec C).

Covers C1 (remediation hint), C2 (ghost-text Tab suffix), C3 (S-key session hint),
C5 (dynamic header tooltip), C6 (SkillPicker footer).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from hermes_cli.tui.tool_blocks._header import ToolHeader, _REMEDIATION_BY_CATEGORY
from hermes_cli.tui.widgets.status_bar import HintBar, _build_hints, _hint_cache, KEY_S
from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
from hermes_cli.tui.tool_panel.density import DensityTier


# ---------------------------------------------------------------------------
# C1 — Remediation hint for collapsed-error headers
# ---------------------------------------------------------------------------

class _TestHeader(ToolHeader):
    """Isolated subclass that shadows the 'collapsed' reactive with a plain property.

    This avoids ReactiveError on object.__new__ instances (Textual's Reactive.__set__
    and __get__ both check hasattr(obj, "_id") and raise if missing).
    """
    @property
    def collapsed(self):
        return self.__dict__.get("_test_collapsed", False)


class TestC1RemediationHint:
    def _make_header(self, collapsed: bool, is_error: bool, error_category=None):
        h = object.__new__(_TestHeader)
        h.__dict__["_test_collapsed"] = collapsed
        h.__dict__["_panel"] = SimpleNamespace(
            _view_state=SimpleNamespace(is_error=is_error, error_category=error_category)
        )
        return h

    def test_remediation_none_when_expanded(self):
        h = self._make_header(collapsed=False, is_error=True, error_category="timeout")
        h._refresh_remediation_hint()
        assert h._remediation_hint is None

    def test_remediation_none_when_no_error(self):
        h = self._make_header(collapsed=True, is_error=False, error_category="timeout")
        h._refresh_remediation_hint()
        assert h._remediation_hint is None

    def test_remediation_renders_for_known_category(self):
        h = self._make_header(collapsed=True, is_error=True, error_category="timeout")
        h._refresh_remediation_hint()
        assert h._remediation_hint == "→ Retry"

    def test_remediation_falls_through_unknown_category(self):
        h = self._make_header(collapsed=True, is_error=True, error_category="alien_thing")
        h._refresh_remediation_hint()
        assert h._remediation_hint is None

    def test_remediation_normalises_enum_category(self):
        """Enum instances with a .value attr are normalised before lookup."""
        from hermes_cli.tui.services.error_taxonomy import ErrorCategory
        h = self._make_header(collapsed=True, is_error=True, error_category=ErrorCategory.TIMEOUT)
        h._refresh_remediation_hint()
        assert h._remediation_hint == "→ Retry"


# ---------------------------------------------------------------------------
# C2 — Compact-mode ghost-text Tab suffix in HintBar
# ---------------------------------------------------------------------------

class TestC2GhostTextHint:
    def _make_bar(self, density_tier: str, has_ghost: bool) -> HintBar:
        bar = object.__new__(HintBar)
        bar._density_tier = density_tier
        bar._has_ghost_suggestion = has_ghost
        return bar

    def test_hintbar_shows_tab_hint_in_compact_with_ghost(self):
        bar = self._make_bar(DensityTier.COMPACT.value, True)
        result = bar._tab_hint_suffix("long", "cyan")
        assert "Tab" in result

    def test_hintbar_hides_tab_hint_no_ghost(self):
        bar = self._make_bar(DensityTier.COMPACT.value, False)
        result = bar._tab_hint_suffix("long", "cyan")
        assert "Tab" not in result

    def test_hintbar_hides_tab_hint_in_default_tier(self):
        bar = self._make_bar(DensityTier.DEFAULT.value, True)
        result = bar._tab_hint_suffix("long", "cyan")
        assert "Tab" not in result

    @pytest.mark.asyncio
    async def test_ghost_suggestion_propagated_from_resolve_assist(self):
        from textual.app import App, ComposeResult
        from textual.reactive import reactive as _reactive
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.input._assist import AssistKind

        class _MinimalApp(App):
            CSS = ""
            status_ghost_suggestion: _reactive[bool] = _reactive(False)

            def compose(self) -> ComposeResult:
                yield HermesInput()

        async with _MinimalApp().run_test() as pilot:
            hermes_input = pilot.app.query_one(HermesInput)
            hermes_input._resolve_assist(AssistKind.GHOST, "some_suggestion")
            await pilot.pause()
            assert pilot.app.status_ghost_suggestion is True


# ---------------------------------------------------------------------------
# C3 — S-key session hint in HintBar idle phase
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_hint_cache():
    _hint_cache.clear()
    yield
    _hint_cache.clear()


class TestC3SessionHint:
    def test_idle_default_hint_contains_s_session(self):
        hints = _build_hints("idle", "cyan")
        long_hint = hints["long"]
        assert KEY_S in long_hint
        assert "session" in long_hint

    def test_idle_minimal_hint_omits_s_session(self):
        hints = _build_hints("idle", "cyan")
        assert "session" not in hints["minimal"]


# ---------------------------------------------------------------------------
# C5 — Dynamic ToolHeader tooltip text
# ---------------------------------------------------------------------------

class _TestHeader5(ToolHeader):
    """Isolated subclass for C5 tooltip tests."""
    @property
    def collapsed(self):
        return self.__dict__.get("_test_collapsed", False)


class TestC5HeaderTooltip:
    def test_tooltip_collapsed_error(self):
        h = object.__new__(_TestHeader5)
        h.__dict__["_test_collapsed"] = True
        h.__dict__["_panel"] = SimpleNamespace(
            _view_state=SimpleNamespace(is_error=True)
        )
        result = h._compute_tooltip_text()
        assert "error detail" in result

    def test_tooltip_collapsed_no_error(self):
        h = object.__new__(_TestHeader5)
        h.__dict__["_test_collapsed"] = True
        h.__dict__["_panel"] = SimpleNamespace(
            _view_state=SimpleNamespace(is_error=False)
        )
        result = h._compute_tooltip_text()
        assert "expand" in result
        assert "error" not in result

    def test_tooltip_expanded(self):
        h = object.__new__(_TestHeader5)
        h.__dict__["_test_collapsed"] = False
        h.__dict__["_panel"] = None
        result = h._compute_tooltip_text()
        assert "collapse" in result


# ---------------------------------------------------------------------------
# C6 — SkillPickerOverlay footer hint formatting
# ---------------------------------------------------------------------------

class TestC6SkillPickerFooter:
    def test_skill_picker_footer_uses_colored_key_markup(self):
        result = SkillPickerOverlay._build_footer_text("cyan")
        assert re.search(r"\[bold [^\]]+\]Enter\[/\]", result)

    def test_skill_picker_footer_uses_user_friendly_verbs(self):
        result = SkillPickerOverlay._build_footer_text("cyan")
        assert "run" in result
        assert "paste" in result
        assert "view docs" in result
        assert "invoke" not in result
        assert "insert" not in result

    def test_skill_picker_footer_fallback_verbs_match_builder(self):
        fallback = "Enter run  ·  Tab paste  ·  ? view docs  ·  Esc cancel"
        builder = SkillPickerOverlay._build_footer_text("cyan")
        for verb in ("run", "paste", "view docs", "cancel"):
            assert verb in fallback
            assert verb in builder
