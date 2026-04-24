"""LogRenderer — log line formatter with level token colorization."""
from __future__ import annotations

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


class LogRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    _timestamp_mode: str = "full"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.LOG

    def build(self):
        """Build Rich Text with colorized log levels and skin-aware level colours."""
        from rich.text import Text
        from rich.style import Style
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER, glyph

        raw = self.payload.output_raw or ""
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

        # First pass: find the first parseable timestamp for relative mode
        first_ts_dt: float | None = None
        if ts_mode == "relative":
            import datetime
            for raw_line in raw.splitlines():
                m = _TS_RE.match(raw_line.strip())
                if m:
                    try:
                        ts_str = m.group(1)
                        # Parse the base part (up to seconds) for epoch reference
                        base = ts_str[:19].replace("T", " ")
                        dt = datetime.datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
                        # Add sub-second if present
                        frac_m = re.search(r"\.(\d+)", ts_str)
                        frac = float("0." + frac_m.group(1)) if frac_m else 0.0
                        first_ts_dt = dt.timestamp() + frac
                        break
                    except Exception:
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
                    except Exception:
                        pass
                # "none" mode: skip timestamp entirely
                rest = rest[len(ts_m.group(0)):].lstrip()

            # Find level token
            level_m = _LEVEL_RE.search(rest)
            if level_m:
                before = rest[:level_m.start()]
                level_token = level_m.group(0)
                after = rest[level_m.end():]
                if before:
                    line_t.append(before)
                line_t.append(level_token, style=style_map.get(level_token, Style()))
                line_t.append(after)
                prev_had_signal = True
            else:
                line_t.append(rest)
                prev_had_signal = bool(ts_m)

            line_t.append("\n")
            result.append_text(line_t)

        return result


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    LogRenderer.kind = ResultKind.LOG


_set_kind()
