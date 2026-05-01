"""Regression tests for sanitized startup banner hero rendering in TUI mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_render_startup_banner_text_sanitizes_braille_blank_hero(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    import cli
    from cli import HermesCLI

    obj = HermesCLI.__new__(HermesCLI)
    obj.enabled_toolsets = []
    obj.model = "test-model"
    obj.session_id = "test-session"
    obj.agent = None
    obj.console = MagicMock()
    obj.config = {"display": {}}

    seen = {}

    def fake_build_welcome_banner(*, hero_renderable=None, print_hero=True, **kwargs):
        seen["hero_renderable"] = hero_renderable
        seen["print_hero"] = print_hero

    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch(
            "hermes_cli.banner.resolve_banner_hero_assets",
            return_value=("markup", "\u2800\u2800X"),
        ),
        patch("hermes_cli.banner.build_welcome_banner", side_effect=fake_build_welcome_banner),
        patch.object(cli, "_hermes_app", None),
    ):
        obj._render_startup_banner_text(print_hero=True)

    assert seen["print_hero"] is False
    assert seen["hero_renderable"] is not None
    assert "\u2800" not in seen["hero_renderable"].plain
    assert seen["hero_renderable"].plain == "  X"
