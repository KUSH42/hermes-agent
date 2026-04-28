"""Tests for UX Audit A — Skin / Visual Hierarchy / Consistency spec.

Covers:
  A1 — Nameplate dead animation cleanup
  A2 — Phase-responsive chevron opacity
  A3 — ReasoningPanel $reasoning-accent token
  A4 — Documented opacity tier rule for category accents
  A5 — Error banner uses $error token
  A6 — Density tier vocabulary (DEFAULT not STANDARD)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets import AssistantNameplate

# ── Paths ─────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent.parent
_TCSS = _ROOT / "hermes_cli" / "tui" / "hermes.tcss"
_APP_PY = _ROOT / "hermes_cli" / "tui" / "app.py"
_CONCEPT_DOC = _ROOT / "docs" / "concept.md"
_SKIN_DIRS = [
    _ROOT / "skins" / "catppuccin" / "DESIGN.md",
    _ROOT / "skins" / "matrix" / "DESIGN.md",
    _ROOT / "skins" / "solarized-dark" / "DESIGN.md",
    _ROOT / "skins" / "tokyo-night" / "DESIGN.md",
]


# ── A1 — Nameplate dead animation cleanup ─────────────────────────────────────


class _HiddenNameplateApp(App):
    CSS = "AssistantNameplate { display: none; }"

    def compose(self) -> ComposeResult:
        yield AssistantNameplate(id="nameplate", name="Test")


class _VisibleNameplateApp(App):
    def compose(self) -> ComposeResult:
        yield AssistantNameplate(id="nameplate", name="Test")


class TestA1NameplateAnimDeadCode:
    @pytest.mark.asyncio
    async def test_nameplate_idle_timer_not_started_when_hidden(self):
        """Hidden nameplate must not start the main animation interval."""
        async with _HiddenNameplateApp().run_test() as pilot:
            await pilot.pause()
            np = pilot.app.query_one(AssistantNameplate)
            assert np._timer is None, (
                "_timer should be None when AssistantNameplate is display:none; "
                "animation guard must fire early"
            )

    @pytest.mark.asyncio
    async def test_nameplate_idle_timer_started_when_visible(self):
        """Visible nameplate must start the main 30fps animation interval."""
        async with _VisibleNameplateApp().run_test() as pilot:
            await pilot.pause()
            np = pilot.app.query_one(AssistantNameplate)
            assert np._timer is not None, (
                "_timer should be set when AssistantNameplate is visible; "
                "animation guard must not fire for visible widgets"
            )

    def test_app_construction_no_animation_kwargs(self):
        """app.py must not pass effects_enabled, idle_effect, or glitch_enabled to AssistantNameplate."""
        source = _APP_PY.read_text()
        tree = ast.parse(source)

        dead_kwargs = {"effects_enabled", "idle_effect", "glitch_enabled"}
        found = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name != "AssistantNameplate":
                continue
            for kw in node.keywords:
                if kw.arg in dead_kwargs:
                    found.add(kw.arg)

        assert not found, (
            f"app.py AssistantNameplate(...) still passes dead kwargs: {found}. "
            "Drop effects_enabled, idle_effect, glitch_enabled."
        )


# ── A2 — Phase-responsive chevron opacity ─────────────────────────────────────

_PHASE_CLASSES = [
    "--phase-done",
    "--phase-stream",
    "--phase-file",
    "--phase-shell",
    "--phase-error",
]


class TestA2ChevronPhaseOpacity:
    def _tcss(self) -> str:
        return _TCSS.read_text()

    def _block_for(self, tcss: str, phase_class: str) -> str:
        pattern = rf"#input-chevron\.{re.escape(phase_class)}\s*\{{([^}}]*)\}}"
        m = re.search(pattern, tcss)
        assert m, f"No rule found for #input-chevron.{phase_class}"
        return m.group(1)

    def test_chevron_phase_classes_have_opacity_rule(self):
        """Every actual phase class must have an opacity: declaration."""
        tcss = self._tcss()
        for phase in _PHASE_CLASSES:
            block = self._block_for(tcss, phase)
            assert "opacity:" in block, (
                f"#input-chevron.{phase} block missing opacity: declaration"
            )

    def test_chevron_error_opacity_is_one(self):
        """--phase-error must have opacity 1.0 (highest among all phase rules)."""
        tcss = self._tcss()
        error_block = self._block_for(tcss, "--phase-error")
        m = re.search(r"opacity:\s*([0-9.]+)", error_block)
        assert m, "#input-chevron.--phase-error: no opacity value found"
        error_opacity = float(m.group(1))
        assert error_opacity == 1.0, (
            f"--phase-error opacity should be 1.0, got {error_opacity}"
        )
        # Also verify it's highest among all phases
        for phase in _PHASE_CLASSES:
            if phase == "--phase-error":
                continue
            block = self._block_for(tcss, phase)
            m2 = re.search(r"opacity:\s*([0-9.]+)", block)
            if m2:
                assert float(m2.group(1)) <= error_opacity, (
                    f"{phase} opacity {m2.group(1)} exceeds error opacity {error_opacity}"
                )


# ── A3 — ReasoningPanel $reasoning-accent token ───────────────────────────────


class TestA3ReasoningAccent:
    def test_skin_exports_reasoning_accent_var(self):
        """reasoning-accent must appear in COMPONENT_VAR_DEFAULTS and all 4 skins."""
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS

        assert "reasoning-accent" in COMPONENT_VAR_DEFAULTS, (
            "COMPONENT_VAR_DEFAULTS in theme_manager.py missing 'reasoning-accent' key"
        )

        tcss = _TCSS.read_text()
        assert re.search(r"^\$reasoning-accent:", tcss, re.MULTILINE), (
            "hermes.tcss missing '$reasoning-accent:' variable declaration"
        )

        for skin_path in _SKIN_DIRS:
            content = skin_path.read_text()
            # Load YAML front-matter if present (between --- markers)
            fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            assert fm_match, f"{skin_path.name}: no YAML front-matter found"
            data = yaml.safe_load(fm_match.group(1))
            component_vars = (
                data.get("x-hermes", {}).get("component-vars", {})
                or data.get("component-vars", {})
                or {}
            )
            assert "reasoning-accent" in component_vars, (
                f"{skin_path.parent.name}/DESIGN.md missing 'reasoning-accent' "
                f"in x-hermes.component-vars"
            )

    def test_reasoning_panel_gutter_at_60pct(self):
        """ReasoningPanel border-left must reference $reasoning-accent at 60%."""
        tcss = _TCSS.read_text()
        m = re.search(r"ReasoningPanel\s*\{([^}]*)\}", tcss, re.DOTALL)
        assert m, "No ReasoningPanel rule found in hermes.tcss"
        block = m.group(1)
        assert "$reasoning-accent" in block, (
            "ReasoningPanel border-left must reference $reasoning-accent"
        )
        assert "60%" in block, (
            "ReasoningPanel border-left must use 60% opacity"
        )


# ── A4 — Documented opacity tier rule for category accents ────────────────────

_CATEGORY_EXPECTED_OPACITY = {
    "file":   "80%",
    "shell":  "80%",
    "vision": "80%",
    "web":    "60%",
    "mcp":    "60%",
    "code":   "60%",
    "search": "40%",
    "agent":  "40%",
}


class TestA4CategoryOpacityTable:
    def _block_for_category(self, tcss: str, cat: str) -> str:
        pattern = (
            rf"ToolPanel\.category-{re.escape(cat)}\.tool-panel--accent\s*\{{([^}}]*)\}}"
        )
        m = re.search(pattern, tcss)
        assert m, f"No rule for ToolPanel.category-{cat}.tool-panel--accent in hermes.tcss"
        return m.group(1)

    def test_category_accent_opacity_table(self):
        """Each category accent must use the opacity defined by the criticality tier."""
        tcss = _TCSS.read_text()
        for cat, expected_pct in _CATEGORY_EXPECTED_OPACITY.items():
            block = self._block_for_category(tcss, cat)
            assert expected_pct in block, (
                f"category-{cat}: expected opacity {expected_pct}, "
                f"but block contains: {block.strip()!r}"
            )

    def test_category_opacity_comment_present(self):
        """hermes.tcss must contain the tier documentation comment."""
        tcss = _TCSS.read_text()
        assert "Category accent opacity is tiered" in tcss, (
            "hermes.tcss missing tier documentation comment above category rules"
        )


# ── A5 — Error banner uses $error token ───────────────────────────────────────


class TestA5ErrorBannerToken:
    def test_error_banner_uses_theme_error_token(self):
        """The .error-banner rule must not contain any hardcoded hex colors."""
        tcss = _TCSS.read_text()
        m = re.search(r"\.error-banner\s*\{([^}]*)\}", tcss, re.DOTALL)
        assert m, "No .error-banner rule found in hermes.tcss"
        block = m.group(1)

        hex_match = re.search(r"#[0-9a-fA-F]{3,6}", block)
        assert not hex_match, (
            f".error-banner contains hardcoded hex color: {hex_match.group()!r}; "
            "use $error token instead"
        )
        assert "$error" in block, (
            ".error-banner must reference $error for color properties"
        )


# ── A6 — Density tier vocabulary (DEFAULT not STANDARD) ───────────────────────


class TestA6DensityVocab:
    def test_concept_doc_uses_default_not_standard(self):
        """docs/concept.md must not use STANDARD as a density tier name."""
        text = _CONCEPT_DOC.read_text()
        m = re.search(r"\bSTANDARD\b", text)
        assert m is None, (
            "docs/concept.md contains STANDARD as a tier name; "
            "the canonical name is DEFAULT"
        )

    def test_concept_doc_default_tier_referenced(self):
        """docs/concept.md must reference DEFAULT as a density tier at least once."""
        text = _CONCEPT_DOC.read_text()
        assert "DEFAULT" in text, (
            "docs/concept.md must reference DEFAULT as a density tier name"
        )
