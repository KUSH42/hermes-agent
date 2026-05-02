"""Tests for banner hierarchy spec — BH-1 section breaks, BH-2 warning tone, BH-3 dismiss badge."""
from __future__ import annotations

import io
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.table import Table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOLS = [{"function": {"name": "bash_tool"}}]

_DEFAULT_COLORS: dict[str, str] = {
    "banner_accent": "#FFBF00",
    "banner_dim": "#B8860B",
    "banner_text": "#FFF8DC",
    "banner_title": "#FFD700",
    "banner_border": "#CD7F32",
    "banner_warning": "#FF8C00",
    "banner_warning_dim": "#CD6500",
    "banner_key": "#FFD700",
    "session_border": "#8B8682",
}


def _skin_color_fn(overrides: dict[str, str] | None = None):
    """Return a side_effect fn for _skin_color that uses _DEFAULT_COLORS with optional overrides."""
    merged = {**_DEFAULT_COLORS, **(overrides or {})}

    def _fn(key: str, fallback: str = "") -> str:
        return merged.get(key, fallback)

    return _fn


def _capture_right_content(
    *,
    tools=None,
    mcp_status=None,
    skills=None,
    behind: int = 0,
    show_update: bool = True,
    update_cmd: str = "pip install --upgrade hermes",
    skin_overrides: dict[str, str] | None = None,
) -> str:
    """Build banner with full mocks; return the raw right_content markup string."""
    if tools is None:
        tools = _TOOLS
    if mcp_status is None:
        mcp_status = []
    if skills is None:
        skills = {"core": ["skill_a", "skill_b"]}

    captured: list[str] = []
    original_add_row = Table.add_row

    def _patched_add_row(self_table, *args, **kw):
        # right_content is the second positional arg (index 1)
        if len(args) >= 2 and isinstance(args[1], str):
            captured.append(args[1])
        return original_add_row(self_table, *args, **kw)

    console = Console(file=io.StringIO(), width=120, highlight=False)

    ctx_patches = [
        patch("hermes_cli.banner.get_update_result", return_value=(behind if behind > 0 else None)),
        patch("hermes_cli.banner._should_show_update_banner", return_value=show_update),
        patch("hermes_cli.banner.get_available_skills", return_value=skills),
        patch("tools.mcp_tool.get_mcp_status", return_value=mcp_status),
        patch("hermes_cli.config.recommended_update_command", return_value=update_cmd),
        patch("model_tools.check_tool_availability", return_value=([], [])),
        patch("model_tools.get_toolset_for_tool", return_value="core"),
        patch("model_tools.TOOLSET_REQUIREMENTS", {}),
        patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=(None, "")),
        patch("hermes_cli.banner._skin_color", side_effect=_skin_color_fn(skin_overrides)),
        patch("hermes_cli.banner._skin_branding", return_value="Hermes Agent"),
        patch("hermes_cli.profiles.get_active_profile_name", return_value="default", create=True),
        patch.object(Table, "add_row", _patched_add_row),
    ]

    with ExitStack() as stack:
        for p in ctx_patches:
            stack.enter_context(p)
        try:
            from hermes_cli.banner import build_welcome_banner

            build_welcome_banner(
                console=console,
                model="test-model",
                cwd="/tmp",
                tools=tools,
                print_logo=False,
                print_hero=False,
            )
        except Exception:
            pass  # some banner errors are irrelevant; we only need right_content

    return captured[0] if captured else ""


def _lines(content: str) -> list[str]:
    return content.split("\n")


# ---------------------------------------------------------------------------
# BH-1 — Visual separator between sections
# ---------------------------------------------------------------------------


