"""CSS variable single-source-of-truth scanner + generator.

Implements RX3 spec (/home/xush/.hermes/2026-04-22-tui-v2-RX3-css-var-single-source-spec.md).

Entry points:
    python -m hermes_cli.tui.build_skin_vars           # regenerate blocks
    python -m hermes_cli.tui.build_skin_vars --check   # CI drift gate
    python -m hermes_cli.tui.build_skin_vars --fill-skin <path>
    python -m hermes_cli.tui.build_skin_vars --matrix  # audit report
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]
TCSS_PATH = _REPO / "hermes_cli" / "tui" / "hermes.tcss"
SKIN_ENGINE_PATH = _REPO / "hermes_cli" / "skin_engine.py"
SKINS_DIR = _REPO / "skins"
TUI_DIR = _REPO / "hermes_cli" / "tui"


# ---------------------------------------------------------------------------
# VarSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VarSpec:
    """Canonical description of a component CSS variable."""

    default: str
    description: str = ""
    since: str | None = None
    optional_in_skin: bool = False
    category: str = "misc"


def _default_of(x: "str | VarSpec") -> str:
    """Unwrap a COMPONENT_VAR_DEFAULTS value to its hex default."""
    return x if isinstance(x, str) else x.default


# ---------------------------------------------------------------------------
# Textual built-in allowlist
# ---------------------------------------------------------------------------

# Hand-enumerated fallback used when App().get_css_variables() is unavailable
# (e.g. import-time error paths). Kept as a machine-generated snapshot of
# Textual 8.2.3 so the lint tool still works in degraded environments.
TEXTUAL_BUILTIN_VARS_FALLBACK: frozenset[str] = frozenset({
    # Base palette (each has -lighten-1/2/3, -darken-1/2/3, -muted variants)
    "accent", "background", "boost", "error", "foreground", "panel",
    "primary", "secondary", "success", "surface", "warning",
    # Text auto-contrast
    "text", "text-accent", "text-disabled", "text-error", "text-muted",
    "text-primary", "text-secondary", "text-success", "text-warning",
    # Scrollbar
    "scrollbar", "scrollbar-active", "scrollbar-background",
    "scrollbar-background-active", "scrollbar-background-hover",
    "scrollbar-corner-color", "scrollbar-hover",
    # Block cursor
    "block-cursor-background", "block-cursor-blurred-background",
    "block-cursor-blurred-foreground", "block-cursor-blurred-text-style",
    "block-cursor-foreground", "block-cursor-text-style",
    # Input / selection
    "input-cursor-background", "input-cursor-foreground",
    "input-cursor-text-style", "input-selection-background",
    # Link
    "link-background", "link-background-hover", "link-color",
    "link-color-hover", "link-style", "link-style-hover",
    # Footer / misc
    "footer-background", "footer-description-background",
    "footer-description-foreground", "footer-foreground",
    "footer-item-background", "footer-key-background", "footer-key-foreground",
    "border", "border-blurred",
})


def _get_textual_builtins() -> frozenset[str]:
    """Introspect Textual built-in CSS variables at call time.

    Raises AssertionError if Textual major/minor doesn't match the pinned
    version — forces the maintainer to audit the allowlist on upgrade.
    Falls back to TEXTUAL_BUILTIN_VARS_FALLBACK on any error.
    """
    try:
        import textual
        ver = textual.__version__
        assert ver.startswith("8."), (
            f"TEXTUAL_BUILTIN_VARS was pinned for Textual 8.x; "
            f"installed {ver}. Audit build_skin_vars.TEXTUAL_BUILTIN_VARS_FALLBACK "
            f"and bump the pin."
        )
        from textual.app import App

        class _Probe(App):  # type: ignore[misc]
            pass

        return frozenset(_Probe().get_css_variables().keys())
    except AssertionError:
        raise
    except Exception:
        return TEXTUAL_BUILTIN_VARS_FALLBACK


TEXTUAL_BUILTIN_VARS: frozenset[str] = _get_textual_builtins()


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------

_VAR_REF_RE = re.compile(r"\$([a-z][a-z0-9-]*)")
_VAR_DECL_RE = re.compile(r"^\s*\$([a-z][a-z0-9-]*)\s*:\s*([^;]+);", re.MULTILINE)
_TCSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_DEFAULT_CSS_RE = re.compile(
    r'DEFAULT_CSS\s*(?::\s*[^\n=]+)?=\s*(?:r?["\']{3})(.+?)["\']{3}',
    re.DOTALL,
)


def scan_tcss_references(path: Path = TCSS_PATH) -> set[str]:
    """All $var-name tokens in selectors/rules (excluding declaration LHS and comments)."""
    text = path.read_text(encoding="utf-8")
    # Strip TCSS comments first — they often mention `$var` generically
    text = _TCSS_COMMENT_RE.sub("", text)
    # Strip declaration LHS so we only count *references*
    stripped = _VAR_DECL_RE.sub("", text)
    return set(_VAR_REF_RE.findall(stripped))


def scan_tcss_declarations(path: Path = TCSS_PATH) -> dict[str, str]:
    """All `$name: value;` declarations in hermes.tcss."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for name, val in _VAR_DECL_RE.findall(text):
        out[name] = val.strip()
    return out


