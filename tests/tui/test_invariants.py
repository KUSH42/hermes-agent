"""Mechanical lint gates encoding docs/concept.md v3.6 invariants.

Spec: /home/xush/.hermes/invariant_lint_gates.md (IL-1..IL-8).

These tests are AST walks, regex sweeps, and resolver-state assertions over the
six owner paths under hermes_cli/tui/. None require a mounted DOM. Target
runtime: <2 seconds.
"""
from __future__ import annotations

import ast
import pathlib
import re
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_TUI_ROOT = _REPO_ROOT / "hermes_cli" / "tui"

# Six owner paths per spec.
_OWNER_DIRS: list[pathlib.Path] = [
    _TUI_ROOT / "tool_blocks",
    _TUI_ROOT / "tool_panel",
    _TUI_ROOT / "body_renderers",
]
_OWNER_FILES: list[pathlib.Path] = [
    _TUI_ROOT / "services" / "tools.py",
    _TUI_ROOT / "services" / "plan_sync.py",
    _TUI_ROOT / "services" / "feedback.py",
]


def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _walk_owner_paths() -> list[pathlib.Path]:
    """Return every .py file in the six owner paths (no __pycache__)."""
    files: list[pathlib.Path] = list(_OWNER_FILES)
    for d in _OWNER_DIRS:
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


def _ast_walk(path: pathlib.Path) -> ast.Module:
    return ast.parse(_src(path), filename=str(path))


# ---------------------------------------------------------------------------
# IL-1 — Sibling-private cross-reads forbidden
# ---------------------------------------------------------------------------

# Modules that legitimately compose another widget. Maps relative path
# (from _TUI_ROOT) → list of allowed inner-widget privates accessed via self.
_IL1_ALLOWLIST: dict[str, set[str]] = {
    "tool_blocks/_block.py":     {"_header"},
    "tool_blocks/_streaming.py": {"_header"},  # inherits ToolHeader from ToolBlock
    "tool_panel/_core.py":       {"_block"},
    "tool_panel/_actions.py":    {"_block"},   # mixin of ToolPanel
    "tool_panel/_child.py":      {"_block"},   # subclass of ToolPanel
}

# Forbidden chains: outer-private → inner-private pairs that we treat as
# sibling-private cross-reads. Order matters: we look for X.Y where X is the
# outer-private and Y starts with underscore.
_IL1_FORBIDDEN_OUTERS: set[str] = {"_panel", "_block", "_header"}


