from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cli import HermesCLI, _rich_text_from_ansi
from agent.display import set_code_highlight_active
from agent.rich_output import StreamingBlockBuffer, StreamingCodeBlockHighlighter
from hermes_cli.skin_engine import get_active_skin, set_active_skin


def _make_cli_stub():
    cli = HermesCLI.__new__(HermesCLI)
    cli._sudo_state = None
    cli._secret_state = None
    cli._approval_state = None
    cli._clarify_state = None
    cli._clarify_freetext = False
    cli._command_running = False
    cli._agent_running = False
    cli._voice_recording = False
    cli._voice_processing = False
    cli._voice_mode = False
    cli._stream_box_opened = False
    cli._command_spinner_frame = lambda: "⟳"
    cli._tui_style_base = {
        "prompt": "#fff",
        "input-area": "#fff",
        "input-rule": "#aaa",
        "prompt-working": "#888 italic",
    }
    cli._app = SimpleNamespace(style=None)
    cli._invalidate = MagicMock()
    return cli


class TestCliSkinPromptIntegration:
    def test_default_prompt_fragments_use_default_symbol(self):
        cli = _make_cli_stub()

        set_active_skin("default")
        assert cli._get_tui_prompt_fragments() == [("class:prompt", "❯ ")]

    def test_ares_prompt_fragments_use_skin_symbol(self):
        cli = _make_cli_stub()

        set_active_skin("ares")
        assert cli._get_tui_prompt_fragments() == [("class:prompt", "⚔ ❯ ")]

    def test_secret_prompt_fragments_preserve_secret_state(self):
        cli = _make_cli_stub()
        cli._secret_state = {"response_queue": object()}

        set_active_skin("ares")
        assert cli._get_tui_prompt_fragments() == [("class:sudo-prompt", "🔑 ❯ ")]

    def test_icon_only_skin_symbol_still_visible_in_special_states(self):
        cli = _make_cli_stub()
        cli._secret_state = {"response_queue": object()}

        with patch("hermes_cli.skin_engine.get_active_prompt_symbol", return_value="⚔ "):
            assert cli._get_tui_prompt_fragments() == [("class:sudo-prompt", "🔑 ⚔ ")]

    def test_build_tui_style_dict_uses_skin_overrides(self):
        cli = _make_cli_stub()

        set_active_skin("ares")
        skin = get_active_skin()
        style_dict = cli._build_tui_style_dict()

        assert style_dict["prompt"] == skin.get_color("prompt")
        assert style_dict["input-rule"] == skin.get_color("input_rule")
        assert style_dict["prompt-working"] == f"{skin.get_color('banner_dim')} italic"
        assert style_dict["approval-title"] == f"{skin.get_color('ui_warn')} bold"

    def test_apply_tui_skin_style_updates_running_app(self):
        cli = _make_cli_stub()

        set_active_skin("ares")
        assert cli._apply_tui_skin_style() is True
        assert cli._app.style is not None
        cli._invalidate.assert_called_once_with(min_interval=0.0)

    def test_handle_skin_command_refreshes_live_tui(self, capsys):
        cli = _make_cli_stub()

        with patch("cli.save_config_value", return_value=True):
            cli._handle_skin_command("/skin ares")

        output = capsys.readouterr().out
        assert "Skin set to: ares (saved)" in output
        assert "Prompt + TUI colors updated." in output
        assert cli._app.style is not None


class TestAnsiRichTextHelper:
    def test_preserves_literal_brackets(self):
        text = _rich_text_from_ansi("[notatag] literal")
        assert text.plain == "[notatag] literal"

    def test_strips_ansi_but_keeps_plain_text(self):
        text = _rich_text_from_ansi("\x1b[31mred\x1b[0m")
        assert text.plain == "red"


class TestCliMarkdownStreaming:
    def test_flush_stream_renders_markdown_when_code_highlight_disabled(self):
        cli = _make_cli_stub()
        cli.markdown_enabled = True
        cli._stream_buf = "**bold**"
        cli._stream_text_ansi = ""
        cli._stream_block_buf = StreamingBlockBuffer()
        cli._stream_code_hl = StreamingCodeBlockHighlighter()
        cli._close_reasoning_box = MagicMock()

        rendered = []
        set_code_highlight_active(False)
        try:
            with patch("cli._cprint", side_effect=rendered.append):
                HermesCLI._flush_stream(cli)
        finally:
            set_code_highlight_active(False)

        assert rendered
        assert "**bold**" not in rendered[0]
        assert "\033[1m" in rendered[0]
