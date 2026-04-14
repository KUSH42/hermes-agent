"""Tests for tool icon and emoji resolution in ``agent.display``."""

import sys
from unittest.mock import MagicMock, patch as mock_patch

from agent.display import get_tool_emoji, get_tool_icon, set_tool_icon_mode


class TestGetToolIcon:
    """Verify nerd font → emoji → ASCII fallback behavior."""

    def teardown_method(self):
        set_tool_icon_mode("auto")

    def test_auto_prefers_registry_icon(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_reg.get_emoji.return_value = "💻"
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal") == ""

    def test_nerdfont_mode_falls_back_to_emoji(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_reg.get_emoji.return_value = "💻"
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal", mode="nerdfont") == "💻"

    def test_auto_falls_back_to_ascii_when_icon_and_emoji_missing(self):
        mock_reg = MagicMock()
        mock_reg.get_icon.return_value = ""
        mock_reg.get_emoji.return_value = ""
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_icon("terminal", mode="auto") == ">"

    def test_skin_tool_icons_override_registry(self):
        skin = MagicMock()
        skin.tool_icons = {"terminal": "X"}
        skin.tool_emojis = {"terminal": "💻"}
        with mock_patch("agent.display._get_skin", return_value=skin):
            assert get_tool_icon("terminal") == "X"

    def test_emoji_mode_uses_legacy_emoji_chain(self):
        skin = MagicMock()
        skin.tool_icons = {"terminal": ""}
        skin.tool_emojis = {"terminal": "💻"}
        with mock_patch("agent.display._get_skin", return_value=skin):
            assert get_tool_icon("terminal", mode="emoji") == "💻"


class TestGetToolEmoji:
    """Verify legacy emoji path still works for compatibility."""

    def test_returns_registry_emoji_when_no_skin(self):
        mock_reg = MagicMock()
        mock_reg.get_emoji.return_value = "📖"
        mock_module = MagicMock()
        mock_module.registry = mock_reg
        with mock_patch("agent.display._get_skin", return_value=None), \
             mock_patch.dict(sys.modules, {"tools.registry": mock_module}):
            assert get_tool_emoji("read_file") == "📖"

    def test_skin_override_takes_precedence(self):
        skin = MagicMock()
        skin.tool_emojis = {"terminal": "⚔"}
        with mock_patch("agent.display._get_skin", return_value=skin):
            assert get_tool_emoji("terminal") == "⚔"


class TestSkinConfigToolIcons:
    """Verify SkinConfig handles both tool_icons and legacy tool_emojis."""

    def test_skin_config_has_tool_icons_field(self):
        from hermes_cli.skin_engine import SkinConfig
        skin = SkinConfig(name="test")
        assert skin.tool_icons == {}
        assert skin.tool_emojis == {}

    def test_build_skin_config_reads_tool_icons(self):
        from hermes_cli.skin_engine import _build_skin_config
        skin = _build_skin_config({
            "name": "custom",
            "tool_icons": {"terminal": "", "patch": ""},
        })
        assert skin.tool_icons == {"terminal": "", "patch": ""}
        assert skin.tool_emojis == {}

    def test_build_skin_config_legacy_tool_emojis_populate_tool_icons(self):
        from hermes_cli.skin_engine import _build_skin_config
        skin = _build_skin_config({
            "name": "legacy",
            "tool_emojis": {"terminal": "💻", "patch": "🔧"},
        })
        assert skin.tool_icons == {"terminal": "💻", "patch": "🔧"}
        assert skin.tool_emojis == {"terminal": "💻", "patch": "🔧"}
