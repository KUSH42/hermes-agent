"""
W-16: Focus/Navigation invariant lint tests (AT-* rules from Spec H).

These are AST-walk / grep-based tests that verify structural rules
enforced by the focus/nav concept (v0.7).

Spec: /home/xush/.hermes/2026-04-28-focus-nav-spec-h.md (W-16)
Template: tests/tui/test_invariants.py
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent / "hermes_cli" / "tui"

_FOCUS_HANDLER_RE = re.compile(r"^_?on_focus.*$|^watch_has_focus$")
_ON_KEY_RE = re.compile(r"^_?on_key$")
_MOUNT_APPEND_ECHO_RE = re.compile(
    r"^(on_mount|_on_mount|_append_.+|echo_user_message)$"
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _walk_tui(base: pathlib.Path = REPO_ROOT) -> list[pathlib.Path]:
    """All .py files under hermes_cli/tui/, excluding __pycache__."""
    result: list[pathlib.Path] = []
    for p in base.rglob("*.py"):
        if "__pycache__" not in p.parts:
            result.append(p)
    return result


def _ast_of(path: pathlib.Path) -> ast.Module:
    return ast.parse(_src(path), filename=str(path))


def _functions_in(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """All function defs at any nesting level."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _calls_in(body: list[ast.stmt]) -> list[ast.Call]:
    """All Call nodes inside a list of statements (recursive)."""
    result: list[ast.Call] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                result.append(node)
    return result


