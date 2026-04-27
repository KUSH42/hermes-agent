"""JsonRenderer — pretty-printed JSON using rich.syntax.Syntax."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_DEFAULT_COLLAPSE_THRESHOLD = 200


def _get_collapse_threshold(app) -> int:
    try:
        cfg = app.config if app else {}
        return int((cfg.get("tui") or {}).get("json", {}).get("collapse_threshold", _DEFAULT_COLLAPSE_THRESHOLD))
    except Exception:
        return _DEFAULT_COLLAPSE_THRESHOLD


def _build_summary_text(data, pretty: str):
    from rich.text import Text as RichText
    chars_k = len(pretty) // 1000
    if isinstance(data, dict):
        n = len(data)
        t = RichText(f"{{{{ {n} keys · {chars_k}k chars collapsed · ")
        t.append("[expand]")
        t.append(" }}")
    else:
        n = len(data) if isinstance(data, list) else 1
        t = RichText(f"[ {n} items · {chars_k}k chars collapsed · ")
        t.append("[expand]")
        t.append(" ]")
    return t


class _JsonCollapseWidget:
    """Collapsible JSON view. Child widgets live in __init__ so they exist pre-mount."""

    def __init__(self, summary_text, syntax, full_json: str) -> None:
        from textual.widgets import Static
        self._summary = Static(summary_text)
        self._syntax_view = Static(syntax)
        self._syntax_view.display = False
        self._full_json = full_json

    def compose(self):
        yield self._summary
        yield self._syntax_view

    def _toggle_expand(self) -> None:
        self._syntax_view.display = not self._syntax_view.display


# Upgrade to a proper Textual Widget so it can be mounted in the DOM.
try:
    from textual.widget import Widget as _Widget

    class _JsonCollapseWidget(_Widget):  # type: ignore[no-redef]
        def __init__(self, summary_text, syntax, full_json: str) -> None:
            from textual.widgets import Static
            super().__init__()
            self._summary = Static(summary_text)
            self._syntax_view = Static(syntax)
            self._syntax_view.display = False
            self._full_json = full_json

        def compose(self):
            yield self._summary
            yield self._syntax_view

        def _toggle_expand(self) -> None:
            self._syntax_view.display = not self._syntax_view.display

except ImportError:
    pass


class JsonRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "head"
    kind_icon: ClassVar[str] = "{}"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.JSON

    @classmethod
    def streaming_kind_hint(cls, first_chunk: str) -> "ResultKind | None":
        from hermes_cli.tui.tool_payload import ResultKind
        stripped = first_chunk[:256].lstrip()
        if stripped and stripped[0] in ("{", "["):
            return ResultKind.JSON
        return None

    def _render_parse_failure(self, raw: str, exc: Exception):
        from rich.text import Text
        from rich.console import Group

        line = getattr(exc, "lineno", "?")
        col = getattr(exc, "colno", "?")
        msg = getattr(exc, "msg", str(exc))
        hint = Text(f"JSON parse failed at line {line}:{col} · {msg}", style=self.colors.muted)
        body = Text()
        for ln in raw.splitlines():
            body.append(ln)
            body.append("\n")
        return Group(hint, body)

    def _parse_and_pretty(self, raw: str):
        """Returns (data, pretty_str) or raises."""
        data = json.loads(raw)
        pretty = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
        return data, pretty

    def build(self):
        """Build a Syntax renderable, or a collapse summary Text for large payloads."""
        from rich.syntax import Syntax

        raw = self.payload.output_raw or ""
        try:
            data, pretty = self._parse_and_pretty(raw)
        except (json.JSONDecodeError, MemoryError, ValueError) as e:
            return self._render_parse_failure(raw, e)

        threshold = _get_collapse_threshold(self._app)
        if pretty.count("\n") + 1 > threshold:
            return _build_summary_text(data, pretty)

        return Syntax(
            pretty, "json",
            theme=self.colors.syntax_theme,
            background_color="default",
            word_wrap=False,
        )

    def _json_top_keys(self) -> str:
        import json as _json_mod
        try:
            obj = _json_mod.loads(self.payload.output_raw or "{}")
            keys = list(obj.keys())[:4] if isinstance(obj, dict) else []
            return ", ".join(keys) if keys else "…"
        except Exception:
            return "…"

    def summary_line(self) -> str:
        return f"{{ {self._json_top_keys()} }}"

    def build_widget(self, density=None, clamp_rows=None) -> "object":
        from rich.syntax import Syntax
        from hermes_cli.tui.body_renderers._grammar import build_rule, build_parse_failure, BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        raw = self.payload.output_raw or ""
        try:
            data, pretty = self._parse_and_pretty(raw)
        except (json.JSONDecodeError, MemoryError, ValueError) as e:
            body = build_parse_failure(raw, e, colors=self.colors)
            return BodyFrame(
                header=build_rule("json", colors=self.colors),
                body=body,
                footer=BodyFooter(("y", "copy")),
                density=density,
            )

        threshold = _get_collapse_threshold(self._app)
        if pretty.count("\n") + 1 > threshold:
            summary_text = _build_summary_text(data, pretty)
            syntax = Syntax(
                pretty, "json",
                theme=self.colors.syntax_theme,
                background_color="default",
                word_wrap=False,
            )
            body = _JsonCollapseWidget(summary_text, syntax, pretty)
        else:
            body = Syntax(
                pretty, "json",
                theme=self.colors.syntax_theme,
                background_color="default",
                word_wrap=False,
            )

        return BodyFrame(
            header=build_rule("json", colors=self.colors),
            body=body,
            footer=BodyFooter(("y", "copy")),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    JsonRenderer.kind = ResultKind.JSON


_set_kind()