def scan_default_css_references(tui_dir: Path = TUI_DIR) -> dict[str, set[Path]]:
    """All $var-name tokens inside DEFAULT_CSS triple-string blocks.

    Returns {var_name: {source_paths_where_referenced}}.
    """
    refs: dict[str, set[Path]] = {}
    for py in tui_dir.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        if "DEFAULT_CSS" not in text:
            continue
        for block in _DEFAULT_CSS_RE.findall(text):
            for name in _VAR_REF_RE.findall(block):
                refs.setdefault(name, set()).add(py)
    return refs


def scan_skin_keys(skin_path: Path) -> set[str]:
    """Keys under `component_vars:` in a bundled/user skin YAML."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return set()
    try:
        data = yaml.safe_load(skin_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    cv = data.get("component_vars", {}) if isinstance(data, dict) else {}
    if not isinstance(cv, dict):
        return set()
    return {str(k) for k in cv.keys()}


def scan_bundled_skins(skins_dir: Path = SKINS_DIR) -> dict[str, set[str]]:
    """{skin_name: {component_var_keys}} for each bundled YAML."""
    out: dict[str, set[str]] = {}
    if not skins_dir.exists():
        return out
    for yf in sorted(skins_dir.glob("*.yaml")):
        out[yf.stem] = scan_skin_keys(yf)
    return out


def scan_docstring_keys(path: Path = SKIN_ENGINE_PATH) -> set[str]:
    """Keys listed in the `component_vars:` section of skin_engine.py docstring."""
    text = path.read_text(encoding="utf-8")
    # Scoped search — find the `component_vars:` marker inside docstring context
    # and collect 2-space-indented `<name>:` lines until a non-indented line.
    out: set[str] = set()
    idx = text.find("component_vars:")
    if idx < 0:
        return out
    # Walk forward line-by-line
    remainder = text[idx:].splitlines()
    for line in remainder[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # A key line inside docstring: `  name:   "#hex"   # comment`
        m = re.match(r"\s{2,}([a-z][a-z0-9-]+)\s*:\s*", line)
        if m:
            out.add(m.group(1))
            continue
        # Any line not matching the pattern breaks the block
        if not line.startswith(" "):
            break
    return out


# ---------------------------------------------------------------------------
# Matrix / audit
# ---------------------------------------------------------------------------


def build_matrix(defaults: dict[str, "str | VarSpec"]) -> list[dict]:
    """Build an audit matrix row per unique name."""
    tcss_refs = scan_tcss_references()
    tcss_decls = scan_tcss_declarations()
    default_css_refs = scan_default_css_references()
    docstring = scan_docstring_keys()
    skins = scan_bundled_skins()

    all_names: set[str] = set()
    all_names.update(tcss_refs)
    all_names.update(tcss_decls.keys())
    all_names.update(default_css_refs.keys())
    all_names.update(defaults.keys())
    all_names.update(docstring)
    for keys in skins.values():
        all_names.update(keys)

    rows: list[dict] = []
    for name in sorted(all_names):
        referenced = name in tcss_refs or name in default_css_refs
        is_builtin = name in TEXTUAL_BUILTIN_VARS
        row = {
            "name": name,
            "referenced": referenced,
            "in_tcss_decl": name in tcss_decls,
            "in_py_default": name in defaults,
            "in_docstring": name in docstring,
            "builtin": is_builtin,
        }
        for skin_name, keys in skins.items():
            row[f"skin_{skin_name}"] = name in keys
        rows.append(row)
    return rows


def print_matrix(rows: list[dict]) -> None:
    """Print the audit matrix as a readable report."""
    skins = sorted({k[len("skin_"):] for r in rows for k in r if k.startswith("skin_")})
    header = ["name", "ref", "tcss", "py", "doc", "builtin"] + skins
    widths = [max(len(h), 3) for h in header]
    for r in rows:
        widths[0] = max(widths[0], len(r["name"]))
    fmt = "  ".join("{:<%d}" % w for w in widths)
    print(fmt.format(*header))
    print(fmt.format(*("-" * w for w in widths)))
    drift_count = 0
    for r in rows:
        vals = [
            r["name"],
            "✓" if r["referenced"] else "—",
            "✓" if r["in_tcss_decl"] else "—",
            "✓" if r["in_py_default"] else "—",
            "✓" if r["in_docstring"] else "—",
            "B" if r["builtin"] else "—",
        ]
        for s in skins:
            vals.append("✓" if r.get(f"skin_{s}", False) else "—")
        print(fmt.format(*vals))
        if _row_has_drift(r, skins):
            drift_count += 1
    print()
    print(f"drift rows: {drift_count}/{len(rows)}")


def _row_has_drift(row: dict, skins: list[str]) -> bool:
    if row["builtin"]:
        return False
    if not row["in_py_default"]:
        return row["referenced"] or any(row.get(f"skin_{s}") for s in skins)
    # In py default: expect tcss decl, docstring, every bundled skin
    if not row["in_tcss_decl"]:
        return True
    if not row["in_docstring"]:
        return True
    for s in skins:
        if not row.get(f"skin_{s}"):
            return True
    return False


# ---------------------------------------------------------------------------
# Generator — TCSS block
# ---------------------------------------------------------------------------

_TCSS_BEGIN = "/* ====== GENERATED: component-vars BEGIN (do not edit; see COMPONENT_VAR_DEFAULTS) ====== */"
_TCSS_END = "/* ====== GENERATED: component-vars END ==================================================== */"
_TCSS_BLOCK_RE = re.compile(
    re.escape(_TCSS_BEGIN) + r"(.+?)" + re.escape(_TCSS_END),
    re.DOTALL,
)

_DOC_BEGIN = "# BEGIN:generated-component-vars  (do not edit; run build_skin_vars)"
_DOC_END = "# END:generated-component-vars"
_DOC_BLOCK_RE = re.compile(
    re.escape(_DOC_BEGIN) + r"(.+?)" + re.escape(_DOC_END),
    re.DOTALL,
)


def _as_specs(defaults: dict[str, "str | VarSpec"]) -> dict[str, VarSpec]:
    """Coerce str entries to VarSpec during migration."""
    out: dict[str, VarSpec] = {}
    for name, v in defaults.items():
        if isinstance(v, VarSpec):
            out[name] = v
        else:
            out[name] = VarSpec(default=v, description="", category="misc")
    return out


def _compute_hash(specs: dict[str, VarSpec]) -> str:
    """sha256 over (category, name, default, description, since, optional_in_skin)."""
    h = hashlib.sha256()
    for name in sorted(specs):
        s = specs[name]
        h.update(
            f"{s.category}|{name}|{s.default}|{s.description}|{s.since}|{s.optional_in_skin}\n".encode()
        )
    return h.hexdigest()


def render_tcss_block(defaults: dict[str, "str | VarSpec"]) -> str:
    """Render the TCSS generated block content (between markers, inclusive)."""
    specs = _as_specs(defaults)
    digest = _compute_hash(specs)
    by_cat: dict[str, list[tuple[str, VarSpec]]] = {}
    for name in sorted(specs):
        by_cat.setdefault(specs[name].category, []).append((name, specs[name]))

    lines = [_TCSS_BEGIN, f"/* hash: sha256:{digest} */"]
    for cat in sorted(by_cat):
        lines.append(f"/* category: {cat} */")
        for name, s in by_cat[cat]:
            comment = f"  /* {s.description} */" if s.description else ""
            lines.append(f"${name}: {s.default};{comment}")
    lines.append(_TCSS_END)
    return "\n".join(lines) + "\n"


def render_docstring_block(defaults: dict[str, "str | VarSpec"]) -> str:
    """Render the skin_engine.py docstring component_vars block."""
    specs = _as_specs(defaults)
    digest = _compute_hash(specs)
    lines = [_DOC_BEGIN, f"# hash: sha256:{digest}", "component_vars:"]
    by_cat: dict[str, list[tuple[str, VarSpec]]] = {}
    for name in sorted(specs):
        by_cat.setdefault(specs[name].category, []).append((name, specs[name]))
    for cat in sorted(by_cat):
        lines.append(f"  # category: {cat}")
        for name, s in by_cat[cat]:
            suffix = f"   # {s.description}" if s.description else ""
            lines.append(f'  {name}: "{s.default}"{suffix}')
    lines.append(_DOC_END)
    return "\n".join(lines) + "\n"


def write_tcss(defaults: dict[str, "str | VarSpec"], path: Path = TCSS_PATH) -> bool:
    """Replace generated block in hermes.tcss. Returns True if file changed."""
    text = path.read_text(encoding="utf-8")
    new_block = render_tcss_block(defaults)
    if _TCSS_BLOCK_RE.search(text):
        new_text = _TCSS_BLOCK_RE.sub(lambda _m: new_block.rstrip("\n"), text)
    else:
        # Append at end of file (first-run install); developer will move the
        # block to its intended location inside hermes.tcss on review.
        sep = "" if text.endswith("\n") else "\n"
        new_text = text + sep + "\n" + new_block
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


def write_docstring(defaults: dict[str, "str | VarSpec"], path: Path = SKIN_ENGINE_PATH) -> bool:
    text = path.read_text(encoding="utf-8")
    new_block = render_docstring_block(defaults)
    if _DOC_BLOCK_RE.search(text):
        new_text = _DOC_BLOCK_RE.sub(lambda _m: new_block.rstrip("\n"), text)
    else:
        # Not installed yet — append at end of module docstring section.
        # Developer manually splices on first install.
        return False
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


# ---------------------------------------------------------------------------
# --fill-skin
# ---------------------------------------------------------------------------


def fill_skin(skin_path: Path, defaults: dict[str, "str | VarSpec"]) -> int:
    """Add missing component_vars keys to a skin YAML. Returns count added."""
    import yaml  # type: ignore
    text = skin_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{skin_path}: top level not a mapping")
    cv = data.setdefault("component_vars", {})
    if not isinstance(cv, dict):
        raise ValueError(f"{skin_path}: component_vars not a mapping")
    added = 0
    for name in sorted(defaults):
        if name in cv:
            continue
        cv[name] = _default_of(defaults[name])
        added += 1
    if added == 0:
        return 0
    # Re-serialize preserving existing top-level keys where possible by
    # appending an auto-generated block at the end of component_vars.
    new_text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    skin_path.write_text(new_text, encoding="utf-8", newline="\n")
    return added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_check(defaults: dict[str, "str | VarSpec"]) -> int:
    """Compare on-disk blocks against what generation would produce."""
    tcss_text = TCSS_PATH.read_text(encoding="utf-8")
    doc_text = SKIN_ENGINE_PATH.read_text(encoding="utf-8")
    want_tcss = render_tcss_block(defaults)
    want_doc = render_docstring_block(defaults)

    tcss_match = _TCSS_BLOCK_RE.search(tcss_text)
    doc_match = _DOC_BLOCK_RE.search(doc_text)

    ok = True
    if not tcss_match:
        print("DRIFT: hermes.tcss has no GENERATED block; run build_skin_vars")
        ok = False
    elif tcss_match.group(0) + "\n" != want_tcss:
        print("DRIFT: hermes.tcss GENERATED block differs from source")
        ok = False
    if not doc_match:
        print("WARN: skin_engine.py has no GENERATED docstring block")
        # warning-only; doesn't fail check
    elif doc_match.group(0) + "\n" != want_doc:
        print("DRIFT: skin_engine.py docstring GENERATED block differs")
        ok = False
    if ok:
        print("OK: generated blocks in sync")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_skin_vars", description=__doc__)
    ap.add_argument("--check", action="store_true", help="CI drift gate")
    ap.add_argument("--matrix", action="store_true", help="Print audit matrix")
    ap.add_argument("--fill-skin", metavar="PATH", help="Add missing keys to a skin YAML")
    args = ap.parse_args(argv)

    # Lazy import so this module is callable without the TUI stack available.
    from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS

    if args.matrix:
        rows = build_matrix(COMPONENT_VAR_DEFAULTS)
        print_matrix(rows)
        return 0

    if args.fill_skin:
        added = fill_skin(Path(args.fill_skin), COMPONENT_VAR_DEFAULTS)
        print(f"added {added} keys to {args.fill_skin}")
        return 0

    if args.check:
        return _cli_check(COMPONENT_VAR_DEFAULTS)

    tcss_changed = write_tcss(COMPONENT_VAR_DEFAULTS)
    doc_changed = write_docstring(COMPONENT_VAR_DEFAULTS)
    print(f"hermes.tcss: {'updated' if tcss_changed else 'unchanged'}")
    print(f"skin_engine.py: {'updated' if doc_changed else 'unchanged (no block marker)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
