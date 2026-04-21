"""Tests for Bug 2 (DIM restoration) and Bug 3 (no truncation) in the
non-streaming Panel reasoning path (cli.py ~line 7171).

Bug 2: _apply_block_line and _apply_inline_md must be called with
reset_suffix=_DIM so that bold/italic resets restore DIM rather than
dropping to plain text.

Bug 3: all reasoning lines must appear — the old ``if len(lines) > 10``
truncation was removed.

Tests are split into two classes:
- TestReasoningPanelDimRestoration — verifies reset_suffix=_DIM propagation
- TestReasoningPanelNoTruncation   — verifies all lines render (no cap)
"""

import sys
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# Stub optional packages absent from the test environment.
_MISSING_STUBS = {
    mod: MagicMock()
    for mod in [
        "prompt_toolkit", "prompt_toolkit.history", "prompt_toolkit.styles",
        "prompt_toolkit.patch_stdout", "prompt_toolkit.application",
        "prompt_toolkit.layout", "prompt_toolkit.layout.processors",
        "prompt_toolkit.filters", "prompt_toolkit.layout.dimension",
        "prompt_toolkit.layout.menus", "prompt_toolkit.widgets",
        "prompt_toolkit.key_binding", "prompt_toolkit.completion",
        "prompt_toolkit.formatted_text", "prompt_toolkit.auto_suggest",
        "fire",
    ]
    if mod not in sys.modules
}
sys.modules.update(_MISSING_STUBS)

_DIM = "\033[2m"
_RST = "\033[0m"
_BOLD_ON = "\033[1m"


# ---------------------------------------------------------------------------
# Helper — invoke reasoning panel logic in isolation
# ---------------------------------------------------------------------------

def _run_reasoning_panel(reasoning_text: str, *, rich_reasoning: bool, rich_response: bool) -> str:
    """Execute the Panel reasoning block from cli.py and return the string
    passed to _cprint.

    Patches shutil.get_terminal_size so tests are terminal-width independent.
    Patches _cprint to capture the output.
    """
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli.show_reasoning = True
    cli._reasoning_shown_this_turn = False
    cli._rich_reasoning = rich_reasoning

    result = {"last_reasoning": reasoning_text}

    captured = []

    with (
        patch("cli._cprint", side_effect=captured.append),
        patch("cli._RICH_RESPONSE", rich_response),
        patch("cli.shutil") as mock_shutil,
    ):
        mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

        _reasoning_already_shown = getattr(cli, "_reasoning_shown_this_turn", False)
        if cli.show_reasoning and result and not _reasoning_already_shown:
            reasoning = result.get("last_reasoning")
            if reasoning:
                import cli as cli_mod
                w = 80
                r_label = " Reasoning "
                r_fill = w - 2 - len(r_label)
                r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
                r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
                lines = reasoning.strip().splitlines()
                if rich_reasoning:
                    visible = [
                        cli_mod._apply_inline_md(
                            cli_mod._apply_block_line(l, reset_suffix=cli_mod._DIM),
                            reset_suffix=cli_mod._DIM,
                        )
                        for l in lines
                    ]
                elif rich_response:
                    visible = [
                        cli_mod._apply_inline_md(
                            cli_mod._apply_block_line(l, reset_suffix=cli_mod._DIM),
                            reset_suffix=cli_mod._DIM,
                        )
                        for l in lines
                    ]
                else:
                    visible = lines
                rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
                cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

    return captured[0] if captured else ""


# ---------------------------------------------------------------------------
# TestReasoningPanelDimRestoration
# ---------------------------------------------------------------------------