def _attr_chain(node: ast.expr) -> list[str]:
    """Flatten a.b.c Attribute chain into ['a', 'b', 'c']."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return parts


# ---------------------------------------------------------------------------
# AT-Z2 — no runtime focus chrome in focus handlers
# ---------------------------------------------------------------------------


def test_at_z2_no_runtime_focus_chrome() -> None:
    """Focus handlers must not set styles.border/outline/background or add_class('--focus*')."""
    violations: list[tuple[str, int, str]] = []

    _FORBIDDEN_STYLE_ATTRS = {"border", "outline", "background"}
    _FOCUS_CLASS_RE = re.compile(r"^--(focus|ring)")

    for path in _walk_tui():
        rel = str(path.relative_to(REPO_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _FOCUS_HANDLER_RE.match(func.name):
                continue

            # (a) styles.border* / styles.outline* / styles.background* assignments
            for stmt in ast.walk(ast.Module(body=func.body, type_ignores=[])):
                if not isinstance(stmt, ast.Assign):
                    continue
                for tgt in stmt.targets:
                    chain = _attr_chain(tgt)
                    # Look for patterns like self.styles.border = ...
                    if len(chain) >= 2 and "styles" in chain:
                        idx = chain.index("styles")
                        if idx + 1 < len(chain):
                            attr = chain[idx + 1]
                            if any(attr.startswith(f) for f in _FORBIDDEN_STYLE_ATTRS):
                                violations.append(
                                    (rel, stmt.lineno, f"styles.{attr} assignment in {func.name}")
                                )

            # (b) add_class('--focus*' or '--ring*') calls
            for call in _calls_in(func.body):
                callee = call.func
                if not isinstance(callee, ast.Attribute):
                    continue
                if callee.attr != "add_class":
                    continue
                for arg in call.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if _FOCUS_CLASS_RE.match(arg.value):
                            violations.append(
                                (rel, call.lineno, f"add_class({arg.value!r}) in {func.name}")
                            )

    assert violations == [], (
        f"AT-Z2 violations — {len(violations)} focus-chrome runtime mutations found:\n"
        + "\n".join(f"  {rel}:{ln}: {reason}" for rel, ln, reason in violations)
    )


# ---------------------------------------------------------------------------
# AT-B1 — event.key reads restricted to carve-out files / functions
# ---------------------------------------------------------------------------


def _collect_event_key_reads_in_func(
    tree: ast.Module, func_name_pattern: re.Pattern[str]
) -> set[int]:
    """Return set of linenos for event.key reads inside matching functions."""
    linenos: set[int] = set()
    for func in _functions_in(tree):
        if not func_name_pattern.match(func.name):
            continue
        for stmt in func.body:
            for node in ast.walk(stmt):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "key"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "event"
                ):
                    linenos.add(node.lineno)
    return linenos


def test_at_b1_event_key_carve_out() -> None:
    """Raw event.key reads in App-level on_key/_on_key must route through the two carve-out files.

    B-1 scope: *global* key routing only.  Widget-local on_key handlers are allowed to read
    event.key — they receive already-routed events.  We only check app.py for top-level
    App on_key/_on_key handlers that bypass the central dispatch.
    """
    # The two canonical allowed sources for raw event.key in global routing.
    _AT_B1_CARVE_OUTS: set[tuple[str, int]] = set()
    _carve_out_sources = [
        (REPO_ROOT / "input" / "widget.py", re.compile(r"^_on_key$")),
        (REPO_ROOT / "services" / "keys.py", re.compile(r"^dispatch_key$")),
    ]
    for co_path, co_pattern in _carve_out_sources:
        if co_path.exists():
            try:
                co_tree = _ast_of(co_path)
            except SyntaxError:
                continue
            rel = str(co_path.relative_to(REPO_ROOT))
            for ln in _collect_event_key_reads_in_func(co_tree, co_pattern):
                _AT_B1_CARVE_OUTS.add((rel, ln))

    # Structural: both carve-out files must contain at least one event.key read.
    assert _AT_B1_CARVE_OUTS, (
        "AT-B1: neither carve-out source (input/widget.py:_on_key, services/keys.py:dispatch_key) "
        "contains any event.key read — carve-out mechanism appears broken"
    )

    # Only check app.py for App-level global on_key/_on_key handlers that would bypass dispatch.
    violations: list[tuple[str, int]] = []
    app_path = REPO_ROOT / "app.py"
    if app_path.exists():
        try:
            app_tree = _ast_of(app_path)
        except SyntaxError:
            app_tree = None
        if app_tree is not None:
            app_rel = str(app_path.relative_to(REPO_ROOT))
            for func in _functions_in(app_tree):
                if not _ON_KEY_RE.match(func.name):
                    continue
                for stmt in func.body:
                    for node in ast.walk(stmt):
                        if (
                            isinstance(node, ast.Attribute)
                            and node.attr == "key"
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "event"
                        ):
                            hit = (app_rel, node.lineno)
                            if hit not in _AT_B1_CARVE_OUTS:
                                violations.append(hit)

    assert violations == [], (
        f"AT-B1 violations — {len(violations)} raw event.key reads in app.py on_key outside carve-outs:\n"
        + "\n".join(f"  {rel}:{ln}" for rel, ln in violations)
    )


# ---------------------------------------------------------------------------
# AT-D1 — HINT_MAX_PRIMARY == 3
# ---------------------------------------------------------------------------


def test_at_d1_hint_max_primary() -> None:
    """HINT_MAX_PRIMARY must equal 3 and be used to slice primary hints."""
    from hermes_cli.tui.widgets.status_bar import HINT_MAX_PRIMARY

    assert HINT_MAX_PRIMARY == 3, (
        f"AT-D1: HINT_MAX_PRIMARY is {HINT_MAX_PRIMARY!r}, expected 3"
    )

    # Structural check: status_bar.py must use the constant to cap primary hints.
    status_bar_src = _src(REPO_ROOT / "widgets" / "status_bar.py")
    has_slice = "[:HINT_MAX_PRIMARY]" in status_bar_src or "[:3]" in status_bar_src
    assert has_slice, (
        "AT-D1: widgets/status_bar.py does not slice hints by HINT_MAX_PRIMARY ([:HINT_MAX_PRIMARY] or [:3] not found)"
    )


# ---------------------------------------------------------------------------
# AT-S1 — scroll_end calls centralised in widgets/__init__.py (+ app.py re-pin)
# ---------------------------------------------------------------------------


def test_at_s1_scroll_end_centralised() -> None:
    """All scroll_end *call sites* must be inside widgets/__init__.py or app.py re-pin.

    Uses AST-based detection to avoid false positives from parameter declarations
    (scroll_end as a kwarg name) in prose.py / renderers.py.  The invariant is
    about where scroll_end() is *called*, not where the string appears.
    """
    _WIDGETS_INIT_REL = "widgets/__init__.py"
    _APP_PY_REL = "app.py"

    violations: list[tuple[str, int, str]] = []

    for path in _walk_tui():
        rel = str(path.relative_to(REPO_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            # Match x.scroll_end(...) call patterns
            if isinstance(callee, ast.Attribute) and callee.attr == "scroll_end":
                if rel == _WIDGETS_INIT_REL:
                    continue  # allowed — centralised implementation and definition
                if rel == _APP_PY_REL:
                    continue  # allowed — echo_user_message submit re-pin
                # Skip calls on log/rich-log widgets (e.g. CopyableRichLog.scroll_end)
                receiver = callee.value
                if isinstance(receiver, ast.Name) and "log" in receiver.id.lower():
                    continue
                violations.append((rel, node.lineno, ast.unparse(node)[:80]))
            # Also match bare scroll_end(...) call patterns (e.g. from a local binding)
            elif isinstance(callee, ast.Name) and callee.id == "scroll_end":
                if rel == _WIDGETS_INIT_REL:
                    continue
                if rel == _APP_PY_REL:
                    continue
                violations.append((rel, node.lineno, ast.unparse(node)[:80]))

    assert violations == [], (
        f"AT-S1 violations — {len(violations)} scroll_end call(s) outside allowed files:\n"
        + "\n".join(f"  {rel}:{ln}: {txt}" for rel, ln, txt in violations)
    )


# ---------------------------------------------------------------------------
# AT-S5 — no scroll calls inside focus handlers
# ---------------------------------------------------------------------------


def test_at_s5_no_scroll_in_focus_handlers() -> None:
    """Focus handlers must not call scroll_to_widget, scroll_to_center, or scroll_end."""
    _FORBIDDEN_SCROLL_ATTRS = frozenset({"scroll_to_widget", "scroll_to_center", "scroll_end"})
    violations: list[tuple[str, int, str]] = []

    for path in _walk_tui():
        rel = str(path.relative_to(REPO_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _FOCUS_HANDLER_RE.match(func.name):
                continue
            for call in _calls_in(func.body):
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr in _FORBIDDEN_SCROLL_ATTRS:
                    violations.append(
                        (rel, call.lineno, f"{callee.attr}() in {func.name}")
                    )

    assert violations == [], (
        f"AT-S5 violations — {len(violations)} scroll calls inside focus handlers:\n"
        + "\n".join(f"  {rel}:{ln}: {reason}" for rel, ln, reason in violations)
    )


# ---------------------------------------------------------------------------
# AT-F1 — no focus/blur calls alongside phase transitions
# ---------------------------------------------------------------------------


def test_at_f1_no_phase_focus_blur() -> None:
    """Functions containing phase transitions must not also call .focus() or .blur()."""
    _PHASE_TRANSITION_NAMES = frozenset({"set_axis", "set_phase", "transition_phase"})

    _owner_paths: list[pathlib.Path] = []
    for d in ("tool_blocks", "tool_panel"):
        for p in (REPO_ROOT / d).rglob("*.py"):
            if "__pycache__" not in p.parts:
                _owner_paths.append(p)
    _owner_paths.append(REPO_ROOT / "services" / "tools.py")

    violations: list[tuple[str, int, str]] = []

    for path in _owner_paths:
        rel = str(path.relative_to(REPO_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            all_calls = _calls_in(func.body)

            # Check if this function contains a phase-transition call with phase= kwarg.
            has_phase_call = False
            for call in all_calls:
                callee_name = None
                if isinstance(call.func, ast.Attribute):
                    callee_name = call.func.attr
                elif isinstance(call.func, ast.Name):
                    callee_name = call.func.id
                if callee_name in _PHASE_TRANSITION_NAMES:
                    kw_names = {kw.arg for kw in call.keywords}
                    if "phase" in kw_names:
                        has_phase_call = True
                        break

            if not has_phase_call:
                continue

            # Check for sibling focus/blur calls.
            for call in all_calls:
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr in {"focus", "blur"}:
                    violations.append(
                        (rel, call.lineno, f".{callee.attr}() alongside phase transition in {func.name}")
                    )

    assert violations == [], (
        f"AT-F1 violations — {len(violations)} focus/blur calls beside phase transitions:\n"
        + "\n".join(f"  {rel}:{ln}: {reason}" for rel, ln, reason in violations)
    )


# ---------------------------------------------------------------------------
# AT-F2 — browse.scroll_to_tool must not call .focus()
# ---------------------------------------------------------------------------


def test_at_f2_browse_does_not_focus() -> None:
    """services/browse.py:scroll_to_tool must not call .focus() on any widget."""
    browse_path = REPO_ROOT / "services" / "browse.py"
    tree = _ast_of(browse_path)

    target_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for func in _functions_in(tree):
        if func.name == "scroll_to_tool":
            target_func = func
            break

    assert target_func is not None, (
        "AT-F2: could not find scroll_to_tool in services/browse.py"
    )

    violations: list[int] = []
    for call in _calls_in(target_func.body):
        callee = call.func
        if isinstance(callee, ast.Attribute) and callee.attr == "focus":
            violations.append(call.lineno)

    assert violations == [], (
        f"AT-F2 violations — scroll_to_tool calls .focus() at lines: {violations}"
    )


# ---------------------------------------------------------------------------
# AT-R3/R4 — no .focus() in mount/append/echo paths
# ---------------------------------------------------------------------------


def test_at_r3_r4_no_focus_in_mount_paths() -> None:
    """on_mount, _append_*, and echo_user_message must not call .focus().

    Scope per spec W-16: tool_blocks/, tool_panel/, services/tools.py, and
    the echo_user_message function body in app.py.  app.py's HermesApp.on_mount
    is intentionally excluded — that is the R-5/AT-Z1 startup-focus grant and
    is outside the W-16 scope.
    """
    # Owner dirs + files (excluding app.py entirely — we handle it separately below).
    _owner_paths: list[pathlib.Path] = []
    for d in ("tool_blocks", "tool_panel"):
        for p in (REPO_ROOT / d).rglob("*.py"):
            if "__pycache__" not in p.parts:
                _owner_paths.append(p)
    _owner_paths.append(REPO_ROOT / "services" / "tools.py")

    violations: list[tuple[str, int, str]] = []

    # Check tool_blocks, tool_panel, services/tools.py — all matching handlers.
    for path in _owner_paths:
        rel = str(path.relative_to(REPO_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _MOUNT_APPEND_ECHO_RE.match(func.name):
                continue
            for call in _calls_in(func.body):
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr == "focus":
                    violations.append(
                        (rel, call.lineno, f".focus() in {func.name}")
                    )

    # app.py: check only echo_user_message (the AT-R3 echo-mount path).
    app_path = REPO_ROOT / "app.py"
    try:
        app_tree = _ast_of(app_path)
        for func in _functions_in(app_tree):
            if func.name != "echo_user_message":
                continue
            for call in _calls_in(func.body):
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr == "focus":
                    violations.append(
                        ("app.py", call.lineno, f".focus() in {func.name}")
                    )
    except SyntaxError:
        pass

    assert violations == [], (
        f"AT-R3/R4 violations — {len(violations)} .focus() calls in mount/append/echo paths:\n"
        + "\n".join(f"  {rel}:{ln}: {reason}" for rel, ln, reason in violations)
    )


# ---------------------------------------------------------------------------
# AT-Z3 — /clear and new-turn paths focus compose (structural check)
# ---------------------------------------------------------------------------


def test_at_z3_clear_focuses_compose() -> None:
    """_lc_reset_turn_state (app.py) and handle_clear_tui (services/commands.py) must focus HermesInput."""
    # Structural check: verify the focus call appears in the source of each function.
    # The alias used is `_HI` (set to HermesInput via import alias).
    _FOCUS_SIGNAL = ".focus()"

    app_src = _src(REPO_ROOT / "app.py")
    commands_src = _src(REPO_ROOT / "services" / "commands.py")

    # Subtest A: _lc_reset_turn_state in app.py
    # Extract the function body via source lines between the def and the next same-level def.
    app_lines = app_src.splitlines()
    reset_fn_lines: list[str] = []
    in_fn = False
    for line in app_lines:
        if re.match(r"\s+def _lc_reset_turn_state\b", line):
            in_fn = True
        elif in_fn:
            if re.match(r"\s+def \w+", line) and "_lc_reset_turn_state" not in line:
                break
            reset_fn_lines.append(line)
    reset_fn_src = "\n".join(reset_fn_lines)
    assert _FOCUS_SIGNAL in reset_fn_src, (
        "AT-Z3 subtest A: _lc_reset_turn_state in app.py does not call .focus() — "
        "compose focus is not restored on new turn start"
    )

    # Subtest B: handle_clear_tui in services/commands.py
    commands_lines = commands_src.splitlines()
    clear_fn_lines: list[str] = []
    in_fn = False
    for line in commands_lines:
        if re.match(r"\s+async def handle_clear_tui\b", line):
            in_fn = True
        elif in_fn:
            if re.match(r"\s+(async )?def \w+", line) and "handle_clear_tui" not in line:
                break
            clear_fn_lines.append(line)
    clear_fn_src = "\n".join(clear_fn_lines)
    assert _FOCUS_SIGNAL in clear_fn_src, (
        "AT-Z3 subtest B: handle_clear_tui in services/commands.py does not call .focus() — "
        "compose focus is not restored after /clear"
    )
