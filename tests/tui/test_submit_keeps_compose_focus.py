"""
W-17: Submit-keeps-compose-focus regression tests (AT-R3/R4, H-T4).

Structural checks verifying that tool block append, echo, and submit paths
do not call .focus() in mount handlers — a lighter-weight proxy for the
runtime focus invariant.

Spec: /home/xush/.hermes/2026-04-28-focus-nav-spec-h.md (W-17)
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TUI_ROOT = pathlib.Path(__file__).parent.parent.parent / "hermes_cli" / "tui"

_APPEND_RE = re.compile(r"^_append_.+$")
_MOUNT_RE = re.compile(r"^(on_mount|_on_mount)$")


def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _ast_of(path: pathlib.Path) -> ast.Module:
    return ast.parse(_src(path), filename=str(path))


def _functions_in(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _calls_in(body: list[ast.stmt]) -> list[ast.Call]:
    result: list[ast.Call] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                result.append(node)
    return result


def _py_files_under(*dirs: pathlib.Path) -> list[pathlib.Path]:
    result: list[pathlib.Path] = []
    for d in dirs:
        for p in d.rglob("*.py"):
            if "__pycache__" not in p.parts:
                result.append(p)
    return result


# ---------------------------------------------------------------------------
# Test 1: echo_user_message in app.py must not call .focus()
# ---------------------------------------------------------------------------


def test_no_focus_call_in_echo_user_message() -> None:
    """echo_user_message (app.py) must not call .focus() on any widget.

    AT-R3: the echo path appends a UserMessagePanel to OutputPanel; stealing
    focus here would break compose-stays-focused on submit.
    """
    app_path = _TUI_ROOT / "app.py"
    try:
        tree = _ast_of(app_path)
    except SyntaxError as e:
        pytest.fail(f"Could not parse app.py: {e}")

    echo_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for func in _functions_in(tree):
        if func.name == "echo_user_message":
            echo_func = func
            break

    assert echo_func is not None, "echo_user_message not found in app.py"

    violations: list[int] = []
    for call in _calls_in(echo_func.body):
        callee = call.func
        if isinstance(callee, ast.Attribute) and callee.attr == "focus":
            violations.append(call.lineno)

    assert violations == [], (
        f"AT-R3: echo_user_message calls .focus() at lines {violations} in app.py — "
        "this steals focus from compose on submit"
    )


# ---------------------------------------------------------------------------
# Test 2: _append_* functions in tool_blocks/ and tool_panel/ must not call .focus()
# ---------------------------------------------------------------------------


def test_no_focus_call_in_tool_block_append() -> None:
    """_append_* handlers in tool_blocks/ and tool_panel/ must not call .focus().

    AT-R4: appending a new tool block during a streaming turn must not move
    keyboard focus away from the compose zone.
    """
    search_dirs = [
        _TUI_ROOT / "tool_blocks",
        _TUI_ROOT / "tool_panel",
    ]

    violations: list[tuple[str, int, str]] = []

    for path in _py_files_under(*search_dirs):
        rel = str(path.relative_to(_TUI_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _APPEND_RE.match(func.name):
                continue
            for call in _calls_in(func.body):
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr == "focus":
                    violations.append((rel, call.lineno, func.name))

    assert violations == [], (
        f"AT-R4: {len(violations)} .focus() call(s) in _append_* handlers:\n"
        + "\n".join(
            f"  {rel}:{ln}: in {fn_name}()" for rel, ln, fn_name in violations
        )
    )


# ---------------------------------------------------------------------------
# Test 3: on_mount handlers in tool_blocks/ and tool_panel/ must not call .focus()
# ---------------------------------------------------------------------------


def test_no_focus_call_in_on_mount_handlers() -> None:
    """on_mount and _on_mount handlers in tool_blocks/ and tool_panel/ must not call .focus().

    AT-R3/R4: mounting a tool block widget must not steal focus. The compose
    zone owns focus throughout streaming.
    """
    search_dirs = [
        _TUI_ROOT / "tool_blocks",
        _TUI_ROOT / "tool_panel",
    ]

    violations: list[tuple[str, int, str]] = []

    for path in _py_files_under(*search_dirs):
        rel = str(path.relative_to(_TUI_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _MOUNT_RE.match(func.name):
                continue
            for call in _calls_in(func.body):
                callee = call.func
                if isinstance(callee, ast.Attribute) and callee.attr == "focus":
                    violations.append((rel, call.lineno, func.name))

    assert violations == [], (
        f"AT-R3/R4: {len(violations)} .focus() call(s) in on_mount handlers:\n"
        + "\n".join(
            f"  {rel}:{ln}: in {fn_name}()" for rel, ln, fn_name in violations
        )
    )


# ---------------------------------------------------------------------------
# Test 4: _append_* handlers must not call set_focus() or .focus() at all
# ---------------------------------------------------------------------------


def test_tool_block_focus_restore_not_overwritten() -> None:
    """_append_* handlers must not call .focus() or set_focus() on anything.

    This is a negative check — append paths should be focus-neutral. Any
    focus() or set_focus() call in an append handler is a violation of the
    AT-R4 contract that says compose focus is never overwritten by tool block
    DOM mutations.
    """
    search_dirs = [
        _TUI_ROOT / "tool_blocks",
        _TUI_ROOT / "tool_panel",
    ]

    _FOCUS_CALL_NAMES = frozenset({"focus", "set_focus"})
    violations: list[tuple[str, int, str, str]] = []

    for path in _py_files_under(*search_dirs):
        rel = str(path.relative_to(_TUI_ROOT))
        try:
            tree = _ast_of(path)
        except SyntaxError:
            continue

        for func in _functions_in(tree):
            if not _APPEND_RE.match(func.name):
                continue
            for call in _calls_in(func.body):
                callee = call.func
                call_name: str | None = None
                if isinstance(callee, ast.Attribute):
                    call_name = callee.attr
                elif isinstance(callee, ast.Name):
                    call_name = callee.id
                if call_name in _FOCUS_CALL_NAMES:
                    violations.append((rel, call.lineno, func.name, call_name))

    assert violations == [], (
        f"AT-R4: {len(violations)} focus-stealing call(s) in _append_* handlers:\n"
        + "\n".join(
            f"  {rel}:{ln}: {call_name}() in {fn_name}()"
            for rel, ln, fn_name, call_name in violations
        )
    )
