"""
tests/tui/test_math_renderer.py — 30 tests for math/diagram rendering

Groups:
  A (7): MathRenderer.render_unicode — symbol table + transformations
  B (5): MathRenderer.render_block — PNG output + failure handling
  C (2): render_mermaid — absent CLI + mock success
  D (6): Inline math substitution via ResponseFlowEngine
  E (6): Block math detection in ResponseFlowEngine
  F (4): Mermaid rendering in StreamingCodeBlock
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from hermes_cli.tui.math_renderer import MathRenderer, render_mermaid, _SYMBOL_TABLE
from hermes_cli.tui.response_flow import (
    ResponseFlowEngine,
    _BLOCK_MATH_OPEN_RE,
    _BLOCK_MATH_ONELINE_RE,
    _INLINE_MATH_RE,
)


# ---------------------------------------------------------------------------
# Group A — MathRenderer.render_unicode
# ---------------------------------------------------------------------------

class TestRenderUnicode:
    def setup_method(self) -> None:
        self.r = MathRenderer()

    def test_a1_greek_letters(self) -> None:
        result = self.r.render_unicode(r"\alpha \beta \gamma")
        assert "α" in result
        assert "β" in result
        assert "γ" in result

    def test_a2_operators(self) -> None:
        result = self.r.render_unicode(r"\sum \int \infty")
        assert "∑" in result
        assert "∫" in result
        assert "∞" in result

    def test_a3_superscript_single(self) -> None:
        result = self.r.render_unicode(r"x^2")
        assert "²" in result

    def test_a4_subscript_single(self) -> None:
        result = self.r.render_unicode(r"x_n")
        assert "ₙ" in result

    def test_a5_mathbb_R(self) -> None:
        result = self.r.render_unicode(r"\mathbb{R}")
        assert "ℝ" in result

    def test_a6_unknown_commands_stripped(self) -> None:
        # Unknown command \unknowncmd — backslash and braces stripped but text left
        result = self.r.render_unicode(r"\unknowncmd")
        assert "unknowncmd" in result

    def test_a7_frac(self) -> None:
        result = self.r.render_unicode(r"\frac{a}{b}")
        assert "(a)/(b)" in result


# ---------------------------------------------------------------------------
# Group B — MathRenderer.render_block
# ---------------------------------------------------------------------------

class TestRenderBlock:
    def setup_method(self) -> None:
        self.r = MathRenderer()

    def test_b1_returns_path_on_success(self) -> None:
        path = self.r.render_block(r"E=mc^2")
        if path is None:
            pytest.skip("matplotlib not available")
        try:
            assert path.exists()
            assert path.suffix == ".png"
        finally:
            path.unlink(missing_ok=True)

    def test_b2_returns_none_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"matplotlib": None, "matplotlib.pyplot": None}):
            result = self.r.render_block(r"x^2")
        assert result is None

    def test_b3_file_is_png_when_returned(self) -> None:
        path = self.r.render_block(r"\alpha + \beta")
        if path is None:
            pytest.skip("matplotlib not available")
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
            assert magic == b"\x89PNG", f"Expected PNG magic, got {magic!r}"
        finally:
            path.unlink(missing_ok=True)

    def test_b4_no_exception_on_bad_latex(self) -> None:
        try:
            result = self.r.render_block(r"\notacommand{{{{{")
            if result is not None:
                result.unlink(missing_ok=True)
        except Exception as exc:
            pytest.fail(f"render_block raised unexpectedly: {exc}")

    def test_b5_accepts_already_wrapped_expr(self) -> None:
        # Expr already has $...$; should not double-wrap
        path = self.r.render_block(r"$x + y$")
        if path is None:
            pytest.skip("matplotlib not available")
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Group C — render_mermaid
# ---------------------------------------------------------------------------

class TestRenderMermaid:
    def test_c1_no_cli_returns_none(self) -> None:
        with patch("shutil.which", return_value=None):
            result = render_mermaid("graph TD\n  A-->B")
        assert result is None

    def test_c2_mock_mmdc_success(self, tmp_path: Path) -> None:
        fake_out = tmp_path / "diagram.png"
        fake_out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        def _fake_which(cmd: str) -> str | None:
            return "/usr/bin/mmdc" if cmd == "mmdc" else None

        def _fake_run(cmd: list, **kw: object) -> MagicMock:
            import shutil as _sh
            out_idx = cmd.index("-o") + 1
            _sh.copy(str(fake_out), cmd[out_idx])
            r = MagicMock()
            r.returncode = 0
            return r

        with patch("shutil.which", side_effect=_fake_which):
            with patch("subprocess.run", side_effect=_fake_run):
                result = render_mermaid("graph TD\n  A-->B")
        assert result is not None
        result.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# ResponseFlowEngine fixture helper
# ---------------------------------------------------------------------------

def _make_engine(math_enabled: bool = True, mermaid_enabled: bool = True,
                 math_renderer: str = "unicode") -> ResponseFlowEngine:
    panel = MagicMock()
    panel.app.get_css_variables.return_value = {}
    panel.app._math_enabled = math_enabled
    panel.app._math_renderer = math_renderer
    panel.app._mermaid_enabled = mermaid_enabled
    panel.app._math_dpi = 150
    panel.app._math_max_rows = 12
    panel.response_log = MagicMock()
    panel.response_log.write_with_source = MagicMock()
    panel.response_log._plain_lines = []
    panel.current_prose_log = MagicMock(return_value=panel.response_log)
    panel.is_attached = True
    return ResponseFlowEngine(panel=panel)


# ---------------------------------------------------------------------------
# Group D — Inline math substitution
# ---------------------------------------------------------------------------

class TestInlineMath:
    def test_d1_substitutes_backslash_command(self) -> None:
        engine = _make_engine()
        result = engine._apply_inline_math(r"The value is $\alpha$ here")
        assert "α" in result

    def test_d2_substitutes_caret(self) -> None:
        engine = _make_engine()
        result = engine._apply_inline_math(r"Area is $x^2$ units")
        assert "²" in result

    def test_d3_no_substitute_currency(self) -> None:
        engine = _make_engine()
        result = engine._apply_inline_math("costs $100 off today")
        assert "$100" in result  # unchanged

    def test_d4_no_substitute_shell_var(self) -> None:
        engine = _make_engine()
        result = engine._apply_inline_math("echo $HOME")
        # No backslash, ^, or _ in "HOME" — should not substitute
        assert "$HOME" in result

    def test_d5_not_applied_in_code_state(self) -> None:
        engine = _make_engine()
        engine._state = "IN_CODE"
        captured: list[str] = []
        engine._active_block = MagicMock()
        engine._active_block.append_line.side_effect = lambda l: captured.append(l)
        engine.process_line(r"x = $\alpha$ + 1")
        assert len(captured) == 1
        assert r"\alpha" in captured[0]  # raw line passed through, not substituted

    def test_d5b_inline_double_dollar_simple(self) -> None:
        """$$F = ma$$ embedded in prose line renders as unicode, not raw LaTeX."""
        engine = _make_engine()
        result = engine._apply_inline_math("Newton's Law: $$F = ma$$")
        assert "$$" not in result

    def test_d5c_inline_double_dollar_with_frac(self) -> None:
        """$$\\frac{1}{2}mv^2$$ inline renders unicode and strips delimiters."""
        engine = _make_engine()
        result = engine._apply_inline_math(r"KE: $$\frac{1}{2}mv^2$$")
        assert "$$" not in result
        assert r"\frac" not in result  # rendered, not raw

    def test_d5d_inline_double_dollar_mid_sentence(self) -> None:
        """Text before and after $$...$$ is preserved."""
        engine = _make_engine()
        result = engine._apply_inline_math("where $$E = mc^2$$ is mass-energy")
        assert "where" in result
        assert "mass-energy" in result
        assert "$$" not in result

    def test_d6_guard_disabled_when_math_off(self) -> None:
        engine = _make_engine(math_enabled=False)
        # process_line skips inline math when _math_enabled is False
        written: list[str] = []
        engine._prose_log.write_with_source.side_effect = lambda t, p: written.append(p)
        engine._block_buf = MagicMock()
        engine._block_buf.process_line.return_value = r"$\alpha$"
        engine._block_buf.flush.return_value = None
        engine.process_line(r"$\alpha$")
        # With math off the raw string passes through unchanged
        assert any(r"\alpha" in w for w in written)


# ---------------------------------------------------------------------------
# Group E — Block math detection
# ---------------------------------------------------------------------------

class TestBlockMathDetection:
    def test_e1_double_dollar_transitions_to_in_math(self) -> None:
        engine = _make_engine()
        engine.process_line("$$")
        assert engine._state == "IN_MATH"

    def test_e2_backslash_bracket_open(self) -> None:
        engine = _make_engine()
        engine.process_line(r"\[")
        assert engine._state == "IN_MATH"

    def test_e3_oneline_block_math_no_state_transition(self) -> None:
        engine = _make_engine()
        called: list[str] = []
        engine._flush_math_block = lambda latex: called.append(latex)  # type: ignore[method-assign]
        engine.process_line(r"$$E=mc^2$$")
        assert engine._state == "NORMAL"
        assert len(called) == 1
        assert "E=mc^2" in called[0]

    def test_e4_begin_equation_detected(self) -> None:
        engine = _make_engine()
        engine.process_line(r"\begin{equation}")
        assert engine._state == "IN_MATH"

    def test_e5_flush_clears_unclosed_math(self) -> None:
        engine = _make_engine()
        engine.process_line("$$")
        engine._math_lines = [r"\alpha + \beta"]
        engine.flush()  # must not raise
        assert engine._state == "NORMAL"
        assert engine._math_lines == []

    def test_e6_double_dollar_not_treated_as_code_fence(self) -> None:
        engine = _make_engine()
        engine.process_line("$$")
        assert engine._state == "IN_MATH"
        assert engine._state != "IN_CODE"


# ---------------------------------------------------------------------------
# Group F — Mermaid rendering in StreamingCodeBlock
# ---------------------------------------------------------------------------

class TestMermaidRendering:
    """Tests for the mermaid branch wired into StreamingCodeBlock.complete()."""

    def _scb_bare(self):
        from hermes_cli.tui.widgets import StreamingCodeBlock
        scb = object.__new__(StreamingCodeBlock)
        scb._lang = "mermaid"
        scb._code_lines = ["graph TD", "  A-->B"]
        scb._resolved_lang = None
        scb._state = "STREAMING"
        scb._pygments_theme = "monokai"
        scb._partial_line = ""
        scb._log = MagicMock()
        scb._partial_display = MagicMock()
        scb._collapsed = False
        scb._copy_flash = False
        scb._controls_text_plain = ""
        scb.call_after_refresh = lambda fn, *a: fn(*a)
        scb.add_class = MagicMock()
        scb.refresh = MagicMock()
        return scb

    def test_f1_mermaid_lang_triggers_worker(self) -> None:
        from hermes_cli.tui.widgets import StreamingCodeBlock
        scb = self._scb_bare()
        app_mock = MagicMock()
        app_mock._mermaid_enabled = True
        app_mock._math_max_rows = 24
        app_mock.get_css_variables.return_value = {}
        workers: list[str] = []
        scb._try_render_mermaid_async = lambda: workers.append("started")  # type: ignore[method-assign]
        with patch.object(type(scb), "app", new_callable=PropertyMock, return_value=app_mock):
            scb.complete({"preview-syntax-theme": "monokai"})
        assert "started" in workers

    def test_f2_mermaid_off_config_no_worker(self) -> None:
        from hermes_cli.tui.widgets import StreamingCodeBlock
        scb = self._scb_bare()
        app_mock = MagicMock()
        app_mock._mermaid_enabled = False
        app_mock._math_max_rows = 24
        app_mock.get_css_variables.return_value = {}
        workers: list[str] = []
        scb._try_render_mermaid_async = lambda: workers.append("started")  # type: ignore[method-assign]
        with patch.object(type(scb), "app", new_callable=PropertyMock, return_value=app_mock):
            scb.complete({"preview-syntax-theme": "monokai"})
        assert workers == []

    def test_f3_on_mermaid_rendered_none_no_mount(self) -> None:
        from hermes_cli.tui.widgets import StreamingCodeBlock
        scb = object.__new__(StreamingCodeBlock)
        parent_mock = MagicMock()
        with patch.object(type(scb), "parent", new_callable=PropertyMock, return_value=parent_mock):
            scb._on_mermaid_rendered(None)
        parent_mock.mount.assert_not_called()

    def test_f4_on_mermaid_rendered_mounts_sibling(self, tmp_path: Path) -> None:
        from hermes_cli.tui.widgets import StreamingCodeBlock
        scb = object.__new__(StreamingCodeBlock)
        parent_mock = MagicMock()
        app_mock = MagicMock()
        app_mock._math_max_rows = 24
        fake_png = tmp_path / "diagram.png"
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        with patch.object(type(scb), "parent", new_callable=PropertyMock, return_value=parent_mock):
            with patch.object(type(scb), "app", new_callable=PropertyMock, return_value=app_mock):
                scb._on_mermaid_rendered(fake_png)
        parent_mock.mount.assert_called_once()