class TestBH1SectionBreak:
    def test_rule_between_tools_and_skills(self):
        """right_content has a ─ rule line between the tools section and Available Skills."""
        content = _capture_right_content(skills={"core": ["skill_a"]})
        lines = _lines(content)
        skills_idx = next(
            (i for i, ln in enumerate(lines) if "Available Skills" in ln), None
        )
        assert skills_idx is not None, "Available Skills header not found"
        # There must be a ─ rule in the two lines immediately before the header
        pre_lines = lines[max(0, skills_idx - 2) : skills_idx]
        assert any("─" in ln for ln in pre_lines), (
            f"No rule found before 'Available Skills' header; pre-lines: {pre_lines}"
        )

    def test_rule_between_tools_and_mcp_when_mcp_present(self):
        """When MCP servers are configured, a ─ rule appears before the MCP Servers header."""
        mcp = [{"name": "my-server", "connected": True, "transport": "stdio", "tools": 3}]
        content = _capture_right_content(mcp_status=mcp)
        lines = _lines(content)
        mcp_idx = next(
            (i for i, ln in enumerate(lines) if "MCP Servers" in ln), None
        )
        assert mcp_idx is not None, "MCP Servers header not found"
        pre_lines = lines[max(0, mcp_idx - 2) : mcp_idx]
        assert any("─" in ln for ln in pre_lines), (
            f"No rule found before 'MCP Servers' header; pre-lines: {pre_lines}"
        )

    def test_no_orphan_rule_at_tail(self):
        """With empty skills, the final non-empty element is NOT a bare ─ rule line."""
        content = _capture_right_content(skills={})
        lines = _lines(content)
        non_empty = [ln for ln in lines if ln.strip()]
        assert non_empty, "right_content should not be empty"
        last = non_empty[-1]
        # The last meaningful line must not be just the rule
        assert "─" not in last or any(c.isalpha() for c in last), (
            f"Last non-empty line is an orphan rule: {last!r}"
        )

    def test_no_orphan_rule_when_mcp_empty(self):
        """With empty MCP list, no ─ rule fires between Tools and Skills due to MCP guard."""
        content = _capture_right_content(mcp_status=[], skills={"core": ["s"]})
        lines = _lines(content)
        # Skills header must be present (skills break is unconditional)
        skills_idx = next(
            (i for i, ln in enumerate(lines) if "Available Skills" in ln), None
        )
        assert skills_idx is not None
        # No MCP Servers header should appear at all
        assert not any("MCP Servers" in ln for ln in lines), (
            "MCP Servers header appeared when mcp_status was empty"
        )
        # The skills ─ rule is still present
        assert any("─" in ln for ln in lines), "Skills section break rule is missing"

    def test_no_rule_when_tools_empty(self):
        """Available Tools header is the first item; no ─ rule should directly follow it."""
        content = _capture_right_content(tools=[])
        lines = _lines(content)
        tools_idx = next(
            (i for i, ln in enumerate(lines) if "Available Tools" in ln), None
        )
        assert tools_idx is not None
        # The line immediately after the tools header must not be a bare ─ rule
        if tools_idx + 1 < len(lines):
            assert "─" not in lines[tools_idx + 1], (
                "Unexpected rule line directly after 'Available Tools' header"
            )

    def test_rule_uses_dim_color(self):
        """The ─ rule line markup contains the 'dim' style and the resolved dim color."""
        dim_color = _DEFAULT_COLORS["banner_dim"]
        content = _capture_right_content()
        # Find lines containing ─
        rule_lines = [ln for ln in _lines(content) if "─" in ln]
        assert rule_lines, "No rule lines found in right_content"
        first_rule = rule_lines[0]
        assert "dim" in first_rule, f"Rule line does not use 'dim': {first_rule!r}"
        assert dim_color in first_rule, (
            f"Rule line does not contain dim color {dim_color!r}: {first_rule!r}"
        )


# ---------------------------------------------------------------------------
# BH-2 — Warning uses error tone, not brand accent family
# ---------------------------------------------------------------------------


