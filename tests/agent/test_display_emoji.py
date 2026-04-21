"""Tests for tool icon resolution in ``agent.display``."""

import sys
from unittest.mock import MagicMock, patch as mock_patch

from agent.display import get_tool_emoji, get_tool_icon, set_tool_icon_mode


class TestGetToolIcon:
    """Verify skin → registry → ASCII fallback behavior."""

    def teardown_method(self):
        set_tool_icon_mode("auto")

    def test_auto_prefers_registry_icon(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = "󰆍"
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal") == "󰆍"

    def test_nerdfont_falls_back_to_ascii(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal", mode="nerdfont") == ">"

    def test_auto_falls_back_to_ascii_when_icon_missing(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal", mode="auto") == ">"

    def test_skin_tool_icons_override_registry(self):
        skin = MagicMock()
        skin.tool_icons = {"terminal": "X"}
        with mock_patch("agent.display._get_skin", return_value=skin):
            assert get_tool_icon("terminal") == "X"

    def test_emoji_mode_treated_as_auto(self):
        """Legacy 'emoji' mode → auto (skips to registry → ASCII)."""
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal", mode="emoji") == ">"

    def test_ascii_mode_skips_registry(self):
        assert get_tool_icon("terminal", mode="ascii") == ">"


class TestGetToolEmoji:
    """Verify get_tool_emoji is a thin alias for get_tool_icon."""

    def test_delegates_to_get_tool_icon(self):
        with mock_patch("agent.display.get_tool_icon", return_value="X") as mock_fn:
            assert get_tool_emoji("terminal") == "X"
            mock_fn.assert_called_once_with("terminal", default="⚡")


class TestSkinConfigToolIcons:
    """Verify SkinConfig tool_icons field."""

    def test_skin_config_has_tool_icons_field(self):
        from hermes_cli.skin_engine import SkinConfig
        skin = SkinConfig(name="test")
        assert skin.tool_icons == {}
        assert not hasattr(skin, "tool_emojis")

    def test_build_skin_config_reads_tool_icons(self):
        from hermes_cli.skin_engine import _build_skin_config
        skin = _build_skin_config({
            "name": "custom",
            "tool_icons": {"terminal": "󰆍", "patch": " "},
        })
        assert skin.tool_icons == {"terminal": "󰆍", "patch": " "}

    def test_build_skin_config_legacy_tool_emojis_merges_into_tool_icons(self):
        from hermes_cli.skin_engine import _build_skin_config
        skin = _build_skin_config({
            "name": "legacy",
            "tool_emojis": {"terminal": "💻", "patch": "🔧"},
        })
        assert skin.tool_icons == {"terminal": "💻", "patch": "🔧"}