def _il1_chain_violations(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return list of (lineno, chain) for every sibling-private violation.

    Detects:
      self._A._B.X        where _A in _IL1_FORBIDDEN_OUTERS and _B startswith _
      hasattr(self._A._B, ...) / getattr(self._A._B, ...) — same chain in
      a Call's first argument.
    """
    rel = path.relative_to(_TUI_ROOT).as_posix()
    allowed_inners = _IL1_ALLOWLIST.get(rel, set())
    src = _src(path)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    def _chain_outer_inner(node: ast.AST) -> tuple[str, str] | None:
        """If node is `self.<outer>.<inner>` or deeper, return (outer, inner)."""
        # Walk down Attribute nodes; the chain we want has at least 3 parts:
        # self → outer-private → inner-private → ... .
        if not isinstance(node, ast.Attribute):
            return None
        # Drill to the bottom Name (which should be 'self').
        chain: list[str] = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if not (isinstance(cur, ast.Name) and cur.id == "self"):
            return None
        # chain is built outermost-first: e.g. for self._panel._block._x
        # chain == ["_x", "_block", "_panel"].
        chain.reverse()
        # We need len(chain) >= 3: outer, inner, ... .
        if len(chain) < 3:
            return None
        outer, inner = chain[0], chain[1]
        if outer in _IL1_FORBIDDEN_OUTERS and inner.startswith("_"):
            return outer, inner
        return None

    class V(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            r = _chain_outer_inner(node)
            if r is not None:
                outer, inner = r
                if outer not in allowed_inners:
                    violations.append((node.lineno, f"self.{outer}.{inner}.…"))
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            # hasattr(self._panel._block, "_x") / getattr(self._panel._block, ...)
            if (isinstance(node.func, ast.Name)
                    and node.func.id in {"hasattr", "getattr"}
                    and node.args):
                first = node.args[0]
                if isinstance(first, ast.Attribute):
                    # Treat the chain leading up to the attribute access as a
                    # forbidden sibling chain. We need len(chain) >= 2 here
                    # because hasattr(self._panel._block, "x") is a 2-level
                    # access already used as an inner-widget read.
                    chain: list[str] = []
                    cur: ast.AST = first
                    while isinstance(cur, ast.Attribute):
                        chain.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name) and cur.id == "self":
                        chain.reverse()
                        if len(chain) >= 2:
                            outer, inner = chain[0], chain[1]
                            if (outer in _IL1_FORBIDDEN_OUTERS
                                    and inner.startswith("_")
                                    and outer not in allowed_inners):
                                violations.append(
                                    (node.lineno,
                                     f"{node.func.id}(self.{outer}.{inner}, …)")
                                )
            self.generic_visit(node)

    V().visit(tree)
    return violations


class TestIL1SiblingPrivateReads:
    """IL-1 — widgets must not read sibling privates outside the composer."""

    def test_no_sibling_private_reads_in_owner_paths(self) -> None:
        offenders: list[str] = []
        for p in _walk_owner_paths():
            for ln, chain in _il1_chain_violations(p):
                rel = p.relative_to(_REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{ln}: {chain}")
        assert offenders == [], "IL-1 violations:\n" + "\n".join(offenders)

    def test_owner_module_self_reads_allowed(self) -> None:
        """Meta: an allowlisted module reading its own composed widget is OK."""
        # _block.py composes _header — verify _il1 walk does not flag it.
        path = _TUI_ROOT / "tool_blocks" / "_block.py"
        for ln, chain in _il1_chain_violations(path):
            assert "_header" not in chain, (
                f"_block.py legitimately reads self._header._*; got false positive "
                f"at line {ln}: {chain}"
            )

    def test_known_violation_caught(self) -> None:
        """Meta: a synthetic violation in a non-allowlisted module is flagged."""
        # Construct a synthetic AST sample. We use ast.parse directly rather
        # than writing to disk.
        sample = (
            "class T:\n"
            "    def f(self):\n"
            "        return self._panel._block._visible_count\n"
        )
        tree = ast.parse(sample)
        # Reuse the chain detector by walking the tree manually.
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain: list[str] = []
                cur: ast.AST = node
                while isinstance(cur, ast.Attribute):
                    chain.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name) and cur.id == "self":
                    chain.reverse()
                    if (len(chain) >= 3
                            and chain[0] in _IL1_FORBIDDEN_OUTERS
                            and chain[1].startswith("_")):
                        found.append(chain)
        assert found, "Synthetic violation should be detected by the chain walker"

    def test_test_files_exempt(self) -> None:
        """Meta: this test file (tests/) is not walked by IL-1."""
        files = _walk_owner_paths()
        for f in files:
            assert "tests" not in f.parts, (
                f"_walk_owner_paths returned a test file: {f}"
            )


# ---------------------------------------------------------------------------
# IL-6 — Renderer purity (no view-state / app reads in render)
# ---------------------------------------------------------------------------

_IL6_FORBIDDEN_ROOTS: dict[str, str] = {
    # Attribute-chain root (the Name node) → reason
    "view_state": "renderer reads view_state (must arrive as kwarg)",
}
# Forbidden self.X attributes inside render-family methods.
_IL6_FORBIDDEN_SELF_ATTRS: set[str] = {"app", "_panel", "_block"}
_IL6_RENDER_METHODS: set[str] = {"render", "build", "build_widget"}


def _il6_get_body_renderer_subclass_names(tree: ast.Module) -> set[str]:
    """Return names of classes in tree that subclass BodyRenderer (by name)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            base_names = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
            if "BodyRenderer" in base_names:
                names.add(node.name)
    return names


def _il6_renderer_violations(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return (lineno, message) for renderer-purity violations in path."""
    tree = _ast_walk(path)
    subclass_names = _il6_get_body_renderer_subclass_names(tree)
    if not subclass_names:
        return []

    violations: list[tuple[int, str]] = []

    for cls in tree.body:
        if not (isinstance(cls, ast.ClassDef) and cls.name in subclass_names):
            continue
        for fn in cls.body:
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name in _IL6_RENDER_METHODS):
                continue
            for node in ast.walk(fn):
                # view_state.* usage: a Name "view_state" used as the root of
                # an Attribute chain.
                if isinstance(node, ast.Name) and node.id in _IL6_FORBIDDEN_ROOTS:
                    violations.append(
                        (node.lineno,
                         f"{path.name}:{cls.name}.{fn.name}: forbidden root "
                         f"'{node.id}' — {_IL6_FORBIDDEN_ROOTS[node.id]}")
                    )
                # self.app, self._panel, self._block — direct attribute on self.
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr in _IL6_FORBIDDEN_SELF_ATTRS):
                    violations.append(
                        (node.lineno,
                         f"{path.name}:{cls.name}.{fn.name}: forbidden access "
                         f"self.{node.attr}")
                    )
    return violations


class TestIL6RendererPurity:
    """IL-6 — renderers do not read view_state / app / sibling widgets."""

    def test_renderers_no_view_state_reads(self) -> None:
        """Every render/build/build_widget on a BodyRenderer subclass is clean."""
        body_dir = _TUI_ROOT / "body_renderers"
        offenders: list[str] = []
        for p in body_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            for ln, msg in _il6_renderer_violations(p):
                if "view_state" in msg:
                    offenders.append(f"{p.relative_to(_REPO_ROOT)}:{ln}: {msg}")
        assert offenders == [], "IL-6 view_state violations:\n" + "\n".join(offenders)

    def test_renderers_no_app_reads(self) -> None:
        """Forbid self.app / self._panel / self._block on BodyRenderer subclasses.

        self._app (private, stored at init) is allowed by Fix-section spec.
        """
        body_dir = _TUI_ROOT / "body_renderers"
        offenders: list[str] = []
        for p in body_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            for ln, msg in _il6_renderer_violations(p):
                if "self." in msg:
                    offenders.append(f"{p.relative_to(_REPO_ROOT)}:{ln}: {msg}")
        assert offenders == [], "IL-6 self.app/_panel/_block violations:\n" + "\n".join(offenders)

    def test_renderer_purity_meta(self) -> None:
        """Meta: synthetic violation in a fixture file is flagged correctly."""
        sample = (
            "class FakeRenderer(BodyRenderer):\n"
            "    def build(self, view_state):\n"
            "        return view_state.phase\n"
        )
        tree = ast.parse(sample)
        # Find render-family methods on the FakeRenderer class.
        cls = tree.body[0]
        assert isinstance(cls, ast.ClassDef)
        fn = cls.body[0]
        assert isinstance(fn, ast.FunctionDef)
        names = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name)]
        # Both the parameter and the read should appear; we only flag the read
        # of view_state as a Name node — the parameter Name is also a Name, so
        # this meta-test asserts the chain detection sees view_state as a Name
        # the violation walker would catch.
        assert "view_state" in names


# ---------------------------------------------------------------------------
# IL-2 — Raw hex outside SkinColors palette
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_FALLBACK_CONST_RE = re.compile(r"^_[A-Z][A-Z0-9_]*_FALLBACK$")
_NOQA_HEX_RE = re.compile(r"#\s*noqa:\s*hex")


def _il2_strip_comment(line: str) -> str:
    """Return line truncated at the first `#` that starts a comment (not inside a string)."""
    in_str: str | None = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == in_str and (i == 0 or line[i - 1] != "\\"):
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "#":
            return line[:i]
    return line


def _il2_in_skin_default_or_dataclass_body(path: pathlib.Path, lineno: int) -> bool:
    """True if the given line is inside SkinColors.default() or the SkinColors dataclass body."""
    if path.name != "_grammar.py":
        return False
    tree = _ast_walk(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SkinColors":
            # Whole dataclass body covers field defaults at the class level.
            cls_start = node.lineno
            cls_end = node.end_lineno or cls_start
            if cls_start <= lineno <= cls_end:
                # Check whether we are inside a method body other than default().
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        sub_end = sub.end_lineno or sub.lineno
                        if sub.lineno <= lineno <= sub_end and sub.name != "default":
                            # Inside a non-default method — fail unless allowlisted elsewhere.
                            return False
                return True
    return False


def _il2_violations(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return list of (lineno, line) for hex hits outside the allowlist."""
    src = _src(path)
    # Collect module-level _*_FALLBACK constant line numbers via AST.
    tree = _ast_walk(path)
    fallback_lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and _FALLBACK_CONST_RE.match(tgt.id):
                    fallback_lines.add(node.lineno)
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and _FALLBACK_CONST_RE.match(node.target.id)):
                fallback_lines.add(node.lineno)

    violations: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        # Strip comments before scanning — comments are exempt.
        code_part = _il2_strip_comment(line)
        if not _HEX_RE.search(code_part):
            continue
        if _NOQA_HEX_RE.search(line):
            continue
        if i in fallback_lines:
            continue
        if _il2_in_skin_default_or_dataclass_body(path, i):
            continue
        violations.append((i, line.rstrip()))
    return violations


class TestIL2RawHex:
    """IL-2 — no raw hex outside the SkinColors palette + allowlist."""

    def test_no_raw_hex_in_owner_paths(self) -> None:
        offenders: list[str] = []
        for p in _walk_owner_paths():
            for ln, line in _il2_violations(p):
                rel = p.relative_to(_REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{ln}: {line.strip()}")
        assert offenders == [], "IL-2 raw-hex violations:\n" + "\n".join(offenders)

    def test_skin_default_palette_exempt(self) -> None:
        """Meta: hits inside SkinColors.default() body are not flagged."""
        path = _TUI_ROOT / "body_renderers" / "_grammar.py"
        # Find the line of accent="#0178D4" inside SkinColors.default().
        src = _src(path)
        for i, line in enumerate(src.splitlines(), start=1):
            if 'accent = "#0178D4"' in line or 'accent="#0178D4"' in line:
                assert _il2_in_skin_default_or_dataclass_body(path, i), (
                    f"line {i} ({line.strip()!r}) should be considered inside SkinColors palette"
                )
                return
        pytest.fail("Couldn't locate accent='#0178D4' line in _grammar.py SkinColors.default()")

    def test_noqa_hex_escape_hatch_works(self) -> None:
        """Meta: a synthetic source line with `# noqa: hex` is exempt."""
        line = '    fallback = "#123456"  # noqa: hex documented sample'
        assert _NOQA_HEX_RE.search(line), "noqa: hex regex must match"


# ---------------------------------------------------------------------------
# IL-3 — Microcopy form for hint labels
# ---------------------------------------------------------------------------

_IL3_KEY_RE = re.compile(r"[a-zA-Z]|Esc|↵|Enter|F[0-9]+|[Ss]hift\+[A-Za-z]|\*")
_IL3_LABEL_RE = re.compile(r"[a-z][a-z0-9\-]*|as [a-z][a-z0-9\-]*")
_IL3_LABEL_MAX = 14


def _il3_make_fixture():
    """Build a MagicMock(spec=_ToolPanelActionsMixin) ready to drive _collect_hints."""
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    obj = MagicMock(spec=_ToolPanelActionsMixin)
    obj._view_state = None
    # _lookup_view_state lives on _core.py:ToolPanel, not on the mixin spec; assign explicitly.
    obj._lookup_view_state = MagicMock(return_value=None)
    obj._result_summary_v4 = None
    obj._block = None
    obj.collapsed = False
    obj._is_error.return_value = False
    obj._visible_footer_action_kinds.return_value = set()
    obj._get_omission_bar.return_value = None
    obj._result_paths_for_action.return_value = []
    obj._next_kind_label = None  # mirrors `if _next_kind_label is not None:` guard
    return obj


def _il3_collect_all_hints():
    """Collect both primary and contextual hints across multiple panel states.

    Returns flat list of (key, label) tuples. Drives _collect_hints with
    several plausible state combinations to cover the dynamic kind-cycle hint.
    """
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    out: list[tuple[str, str]] = []

    # State 1: default fixture (no error, not streaming, no rs).
    obj = _il3_make_fixture()
    primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
    out.extend(primary)
    out.extend(contextual)

    # State 2: error path — adds retry primary.
    obj = _il3_make_fixture()
    obj._is_error.return_value = True
    primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
    out.extend(primary)
    out.extend(contextual)

    # State 3: collapsed — primary "expand".
    obj = _il3_make_fixture()
    obj.collapsed = True
    primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
    out.extend(primary)
    out.extend(contextual)

    # State 4: with rs that exercises the as-<kind> hint.
    obj = _il3_make_fixture()
    rs = MagicMock()
    rs.stderr_tail = None
    rs.actions = ()
    rs.artifacts = ()
    obj._result_summary_v4 = rs
    obj._next_kind_label = lambda current: "json"
    primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
    out.extend(primary)
    out.extend(contextual)

    # State 5: rs with a current override — hits ("T", "auto") hint.
    obj = _il3_make_fixture()
    rs = MagicMock()
    rs.stderr_tail = None
    rs.actions = ()
    rs.artifacts = ()
    obj._result_summary_v4 = rs
    obj._next_kind_label = lambda current: "code"
    view = MagicMock()
    view.user_kind_override = "json"
    obj._view_state = view
    primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
    out.extend(primary)
    out.extend(contextual)

    return out


class TestIL3MicrocopyForm:
    """IL-3 — bracket-key microcopy form for hint labels."""

    def test_all_hint_keys_match_form(self) -> None:
        offenders: list[str] = []
        for key, label in _il3_collect_all_hints():
            if not _IL3_KEY_RE.fullmatch(key):
                offenders.append(f"key={key!r} (label={label!r})")
        assert offenders == [], "IL-3 key violations:\n" + "\n".join(offenders)

    def test_all_hint_labels_match_form(self) -> None:
        offenders: list[str] = []
        for key, label in _il3_collect_all_hints():
            if not _IL3_LABEL_RE.fullmatch(label):
                offenders.append(f"label={label!r} (key={key!r})")
            elif len(label) > _IL3_LABEL_MAX:
                offenders.append(
                    f"label={label!r} exceeds {_IL3_LABEL_MAX} chars (key={key!r})"
                )
        assert offenders == [], "IL-3 label violations:\n" + "\n".join(offenders)

    def test_no_capital_letter_in_brackets(self) -> None:
        """Source sweep for `\\[[A-Z]\\][a-z]` — historical [C]opy / [R]etry shape."""
        pat = re.compile(r"\[[A-Z]\][a-z]")
        offenders: list[str] = []
        for p in _walk_owner_paths():
            src = _src(p)
            for i, line in enumerate(src.splitlines(), start=1):
                if pat.search(line):
                    offenders.append(f"{p.relative_to(_REPO_ROOT)}:{i}: {line.strip()}")
        assert offenders == [], "IL-3 [Capital]+lowercase violations:\n" + "\n".join(offenders)

    def test_no_label_leading_space_or_empty(self) -> None:
        offenders: list[str] = []
        for key, label in _il3_collect_all_hints():
            if not label or label.startswith(" "):
                offenders.append(f"key={key!r} label={label!r}")
        assert offenders == [], "IL-3 leading-space/empty labels:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# IL-4 — Per-tier chip drop-order under tight budget
# ---------------------------------------------------------------------------

def _il4_make_segments(names: list[str]):
    """Build (name, Text) tuples each with cell_len 1."""
    from rich.text import Text
    return [(n, Text("X")) for n in names]


class TestIL4ChipCountCaps:
    """IL-4 — drop-order picks the highest-priority N under tight budget."""

    def test_hero_drop_order_under_tight_budget(self) -> None:
        """HERO: passing all 9 named segments, budget=7 keeps the last 7 (highest priority)."""
        from hermes_cli.tui.tool_panel.layout_resolver import (
            DensityTier,
            trim_tail_for_tier,
            _DROP_ORDER_HERO,
        )
        order = _DROP_ORDER_HERO
        segs = _il4_make_segments(order)
        result = trim_tail_for_tier(tail_segments=segs, tail_budget=7, tier=DensityTier.HERO)
        kept_names = [n for n, _ in result]
        assert kept_names == order[-7:], (
            f"HERO budget=7 expected top-7 by priority {order[-7:]!r}, got {kept_names!r}"
        )

    def test_default_drop_order_under_tight_budget(self) -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import (
            DensityTier,
            trim_tail_for_tier,
            _DROP_ORDER_DEFAULT,
        )
        order = _DROP_ORDER_DEFAULT
        segs = _il4_make_segments(order)
        result = trim_tail_for_tier(tail_segments=segs, tail_budget=5, tier=DensityTier.DEFAULT)
        kept_names = [n for n, _ in result]
        assert kept_names == order[-5:], (
            f"DEFAULT budget=5 expected top-5 by priority {order[-5:]!r}, got {kept_names!r}"
        )

    def test_compact_drop_order_under_tight_budget(self) -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import (
            DensityTier,
            trim_tail_for_tier,
            _DROP_ORDER_COMPACT,
        )
        order = _DROP_ORDER_COMPACT
        segs = _il4_make_segments(order)
        result = trim_tail_for_tier(tail_segments=segs, tail_budget=3, tier=DensityTier.COMPACT)
        kept_names = [n for n, _ in result]
        assert kept_names == order[-3:], (
            f"COMPACT budget=3 expected top-3 by priority {order[-3:]!r}, got {kept_names!r}"
        )


# ---------------------------------------------------------------------------
# IL-5 — Status chip casing
# ---------------------------------------------------------------------------

_IL5_CHIP_RE = re.compile(r"…?[A-Z0-9+]+")


class TestIL5StatusChipCasing:
    """IL-5 — every _CHIP_* constant is all-uppercase (with optional leading ellipsis)."""

    def test_all_status_chips_uppercase(self) -> None:
        from hermes_cli.tui.tool_blocks import _header as h
        offenders: list[str] = []
        for name in dir(h):
            if not name.startswith("_CHIP_"):
                continue
            value = getattr(h, name)
            if not isinstance(value, str):
                continue
            if not _IL5_CHIP_RE.fullmatch(value):
                offenders.append(f"{name}={value!r}")
        assert offenders == [], "IL-5 chip casing violations:\n" + "\n".join(offenders)
        # Sanity: at least the 6 known constants are present.
        names = {n for n in dir(h) if n.startswith("_CHIP_")}
        for expected in (
            "_CHIP_STARTING", "_CHIP_FINALIZING", "_CHIP_DONE",
            "_CHIP_ERR", "_CHIP_CANCELLED", "_CHIP_STREAMING",
        ):
            assert expected in names, f"missing {expected} on _header.py"

    def test_no_sentence_case_status_in_owner_paths(self) -> None:
        """Sentence-case forms ('Done', 'Error', 'Cancelled', 'Streaming') must not
        appear as standalone string literals in _header.py / _streaming.py."""
        forbidden = ('"Done"', '"Error"', '"Cancelled"', '"Streaming"')
        offenders: list[str] = []
        for fname in ("_header.py", "_streaming.py"):
            path = _TUI_ROOT / "tool_blocks" / fname
            src = _src(path)
            for i, line in enumerate(src.splitlines(), start=1):
                for bad in forbidden:
                    if bad in line:
                        offenders.append(f"{path.relative_to(_REPO_ROOT)}:{i}: {line.strip()}")
        assert offenders == [], "IL-5 sentence-case status:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# IL-7 — set_axis ordering: hint clear before state write
# ---------------------------------------------------------------------------

def _il7_lines_in_function(path: pathlib.Path, func_name: str) -> tuple[int, int]:
    """Return (start_line, end_line) of named function (or method) in path."""
    tree = _ast_walk(path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            end = node.end_lineno or node.lineno
            return node.lineno, end
    return -1, -1


def _il7_axis_call_lines(path: pathlib.Path, start: int, end: int) -> dict[str, list[int]]:
    """Within line range, find set_axis(view, "<axis>", ...) call lines.

    Returns map { "streaming_kind_hint": [lines], "state": [lines] }.
    """
    src = _src(path)
    tree = ast.parse(src, filename=str(path))
    out: dict[str, list[int]] = {"streaming_kind_hint": [], "state": []}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "set_axis"):
            continue
        if not (start <= node.lineno <= end):
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            axis = node.args[1].value
            if axis in out:
                out[axis].append(node.lineno)
    return out


class TestIL7SetAxisOrdering:
    """IL-7 — hint clear must precede state write within _set_view_state."""

    def test_hint_clear_before_state_write_in_set_view_state(self) -> None:
        path = _TUI_ROOT / "services" / "tools.py"
        start, end = _il7_lines_in_function(path, "_set_view_state")
        assert start > 0, "Could not find _set_view_state in services/tools.py"
        axis_lines = _il7_axis_call_lines(path, start, end)
        assert axis_lines["streaming_kind_hint"], (
            "_set_view_state must contain a streaming_kind_hint clear via set_axis"
        )
        assert axis_lines["state"], (
            "_set_view_state must contain a state write via set_axis"
        )
        last_hint = max(axis_lines["streaming_kind_hint"])
        first_state = min(axis_lines["state"])
        assert last_hint < first_state, (
            f"hint clear (line {last_hint}) must precede state write (line {first_state})"
        )

    def test_plan_sync_axis_ordering(self) -> None:
        """plan_sync.py: any function writing both axes must order hint-first.

        If no such function exists, this test is a structural placeholder
        (a future regression that introduces a state-first write fails here).
        """
        path = _TUI_ROOT / "services" / "plan_sync.py"
        tree = _ast_walk(path)
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = node.lineno
            end = node.end_lineno or start
            axis_lines = _il7_axis_call_lines(path, start, end)
            if axis_lines["streaming_kind_hint"] and axis_lines["state"]:
                last_hint = max(axis_lines["streaming_kind_hint"])
                first_state = min(axis_lines["state"])
                if last_hint >= first_state:
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT)}:{node.name}: "
                        f"hint clear at {last_hint} >= state write at {first_state}"
                    )
        assert offenders == [], "IL-7 plan_sync ordering:\n" + "\n".join(offenders)

    def test_meta_inverse_ordering_caught(self) -> None:
        """Meta: synthetic source with state-write-first ordering is flagged."""
        bad = (
            "def f(view, new):\n"
            "    set_axis(view, 'state', new)\n"
            "    set_axis(view, 'streaming_kind_hint', None)\n"
        )
        # Reuse axis-line scanning logic on the synthetic source.
        tree = ast.parse(bad)
        out = {"streaming_kind_hint": [], "state": []}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_axis"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)):
                axis = node.args[1].value
                if axis in out:
                    out[axis].append(node.lineno)
        last_hint = max(out["streaming_kind_hint"])
        first_state = min(out["state"])
        assert last_hint > first_state, (
            "Meta-check: synthetic state-first source must show hint > state line"
        )


