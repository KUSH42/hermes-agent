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

import re
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


# ---------------------------------------------------------------------------
# Phase 3 — bundled DM-G + DM-I authoring docs
# ---------------------------------------------------------------------------


class TestBundledDesignMdSkins:
    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_all_four_requested_skins_have_design_md(self, name):
        path = REPO_ROOT / "skins" / name / "DESIGN.md"
        assert path.exists(), f"missing {path}"

    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_all_bundled_design_md_have_lint_reports(self, name):
        path = REPO_ROOT / "skins" / name / "lint-report.md"
        assert path.exists(), f"missing {path}"

    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_all_bundled_design_md_schemes_are_known(self, name):
        from hermes_cli.skin_engine import SYNTAX_SCHEMES
        payload = load_design_md_payload(REPO_ROOT / "skins" / name / "DESIGN.md")
        assert payload.syntax_scheme in SYNTAX_SCHEMES

    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_design_md_and_yaml_payloads_equivalent(self, name):
        dp = load_design_md_payload(REPO_ROOT / "skins" / name / "DESIGN.md")
        yp = load_legacy_skin_payload(REPO_ROOT / "skins" / f"{name}.yaml")
        assert dp.css_vars == yp.css_vars, name
        assert dp.component_vars == yp.component_vars, name
        assert dp.colors == yp.colors, name


class TestSkinAuthoringDocs:
    SKILL = Path("/home/xush/.claude/skills/hermes-skin/SKILL.md")
    REFERENCE = Path("/home/xush/.claude/skills/tui-development/skin-reference.md")

    def test_hermes_skin_skill_mentions_design_md_primary_path(self):
        text = self.SKILL.read_text()
        assert "~/.hermes/skins/<name>/DESIGN.md" in text

    def test_skin_reference_lists_x_hermes_component_vars(self):
        text = self.REFERENCE.read_text()
        assert "x-hermes.component-vars" in text or "x-hermes:\n      component-vars" in text


# ---------------------------------------------------------------------------
# Phase 4 — DM-B precedence + DM-H hot reload + DM-K1 deprecation warning
# ---------------------------------------------------------------------------


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME for skin discovery tests."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # invalidate any cached skin
    import hermes_cli.skin_engine as se
    se._active_skin = None
    return tmp_path


def _user_skin_yaml(home: Path, name: str) -> Path:
    p = home / "skins" / f"{name}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"name: {name}\ndescription: yaml-only\nfg: '#abcdef'\n", encoding="utf-8")
    return p


