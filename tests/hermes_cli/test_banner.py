"""Tests for banner toolset name normalization and skin color usage."""

from pathlib import Path
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


def test_render_banner_logo_text_applies_accent_to_dim_gradient_for_plain_ascii():
    with (
        patch.object(banner, "_skin_color", side_effect=lambda key, default: {
            "banner_accent": "#00cc33",
            "banner_dim": "#003b00",
        }.get(key, default)),
    ):
        logo = banner.render_banner_logo_text("AAA\nBBB")

    console = Console(force_terminal=True, color_system="truecolor", width=20)
    top = logo.get_style_at_offset(console, 0)
    bottom = logo.get_style_at_offset(console, 4)
    assert top.color is not None
    assert bottom.color is not None
    assert top.color.triplet.hex == "#00cc33"
    assert bottom.color.triplet.hex == "#003b00"


def test_recover_multiline_user_skin_art_from_folded_yaml(tmp_path, monkeypatch):
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "matrix.yaml").write_text(
        "banner_hero:   /\\\\\n"
        "             /##\\\\\n"
        "            /####\\\\\n"
        "branding:\n"
        "  agent_name: Matrix\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("hermes_cli.skin_engine._skins_dir", lambda: Path(skins_dir))

    recovered = banner._recover_multiline_user_skin_art("matrix", "banner_hero", "/\\\\ /##\\\\ /####\\\\")
    assert recovered == "  /\\\\\n             /##\\\\\n            /####\\\\"


def test_resolve_banner_hero_assets_recovers_folded_user_skin_art(tmp_path, monkeypatch):
    from hermes_cli import skin_engine

    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "matrix.yaml").write_text(
        "name: matrix\n"
        "banner_hero:   /\\\\\n"
        "             /##\\\\\n"
        "            /####\\\\\n"
        "branding:\n"
        "  agent_name: Matrix\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("hermes_cli.skin_engine._skins_dir", lambda: Path(skins_dir))
    skin_engine._active_skin = None
    skin_engine._active_skin_name = "matrix"

    markup_hero, plain_hero = banner.resolve_banner_hero_assets()
    assert markup_hero.count("\n") == 2
    assert plain_hero.splitlines() == ["  /\\\\", "             /##\\\\", "            /####\\\\"]


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


def test_build_welcome_banner_centers_logo_above_panel():
    with (
        patch.object(
            model_tools,
            "check_tool_availability",
            return_value=([], []),
        ),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
        patch("shutil.get_terminal_size", return_value=__import__("os").terminal_size((100, 40))),
        patch.object(banner, "resolve_banner_logo_assets", return_value=("LOGO", "LOGO")),
    ):
        console = Console(record=True, force_terminal=False, color_system=None, width=100)
        banner.build_welcome_banner(
            console=console,
            model="anthropic/test-model",
            cwd="/tmp/project",
            tools=[],
            print_logo=True,
        )

    first_logo_line = next(line for line in console.export_text().splitlines() if "LOGO" in line)
    assert first_logo_line.startswith(" " * 48)


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
