"""Math and diagram rendering utilities for the Hermes TUI.

MathRenderer: render LaTeX expressions to PNG (matplotlib.mathtext) or unicode
              symbol approximations (always available, no dependencies).
render_mermaid: render a mermaid diagram to PNG via the mmdc CLI (optional).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Unicode symbol table
# ---------------------------------------------------------------------------

_SYMBOL_TABLE: dict[str, str] = {
    # Greek lowercase
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ",
    r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ",
    r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ",
    r"\sigma": "σ", r"\tau": "τ", r"\upsilon": "υ", r"\phi": "φ",
    r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    # Greek uppercase
    r"\Alpha": "Α", r"\Beta": "Β", r"\Gamma": "Γ", r"\Delta": "Δ",
    r"\Epsilon": "Ε", r"\Theta": "Θ", r"\Lambda": "Λ", r"\Xi": "Ξ",
    r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
    # Operators
    r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
    r"\equiv": "≡", r"\sim": "∼", r"\simeq": "≃", r"\propto": "∝",
    # Set / logic
    r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
    r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
    r"\forall": "∀", r"\exists": "∃", r"\neg": "¬",
    r"\land": "∧", r"\lor": "∨", r"\implies": "⟹", r"\iff": "⟺",
    # Calculus / analysis
    r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇",
    r"\int": "∫", r"\oint": "∮", r"\sum": "∑", r"\prod": "∏",
    r"\sqrt": "√", r"\lim": "lim",
    # Arrows
    r"\to": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐", r"\leftrightarrow": "↔", r"\Leftrightarrow": "⟺",
    r"\uparrow": "↑", r"\downarrow": "↓",
    # Misc
    r"\circ": "∘", r"\bullet": "•", r"\ldots": "…", r"\cdots": "⋯",
    r"\prime": "′", r"\dagger": "†", r"\hbar": "ℏ",
    r"\mathbb{R}": "ℝ", r"\mathbb{N}": "ℕ", r"\mathbb{Z}": "ℤ",
    r"\mathbb{Q}": "ℚ", r"\mathbb{C}": "ℂ",
}

_SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT_MAP   = str.maketrans("0123456789aeijnorstuvx", "₀₁₂₃₄₅₆₇₈₉ₐₑᵢⱼₙₒᵣₛₜᵤᵥₓ")

_FRAC_RE    = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_SUP_BRACE  = re.compile(r"\^{([^{}]+)}")
_SUP_SINGLE = re.compile(r"\^(.)")
_SUB_BRACE  = re.compile(r"_{([^{}]+)}")
_SUB_SINGLE = re.compile(r"_(.)")
_MATHBF_RE  = re.compile(r"\\mathbf\{([^{}]+)\}")
_MATHIT_RE  = re.compile(r"\\mathit\{([^{}]+)\}")

# Bold and italic math char maps (basic ASCII)
_BOLD_OFFSET   = 0x1D400 - ord("A")  # 𝐀
_ITALIC_OFFSET = 0x1D434 - ord("A")  # 𝐴


def _mathbf_char(c: str) -> str:
    if "A" <= c <= "Z":
        return chr(ord(c) + _BOLD_OFFSET)
    if "a" <= c <= "z":
        return chr(ord(c) + (0x1D41A - ord("a")))
    return c


def _mathit_char(c: str) -> str:
    if "A" <= c <= "Z":
        return chr(ord(c) + _ITALIC_OFFSET)
    if "a" <= c <= "z":
        return chr(ord(c) + (0x1D44E - ord("a")))
    return c


class MathRenderer:
    """Render LaTeX math expressions to PNG or unicode approximation."""

    def render_unicode(self, latex: str) -> str:
        """Approximate a LaTeX expression as unicode. Always succeeds."""
        s = latex.strip()
        # 1. Font commands
        s = _MATHBF_RE.sub(lambda m: "".join(_mathbf_char(c) for c in m.group(1)), s)
        s = _MATHIT_RE.sub(lambda m: "".join(_mathit_char(c) for c in m.group(1)), s)
        # 2. \frac{a}{b} → (a)/(b)
        s = _FRAC_RE.sub(lambda m: f"({m.group(1)})/({m.group(2)})", s)
        # 3. Superscripts: ^{expr} or ^x
        def _apply_sup(chars: str) -> str:
            if len(chars) == 1:
                return chars.translate(_SUPERSCRIPT_MAP)
            return "".join(c.translate(_SUPERSCRIPT_MAP) for c in chars)
        s = _SUP_BRACE.sub(lambda m: _apply_sup(m.group(1)), s)
        s = _SUP_SINGLE.sub(lambda m: _apply_sup(m.group(1)), s)
        # 4. Subscripts: _{expr} or _x
        def _apply_sub(chars: str) -> str:
            if len(chars) == 1:
                return chars.translate(_SUBSCRIPT_MAP)
            return "".join(c.translate(_SUBSCRIPT_MAP) for c in chars)
        s = _SUB_BRACE.sub(lambda m: _apply_sub(m.group(1)), s)
        s = _SUB_SINGLE.sub(lambda m: _apply_sub(m.group(1)), s)
        # 5. Symbol table (longest keys first to avoid partial matches)
        for key in sorted(_SYMBOL_TABLE, key=len, reverse=True):
            s = s.replace(key, _SYMBOL_TABLE[key])
        # 6. Strip unresolved LaTeX markup
        s = s.replace("{", "").replace("}", "").replace("\\", "")
        return s

    def render_block(self, latex: str, dpi: int = 150) -> Path | None:
        """Render block math to a PNG file via matplotlib.mathtext.

        Returns the path on success, None on any failure (matplotlib absent,
        parse error, etc.). Caller must delete the file after use.
        """
        try:
            import matplotlib
            import matplotlib.pyplot as plt
            import tempfile
            matplotlib.use("Agg")  # off-screen backend, must be set before pyplot

            expr = latex.strip()
            # mathtext requires $...$ wrapping
            if not (expr.startswith("$") and expr.endswith("$")):
                expr = f"${expr}$"

            fig = plt.figure(figsize=(0.01, 0.01))
            fig.text(0.5, 0.5, expr, fontsize=14, ha="center", va="center",
                     color="white", fontfamily="serif")
            fig.patch.set_alpha(0)

            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="hermes_math_", delete=False
            )
            try:
                fig.savefig(
                    tmp.name, dpi=dpi, bbox_inches="tight",
                    transparent=True, facecolor="none",
                )
                plt.close(fig)
                if Path(tmp.name).stat().st_size > 0:
                    return Path(tmp.name)
                Path(tmp.name).unlink(missing_ok=True)
                return None
            except Exception:
                plt.close(fig)
                Path(tmp.name).unlink(missing_ok=True)
                return None
        except Exception:
            return None


def render_mermaid(src: str) -> Path | None:
    """Render a mermaid diagram via the mmdc CLI. Returns PNG path or None."""
    import shutil
    import subprocess
    import tempfile

    mmdc_path = shutil.which("mmdc")
    npx_path = shutil.which("npx")
    if mmdc_path is None and npx_path is None:
        return None

    inp = tempfile.NamedTemporaryFile(suffix=".mmd", delete=False, mode="w", encoding="utf-8")
    inp.write(src)
    inp.close()
    out = tempfile.NamedTemporaryFile(suffix=".png", prefix="hermes_mermaid_", delete=False)
    out.close()
    try:
        if mmdc_path:
            cmd = [mmdc_path, "-i", inp.name, "-o", out.name, "-b", "transparent"]
        else:
            cmd = ["npx", "-y", "@mermaid-js/mermaid-cli",
                   "-i", inp.name, "-o", out.name, "-b", "transparent"]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode == 0 and Path(out.name).stat().st_size > 0:
            return Path(out.name)
    except Exception:
        pass
    finally:
        Path(inp.name).unlink(missing_ok=True)
    # Leave out file for caller to clean up if it exists, but signal failure
    try:
        Path(out.name).unlink(missing_ok=True)
    except Exception:
        pass
    return None