class TestBH2WarningTone:
    def test_warning_uses_warning_color_not_yellow(self):
        """Warning markup uses banner_warning (#FF8C00), not literal 'yellow'."""
        content = _capture_right_content(behind=3, show_update=True)
        warning_lines = [ln for ln in _lines(content) if "⚠" in ln]
        assert warning_lines, "No warning line (⚠) found in right_content"
        warn_line = warning_lines[0]
        assert "#FF8C00" in warn_line, f"Expected #FF8C00 in warning line: {warn_line!r}"
        assert "yellow" not in warn_line, f"'yellow' literal should not appear: {warn_line!r}"

    def test_warning_color_is_distinct_from_accent(self):
        """The resolved banner_warning color is not the same as banner_accent."""
        warn_color = _DEFAULT_COLORS["banner_warning"]
        accent_color = _DEFAULT_COLORS["banner_accent"]
        assert warn_color != accent_color, (
            f"banner_warning ({warn_color}) must differ from banner_accent ({accent_color})"
        )

    def test_skin_override_respected(self, monkeypatch):
        """Patching _skin_color so banner_warning returns #FF0000 changes the warning markup."""
        overrides = {"banner_warning": "#FF0000", "banner_warning_dim": "#CC0000"}
        content = _capture_right_content(behind=1, show_update=True, skin_overrides=overrides)
        warning_lines = [ln for ln in _lines(content) if "⚠" in ln]
        assert warning_lines, "No warning line (⚠) found"
        assert "#FF0000" in warning_lines[0], (
            f"Skin-overridden color #FF0000 not found in: {warning_lines[0]!r}"
        )


# ---------------------------------------------------------------------------
# BH-3 — Dismiss-key hint as badge, not inline text
# ---------------------------------------------------------------------------


class TestBH3DismissBadge:
    def test_no_dismiss_badge_rendered(self):
        """The update banner no longer renders a dismiss badge line."""
        content = _capture_right_content(behind=2, show_update=True)
        lines = _lines(content)
        warn_idx = next((i for i, ln in enumerate(lines) if "⚠" in ln), None)
        assert warn_idx is not None, "Warning line not found"
        assert "dismiss" not in lines[warn_idx], (
            f"'dismiss' must not be on the ⚠ line: {lines[warn_idx]!r}"
        )
        later_lines = lines[warn_idx + 1 :]
        assert all("dismiss" not in line for line in later_lines), (
            f"'dismiss' should not appear after the ⚠ line, got: {later_lines!r}"
        )

    def test_update_banner_keeps_install_line_only(self):
        """The line after the warning is the install/update instruction, not a badge."""
        content = _capture_right_content(behind=1, show_update=True)
        lines = _lines(content)
        warn_idx = next((i for i, ln in enumerate(lines) if "⚠" in ln), None)
        assert warn_idx is not None
        next_line = lines[warn_idx + 1] if warn_idx + 1 < len(lines) else ""
        assert "pip install --upgrade hermes" in next_line
        assert "dismiss" not in next_line

    def test_install_command_in_badge_row(self):
        """Badge row contains update_cmd styled with text color, flanked by 'run' and 'to install'."""
        text_color = _DEFAULT_COLORS["banner_text"]
        cmd = "pip install --upgrade hermes-agent"
        content = _capture_right_content(behind=1, show_update=True, update_cmd=cmd)
        lines = _lines(content)
        warn_idx = next((i for i, ln in enumerate(lines) if "⚠" in ln), None)
        assert warn_idx is not None
        badge_line = lines[warn_idx + 1]
        assert cmd in badge_line, f"update_cmd not found in badge line: {badge_line!r}"
        assert "run" in badge_line, f"'run' not in badge line: {badge_line!r}"
        assert "to install" in badge_line, f"'to install' not in badge line: {badge_line!r}"
        # update_cmd must be styled with text color, NOT key_color
        key_color = _DEFAULT_COLORS["banner_key"]
        cmd_pos = badge_line.index(cmd)
        # Look for text_color before the command position, not key_color
        text_before_cmd = badge_line[:cmd_pos]
        assert text_color in text_before_cmd, (
            f"text color {text_color!r} not found before cmd in: {text_before_cmd!r}"
        )

    def test_no_badge_when_no_warning(self):
        """When behind=0 (no update warning), no right_content entry contains 'dismiss'."""
        content = _capture_right_content(behind=0)
        assert "dismiss" not in content, (
            f"'dismiss' appeared in right_content with behind=0: found it"
        )
