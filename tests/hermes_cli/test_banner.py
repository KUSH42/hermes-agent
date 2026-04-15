"""Tests for banner toolset name normalization and skin color usage."""

from unittest.mock import patch

from rich.console import Console

import hermes_cli.banner as banner
import model_tools
import tools.mcp_tool


def test_display_toolset_name_strips_legacy_suffix():
    assert banner._display_toolset_name("homeassistant_tools") == "homeassistant"
    assert banner._display_toolset_name("honcho_tools") == "honcho"
    assert banner._display_toolset_name("web_tools") == "web"


def test_display_toolset_name_preserves_clean_names():
    assert banner._display_toolset_name("browser") == "browser"
    assert banner._display_toolset_name("file") == "file"
    assert banner._display_toolset_name("terminal") == "terminal"


def test_display_toolset_name_handles_empty():
    assert banner._display_toolset_name("") == "unknown"
    assert banner._display_toolset_name(None) == "unknown"


def test_build_welcome_banner_uses_normalized_toolset_names():
    """Unavailable toolsets should not have '_tools' appended in banner output."""
    with (
        patch.object(
            model_tools,
            "check_tool_availability",
            return_value=(
                ["web"],
                [
                    {"name": "homeassistant", "tools": ["ha_call_service"]},
                    {"name": "honcho", "tools": ["honcho_conclude"]},
                ],
            ),
        ),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
    ):
        console = Console(
            record=True, force_terminal=False, color_system=None, width=160
        )
        banner.build_welcome_banner(
            console=console,
            model="anthropic/test-model",
            cwd="/tmp/project",
            tools=[
                {"function": {"name": "web_search"}},
                {"function": {"name": "read_file"}},
            ],
            get_toolset_for_tool=lambda name: {
                "web_search": "web_tools",
                "read_file": "file",
            }.get(name),
        )

    output = console.export_text()
    assert "homeassistant:" in output
    assert "honcho:" in output
    assert "web:" in output
    assert "homeassistant_tools:" not in output
    assert "honcho_tools:" not in output
    assert "web_tools:" not in output


def test_resolve_banner_logo_assets_strips_rich_markup():
    markup_logo, plain_logo = banner.resolve_banner_logo_assets()
    assert "[bold" in markup_logo
    assert "[/" not in plain_logo
    assert "Hermes" not in plain_logo or isinstance(plain_logo, str)
    assert "██" in plain_logo


def test_build_welcome_banner_can_suppress_logo_print():
    with (
        patch.object(
            model_tools,
            "check_tool_availability",
            return_value=([], []),
        ),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
    ):
        console = Console(
            record=True, force_terminal=False, color_system=None, width=160
        )
        banner.build_welcome_banner(
            console=console,
            model="anthropic/test-model",
            cwd="/tmp/project",
            tools=[],
            print_logo=False,
        )

    output = console.export_text()
    assert "Available Tools" in output
    assert "███████" not in output


def test_build_welcome_banner_accepts_ansi_hero_renderable():
    with (
        patch.object(
            model_tools,
            "check_tool_availability",
            return_value=([], []),
        ),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
    ):
        console = Console(
            record=True, force_terminal=True, color_system="truecolor", width=160
        )
        hero = banner.Text.from_ansi("\x1b[38;2;255;255;255mX\x1b[0m\n\x1b[38;2;0;255;0mY\x1b[0m")
        banner.build_welcome_banner(
            console=console,
            model="anthropic/test-model",
            cwd="/tmp/project",
            tools=[],
            print_logo=False,
            print_hero=False,
            hero_renderable=hero,
        )

    output = console.export_text()
    assert "Available Tools" in output
    assert "X" in output
    assert "Y" in output


def test_build_welcome_banner_uses_fixed_hero_column_width():
    with (
        patch.object(
            model_tools,
            "check_tool_availability",
            return_value=([], []),
        ),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
        patch.object(banner, "resolve_banner_hero_assets", return_value=("", "abc\n12345")),
    ):
        console = Console(
            record=True, force_terminal=False, color_system=None, width=80
        )
        banner.build_welcome_banner(
            console=console,
            model="anthropic/test-model",
            cwd="/tmp/project",
            tools=[],
            print_logo=False,
        )

    tables = [r for r in console.export_text().splitlines() if "│" in r]
    assert any("Available Tools" in line for line in tables)
