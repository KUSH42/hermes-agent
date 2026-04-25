"""Tests for SYN-1/SYN-2/SYN-3 foundations folded into the DESIGN.md spec.

Covers:
- DM-D ``SkinColors.syntax_scheme`` + ``resolve_syntax_palette()``
- DM-E ``_NON_HEX_COMPONENT_VARS`` runtime validator allowlist
- SYN-3 bundled YAMLs use named SYNTAX_SCHEMES
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from hermes_cli.skin_engine import SYNTAX_SCHEMES
from hermes_cli.tui.body_renderers._grammar import SkinColors
from hermes_cli.tui.theme_manager import (
    _NON_HEX_COMPONENT_VARS,
    SkinValidationError,
    validate_skin_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_NAMES = ("matrix", "catppuccin", "solarized-dark", "tokyo-night")


# ---------------------------------------------------------------------------
# DM-D — SkinColors.syntax_scheme + resolve_syntax_palette
# ---------------------------------------------------------------------------


class TestSkinColorsDesignMdSyntax:
    def test_default_syntax_scheme_is_hermes(self):
        assert SkinColors.default().syntax_scheme == "hermes"

    def test_from_app_reads_syntax_scheme(self):
        app = MagicMock()
        app.get_css_variables.return_value = {"syntax-scheme": "catppuccin"}
        sc = SkinColors.from_app(app)
        assert sc.syntax_scheme == "catppuccin"

    def test_from_app_keeps_color_hex_validation(self):
        app = MagicMock()
        app.get_css_variables.return_value = {
            "info": "not-hex",
            "syntax-scheme": "tokyo-night",
        }
        sc = SkinColors.from_app(app)
        # color falls back, syntax_scheme accepts the non-hex string
        assert sc.info == SkinColors.default().info
        assert sc.syntax_scheme == "tokyo-night"

    def test_resolve_syntax_palette_with_overrides(self):
        sc = SkinColors.default()._replace_syntax_scheme("catppuccin") if False else SkinColors(
            accent="#000000", muted="#000000", success="#000000", error="#000000",
            warning="#000000", info="#000000",
            icon_dim="#000000", separator_dim="#000000",
            diff_add_bg="#000000",
            diff_del_bg="#000000", syntax_theme="ansi_dark", syntax_scheme="catppuccin",
        )
        original = dict(SYNTAX_SCHEMES["catppuccin"])
        out = sc.resolve_syntax_palette(overrides={"keyword": "bold #FFFFFF"})
        assert out["keyword"] == "bold #FFFFFF"
        # untouched keys come from the named scheme
        assert out["string"] == SYNTAX_SCHEMES["catppuccin"]["string"]
        # SYNTAX_SCHEMES is not mutated
        assert SYNTAX_SCHEMES["catppuccin"] == original

    def test_resolve_syntax_palette_unknown_scheme_returns_empty(self):
        sc = SkinColors(
            accent="#000000", muted="#000000", success="#000000", error="#000000",
            warning="#000000", info="#000000",
            icon_dim="#000000", separator_dim="#000000",
            diff_add_bg="#000000",
            diff_del_bg="#000000", syntax_theme="ansi_dark",
            syntax_scheme="does-not-exist",
        )
        assert sc.resolve_syntax_palette() == {}


# ---------------------------------------------------------------------------
# DM-E — runtime validator non-hex allowlist
# ---------------------------------------------------------------------------


class TestRuntimeValidator:
    def test_non_hex_component_allowlist_contains_syntax_keys(self):
        assert "syntax-theme" in _NON_HEX_COMPONENT_VARS
        assert "syntax-scheme" in _NON_HEX_COMPONENT_VARS

    def test_validate_allows_syntax_theme_and_scheme_strings(self):
        validate_skin_payload(
            {
                "component_vars": {
                    "syntax-theme": "catppuccin",
                    "syntax-scheme": "catppuccin",
                },
                "vars": {},
            },
            source="<test>",
            warn_missing=False,
        )

    def test_validate_rejects_bad_hex_for_color_key(self):
        with pytest.raises(SkinValidationError) as ei:
            validate_skin_payload(
                {"component_vars": {"cursor-color": "not-hex"}, "vars": {}},
                source="<test>",
                warn_missing=False,
            )
        assert "cursor-color" in str(ei.value)


# ---------------------------------------------------------------------------
# SYN-3 — bundled YAMLs use a named scheme + emit syntax-scheme component var
# ---------------------------------------------------------------------------


class TestBundledYamlSyntaxScheme:
    @pytest.mark.parametrize("name", BUNDLED_NAMES)
    def test_bundled_yaml_syntax_scheme_is_known(self, name):
        path = REPO_ROOT / "skins" / f"{name}.yaml"
        data = yaml.safe_load(path.read_text())
        assert data["syntax_scheme"] in SYNTAX_SCHEMES

    @pytest.mark.parametrize("name", BUNDLED_NAMES)
    def test_bundled_yaml_emits_syntax_scheme_component_var(self, name):
        path = REPO_ROOT / "skins" / f"{name}.yaml"
        data = yaml.safe_load(path.read_text())
        cv = data.get("component_vars", {})
        assert "syntax-scheme" in cv, f"{name} missing syntax-scheme component var"

    def test_matrix_uses_hermes_scheme(self):
        data = yaml.safe_load((REPO_ROOT / "skins" / "matrix.yaml").read_text())
        assert data["syntax_scheme"] == "hermes"

    def test_bundled_yamls_load_through_runtime_validator(self):
        # Smoke: every bundled YAML's component_vars dict passes runtime
        # validation now that syntax-scheme/syntax-theme are allowlisted.
        for name in BUNDLED_NAMES:
            path = REPO_ROOT / "skins" / f"{name}.yaml"
            data = yaml.safe_load(path.read_text())
            cv = {k: v for k, v in data.get("component_vars", {}).items()}
            validate_skin_payload(
                {"component_vars": cv, "vars": data.get("vars", {})},
                source=str(path),
                warn_missing=False,
            )
