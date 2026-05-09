"""MDTYPE spec tests — bullet em-dash normalisation, nested indent, placeholder contrast."""

import re

from agent.rich_output import apply_block_line


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _wcag_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG 2.1 §1.4.3 contrast ratio. Inputs are 6-char hex strings (with or without '#')."""
    def lum(hex6: str) -> float:
        rgb = [int(hex6[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        rgb_lin = [
            (c / 12.92) if c <= 0.03928 else (((c + 0.055) / 1.055) ** 2.4)
            for c in rgb
        ]
        return 0.2126 * rgb_lin[0] + 0.7152 * rgb_lin[1] + 0.0722 * rgb_lin[2]
    fg = lum(fg_hex.lstrip("#"))
    bg = lum(bg_hex.lstrip("#"))
    L1, L2 = max(fg, bg), min(fg, bg)
    return (L1 + 0.05) / (L2 + 0.05)


class TestBulletSeparator:
    def test_dash_title_rewritten_to_colon(self):
        out = _strip_ansi(apply_block_line("- **Foo** — bar"))
        assert "Foo: bar" in out
        assert "Foo — bar" not in out

    def test_colon_title_unchanged(self):
        out = _strip_ansi(apply_block_line("- **Foo**: bar"))
        assert "Foo: bar" in out

    def test_em_dash_inside_body_preserved(self):
        out = _strip_ansi(apply_block_line("- **Foo** — bar — baz"))
        assert "Foo: bar" in out
        assert "bar — baz" in out

    def test_em_dash_inside_title_collapses_into_bold(self):
        out = _strip_ansi(apply_block_line("- **Foo — bar** — baz"))
        assert "Foo — bar" in out
        assert ": baz" in out


class TestNestedIndent:
    def test_plain_nested_bullets_use_four_space_indent(self):
        parent = _strip_ansi(apply_block_line("- parent"))
        child = _strip_ansi(apply_block_line("  - child"))
        grand = _strip_ansi(apply_block_line("    - grandchild"))
        assert parent.startswith("• parent")
        assert child.startswith("    ◦ child")
        assert grand.startswith("        ▸ grandchild")

    def test_nested_task_list_uses_four_space_indent(self):
        task = _strip_ansi(apply_block_line("- [ ] task"))
        sub = _strip_ansi(apply_block_line("  - [x] subtask"))
        assert task.startswith("• ○ task")
        assert sub.startswith("    ◦ ✓ subtask")

    def test_top_level_bullet_unindented(self):
        out = _strip_ansi(apply_block_line("- top"))
        assert out.startswith("• top")
        assert not out.startswith(" ")


class TestPlaceholderContrast:
    def test_placeholder_contrast_meets_aa(self):
        from hermes_cli.skin_engine import _bundled_default_payload

        cv = _bundled_default_payload().component_vars
        assert "cursor-placeholder" in cv, "cursor-placeholder token missing from default skin"
        assert "app-bg" in cv, "app-bg token missing from default skin"
        fg_hex = cv["cursor-placeholder"]
        bg_hex = cv["app-bg"]
        ratio = _wcag_ratio(fg_hex, bg_hex)
        assert ratio >= 4.5, f"contrast {ratio:.2f}:1 below AA 4.5:1 (fg={fg_hex} bg={bg_hex})"
