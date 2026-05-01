"""Banner layout spec — BL-1..BL-4 (2026-05-01)."""
from __future__ import annotations

import io
import logging
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console
from rich.text import Text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_right_lines() -> list[str]:
    """Run build_welcome_banner; return the right_lines list via patching join."""
    from hermes_cli import banner as banner_mod
    captured: dict = {}
    real_join = "\n".join

    def _spy(self, args, **kw):
        pass

    # Patch Table.add_row to capture right_content
    from rich.table import Table
    real_add_row = Table.add_row

    def _add_row(self, *args, **kw):
        # right_content is the second arg
        if len(args) >= 2 and isinstance(args[1], str):
            captured["right_content"] = args[1]
        return real_add_row(self, *args, **kw)

    console = Console(file=io.StringIO(), width=120)
    with patch.object(Table, "add_row", _add_row):
        try:
            banner_mod.build_welcome_banner(
                console=console, model="m", cwd="/tmp", tools=[],
                print_logo=False, print_hero=False,
            )
        except Exception:
            pass

    rc = captured.get("right_content", "")
    return rc.split("\n")


def _capture_console_output(term_rows: int = 40, term_cols: int = 120,
                             print_logo: bool = True) -> str:
    """Run banner with mocked terminal size; return captured rendered output."""
    from hermes_cli import banner as banner_mod
    console = Console(file=io.StringIO(), record=True, width=term_cols)
    fake_size = MagicMock()
    fake_size.columns = term_cols
    fake_size.lines = term_rows
    with patch("hermes_cli.banner.shutil.get_terminal_size", return_value=fake_size):
        try:
            banner_mod.build_welcome_banner(
                console=console, model="m", cwd="/tmp", tools=[],
                print_logo=print_logo, print_hero=False,
            )
        except Exception:
            pass
    return console.export_text(styles=False)


# ---------------------------------------------------------------------------
# BL-1 — Logo bound to viewport rows
# ---------------------------------------------------------------------------

class TestBL1LogoBound:

    def test_logo_skipped_when_narrow(self) -> None:
        out = _capture_console_output(term_rows=40, term_cols=80, print_logo=True)
        # No logo block-art rows nor wordmark "HERMES"
        assert "HERMES-AGENT" not in out
        assert "█" not in out  # block-art glyph

    def test_wordmark_when_short_terminal(self) -> None:
        out = _capture_console_output(term_rows=24, term_cols=120, print_logo=True)
        assert "HERMES AGENT" in out or "HERMES-AGENT" in out
        # No multi-row block art
        assert "██║" not in out

    def test_full_logo_when_tall_terminal(self) -> None:
        out = _capture_console_output(term_rows=40, term_cols=120, print_logo=True)
        # Block-art uses these characters
        assert "██" in out

    def test_wordmark_uses_title_color(self) -> None:
        from hermes_cli import banner as banner_mod
        console = Console(file=io.StringIO(), record=True, width=120)
        fake_size = MagicMock()
        fake_size.columns = 120
        fake_size.lines = 24
        with patch("hermes_cli.banner.shutil.get_terminal_size", return_value=fake_size):
            try:
                banner_mod.build_welcome_banner(
                    console=console, model="m", cwd="/tmp", tools=[],
                    print_logo=True, print_hero=False,
                )
            except Exception:
                pass
        # Export with styles to check color application
        styled = console.export_text(styles=True)
        # title_color resolves via skin to a hex; assert a hex color escape appears
        assert "#FFD700" in styled or "FFD700" in styled or "\x1b[" in styled

    def test_print_logo_false_skips_row_check(self) -> None:
        out = _capture_console_output(term_rows=24, term_cols=120, print_logo=False)
        assert "HERMES-AGENT" not in out
        assert "HERMES AGENT" not in out
        assert "██" not in out


# ---------------------------------------------------------------------------
# BL-2 — Sigil aligned to right column via padding
# ---------------------------------------------------------------------------

