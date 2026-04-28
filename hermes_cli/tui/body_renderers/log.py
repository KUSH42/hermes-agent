"""LogRenderer — log line formatter with level token colorization."""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_LEVEL_RE = re.compile(
    r"\b(INFO|WARN(?:ING)?|ERROR|DEBUG|TRACE|FATAL)\b"
)

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

_ISO_PREFIX_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_CONTINUATION_RE = re.compile(r"^(?:\t| {2,})")

# Matches lines that already carry a level chip like "[INFO]", "[WARN]", etc.
_EXISTING_CHIP_RE = re.compile(r"^\[(INFO|WARN|WARNING|ERROR|DEBUG)\]")

# Map canonical level tokens to their chip label
_CHIP_LABEL: dict[str, str] = {
    "INFO":    "INFO",
    "WARN":    "WARN",
    "WARNING": "WARN",
    "ERROR":   "ERROR",
    "FATAL":   "ERROR",
    "DEBUG":   "DEBUG",
    "TRACE":   "DEBUG",
}


class LogRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "tail"
    kind_icon: ClassVar[str] = "📋"
    _timestamp_mode: str = "full"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.LOG

    def _build_body_with_counts(self, raw: str):
        """Build body Text plus (n_info, n_warn, n_err) counts.

        Each line prefixed with a [INFO]/[WARN]/[ERROR]/[DEBUG] chip styled per
        level colour, unless the line already starts with a chip pattern.
        """
        from rich.text import Text
        from rich.style import Style
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER, glyph

        c = self.colors
        style_map = {
            "INFO":    Style(color=c.info),
            "WARN":    Style(color=c.warning),
            "WARNING": Style(color=c.warning),
            "ERROR":   Style(color=c.error),
            "FATAL":   Style(color=c.error, bold=True),
            "DEBUG":   Style(color=c.muted),
            "TRACE":   Style(color=c.muted),
        }

        ts_mode = self._timestamp_mode
        result = Text()
        n_info = n_warn = n_err = 0

        # First pass: find the first parseable timestamp for relative mode
        first_ts_dt: float | None = None
        if ts_mode == "relative":
            import datetime
            for raw_line in raw.splitlines():
                m = _TS_RE.match(raw_line.strip())
                if m:
                    try:
                        ts_str = m.group(1)
                        base = ts_str[:19].replace("T", " ")
                        dt = datetime.datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
                        frac_m = re.search(r"\.(\d+)", ts_str)
                        frac = float("0." + frac_m.group(1)) if frac_m else 0.0
                        first_ts_dt = dt.timestamp() + frac
                        break
                    except Exception:  # timestamp line malformed — skip relative-time annotation
                        pass

        prev_had_signal = False
        for line in raw.splitlines():
            line_t = Text()
            rest = line

            # Continuation line gutter
            if prev_had_signal and _CONTINUATION_RE.match(line):
                gutter_str = glyph(GLYPH_GUTTER) + " "
                line_t.append(gutter_str, style=Style(color=c.muted))
                line_t.append(line.lstrip("\t ").rstrip("\n"))
                line_t.append("\n")
                result.append_text(line_t)
                continue

            # Timestamp prefix
            ts_m = _TS_RE.match(rest)
            if ts_m:
                ts_full = ts_m.group(1)
                if ts_mode == "full":
                    line_t.append(ts_full, style=Style(dim=True))
                    line_t.append(" ")
                elif ts_mode == "relative" and first_ts_dt is not None:
                    import datetime
                    try:
                        base = ts_full[:19].replace("T", " ")
                        dt = datetime.datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
                        frac_m = re.search(r"\.(\d+)", ts_full)
                        frac = float("0." + frac_m.group(1)) if frac_m else 0.0
                        elapsed = dt.timestamp() + frac - first_ts_dt
                        line_t.append(f"+{elapsed:.3f}s", style=Style(dim=True))
                        line_t.append(" ")
                    except Exception:  # noqa: bare-except
                        pass
                # "none" mode: skip timestamp entirely
                rest = rest[len(ts_m.group(0)):].lstrip()

            # Find level token
            level_m = _LEVEL_RE.search(rest)
            if level_m:
                level_token = level_m.group(0)
                before = rest[:level_m.start()]
                after = rest[level_m.end():]
                level_style = style_map.get(level_token, Style())

                # Prefix chip unless line already has one
                if not _EXISTING_CHIP_RE.match(rest):
                    chip_label = _CHIP_LABEL.get(level_token, level_token)
                    line_t.append(f"[{chip_label}]", style=level_style)
                    line_t.append(" ")

                if before:
                    line_t.append(before)
                line_t.append(level_token, style=level_style)
                line_t.append(after)
                prev_had_signal = True

                # Count levels
                norm = level_token.upper()
                if norm == "INFO":
                    n_info += 1
                elif norm in ("WARN", "WARNING"):
                    n_warn += 1
                elif norm in ("ERROR", "FATAL"):
                    n_err += 1
            else:
                line_t.append(rest)
                prev_had_signal = bool(ts_m)

            line_t.append("\n")
            result.append_text(line_t)

        return result, (n_info, n_warn, n_err)

    def build(self):
        """Build Rich Text with colorized log levels and skin-aware level colours."""
        raw = self.payload.output_raw or ""
        result, _ = self._build_body_with_counts(raw)
        return result

    def last_log_line(self, maxlen: int = 60) -> str:
        lines = [l for l in (self.payload.output_raw or "").splitlines() if l.strip()]
        return lines[-1][:maxlen] if lines else ""

    def summary_line(self, *, density=None, cls_result=None) -> str:
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        if density == DensityTier.COMPACT:
            last = self.last_log_line(maxlen=60)
            if not last:
                return "(no output)"
            from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph
            sep = glyph(GLYPH_META_SEP)
            n_lines = len((self.payload.output_raw or "").splitlines())
            return f"{last} {sep} {n_lines} lines"
        last = self.last_log_line(maxlen=60)
        return f"… {last}" if last else "(no output)"

    def build_widget(self, density=None, clamp_rows=None):
        from hermes_cli.tui.body_renderers._grammar import build_rule, BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        raw = self.payload.output_raw or ""
        renderable, counts = self._build_body_with_counts(raw)
        n_info, n_warn, n_err = counts
        return BodyFrame(
            header=build_rule("log", colors=self.colors),
            body=renderable,
            footer=BodyFooter(
                f"INFO {n_info}",
                f"WARN {n_warn}",
                f"ERROR {n_err}",
            ),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    LogRenderer.kind = ResultKind.LOG


_set_kind()
