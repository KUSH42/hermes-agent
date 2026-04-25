"""Tests for the DESIGN.md skin pipeline (parent + child specs).

Covers:
- DM-A schema (5)
- DM-C loader (4)
- DM-E lint command isolation (1)
- DM-B precedence/discovery (later phases)
- DM-G bundled skins (later phases)
- DM-H hot reload (later phases)
- DM-I authoring docs (later phases)
- DM-F/DM-J/DM-K child specs
"""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from hermes_cli.skin_engine import (
    BUNDLED_SKIN_NAMES,
    SkinError,
    SkinPayload,
    load_design_md_payload,
    load_legacy_skin_payload,
    load_skin_payload,
    skin_config_from_payload,
    validate_design_md_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_design_md(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "DESIGN.md"
    path.write_text(dedent(body).lstrip(), encoding="utf-8")
    return path


MINIMAL_FRONTMATTER = """
    ---
    name: tiny
    description: minimal test skin
    colors:
      foreground: "#cdd6f4"
      background: "#1e1e2e"
      accent: "#cba6f7"
    ---
    """


# ---------------------------------------------------------------------------
# DM-A — schema
# ---------------------------------------------------------------------------


class TestDesignMdSchema:
    def test_accepts_minimal_frontmatter(self, tmp_path):
        p = _write_design_md(tmp_path, MINIMAL_FRONTMATTER)
        payload = load_design_md_payload(p)
        # fg → foreground + text; bg → background + surface + panel; accent → primary + accent
        assert payload.css_vars["foreground"] == "#cdd6f4"
        assert payload.css_vars["text"] == "#cdd6f4"
        assert payload.css_vars["background"] == "#1e1e2e"
        assert payload.css_vars["surface"] == "#1e1e2e"
        assert payload.css_vars["panel"] == "#1e1e2e"
        assert payload.css_vars["primary"] == "#cba6f7"
        assert payload.css_vars["accent"] == "#cba6f7"

    def test_resolves_token_refs_in_x_hermes_component_vars(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: ref
            description: token ref test
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              component-vars:
                app-bg: "{colors.background}"
            ---
            """)
        payload = load_design_md_payload(p)
        assert payload.component_vars["app-bg"] == "#1e1e2e"

    def test_rejects_hermes_arrays_in_components(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: bad
            description: spinner under components is rejected
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            components:
              spinner:
                frames: ["a", "b"]
            ---
            """)
        with pytest.raises(SkinError) as ei:
            load_design_md_payload(p)
        msg = str(ei.value)
        assert "components.spinner" in msg

    def test_rejects_unknown_x_hermes_key(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: bad
            description: unknown x-hermes key
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              unknown-key: "anything"
            ---
            """)
        with pytest.raises(SkinError) as ei:
            load_design_md_payload(p)
        assert "x-hermes.unknown-key" in str(ei.value)

    def test_hyphenated_banner_colors_map_to_underscores(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: bnr
            description: banner color underscore mapping
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
              banner-title: "{colors.accent}"
            ---
            """)
        payload = load_design_md_payload(p)
        assert payload.colors.get("banner_title") == "#cba6f7"


# ---------------------------------------------------------------------------
# DM-C — loader rework
# ---------------------------------------------------------------------------


class TestDesignMdLoader:
    def test_load_skin_full_design_md_returns_tuple(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: full
            description: full loader test
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              component-vars:
                app-bg: "{colors.background}"
            ---
            """)
        from hermes_cli.tui.skin_loader import load_skin_full
        css_vars, component_vars = load_skin_full(p)
        assert css_vars["primary"] == "#cba6f7"
        assert component_vars["app-bg"] == "#1e1e2e"

    def test_legacy_yaml_payload_matches_current_loader(self):
        # The legacy wrapper must produce the same css_vars/component_vars
        # as the historical skin_loader.load_skin_full for an existing YAML.
        from hermes_cli.tui.skin_loader import load_skin_full
        path = REPO_ROOT / "skins" / "catppuccin.yaml"
        css_vars, component_vars = load_skin_full(path)
        payload = load_legacy_skin_payload(path)
        assert payload.css_vars == css_vars
        assert payload.component_vars == component_vars

    def test_skin_config_from_design_md_preserves_branding(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: brand
            description: branding preservation
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              branding:
                agent_name: "Hermes"
                welcome: "Hello"
            ---
            """)
        payload = load_design_md_payload(p)
        cfg = skin_config_from_payload(payload)
        assert cfg.get_branding("agent_name") == "Hermes"

    def test_skin_config_from_design_md_preserves_syntax_styles(self, tmp_path):
        p = _write_design_md(tmp_path, """
            ---
            name: syn
            description: syntax style preservation
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              syntax:
                scheme: "catppuccin"
                overrides:
                  keyword: "bold #ffffff"
            ---
            """)
        payload = load_design_md_payload(p)
        cfg = skin_config_from_payload(payload)
        styles = cfg.get_syntax_styles()
        # Override wins
        assert styles["keyword"] == "bold #ffffff"
        # Other tokens still come from the named scheme
        from hermes_cli.skin_engine import SYNTAX_SCHEMES
        assert styles["string"] == SYNTAX_SCHEMES["catppuccin"]["string"]


# ---------------------------------------------------------------------------
# DM-E — runtime loader does not invoke npx
# ---------------------------------------------------------------------------


class TestDesignMdLintCommand:
    def test_lint_command_is_ci_only_in_loader_tests(self, tmp_path):
        p = _write_design_md(tmp_path, MINIMAL_FRONTMATTER)
        import subprocess
        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess.run called from loader")):
            with patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess.Popen called from loader")):
                # Must not invoke any subprocess at runtime load
                load_design_md_payload(p)


# ---------------------------------------------------------------------------
# Discovery flag (Phase 1 gate)
# ---------------------------------------------------------------------------


class TestDesignMdDiscoveryFlag:
    def test_env_var_enables_discovery(self, monkeypatch):
        from hermes_cli.skin_engine import _design_md_discovery_enabled
        monkeypatch.setenv("HERMES_DESIGN_MD_SKINS", "1")
        assert _design_md_discovery_enabled() is True

    def test_env_var_off_disables_discovery(self, monkeypatch):
        from hermes_cli.skin_engine import _design_md_discovery_enabled
        monkeypatch.setenv("HERMES_DESIGN_MD_SKINS", "0")
        assert _design_md_discovery_enabled() is False

    def test_env_var_unset_uses_default(self, monkeypatch):
        from hermes_cli.skin_engine import _design_md_discovery_enabled, _DESIGN_MD_DISCOVERY_DEFAULT
        monkeypatch.delenv("HERMES_DESIGN_MD_SKINS", raising=False)
        assert _design_md_discovery_enabled() is _DESIGN_MD_DISCOVERY_DEFAULT


# ---------------------------------------------------------------------------
# Bundled skin names constant (used by DM-K2)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2 — bundled catppuccin DESIGN.md
# ---------------------------------------------------------------------------


class TestCatppuccinDesignMd:
    PATH = REPO_ROOT / "skins" / "catppuccin" / "DESIGN.md"
    LINT = REPO_ROOT / "skins" / "catppuccin" / "lint-report.md"
    YAML = REPO_ROOT / "skins" / "catppuccin.yaml"

    def test_design_md_file_exists(self):
        assert self.PATH.exists(), f"missing {self.PATH}"

    def test_lint_report_exists(self):
        assert self.LINT.exists(), f"missing {self.LINT}"

    def test_design_md_loads_through_load_skin_payload(self):
        payload = load_skin_payload(self.PATH)
        assert payload.name == "catppuccin"
        assert payload.syntax_scheme == "catppuccin"

    def test_design_md_payload_matches_yaml_runtime_surfaces(self):
        # css_vars + component_vars must be byte-equivalent to the legacy YAML
        # (parent DM-G test_design_md_and_yaml_payloads_equivalent_except_scheme,
        # narrowed to catppuccin for Phase 2).
        dp = load_design_md_payload(self.PATH)
        yp = load_legacy_skin_payload(self.YAML)
        assert dp.css_vars == yp.css_vars
        assert dp.component_vars == yp.component_vars
        assert dp.colors == yp.colors
        # syntax_scheme is the intentional field; both YAML+DESIGN.md now
        # use the named scheme (Phase 0 ported the YAML).
        assert dp.syntax_scheme == yp.syntax_scheme == "catppuccin"


def test_bundled_skin_names_constant():
    assert set(BUNDLED_SKIN_NAMES) == {"matrix", "catppuccin", "solarized-dark", "tokyo-night"}