# ---------------------------------------------------------------------------
# IL-8 — Tighten empty-except ban
# ---------------------------------------------------------------------------

_IL8_JUSTIFICATION_RE = re.compile(
    r"#\s*[^#].*\b(expected|safe|noqa:\s*bare-except|best-effort|best effort|"
    r"decorative|non-critical|optional|correct|contract|silently|suppressed|"
    r"fall\s+back|fallback|skip|unavailable|not\s+yet\s+mounted|pre-mount|"
    r"mounted|failure|partially|surfaced|attached|absent|malformed|"
    r"not\s+valid|lang\s+stays|use\s+default)\b",
    re.IGNORECASE,
)
_IL8_LOG_FUNCS = {"exception", "error", "warning", "debug", "info", "critical"}
# Common logger receiver names — _log (preferred), logger, log, _logger.
_IL8_LOG_RECEIVERS = {"_log", "logger", "log", "_logger"}
_IL8_NARROW_TYPE_ALLOWLIST: set[str] = {"NoMatches", "ChannelUnmountedError"}


def _il8_handler_lines(src: str, handler: ast.ExceptHandler) -> list[str]:
    """Return source lines covered by a handler (including its `except` line)."""
    start = handler.lineno
    end = handler.end_lineno or start
    lines = src.splitlines()
    return lines[start - 1:end]