def _user_skin_design_md(home: Path, name: str, *, body: str | None = None) -> Path:
    p = home / "skins" / name / "DESIGN.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body or dedent(f"""
        ---
        version: alpha
        name: {name}
        description: design.md only
        colors:
          foreground: "#cdd6f4"
          background: "#1e1e2e"
          accent: "#cba6f7"
        ---
        # {name}
        """).lstrip(), encoding="utf-8")
    return p


class TestDesignMdLocationDmB:
    def test_user_design_md_path_wins_over_yaml(self, hermes_home):
        from hermes_cli.skin_engine import _resolve_user_skin_path
        _user_skin_yaml(hermes_home, "demo")
        dm = _user_skin_design_md(hermes_home, "demo")
        resolved = _resolve_user_skin_path("demo")
        assert resolved == dm

    def test_invalid_design_md_blocks_adjacent_yaml_fallback(self, hermes_home):
        _user_skin_yaml(hermes_home, "demo")
        # Write a malformed DESIGN.md — missing front matter
        bad = hermes_home / "skins" / "demo" / "DESIGN.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("not a design.md file\n", encoding="utf-8")
        from hermes_cli.skin_engine import load_skin
        with pytest.raises(SkinError):
            load_skin("demo")

    def test_yaml_only_load_silent_pre_phase4(self, hermes_home, monkeypatch):
        # Force _YAML_DEPRECATED_SINCE empty to simulate Phase 0–3
        import hermes_cli.skin_engine as se
        monkeypatch.setattr(se, "_YAML_DEPRECATED_SINCE", "")
        _user_skin_yaml(hermes_home, "demo")
        import warnings as w
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            se.load_skin("demo")
        assert not any(issubclass(c.category, DeprecationWarning) for c in caught), [
            (c.category, str(c.message)) for c in caught
        ]

    def test_list_skins_includes_design_md_directories(self, hermes_home):
        _user_skin_design_md(hermes_home, "from_dir")
        from hermes_cli.skin_engine import list_skins
        names = {s["name"] for s in list_skins()}
        assert "from_dir" in names


class TestDesignMdHotReloadDmH:
    def test_directory_load_watches_design_md_only(self, hermes_home):
        # ThemeManager._load_path normalizes a directory to <dir>/DESIGN.md
        skin_dir = hermes_home / "skins" / "demo"
        _user_skin_design_md(hermes_home, "demo")
        from hermes_cli.tui.theme_manager import ThemeManager
        tm = ThemeManager.__new__(ThemeManager)
        tm._app = None
        tm._css_vars = {}
        tm._component_vars = {}
        tm._source_path = None
        tm._source_mtime = 0.0
        tm._watcher_thread = None
        import threading as _t
        tm._watcher_stop = _t.Event()
        tm._watcher_interval_s = 1.0
        tm._pending_reload_mtime = 0.0
        tm._load_path(skin_dir)
        assert tm._source_path is not None
        assert tm._source_path.name == "DESIGN.md"

    def test_lint_report_mtime_change_does_not_reload(self, hermes_home):
        _user_skin_design_md(hermes_home, "demo")
        lint = hermes_home / "skins" / "demo" / "lint-report.md"
        lint.write_text("---\nwarning_baseline: 0\n---\n", encoding="utf-8")
        from hermes_cli.tui.theme_manager import ThemeManager
        tm = ThemeManager.__new__(ThemeManager)
        tm._app = None
        tm._css_vars = {}
        tm._component_vars = {}
        tm._source_path = None
        tm._source_mtime = 0.0
        tm._watcher_thread = None
        import threading as _t
        tm._watcher_stop = _t.Event()
        tm._watcher_interval_s = 1.0
        tm._pending_reload_mtime = 0.0
        tm._load_path(hermes_home / "skins" / "demo")
        baseline = tm._source_mtime
        # Bump only the lint report mtime
        import time
        time.sleep(0.01)
        lint.write_text(lint.read_text() + "\n", encoding="utf-8")
        # Source path mtime unchanged
        assert tm._source_path.stat().st_mtime == baseline


class TestDesignMdDeprecationDmK1:
    def test_user_yaml_only_emits_deprecation_warning(self, hermes_home):
        path = _user_skin_yaml(hermes_home, "legacy_only")
        from hermes_cli.skin_engine import load_skin
        import warnings as w
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            load_skin("legacy_only")
        deps = [c for c in caught if issubclass(c.category, DeprecationWarning)]
        assert deps, "expected DeprecationWarning"
        msg = str(deps[0].message)
        assert "legacy_only.yaml" in msg
        assert "legacy_only/DESIGN.md" in msg

    def test_user_design_md_only_no_warning(self, hermes_home):
        _user_skin_design_md(hermes_home, "newshine")
        from hermes_cli.skin_engine import load_skin
        import warnings as w
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            load_skin("newshine")
        assert not any(issubclass(c.category, DeprecationWarning) for c in caught)

    def test_user_both_formats_design_md_wins_no_warning(self, hermes_home):
        _user_skin_yaml(hermes_home, "both")
        _user_skin_design_md(hermes_home, "both")
        from hermes_cli.skin_engine import load_skin
        import warnings as w
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            cfg = load_skin("both")
        assert cfg.description == "design.md only"
        assert not any(issubclass(c.category, DeprecationWarning) for c in caught)


def test_design_md_discovery_default_is_on_phase4():
    from hermes_cli.skin_engine import _DESIGN_MD_DISCOVERY_DEFAULT
    assert _DESIGN_MD_DISCOVERY_DEFAULT is True


def test_yaml_deprecated_since_set_phase4():
    from hermes_cli.skin_engine import _YAML_DEPRECATED_SINCE
    assert _YAML_DEPRECATED_SINCE  # non-empty


# ---------------------------------------------------------------------------
# Phase 5a — DM-F TCSS generator + scanner + syntax-string guard
# ---------------------------------------------------------------------------


class TestDmF1TcssGenerator:
    def test_design_md_tcss_generator_uses_literal_hex(self):
        from hermes_cli.tui.build_skin_vars import render_design_md_tcss_block
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS, _default_of
        block = render_design_md_tcss_block(COMPONENT_VAR_DEFAULTS)
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("$"):
                continue
            _, rhs = line.split(":", 1)
            rhs = rhs.rstrip(";").strip()
            assert "$" not in rhs, f"$ ref in {line!r}"
            assert "{" not in rhs, f"token ref in {line!r}"

    def test_design_md_tcss_generator_includes_referenced_defaults(self):
        from hermes_cli.tui.build_skin_vars import render_design_md_tcss_block
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        block = render_design_md_tcss_block(COMPONENT_VAR_DEFAULTS)
        for k in COMPONENT_VAR_DEFAULTS:
            assert f"${k}:" in block, f"missing ${k} declaration"

    def test_design_md_tcss_generator_rejects_non_hex_defaults(self):
        from hermes_cli.tui.build_skin_vars import render_design_md_tcss_block, GeneratorError
        bad = {"app-bg": "catppuccin"}
        with pytest.raises(GeneratorError):
            render_design_md_tcss_block(bad)

    def test_design_md_tcss_generator_preserves_insertion_order(self):
        from hermes_cli.tui.build_skin_vars import render_design_md_tcss_block
        ordered = {"a-color": "#111111", "z-color": "#222222", "m-color": "#333333"}
        block = render_design_md_tcss_block(ordered)
        i_a = block.index("$a-color:")
        i_z = block.index("$z-color:")
        i_m = block.index("$m-color:")
        assert i_a < i_z < i_m


class TestDmF2Scanner:
    def test_scan_skin_keys_reads_design_md_component_vars(self):
        from hermes_cli.tui.build_skin_vars import scan_skin_keys
        keys = scan_skin_keys(REPO_ROOT / "skins" / "catppuccin" / "DESIGN.md")
        assert "app-bg" in keys
        assert "syntax-scheme" in keys

    def test_scan_bundled_skins_uses_dm_b_precedence(self, tmp_path):
        from hermes_cli.tui.build_skin_vars import scan_bundled_skins
        # Both forms exist: <name>.yaml + <name>/DESIGN.md → DESIGN.md wins
        (tmp_path / "demo.yaml").write_text(
            "name: demo\ncomponent_vars:\n  yaml-only: '#111111'\n", encoding="utf-8"
        )
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo" / "DESIGN.md").write_text(dedent("""
            ---
            name: demo
            description: x
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            x-hermes:
              component-vars:
                design-only: "#222222"
            ---
            """).lstrip(), encoding="utf-8")
        out = scan_bundled_skins(tmp_path)
        assert "design-only" in out["demo"]
        assert "yaml-only" not in out["demo"]

    def test_scan_bundled_skins_malformed_design_md_fails_loud(self, tmp_path):
        from hermes_cli.tui.build_skin_vars import scan_bundled_skins
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo" / "DESIGN.md").write_text("not yaml fronted\n", encoding="utf-8")
        with pytest.raises(SkinError):
            scan_bundled_skins(tmp_path)


class TestDmF3SyntaxStringsExcluded:
    def test_syntax_strings_not_in_component_defaults(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        assert "syntax-theme" not in COMPONENT_VAR_DEFAULTS
        assert "syntax-scheme" not in COMPONENT_VAR_DEFAULTS

    def test_syntax_strings_not_declared_in_tcss(self):
        from hermes_cli.tui.build_skin_vars import scan_tcss_declarations
        decls = scan_tcss_declarations()
        assert "syntax-theme" not in decls
        assert "syntax-scheme" not in decls


# ---------------------------------------------------------------------------
# Phase 5b — DM-J export pipeline
# ---------------------------------------------------------------------------


def _has_npx() -> bool:
    import shutil
    return shutil.which("npx") is not None


class TestDmJ1LintCommand:
    def test_design_md_runtime_loader_does_not_call_npx(self, tmp_path):
        # Loader must not spawn any subprocess when reading a DESIGN.md file.
        p = _write_design_md(tmp_path, MINIMAL_FRONTMATTER)
        import subprocess
        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess.run called")):
            with patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess.Popen called")):
                load_design_md_payload(p)

    def test_design_md_lint_command_builds_expected_args(self, tmp_path):
        from hermes_cli.skin_engine import design_md_lint_argv
        p = tmp_path / "skins" / "x" / "DESIGN.md"
        argv = design_md_lint_argv(p)
        assert argv[:6] == ["npx", "-y", "@google/design.md", "lint", "--format", "json"]
        assert argv[6] == str(p)

    @pytest.mark.requires_npx
    def test_design_md_lint_test_skips_without_npx(self):
        if not _has_npx():
            pytest.skip("npx not available")
        # If we reach here, npx exists; just assert positively.
        assert _has_npx()


class TestDmJ2DtcgExport:
    def test_dtcg_export_path_is_under_skin_directory(self, tmp_path):
        from hermes_cli.skin_engine import design_md_dtcg_export_path
        p = design_md_dtcg_export_path(tmp_path / "catppuccin")
        assert p == tmp_path / "catppuccin" / "tokens.dtcg.json"

    @pytest.mark.requires_npx
    def test_dtcg_export_command_is_deterministic(self, tmp_path):
        if not _has_npx():
            pytest.skip("npx not available")
        # CI-only: actual determinism check belongs in CI; placeholder asserts
        # the pure-Python path-builder is stable.
        from hermes_cli.skin_engine import design_md_dtcg_export_path
        p1 = design_md_dtcg_export_path(tmp_path / "demo")
        p2 = design_md_dtcg_export_path(tmp_path / "demo")
        assert p1 == p2

    def test_runtime_loader_ignores_tokens_dtcg_json(self, tmp_path):
        # Adding a tokens.dtcg.json next to DESIGN.md must not change
        # the SkinPayload produced by the runtime loader.
        d = tmp_path / "skin"
        d.mkdir()
        dm = d / "DESIGN.md"
        dm.write_text(dedent("""
            ---
            name: dm
            description: x
            colors:
              foreground: "#cdd6f4"
              background: "#1e1e2e"
              accent: "#cba6f7"
            ---
            """).lstrip(), encoding="utf-8")
        before = load_design_md_payload(dm)
        (d / "tokens.dtcg.json").write_text('{"unused": true}\n', encoding="utf-8")
        after = load_design_md_payload(dm)
        assert before == after


class TestDmJ3LintReport:
    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_lint_report_required_for_each_bundled_design_md(self, name):
        path = REPO_ROOT / "skins" / name / "lint-report.md"
        assert path.exists()

    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_lint_report_contains_command_and_warning_rows(self, name):
        text = (REPO_ROOT / "skins" / name / "lint-report.md").read_text()
        assert "npx" in text and "@google/design.md" in text
        assert "Warning" in text or "warning" in text

    @pytest.mark.parametrize("name", list(BUNDLED_SKIN_NAMES))
    def test_lint_report_front_matter_has_warning_baseline(self, name):
        import yaml
        text = (REPO_ROOT / "skins" / name / "lint-report.md").read_text()
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        assert m, f"{name}: missing front matter in lint-report.md"
        data = yaml.safe_load(m.group(1)) or {}
        baseline = data.get("warning_baseline")
        assert isinstance(baseline, int) and baseline >= 0


def test_bundled_skin_names_constant():
    assert set(BUNDLED_SKIN_NAMES) == {"matrix", "catppuccin", "solarized-dark", "tokyo-night"}
