"""Tests for KB-LP-H1/H2/M1/L1 — keyboard layout parity (QWERTY ⇄ QWERTZ)."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re

import pytest
from textual.binding import Binding

import hermes_cli.tui  # noqa: F401 – ensure package importable


def _get_app_bindings() -> list[Binding]:
    from hermes_cli.tui.app import HermesApp

    return list(HermesApp.BINDINGS)


# ---------------------------------------------------------------------------
# KB-LP-H1 — primary layout-agnostic bindings present
# ---------------------------------------------------------------------------


class TestKbLpH1NewPrimaryBindings:
    def _bindings_map(self) -> dict[str, str]:
        """Return {key: action} for all HermesApp BINDINGS."""
        return {b.key: b.action for b in _get_app_bindings()}

    def test_alt_comma_binding_present(self):
        bmap = self._bindings_map()
        assert "alt+comma" in bmap, "alt+comma binding missing"
        assert bmap["alt+comma"] == "collapse_left_pane"

    def test_alt_fullstop_binding_present(self):
        bmap = self._bindings_map()
        assert "alt+full_stop" in bmap, "alt+full_stop binding missing"
        assert bmap["alt+full_stop"] == "collapse_right_pane"

    def test_alt_m_binding_present(self):
        bmap = self._bindings_map()
        assert "alt+m" in bmap, "alt+m binding missing"
        assert bmap["alt+m"] == "toggle_center_split"

    def test_legacy_bracket_bindings_still_present(self):
        pairs = {(b.key, b.action) for b in _get_app_bindings()}
        legacy = [
            ("ctrl+left_square_bracket", "collapse_left_pane"),
            ("ctrl+right_square_bracket", "collapse_right_pane"),
            ("alt+left_square_bracket", "collapse_left_pane"),
            ("alt+right_square_bracket", "collapse_right_pane"),
            ("ctrl+backslash", "toggle_center_split"),
        ]
        missing = [(k, a) for k, a in legacy if (k, a) not in pairs]
        assert missing == [], f"Legacy compat bindings missing: {missing}"

    def test_no_alt_gr_only_chars_in_primary_bindings(self):
        forbidden_pat = re.compile(
            r"(left_square_bracket|right_square_bracket|backslash"
            r"|left_curly_bracket|right_curly_bracket|vertical_line"
            r"|at_sign|tilde|circumflex_accent)"
        )
        primaries = ["alt+comma", "alt+full_stop", "alt+m"]
        bmap = {b.key: b.action for b in _get_app_bindings()}
        for key in primaries:
            assert key in bmap, f"Primary binding {key!r} not in BINDINGS"
            assert not forbidden_pat.search(key), (
                f"Primary binding {key!r} contains AltGr-only key fragment"
            )


# ---------------------------------------------------------------------------
# KB-LP-H2 — KeymapOverlay shows new primaries; no bracket strings displayed
# ---------------------------------------------------------------------------


class TestKbLpH2KeymapOverlayShowsPrimaries:
    def _wide_sections(self):
        from hermes_cli.tui.widgets.overlays import _KM_SECTIONS_WIDE

        return _KM_SECTIONS_WIDE

    def test_km_sections_wide_pane_row_uses_alt_comma_period(self):
        sections = self._wide_sections()
        row = next(
            r
            for _, rows in sections
            for r in rows
            if r[0] == "Collapse left / right pane"
        )
        assert row == ("Collapse left / right pane", "Alt+,", "Alt+."), (
            f"Unexpected row: {row}"
        )

    def test_km_sections_wide_split_row_uses_alt_m(self):
        sections = self._wide_sections()
        row = next(
            r
            for _, rows in sections
            for r in rows
            if r[0] == "Toggle center split"
        )
        assert row == ("Toggle center split", "Alt+M"), f"Unexpected row: {row}"

    def test_km_sections_no_bracket_strings_in_displayed_keys(self):
        from hermes_cli.tui.widgets.overlays import _KM_SECTIONS_WIDE

        all_display_strings: list[str] = []
        for _section_title, rows in _KM_SECTIONS_WIDE:
            for row in rows:
                # row[0] is the label; row[1:] are key display strings
                all_display_strings.extend(row[1:])

        violations = [s for s in all_display_strings if re.search(r"[\[\]\\]", s)]
        assert violations == [], (
            f"Bracket/backslash found in displayed key strings: {violations}"
        )


# ---------------------------------------------------------------------------
# KB-LP-M1 — IL-KB-1 invariant gate
# ---------------------------------------------------------------------------

_FORBIDDEN_NAMED = frozenset(
    {
        "left_square_bracket",
        "right_square_bracket",
        "backslash",
        "left_curly_bracket",
        "right_curly_bracket",
        "vertical_line",
        "at_sign",
        "tilde",
        "circumflex_accent",
    }
)
_FORBIDDEN_LITERAL = frozenset("[]\\{}|@~^")

_SAFE_BASE_KEYS = frozenset(
    [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [str(d) for d in range(10)]
    + [f"f{n}" for n in range(1, 13)]
    + [
        "escape",
        "enter",
        "tab",
        "space",
        "up",
        "down",
        "left",
        "right",
        "page_up",
        "page_down",
        "home",
        "end",
        "comma",
        "full_stop",
        "semicolon",
        "apostrophe",
        "minus",
        "slash",
        "delete",
        "backspace",
    ]
)


def _discover_tui_classes() -> list[type]:
    import hermes_cli.tui as tui_pkg

    classes: list[type] = []
    for _finder, modname, _ispkg in pkgutil.walk_packages(
        tui_pkg.__path__, prefix=tui_pkg.__name__ + "."
    ):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if hasattr(obj, "BINDINGS") and obj not in classes:
                classes.append(obj)
    return classes


def _normalize_binding(b: object) -> tuple[str, str]:
    """Return (key, action) regardless of whether b is a Binding or a tuple."""
    if isinstance(b, Binding):
        return b.key, b.action
    # Textual also accepts (key,), (key, action), (key, action, description)
    t = tuple(b)  # type: ignore[arg-type]
    key = t[0] if len(t) >= 1 else ""
    action = t[1] if len(t) >= 2 else ""
    return str(key), str(action)


def _collect_il_kb1_violations(
    extra_classes: list[type] | None = None,
) -> list[tuple[type, str, str]]:
    classes = _discover_tui_classes()
    if extra_classes:
        classes.extend(extra_classes)

    violations: list[tuple[type, str, str]] = []
    for cls in classes:
        bindings = getattr(cls, "BINDINGS", [])
        action_to_safe: dict[str, list[str]] = {}
        action_to_forbidden: dict[str, list[str]] = {}
        for raw_b in bindings:
            b_key, b_action = _normalize_binding(raw_b)
            key_base = b_key.split("+")[-1]
            is_forbidden = (
                key_base in _FORBIDDEN_NAMED or key_base in _FORBIDDEN_LITERAL
            )
            if is_forbidden:
                action_to_forbidden.setdefault(b_action, []).append(b_key)
            else:
                action_to_safe.setdefault(b_action, []).append(b_key)

        for action, fkeys in action_to_forbidden.items():
            if action not in action_to_safe:
                for fk in fkeys:
                    violations.append((cls, fk, action))
    return violations


class TestIlKb1NoAltGrOnlyInBindings:
    def test_il_kb1_passes_after_h1(self):
        """Gate green: every forbidden key in BINDINGS has a safe alias."""
        violations = _collect_il_kb1_violations()
        assert violations == [], (
            f"IL-KB-1: {len(violations)} AltGr-only binding(s) with no layout-safe "
            f"alias: {violations}"
        )

    def test_il_kb1_fails_when_lonely_bracket_binding_added(self):
        """Gate red when a class adds ctrl+[ with no safe alias."""

        class _FakeClass:
            BINDINGS = [
                Binding("ctrl+left_square_bracket", "some_action", show=False)
            ]

        violations = _collect_il_kb1_violations(extra_classes=[_FakeClass])
        assert any(
            cls is _FakeClass and key == "ctrl+left_square_bracket"
            for cls, key, _action in violations
        ), f"Expected violation not found; got: {violations}"

    def test_il_kb1_layout_safe_set_covers_known_letters_digits(self):
        """Sanity: safe set contains a-z, 0-9, comma, full_stop, f-keys, nav keys."""
        for c in "abcdefghijklmnopqrstuvwxyz":
            assert c in _SAFE_BASE_KEYS, f"{c!r} missing from safe set"
        for d in range(10):
            assert str(d) in _SAFE_BASE_KEYS, f"{d!r} missing from safe set"
        for key in ("comma", "full_stop", "slash", "semicolon", "apostrophe", "minus"):
            assert key in _SAFE_BASE_KEYS, f"{key!r} missing from safe set"
        for n in range(1, 13):
            assert f"f{n}" in _SAFE_BASE_KEYS, f"f{n!r} missing from safe set"
        for nav in ("up", "down", "left", "right", "page_up", "page_down", "home", "end"):
            assert nav in _SAFE_BASE_KEYS, f"{nav!r} missing from safe set"


# ---------------------------------------------------------------------------
# KB-LP-L1 — Alt+digit pane-focus aliases
# ---------------------------------------------------------------------------


class TestKbLpL1AltDigitAliases:
    def _bmap(self) -> dict[str, str]:
        return {b.key: b.action for b in _get_app_bindings()}

    def test_alt_digit_aliases_present(self):
        bmap = self._bmap()
        for key in ("alt+1", "alt+2", "alt+3"):
            assert key in bmap, f"{key!r} binding missing"

    def test_alt_digit_aliases_share_actions_with_function_keys(self):
        bmap = self._bmap()
        assert bmap.get("alt+1") == bmap.get("f5"), "alt+1 action != f5 action"
        assert bmap.get("alt+2") == bmap.get("f6"), "alt+2 action != f6 action"
        assert bmap.get("alt+3") == bmap.get("f7"), "alt+3 action != f7 action"

    def test_alt_digits_have_no_modifier_clash(self):
        bindings = _get_app_bindings()
        for key in ("alt+1", "alt+2", "alt+3"):
            count = sum(1 for b in bindings if b.key == key)
            assert count == 1, f"{key!r} appears {count} times (expected 1)"