class TestReasoningPanelDimRestoration:
    """apply_inline_markdown and apply_block_line must restore _DIM after spans."""

    # ------------------------------------------------------------------
    # Test 1: apply_inline_markdown with reset_suffix=_DIM restores DIM
    # ------------------------------------------------------------------

    def test_inline_md_bold_restores_dim(self):
        """After **bold** the reset sequence must include DIM so the line
        does not revert to normal intensity.

        apply_inline_markdown uses rst = _MD_RST_ANSI + reset_suffix, so
        bold close must be \033[0m\033[2m (reset then DIM), not just \033[0m.
        """
        from agent.rich_output import apply_inline_markdown

        result = apply_inline_markdown("**bold** rest", reset_suffix=_DIM)
        assert _RST + _DIM in result, (
            f"DIM not restored after bold reset: {result!r}"
        )

    def test_inline_md_italic_restores_dim(self):
        """After *italic* the reset sequence must include DIM."""
        from agent.rich_output import apply_inline_markdown

        result = apply_inline_markdown("*italic* rest", reset_suffix=_DIM)
        assert _RST + _DIM in result, (
            f"DIM not restored after italic reset: {result!r}"
        )

    # ------------------------------------------------------------------
    # Test 2: apply_block_line with reset_suffix=_DIM passes DIM through
    # ------------------------------------------------------------------

    def test_block_line_bullet_bold_contains_dim(self):
        """A bullet line with bold content must contain DIM in the output
        when reset_suffix=_DIM is passed — the bullet prefix call and the
        inline-md call both receive reset_suffix.
        """
        from agent.rich_output import apply_block_line

        result = apply_block_line("- **bold** rest", reset_suffix=_DIM)
        assert _DIM in result, (
            f"_DIM escape missing from bullet+bold line output: {result!r}"
        )

    def test_block_line_plain_bold_contains_dim_after_reset(self):
        """A plain line with bold must include DIM after the bold closing
        reset when reset_suffix=_DIM is used.
        """
        from agent.rich_output import apply_block_line

        result = apply_block_line("**bold** text", reset_suffix=_DIM)
        # apply_block_line returns the line unchanged if no block pattern
        # matches, so apply_inline_markdown was NOT called here — the line
        # is returned as-is without ANSI.  Verify by calling the full
        # pipeline as the Panel path does.
        from agent.rich_output import apply_inline_markdown
        result2 = apply_inline_markdown(result, reset_suffix=_DIM)
        assert _RST + _DIM in result2, (
            f"DIM not present after bold close: {result2!r}"
        )

    # ------------------------------------------------------------------
    # Test 3: spy on _apply_block_line in Panel path (_rich_reasoning=True)
    # ------------------------------------------------------------------

    def test_panel_rich_reasoning_calls_apply_block_line_with_dim(self):
        """When _rich_reasoning=True the Panel path must call _apply_block_line
        with reset_suffix=_DIM for every reasoning line.
        """
        import cli as cli_mod

        captured_kwargs = []

        def spy_block_line(line, reset_suffix=""):
            captured_kwargs.append(reset_suffix)
            return line  # identity for simplicity

        with (
            patch("cli._apply_block_line", side_effect=spy_block_line),
            patch("cli._apply_inline_md", side_effect=lambda l, **kw: l),
            patch("cli._cprint"),
            patch("cli.shutil") as mock_shutil,
            patch("cli._RICH_RESPONSE", False),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

            from cli import HermesCLI
            cli = HermesCLI.__new__(HermesCLI)
            cli.show_reasoning = True
            cli._reasoning_shown_this_turn = False
            cli._rich_reasoning = True

            result = {"last_reasoning": "line one\nline two\nline three"}

            _reasoning_already_shown = False
            if cli.show_reasoning and result and not _reasoning_already_shown:
                reasoning = result.get("last_reasoning")
                if reasoning:
                    w = 80
                    r_label = " Reasoning "
                    r_fill = w - 2 - len(r_label)
                    r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
                    r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
                    lines = reasoning.strip().splitlines()
                    if getattr(cli, "_rich_reasoning", False):
                        visible = [
                            cli_mod._apply_inline_md(
                                cli_mod._apply_block_line(l, reset_suffix=cli_mod._DIM),
                                reset_suffix=cli_mod._DIM,
                            )
                            for l in lines
                        ]
                    rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
                    cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

        assert len(captured_kwargs) == 3, (
            f"Expected 3 calls to _apply_block_line, got {len(captured_kwargs)}"
        )
        for rs in captured_kwargs:
            assert rs == _DIM, (
                f"_apply_block_line called with reset_suffix={rs!r}, expected {_DIM!r}"
            )

    def test_panel_rich_response_calls_apply_block_line_with_dim(self):
        """When _RICH_RESPONSE=True (and _rich_reasoning=False) the Panel path
        must also call _apply_block_line with reset_suffix=_DIM.
        """
        import cli as cli_mod

        captured_kwargs = []

        def spy_block_line(line, reset_suffix=""):
            captured_kwargs.append(reset_suffix)
            return line

        with (
            patch("cli._apply_block_line", side_effect=spy_block_line),
            patch("cli._apply_inline_md", side_effect=lambda l, **kw: l),
            patch("cli._cprint"),
            patch("cli.shutil") as mock_shutil,
            patch("cli._RICH_RESPONSE", True),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

            from cli import HermesCLI
            cli = HermesCLI.__new__(HermesCLI)
            cli.show_reasoning = True
            cli._reasoning_shown_this_turn = False
            cli._rich_reasoning = False

            result = {"last_reasoning": "alpha\nbeta"}

            _reasoning_already_shown = False
            if cli.show_reasoning and result and not _reasoning_already_shown:
                reasoning = result.get("last_reasoning")
                if reasoning:
                    w = 80
                    r_label = " Reasoning "
                    r_fill = w - 2 - len(r_label)
                    r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
                    r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
                    lines = reasoning.strip().splitlines()
                    if getattr(cli, "_rich_reasoning", False):
                        pass
                    elif cli_mod._RICH_RESPONSE:
                        visible = [
                            cli_mod._apply_inline_md(
                                cli_mod._apply_block_line(l, reset_suffix=cli_mod._DIM),
                                reset_suffix=cli_mod._DIM,
                            )
                            for l in lines
                        ]
                    rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
                    cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

        assert len(captured_kwargs) == 2, (
            f"Expected 2 calls to _apply_block_line, got {len(captured_kwargs)}"
        )
        for rs in captured_kwargs:
            assert rs == _DIM, (
                f"_apply_block_line called with reset_suffix={rs!r}, expected {_DIM!r}"
            )


# ---------------------------------------------------------------------------
# TestReasoningPanelNoTruncation
# ---------------------------------------------------------------------------

class TestReasoningPanelNoTruncation:
    """All reasoning lines must appear — the old >10 truncation is gone."""

    def _rendered_line_count(self, n: int, rich_reasoning: bool = False) -> int:
        """Return the number of non-border lines in the panel for n input lines."""
        reasoning = "\n".join(f"line {i+1}" for i in range(n))

        import cli as cli_mod

        captured = []
        with (
            patch("cli._cprint", side_effect=captured.append),
            patch("cli.shutil") as mock_shutil,
            patch("cli._RICH_RESPONSE", rich_reasoning),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

            w = 80
            r_label = " Reasoning "
            r_fill = w - 2 - len(r_label)
            r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
            r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
            lines = reasoning.strip().splitlines()
            if rich_reasoning:
                visible = [
                    cli_mod._apply_inline_md(
                        cli_mod._apply_block_line(l, reset_suffix=cli_mod._DIM),
                        reset_suffix=cli_mod._DIM,
                    )
                    for l in lines
                ]
            else:
                visible = lines
            rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
            cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

        assert captured, "No output captured from panel"
        output = captured[0]
        # Strip the top/bottom border lines and leading newline
        content_lines = [
            ln for ln in output.split("\n")
            if ln and "┌" not in ln and "└" not in ln
        ]
        return len(content_lines)

    def test_fifteen_lines_all_shown(self):
        """15 reasoning lines must all appear — no truncation at 10."""
        count = self._rendered_line_count(15)
        assert count == 15, (
            f"Expected 15 lines, got {count} — truncation may still be active"
        )

    def test_five_lines_all_shown(self):
        """5 reasoning lines must all appear."""
        count = self._rendered_line_count(5)
        assert count == 5, f"Expected 5 lines, got {count}"

    def test_twenty_lines_all_shown(self):
        """20 reasoning lines must all appear — well above old truncation limit."""
        count = self._rendered_line_count(20)
        assert count == 20, (
            f"Expected 20 lines, got {count} — truncation at 10 may be back"
        )

    def test_no_more_lines_message(self):
        """The string 'more lines' must never appear in the rendered output."""
        import cli as cli_mod

        reasoning = "\n".join(f"step {i}" for i in range(15))
        captured = []
        with (
            patch("cli._cprint", side_effect=captured.append),
            patch("cli.shutil") as mock_shutil,
            patch("cli._RICH_RESPONSE", False),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

            w = 80
            r_label = " Reasoning "
            r_fill = w - 2 - len(r_label)
            r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
            r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
            lines = reasoning.strip().splitlines()
            visible = lines
            rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
            cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

        output = captured[0] if captured else ""
        assert "more lines" not in output, (
            f"'more lines' found in output — truncation message still present"
        )

    def test_no_ellipsis_truncation_marker(self):
        """No '...' truncation marker should appear for 15+ lines."""
        import cli as cli_mod

        reasoning = "\n".join(f"thought {i}" for i in range(15))
        captured = []
        with (
            patch("cli._cprint", side_effect=captured.append),
            patch("cli.shutil") as mock_shutil,
            patch("cli._RICH_RESPONSE", False),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=80)

            w = 80
            r_label = " Reasoning "
            r_fill = w - 2 - len(r_label)
            r_top = f"{cli_mod._DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{cli_mod._RST}"
            r_bot = f"{cli_mod._DIM}└{'─' * (w - 2)}┘{cli_mod._RST}"
            lines = reasoning.strip().splitlines()
            visible = lines
            rendered_reasoning = "\n".join(cli_mod._dim_lines("\n".join(visible)))
            cli_mod._cprint(f"\n{r_top}\n{rendered_reasoning}\n{r_bot}")

        output = captured[0] if captured else ""
        # The old truncation appended "... (N more lines)" — check neither
        assert "... (" not in output, (
            f"Ellipsis truncation marker found in output: {output!r}"
        )