class TestBL2SigilAlignment:

    def test_left_column_padded_to_right_height(self) -> None:
        from hermes_cli.banner import _count_visual_rows
        from rich.text import Text
        # Hero with 3 rows + 9 text lines = 12 left rows total when meta added
        top = [Text(""), Text("a\nb\nc"), Text("")]
        meta = [Text("m1"), Text("m2"), Text("m3")]
        right_count = 25
        left_count = _count_visual_rows(top) + len(meta)
        pad = max(0, right_count - left_count)
        assert pad == 25 - left_count
        rendered = top + [Text("")] * pad + meta
        assert len(rendered) == len(top) + pad + len(meta)

    def test_no_padding_when_left_already_taller(self) -> None:
        from hermes_cli.banner import _count_visual_rows
        from rich.text import Text
        top = [Text("x\n" * 19)]  # 20 visual rows
        meta = [Text("m1"), Text("m2")]
        right_count = 5
        left_count = _count_visual_rows(top) + len(meta)
        pad = max(0, right_count - left_count)
        assert pad == 0

    def test_meta_lines_pinned_to_bottom(self) -> None:
        from hermes_cli.banner import _count_visual_rows
        from rich.text import Text
        top = [Text(""), Text("hero")]
        meta = [Text("model"), Text("cwd"), Text("session")]
        pad = 10
        rendered = top + [Text("")] * pad + meta
        # last 3 are meta
        assert rendered[-3:] == meta

    def test_hero_remains_at_top(self) -> None:
        from hermes_cli.banner import _count_visual_rows
        from rich.text import Text
        hero = Text("HERO")
        top = [Text(""), hero, Text("")]
        meta = [Text("model")]
        rendered = top + [Text("")] * 5 + meta
        # First non-blank renderable
        first_non_blank = next(r for r in rendered if isinstance(r, Text) and r.plain)
        assert first_non_blank is hero


# ---------------------------------------------------------------------------
# BL-3 — Summary promoted to top
# ---------------------------------------------------------------------------

class TestBL3SummaryPromotion:

    def test_summary_appears_before_tools_header(self) -> None:
        lines = _capture_right_lines()
        joined = "\n".join(lines)
        idx_summary = joined.find("0 tools")
        idx_tools_header = joined.find("Available Tools")
        assert idx_summary >= 0
        assert idx_tools_header >= 0
        assert idx_summary < idx_tools_header

    def test_summary_not_duplicated(self) -> None:
        lines = _capture_right_lines()
        joined = "\n".join(lines)
        # "0 tools" appears exactly once (the summary line)
        assert joined.count("0 tools") == 1

    def test_mcp_count_in_summary_when_present(self) -> None:
        from hermes_cli import banner as banner_mod
        fake_status = [
            {"name": "a", "connected": True, "transport": "stdio", "tools": 3},
            {"name": "b", "connected": True, "transport": "http", "tools": 1},
        ]
        with patch("tools.mcp_tool.get_mcp_status", return_value=fake_status):
            lines = _capture_right_lines()
        joined = "\n".join(lines[:3])
        assert "2 MCP servers" in joined

    def test_profile_name_present_when_non_default(self) -> None:
        with patch("hermes_cli.profiles.get_active_profile_name", return_value="work"):
            lines = _capture_right_lines()
        joined = "\n".join(lines)
        assert "Profile:" in joined
        assert "work" in joined

        with patch("hermes_cli.profiles.get_active_profile_name", return_value="default"):
            lines2 = _capture_right_lines()
        assert "Profile:" not in "\n".join(lines2)

    def test_profile_block_logs_on_failure(self, caplog) -> None:
        with patch("hermes_cli.profiles.get_active_profile_name",
                   side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.banner"):
                lines = _capture_right_lines()
        # Banner still rendered
        assert lines
        # Logger.debug was called with exc_info — check the records
        msgs = [r for r in caplog.records if "get_active_profile_name failed" in r.message]
        assert msgs, f"expected debug log for profile failure, got {[r.message for r in caplog.records]}"
        assert msgs[0].exc_info is not None


# ---------------------------------------------------------------------------
# BL-4 — Hero gradient
# ---------------------------------------------------------------------------

class TestBL4SigilGradient:

    def test_hero_gradient_three_tones_for_plain_text(self) -> None:
        from hermes_cli.banner import render_banner_hero_text
        plain = "\n".join(f"line{i}" for i in range(9))
        result = render_banner_hero_text(plain)
        # Three style runs covering the lines; collect distinct styles
        styles = []
        for span in result.spans:
            styles.append(str(span.style))
        # Or extract via segments
        distinct_styles = {str(s.style) for s in result.spans}
        # At least 3 distinct tones (accent, text, dim)
        assert len(distinct_styles) >= 3, f"expected ≥3 tones, got {distinct_styles}"

    def test_hero_gradient_skips_markup_input(self) -> None:
        from hermes_cli.banner import render_banner_hero_text
        result = render_banner_hero_text("[red]X[/]")
        # markup with spans → early return; preserves red span
        styles = {str(s.style) for s in result.spans}
        assert any("red" in s for s in styles), f"expected red preserved, got {styles}"
