"""RX3 CSS variable single-source-of-truth tests.

Spec: /home/xush/.hermes/2026-04-22-tui-v2-RX3-css-var-single-source-spec.md
Tests: T1–T8 + T6b.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from hermes_cli.tui import build_skin_vars as bsv
from hermes_cli.tui.build_skin_vars import (
    TEXTUAL_BUILTIN_VARS,
    scan_bundled_skins,
    scan_default_css_references,
    scan_docstring_keys,
    scan_tcss_declarations,
    scan_tcss_references,
)
from hermes_cli.tui.theme_manager import (
    COMPONENT_VAR_DEFAULTS,
    SkinValidationError,
    VarSpec,
    _default_of,
    _defaults_as_strs,
    validate_skin_payload,
)


# ---------------------------------------------------------------------------
# T1 — every referenced $var is declared or is a Textual built-in
# ---------------------------------------------------------------------------


def test_t1_tcss_references_resolvable() -> None:
    refs = scan_tcss_references()
    defaults_names = set(COMPONENT_VAR_DEFAULTS.keys())
    unknown: list[str] = []
    for name in refs:
        if name in TEXTUAL_BUILTIN_VARS or name in defaults_names:
            continue
        unknown.append(name)
    assert not unknown, (
        f"hermes.tcss references undeclared $vars: {sorted(unknown)}. "
        f"Add them to COMPONENT_VAR_DEFAULTS."
    )


def test_t1_default_css_references_resolvable() -> None:
    refs = scan_default_css_references()
    defaults_names = set(COMPONENT_VAR_DEFAULTS.keys())
    unknown: dict[str, set[Path]] = {}
    for name, srcs in refs.items():
        if name in TEXTUAL_BUILTIN_VARS or name in defaults_names:
            continue
        unknown[name] = srcs
    assert not unknown, (
        f"DEFAULT_CSS blocks reference undeclared $vars: "
        f"{[(k, sorted(str(p) for p in v)[:3]) for k, v in unknown.items()]}. "
        f"Add them to COMPONENT_VAR_DEFAULTS."
    )


# ---------------------------------------------------------------------------
# T2 — every COMPONENT_VAR_DEFAULTS key is declared somewhere in TCSS
# ---------------------------------------------------------------------------


def test_t2_referenced_defaults_declared_in_tcss() -> None:
    """Every COMPONENT_VAR_DEFAULTS key that is $-referenced (from TCSS or
    DEFAULT_CSS blocks) MUST be declared in hermes.tcss — Textual parses
    DEFAULT_CSS at class-definition time and needs the declaration to resolve
    the reference.

    Defaults consumed only at runtime via ``app.get_css_variables()`` (e.g.
    status-running-color) do not need a TCSS declaration. Phase 4 will lift
    this to "all defaults declared" once the generator lands.
    """
    decls = scan_tcss_declarations()
    defaults_names = set(COMPONENT_VAR_DEFAULTS.keys())
    referenced: set[str] = set()
    referenced.update(scan_tcss_references())
    referenced.update(scan_default_css_references().keys())
    must_be_declared = referenced & defaults_names
    missing = must_be_declared - set(decls.keys())
    assert not missing, (
        f"COMPONENT_VAR_DEFAULTS keys $-referenced but not declared in "
        f"hermes.tcss: {sorted(missing)}. Add `$name: default;` declarations."
    )


@pytest.mark.xfail(
    reason="Phase 4 generator target — all defaults declared in TCSS",
    strict=False,
)
def test_t2_all_defaults_declared_post_phase4() -> None:
    decls = scan_tcss_declarations()
    missing = set(COMPONENT_VAR_DEFAULTS.keys()) - set(decls.keys())
    assert not missing, sorted(missing)


# ---------------------------------------------------------------------------
# T3 — every bundled skin covers all required component_vars keys
# ---------------------------------------------------------------------------


def test_t3_bundled_skins_cover_all_keys() -> None:
    skins = scan_bundled_skins()
    assert skins, "No bundled skins found at skins/*.yaml"
    required = {
        k for k, v in COMPONENT_VAR_DEFAULTS.items()
        if not (isinstance(v, VarSpec) and v.optional_in_skin)
    }
    missing_report: dict[str, list[str]] = {}
    for skin_name, keys in skins.items():
        missing = sorted(required - keys)
        if missing:
            missing_report[skin_name] = missing
    assert not missing_report, (
        f"Bundled skins missing required component_vars keys: {missing_report}"
    )


# ---------------------------------------------------------------------------
# T4 — no orphan TCSS declarations
# ---------------------------------------------------------------------------


def test_t4_no_orphan_tcss_declarations() -> None:
    """Every $name: value; declaration must be in COMPONENT_VAR_DEFAULTS,
    unless it is a hand-declared utility (none exist today)."""
    decls = scan_tcss_declarations()
    defaults_names = set(COMPONENT_VAR_DEFAULTS.keys())
    orphans = set(decls.keys()) - defaults_names - TEXTUAL_BUILTIN_VARS
    # Allow through built-ins (primary-darken-3 etc. that skins may re-declare).
    # A real orphan would be a var declared in TCSS but neither in defaults
    # nor built-in. Fail if any.
    assert not orphans, (
        f"hermes.tcss has orphan declarations (not in defaults, not built-in): "
        f"{sorted(orphans)}. Either add to COMPONENT_VAR_DEFAULTS or remove."
    )


# ---------------------------------------------------------------------------
# T5 — generator round-trip (defer until generated block lands in tcss)
# ---------------------------------------------------------------------------


def test_t5_generator_runs_without_error() -> None:
    """Generator must produce deterministic output for the current defaults.
    Full round-trip test (--check mode) is deferred until Phase 4 lands the
    generated block in hermes.tcss.
    """
    block1 = bsv.render_tcss_block(COMPONENT_VAR_DEFAULTS)
    block2 = bsv.render_tcss_block(COMPONENT_VAR_DEFAULTS)
    assert block1 == block2, "generator output must be deterministic"
    assert "GENERATED: component-vars BEGIN" in block1
    assert "GENERATED: component-vars END" in block1
    assert "hash: sha256:" in block1


# ---------------------------------------------------------------------------
# T6 — validator rejects malformed payloads
# ---------------------------------------------------------------------------


def test_t6_validator_rejects_bad_hex() -> None:
    with pytest.raises(SkinValidationError, match="cursor-color"):
        validate_skin_payload(
            {"component_vars": {"cursor-color": "not-a-color"}},
            warn_missing=False,
        )


def test_t6_validator_rejects_non_mapping_component_vars() -> None:
    with pytest.raises(SkinValidationError, match="component_vars"):
        validate_skin_payload(
            {"component_vars": "not a dict"},
            warn_missing=False,
        )


def test_t6_validator_rejects_non_mapping_vars() -> None:
    with pytest.raises(SkinValidationError, match="vars"):
        validate_skin_payload(
            {"component_vars": {}, "vars": ["list"]},
            warn_missing=False,
        )


def test_t6_validator_warns_on_missing_keys() -> None:
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        validate_skin_payload({"component_vars": {}, "vars": {}})
    msgs = [str(w.message) for w in rec]
    assert any("missing" in m for m in msgs), (
        f"expected missing-keys warning, got {msgs}"
    )


def test_t6_validator_warns_on_unknown_keys() -> None:
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        validate_skin_payload(
            {"component_vars": {"xyz-not-a-real-key": "#ffffff"}},
        )
    msgs = [str(w.message) for w in rec]
    assert any("unknown" in m for m in msgs), f"expected unknown warning, got {msgs}"


# ---------------------------------------------------------------------------
# T6b — validator runs on merged (skin ⊕ skin_overrides) output
# ---------------------------------------------------------------------------


def test_t6b_validator_flags_bad_override() -> None:
    """When validator is called on merged payload with a bad override, error
    message names the override source."""
    with pytest.raises(SkinValidationError) as ex:
        validate_skin_payload(
            {"component_vars": {"cursor-color": "not-hex"}},
            source="skin_overrides",
            warn_missing=False,
        )
    assert "skin_overrides" in str(ex.value)
    assert "cursor-color" in str(ex.value)


# ---------------------------------------------------------------------------
# T7 — load_dict() does NOT call _apply_overrides()
# ---------------------------------------------------------------------------


def test_t7_load_dict_skips_overrides(monkeypatch) -> None:
    from unittest.mock import MagicMock
    from hermes_cli.tui.theme_manager import ThemeManager

    app = MagicMock()
    tm = ThemeManager(app)
    monkeypatch.setattr(tm, "_apply_overrides", MagicMock())
    tm.load_dict({"accent": "#ffffff"})
    tm._apply_overrides.assert_not_called()


# ---------------------------------------------------------------------------
# T8 — no raw COMPONENT_VAR_DEFAULTS access (grep test for shim)
# ---------------------------------------------------------------------------


def test_t8_all_consumers_use_default_of() -> None:
    """Every `COMPONENT_VAR_DEFAULTS[...]` access must go through
    `_default_of()` or `_defaults_as_strs()` — prevents raw-str access
    after the VarSpec migration."""
    repo = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"COMPONENT_VAR_DEFAULTS\s*\[")
    offenders: list[str] = []
    for py in (repo / "hermes_cli").rglob("*.py"):
        # Ignore the defaults definition site itself + the build tool which
        # lives outside the migration-shim contract (it always uses VarSpecs).
        if py.name in ("theme_manager.py", "build_skin_vars.py"):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line) and "_default_of" not in line:
                offenders.append(f"{py}:{lineno}: {line.strip()}")
    assert not offenders, (
        f"Raw COMPONENT_VAR_DEFAULTS[...] access (must use _default_of): "
        f"{offenders[:5]}"
    )


# ---------------------------------------------------------------------------
# Extra — VarSpec and _default_of semantics
# ---------------------------------------------------------------------------


def test_default_of_str_passthrough() -> None:
    assert _default_of("#ffffff") == "#ffffff"


def test_default_of_varspec_unwrap() -> None:
    spec = VarSpec(default="#123456", description="test", category="misc")
    assert _default_of(spec) == "#123456"


def test_defaults_as_strs_all_hex() -> None:
    out = _defaults_as_strs()
    assert len(out) == len(COMPONENT_VAR_DEFAULTS)
    for name, val in out.items():
        assert isinstance(val, str)
        assert val.startswith("#"), f"{name} default not hex: {val}"


# ---------------------------------------------------------------------------
# Extra — Textual built-in version pin sanity
# ---------------------------------------------------------------------------


def test_textual_builtin_introspection_works() -> None:
    """TEXTUAL_BUILTIN_VARS is introspected at import time; assert it
    contains the standard colors and is non-trivial."""
    for core in ("primary", "background", "foreground", "panel", "boost"):
        assert core in TEXTUAL_BUILTIN_VARS, f"{core} missing from built-ins"
    assert len(TEXTUAL_BUILTIN_VARS) >= 50


# ---------------------------------------------------------------------------
# Extra — generator hash deterministic + sensitive to description changes
# ---------------------------------------------------------------------------


def test_generator_hash_includes_description() -> None:
    """Description-only edits must change the hash (§6.2)."""
    d1 = {"x": VarSpec(default="#aaaaaa", description="one")}
    d2 = {"x": VarSpec(default="#aaaaaa", description="two")}
    h1 = bsv._compute_hash(bsv._as_specs(d1))
    h2 = bsv._compute_hash(bsv._as_specs(d2))
    assert h1 != h2, "description change must change hash"
