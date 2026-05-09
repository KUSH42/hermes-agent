"""Per-skin startup TTE override + default→hermes rename (SPEC-TTE)."""

from __future__ import annotations

import logging
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from hermes_cli import skin_engine
from hermes_cli.skin_engine import (
    BUNDLED_SKIN_NAMES,
    SkinError,
    _bundled_skins_dir,
    _normalize_skin_name,
    _reset_alias_warning_for_tests,
    get_active_skin_name,
    load_design_md_payload,
    load_skin,
    set_active_skin,
    skin_config_from_payload,
    validate_design_md_payload,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_VALID_FRONTMATTER_BASE = """\
---
version: alpha
name: testskin
description: test
colors:
  foreground: '#ffffff'
  background: '#000000'
x-hermes:
  schema: 1
{startup_tte}
---
body
"""


def _payload_with_block(tmp_path: Path, block_yaml: str | None) -> Path:
    """Write a DESIGN.md tmp file with optional startup_tte block; return path."""
    if block_yaml is None:
        body = _VALID_FRONTMATTER_BASE.format(startup_tte="")
    else:
        # block_yaml is the inner YAML lines (already indented at 2 spaces)
        body = _VALID_FRONTMATTER_BASE.format(startup_tte=block_yaml)
    p = tmp_path / "DESIGN.md"
    p.write_text(body)
    return p


@pytest.fixture(autouse=True)
def _reset_alias():
    _reset_alias_warning_for_tests()
    yield
    _reset_alias_warning_for_tests()


# ---------------------------------------------------------------------------
# TTE-1 schema
# ---------------------------------------------------------------------------


class TestStartupTteSchema:
    def test_skin_payload_startup_tte_parsed(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    effect: burn\n    max_wall_s: 4.5\n",
        )
        payload = load_design_md_payload(p)
        assert payload.startup_tte["effect"] == "burn"
        assert payload.startup_tte["max_wall_s"] == 4.5
        # MappingProxyType is read-only
        with pytest.raises(TypeError):
            payload.startup_tte["effect"] = "x"  # type: ignore[index]

    def test_skin_config_startup_tte_copied_from_payload(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    effect: burn\n",
        )
        payload = load_design_md_payload(p)
        cfg = skin_config_from_payload(payload)
        assert cfg.startup_tte == {"effect": "burn"}
        # Plain dict on SkinConfig (mutable) per spec
        cfg.startup_tte["x"] = 1
        assert payload.startup_tte == {"effect": "burn"}  # not aliased

    def test_skin_payload_startup_tte_absent(self, tmp_path):
        p = _payload_with_block(tmp_path, None)
        payload = load_design_md_payload(p)
        assert dict(payload.startup_tte) == {}

    def test_skin_payload_startup_tte_empty_block_is_noop(self, tmp_path):
        p = _payload_with_block(tmp_path, "  startup_tte: {}\n")
        payload = load_design_md_payload(p)
        assert dict(payload.startup_tte) == {}

    def test_skin_payload_startup_tte_other_keys_without_effect_raises(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    max_wall_s: 5.0\n",
        )
        with pytest.raises(SkinError, match="requires 'effect'"):
            load_design_md_payload(p)

    def test_skin_payload_startup_tte_unknown_key_raises(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    effect: burn\n    bogus: 1\n",
        )
        with pytest.raises(SkinError, match="unknown key"):
            load_design_md_payload(p)

    def test_skin_payload_startup_tte_unknown_effect_raises(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    effect: bogus\n",
        )
        with pytest.raises(SkinError, match="unknown effect"):
            load_design_md_payload(p)

    def test_skin_payload_startup_tte_out_of_range_raises(self, tmp_path):
        p = _payload_with_block(
            tmp_path,
            "  startup_tte:\n    effect: burn\n    max_wall_s: 0.5\n",
        )
        with pytest.raises(SkinError, match="max_wall_s"):
            load_design_md_payload(p)

    def test_validator_uses_live_effect_map(self, tmp_path):
        from hermes_cli.tui import tte_runner
        # Inject a fake key into the live map
        tte_runner.EFFECT_MAP["fake_test_effect"] = next(iter(tte_runner.EFFECT_MAP.values()))
        try:
            p = _payload_with_block(
                tmp_path,
                "  startup_tte:\n    effect: fake_test_effect\n",
            )
            payload = load_design_md_payload(p)  # no SkinError
            assert payload.startup_tte["effect"] == "fake_test_effect"
        finally:
            tte_runner.EFFECT_MAP.pop("fake_test_effect", None)

    def test_yaml_skin_path_no_startup_tte(self):
        # Legacy YAML path does not declare startup_tte.
        from hermes_cli.skin_engine import _build_skin_config_from_yaml
        cfg = _build_skin_config_from_yaml({"name": "yaml-only"})
        assert cfg.startup_tte == {}


# ---------------------------------------------------------------------------
# TTE-1 resolver precedence
# ---------------------------------------------------------------------------


class _StubCli:
    """Minimal HermesCLI stand-in for resolver tests."""
    def __init__(self, *, enabled=True, effect="matrix", params=None,
                 max_wall_s=30.0, max_frames=3000, fps=60, reduced_motion=False):
        self.config = {
            "tui": {"reduced_motion": reduced_motion},
            "display": {
                "startup_text_effect": {
                    "enabled": enabled,
                    "effect": effect,
                    "params": params or {},
                    "max_wall_s": max_wall_s,
                    "max_frames": max_frames,
                    "fps": fps,
                },
            },
        }


def _resolve(cli_obj):
    from cli import HermesCLI, _reset_for_tests
    _reset_for_tests()
    return HermesCLI._get_startup_text_effect_config(cli_obj)


class _FakeSkin:
    def __init__(self, tte: dict, name: str = "fake"):
        self._tte = tte
        self.name = name

    def get_startup_tte(self):
        return self._tte


class TestStartupTteResolver:
    def _patch_skin(self, tte: dict, name: str = "fake"):
        return patch.multiple(
            "hermes_cli.skin_engine",
            get_active_skin=lambda: _FakeSkin(tte, name),
            get_active_skin_name=lambda: name,
        )

    def test_resolver_skin_overrides_config_effect(self):
        cli_obj = _StubCli(effect="matrix")
        with self._patch_skin({"effect": "burn"}):
            cfg = _resolve(cli_obj)
        assert cfg is not None
        assert cfg.effect_name == "burn"

    def test_resolver_skin_partial_override_inherits(self):
        cli_obj = _StubCli(effect="burn", max_wall_s=10.0)
        with self._patch_skin({"effect": "burn"}):
            cfg = _resolve(cli_obj)
        assert cfg.max_wall_s == 10.0

    def test_resolver_skin_does_not_force_enable(self):
        cli_obj = _StubCli(enabled=False)
        with self._patch_skin({"effect": "burn"}):
            assert _resolve(cli_obj) is None

    def test_resolver_reduced_motion_wins_over_skin(self):
        cli_obj = _StubCli(reduced_motion=True)
        with self._patch_skin({"effect": "burn"}):
            assert _resolve(cli_obj) is None

    def test_resolver_skin_params_replace_not_merge(self):
        cli_obj = _StubCli(effect="burn", params={"a": 1})
        with self._patch_skin({"effect": "burn", "params": {"b": 2}}):
            cfg = _resolve(cli_obj)
        assert cfg.params == {"b": 2}

    def test_resolver_no_skin_override_falls_through(self):
        cli_obj = _StubCli(effect="matrix")
        with self._patch_skin({}):
            cfg = _resolve(cli_obj)
        assert cfg.effect_name == "matrix"


# ---------------------------------------------------------------------------
# TTE-2 skin declarations
# ---------------------------------------------------------------------------


def _bundled_payload(name: str):
    return load_design_md_payload(_bundled_skins_dir() / name / "DESIGN.md")


class TestSkinDeclarations:
    def test_all_bundled_skins_declare_startup_tte(self):
        from hermes_cli.tui.tte_runner import EFFECT_MAP
        for name in BUNDLED_SKIN_NAMES:
            payload = _bundled_payload(name)
            assert payload.startup_tte.get("effect"), f"{name} missing startup_tte effect"
            assert payload.startup_tte["effect"] in EFFECT_MAP, (
                f"{name} effect not in EFFECT_MAP"
            )

    def test_matrix_skin_max_wall_s(self):
        # Tuned to 10.0s alongside the matrix-effect restoration (commits
        # a30bda9a, b344b756) — long enough for the "matrix" effect to reach
        # its full resolve phase.
        p = _bundled_payload("matrix")
        assert p.startup_tte["max_wall_s"] == 10.0

    def test_hermes_skin_uses_vhstape(self):
        p = _bundled_payload("hermes")
        assert p.startup_tte["effect"] == "vhstape"

    def test_matrix_skin_uses_matrix_effect(self):
        p = _bundled_payload("matrix")
        assert p.startup_tte["effect"] == "matrix"


# ---------------------------------------------------------------------------
# TTE-3 default→hermes rename + alias
# ---------------------------------------------------------------------------


class TestDefaultRename:
    def test_bundled_skin_names_lists_hermes_not_default(self):
        assert "hermes" in BUNDLED_SKIN_NAMES
        assert "default" not in BUNDLED_SKIN_NAMES

    def test_default_config_skin_is_hermes(self):
        # Default config built into hermes_cli/config.py
        src = Path(__file__).parent.parent.parent / "hermes_cli" / "config.py"
        text = src.read_text()
        assert '"skin": "hermes"' in text
        assert '"skin": "default"' not in text

    def test_load_skin_default_aliases_to_hermes(self):
        s = load_skin("default")
        assert s.name == "hermes"

    def test_load_skin_default_logs_alias_once(self, caplog):
        _reset_alias_warning_for_tests()
        with caplog.at_level(logging.INFO, logger="hermes_cli.skin_engine"):
            load_skin("default")
            load_skin("default")
        msgs = [r.message for r in caplog.records if "is now" in r.message]
        assert len(msgs) == 1
        assert "default" in msgs[0] and "hermes" in msgs[0]

    def test_set_active_skin_default_resolves_hermes(self):
        set_active_skin("default")
        assert get_active_skin_name() == "hermes"

    def test_hermes_skin_directory_exists(self):
        assert (_bundled_skins_dir() / "hermes" / "DESIGN.md").exists()

    def test_hermes_payload_name_field(self):
        assert _bundled_payload("hermes").name == "hermes"

    def test_default_directory_removed(self):
        assert not (_bundled_skins_dir() / "default").exists()

    def test_active_skin_name_default_initial_value_is_hermes(self):
        # Module-level default; reading directly to assert source-of-truth
        import importlib
        import hermes_cli.skin_engine as se
        # Re-read source to bypass test-time mutation. Instead, check the
        # post-import constant body via a fresh subprocess would be heavy;
        # a sufficient proxy is that _normalize_skin_name maps "default" → "hermes"
        # and that the in-memory module-level _active_skin_name was initialized to
        # "hermes" (we cannot prove it was never set to default in this process,
        # so assert the alias path and the code-level default by reading the source).
        src = Path(se.__file__).read_text()
        assert '_active_skin_name: str = "hermes"' in src

    def test_alias_does_not_force_enable_unrelated_default_strings(self):
        # The normalizer only fires on inputs to load_skin / set_active_skin.
        # "default" outside that surface (density tier, syntax, persona, container ids)
        # is unaffected because those code paths never call _normalize_skin_name.
        assert _normalize_skin_name("default") == "hermes"
        assert _normalize_skin_name("matrix") == "matrix"
        # density tier value untouched
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier  # noqa: F401
        assert DensityTier.DEFAULT.value == "default"