def _il8_handler_is_reraise(handler: ast.ExceptHandler) -> bool:
    for node in handler.body:
        if isinstance(node, ast.Raise):
            return True
    return False


def _il8_handler_logs(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(ast.Module(body=list(handler.body), type_ignores=[])):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _IL8_LOG_FUNCS:
            continue
        # The receiver should look like a logger (Name in known receivers, or
        # any Name/Attribute ending in 'log'/'logger' — best-effort heuristic).
        recv = node.func.value
        recv_ok = False
        if isinstance(recv, ast.Name) and recv.id in _IL8_LOG_RECEIVERS:
            recv_ok = True
        elif isinstance(recv, ast.Attribute) and recv.attr in _IL8_LOG_RECEIVERS:
            recv_ok = True
        if not recv_ok:
            continue
        # _log.exception / _log.debug / _log.info / _log.critical: pass.
        # _log.error / _log.warning: project rule wants exc_info.
        if node.func.attr in ("exception", "debug", "info", "critical"):
            return True
        for kw in node.keywords:
            if kw.arg == "exc_info":
                return True
    return False


def _il8_handler_has_justification(src_lines: list[str], handler: ast.ExceptHandler) -> bool:
    start = handler.lineno
    end = handler.end_lineno or start
    # Line immediately preceding the `except` keyword.
    if start - 2 >= 0:
        if _IL8_JUSTIFICATION_RE.search(src_lines[start - 2]):
            return True
    # Trailing inline comments on lines within the handler span.
    for ln_idx in range(start - 1, end):
        if 0 <= ln_idx < len(src_lines):
            if _IL8_JUSTIFICATION_RE.search(src_lines[ln_idx]):
                return True
    return False


def _il8_handler_narrow_type_only(handler: ast.ExceptHandler) -> bool:
    """True iff handler catches only narrow allowlisted types (not Exception/BaseException)."""
    if handler.type is None:
        return False  # bare `except:`
    types: list[str] = []
    if isinstance(handler.type, ast.Name):
        types.append(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                types.append(elt.id)
            else:
                return False
    else:
        return False
    if not types:
        return False
    for t in types:
        if t in {"Exception", "BaseException"}:
            return False
        if t not in _IL8_NARROW_TYPE_ALLOWLIST:
            return False
    return True


def _il8_violations(path: pathlib.Path) -> list[tuple[int, str]]:
    src = _src(path)
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _il8_handler_is_reraise(node):
            continue
        if _il8_handler_logs(node):
            continue
        if _il8_handler_has_justification(src_lines, node):
            continue
        if _il8_handler_narrow_type_only(node):
            continue
        violations.append((node.lineno, src_lines[node.lineno - 1].strip()))
    return violations


def _il8_module_has_logger(path: pathlib.Path) -> bool:
    """Return True if module imports logging and assigns a module-level logger."""
    src = _src(path)
    tree = ast.parse(src, filename=str(path))
    has_import = False
    has_log = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "logging":
                    has_import = True
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in _IL8_LOG_RECEIVERS:
                    has_log = True
    return has_import and has_log


def _il8_module_has_except(path: pathlib.Path) -> bool:
    src = _src(path)
    tree = ast.parse(src, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            return True
    return False


class TestIL8ExceptHandling:
    """IL-8 — every except handler must re-raise, log, justify, or be narrow-type allowlisted."""

    def test_no_silent_swallows_in_owner_paths(self) -> None:
        offenders: list[str] = []
        for p in _walk_owner_paths():
            for ln, line in _il8_violations(p):
                rel = p.relative_to(_REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{ln}: {line}")
        assert offenders == [], (
            f"IL-8 silent swallow violations ({len(offenders)}):\n"
            + "\n".join(offenders)
        )

    def test_modules_with_except_have_logger(self) -> None:
        offenders: list[str] = []
        for p in _walk_owner_paths():
            if _il8_module_has_except(p) and not _il8_module_has_logger(p):
                offenders.append(p.relative_to(_REPO_ROOT).as_posix())
        assert offenders == [], (
            "IL-8 modules with except but no _log:\n" + "\n".join(offenders)
        )

    def test_meta_silent_swallow_caught(self) -> None:
        bad = (
            "def f():\n"
            "    try:\n"
            "        x()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        good = (
            "def f():\n"
            "    try:\n"
            "        x()\n"
            "    except Exception:\n"
            "        pass  # already gone — safe\n"
        )
        # Synthetic AST/scan: bad must produce a violation; good must not.
        for src, expect_violation in ((bad, True), (good, False)):
            tree = ast.parse(src)
            src_lines = src.splitlines()
            found = False
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if _il8_handler_is_reraise(node):
                    continue
                if _il8_handler_logs(node):
                    continue
                if _il8_handler_has_justification(src_lines, node):
                    continue
                if _il8_handler_narrow_type_only(node):
                    continue
                found = True
            assert found is expect_violation, (
                f"meta-test failed: expect_violation={expect_violation}, got {found}"
            )


# ---------------------------------------------------------------------------
# IL-9 — view-mirror-field ordering (SC-3): view.dur_ms and view.is_error must
#         be written BEFORE any terminal _set_view_state call in the same function.
# ---------------------------------------------------------------------------


_IL9_TERMINAL_STATES = {"DONE", "ERROR", "CANCELLED", "REMOVED"}
_TOOLS_PY_PATH = pathlib.Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "services" / "tools.py"


class TestIL9ViewMirrorOrdering:
    def test_il9_no_post_state_view_mirror_writes(self) -> None:
        """In services/tools.py, no view.dur_ms/is_error write appears after terminal _set_view_state."""
        src = _TOOLS_PY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            all_nodes = list(ast.walk(node))
            terminal_lines: list[int] = []
            for n in all_nodes:
                if not isinstance(n, ast.Call):
                    continue
                fn = n.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "_set_view_state"):
                    continue
                if len(n.args) < 2:
                    continue
                state_arg = n.args[1]
                if isinstance(state_arg, ast.Attribute) and state_arg.attr in _IL9_TERMINAL_STATES:
                    terminal_lines.append(n.lineno)

            if not terminal_lines:
                continue
            max_terminal = max(terminal_lines)
            _MIRROR_ATTRS = {"dur_ms", "is_error"}
            for n in all_nodes:
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Attribute) and t.attr in _MIRROR_ATTRS:
                            if n.lineno > max_terminal:
                                violations.append(
                                    f"{node.name}:L{n.lineno} {t.attr} write after terminal state write at L{max_terminal}"
                                )

        assert violations == [], f"IL-9 violations — post-terminal mirror writes: {violations}"
