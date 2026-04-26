"""Standalone footer/body widget classes for ToolPanel."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Static

from hermes_cli.tui.io_boundary import safe_open_url
from hermes_cli.tui.resize_utils import THRESHOLD_NARROW, crosses_threshold
from hermes_cli.tui.tooltip import TooltipMixin

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4


def _format_age(elapsed_s: int) -> str:
    if elapsed_s < 60:
        return f"completed {elapsed_s}s ago"
    if elapsed_s < 3600:
        return f"completed {elapsed_s // 60}m ago"
    return f"completed {elapsed_s // 3600}h ago"


_TONE_STYLES: dict[str, str] = {
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "accent": "",  # resolved dynamically
    "neutral": "dim",
}

# Footer action kinds that have real BINDINGS wired.
_IMPLEMENTED_ACTIONS: frozenset[str] = frozenset({
    "copy_body", "open_first", "copy_err", "copy_paths", "retry",
    "copy_invocation", "copy_urls",
    "edit_cmd", "open_url",
})

# Maps every implemented action kind to the ToolPanel method name it calls.
ACTION_KIND_TO_PANEL_METHOD: dict[str, str] = {
    "retry": "action_retry",
    "copy_err": "action_copy_err",
    "open_first": "action_open_primary",
    "copy_body": "action_copy_body",
    "copy_paths": "action_copy_paths",
    "copy_invocation": "action_copy_invocation",
    "copy_urls": "action_copy_urls",
    "edit_cmd": "action_edit_cmd",
    "open_url": "action_open_url",
}


class _ArtifactButton(TooltipMixin, Button):
    """Artifact chip button with tooltip support for full path/URL."""


# Per-category collapsed action strip definitions (lazy-init to avoid import cycle).
_COLLAPSED_ACTIONS: "dict | None" = None


def _build_collapsed_actions_map() -> "dict":
    from hermes_cli.tui.tool_category import ToolCategory
    return {
        ToolCategory.SHELL:  [("r", "retry"), ("e", "err"), ("y", "copy"), ("?", "keys")],
        ToolCategory.FILE:   [("o", "open"), ("y", "copy"), ("?", "keys")],
        ToolCategory.SEARCH: [("y", "copy"), ("o", "open"), ("?", "keys")],
        ToolCategory.WEB:    [("o", "open"), ("y", "copy"), ("?", "keys")],
        ToolCategory.CODE:   [("y", "copy"), ("r", "retry"), ("?", "keys")],
        ToolCategory.AGENT:  [("?", "keys")],
        ToolCategory.MCP:    [("y", "copy"), ("?", "keys")],
    }


def _get_collapsed_actions(category: "object") -> "list[tuple[str, str]]":
    global _COLLAPSED_ACTIONS
    if _COLLAPSED_ACTIONS is None:
        try:
            _COLLAPSED_ACTIONS = _build_collapsed_actions_map()
        except Exception:
            _COLLAPSED_ACTIONS = {}
    return _COLLAPSED_ACTIONS.get(category, [("?", "keys")])  # type: ignore[arg-type]


class _CollapsedActionStrip(Static):
    """One-line action strip shown below header when panel is collapsed+focused."""

    DEFAULT_CSS = """
    _CollapsedActionStrip {
        display: none;
        height: 1;
        color: $text-muted 70%;
        padding: 0 2;
    }
    _CollapsedActionStrip.--visible { display: block; }
    """


def _artifact_icon(kind: str) -> str:
    from agent.display import get_tool_icon_mode as _gim
    _mode = _gim()
    if _mode in ("auto", "nerdfont"):
        _icons = {"file": "", "url": "", "image": ""}
    elif _mode == "emoji":
        _icons = {"file": "📎", "url": "🔗", "image": "🖼"}
    else:
        _icons = {"file": "[F]", "url": "[L]", "image": "[I]"}
    return _icons.get(kind, "[?]")


class BodyPane(Widget):
    """Container for the streaming/static block body."""

    DEFAULT_CSS = "BodyPane { height: auto; }"

    def __init__(
        self,
        block: Widget | None = None,
        category: "object | None" = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._block = block
        self._renderer_degraded: bool = False
        if category is not None:
            try:
                from hermes_cli.tui.body_renderers import (
                    pick_renderer,
                    _STREAMING_EMPTY_CLS,
                )
                from hermes_cli.tui.tool_payload import ToolPayload
                from hermes_cli.tui.services.tools import ToolCallState
                from hermes_cli.tui.tool_panel.density import DensityTier

                _payload = ToolPayload(
                    tool_name="",
                    category=category,
                    args={},
                    input_display=None,
                    output_raw="",
                    line_count=0,
                )
                # Initial phase is STREAMING; pick_renderer is re-invoked on first append_tool_output.
                renderer_cls = pick_renderer(
                    _STREAMING_EMPTY_CLS, _payload,
                    phase=ToolCallState.STREAMING,
                    density=DensityTier.DEFAULT,
                )
                self._renderer = renderer_cls(_payload, _STREAMING_EMPTY_CLS)
            except Exception:
                import logging
                logging.getLogger(__name__).debug(
                    "BodyPane renderer init failed for %r", category, exc_info=True
                )
                from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer
                self._renderer = PlainBodyRenderer()
                self._renderer_degraded = True
        else:
            self._renderer = None

    def on_mount(self) -> None:
        if self._renderer_degraded:
            self.add_class("--body-degraded")

    def _update_preview(self, preview_widget: "Any") -> None:
        block = self._block
        if block is None:
            return
        lines: list[str] = getattr(block, "_all_plain", []) or []
        is_streaming = getattr(block, "_streaming", False) or getattr(block, "_is_streaming", False)
        if not lines:
            return
        if is_streaming:
            tail = lines[-1:]
        else:
            tail = lines[-5:]
        try:
            from rich.text import Text
            t = Text("\n".join(tail))
            preview_widget.update(t)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        if self._block is not None:
            yield self._block


class FooterPane(Widget):
    """Exit-code chip, stat badges, stderr tail, retry hint."""

    DEFAULT_CSS = """
    FooterPane {
        height: auto;
        padding: 0 1;
        display: none;
        color: $text-muted;
        layout: vertical;
    }
    FooterPane > .footer-main { height: 1; }
    FooterPane > .footer-stderr {
        height: auto;
        max-height: 4;
        display: none;
        color: $error 80%;
        padding: 0;
    }
    FooterPane.has-stderr > .footer-stderr { display: block; }
    FooterPane.compact > .footer-stderr { display: none; }
    FooterPane > .footer-remediation {
        height: auto;
        display: none;
        color: $text-muted;
        padding: 0;
    }
    FooterPane.has-remediation > .footer-remediation { display: block; }
    FooterPane > .artifact-row {
        height: auto;
        layout: horizontal;
        display: none;
    }
    FooterPane.has-artifacts > .artifact-row { display: block; }
    FooterPane > .artifact-row > .--artifact-chip {
        height: 1;
        border: none;
        background: transparent;
        min-width: 0;
        color: $accent-muted;
    }
    FooterPane > .action-row {
        height: 1;
        layout: horizontal;
        display: none;
    }
    /* visibility now gated by ToolPanel:focus-within (see hermes.tcss) */
    FooterPane > .action-row > .--action-chip {
        height: 1;
        border: none;
        background: transparent;
        min-width: 0;
        color: $text-muted 80%;
        padding: 0 1;
    }
    FooterPane > .action-row > .--action-chip:hover {
        color: $accent;
        background: $accent 10%;
    }
    """

    COMPONENT_CLASSES = {"footer--exit-chip", "footer--badge", "footer--retry-hint"}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._show_all_artifacts: bool = False
        self._last_summary: "ResultSummaryV4 | None" = None
        self._last_promoted: "frozenset[str]" = frozenset()
        self._last_resize_w: int = 0
        self._diff_kind: str = ""
        self._narrow_diff_glyph: str = "±"
        from hermes_cli.tui.tool_panel.density import DensityTier as _DT
        self._density: "_DT" = _DT.DEFAULT

    def on_mount(self) -> None:
        if getattr(self, "_mounted_once", False):
            raise RuntimeError("FooterPane is not re-mountable; create a new instance")
        self._mounted_once = True

    # ------------------------------------------------------------------
    # DR-3: tier-aware visibility
    # ------------------------------------------------------------------

    def set_density(self, tier: "object") -> None:
        """Update the density tier and refresh visibility accordingly."""
        self._density = tier  # type: ignore[assignment]
        self._refresh_visibility()

    def _refresh_visibility(self) -> None:
        from hermes_cli.tui.tool_panel.density import DensityTier
        if self._density == DensityTier.TRACE:
            if not self._show_all_artifacts:
                self._show_all_artifacts = True
                self._rebuild_chips()
            self.styles.display = "block" if self._has_footer_content() else "none"
            return
        if self._density == DensityTier.COMPACT:
            self.styles.display = "none"
            return
        self.styles.display = "block" if self._has_footer_content() else "none"

    def _has_footer_content(self) -> bool:
        rs = self._last_summary
        if rs is None:
            return False
        return bool(
            rs.chips or rs.stderr_tail or rs.actions or rs.artifacts
            or (rs.exit_code not in (None, 0))
        )

    def compose(self) -> ComposeResult:
        self._content = Static("", classes="footer-main")
        self._stderr_row = Static("", classes="footer-stderr")
        self._remediation_row = Static("", classes="footer-remediation")
        self._artifact_row = Horizontal(classes="artifact-row")
        self._action_row = Horizontal(classes="action-row")
        from hermes_cli.tui.diff_affordance import DiffAffordance
        self._diff_affordance = DiffAffordance()
        yield self._content
        yield self._stderr_row
        yield self._remediation_row
        yield self._artifact_row
        yield self._action_row
        yield self._diff_affordance

    def _render_stderr(self, tail: str) -> "Any":
        from rich.text import Text
        from hermes_cli.tui.body_renderers._grammar import SkinColors as _SC
        _err = _SC.from_app(getattr(self, "app", None)).error
        lines = tail.strip().splitlines()
        result = Text()
        for i, line in enumerate(lines[-8:]):
            if i > 0:
                result.append("\n")
            result.append(f"  {line}", style=f"dim {_err}")
        return result

    def update_summary_v4(
        self,
        summary: "ResultSummaryV4",
        promoted_chip_texts: "frozenset[str]" = frozenset(),
    ) -> None:
        self._last_summary = summary
        self._last_promoted = promoted_chip_texts
        self._render_footer(summary, promoted_chip_texts)

    def _render_footer(
        self,
        summary: "ResultSummaryV4",
        promoted_chip_texts: "frozenset[str]",
    ) -> None:
        from rich.text import Text
        self._diff_kind = getattr(summary, "kind", "") or ""

        parts = Text()

        _block = getattr(getattr(self, "parent", None), "_block", None)
        _is_streaming = (
            _block is not None and
            getattr(_block, "_completed", True) is False
        )

        chips = [c for c in summary.chips if c.text not in promoted_chip_texts]
        for chip in chips:
            tone_style = _TONE_STYLES.get(chip.tone, "dim")
            if not tone_style and chip.tone == "accent":
                try:
                    css = self.app.get_css_variables()
                    _ac = css.get("accent-interactive") or css.get("primary") or "#5f87d7"
                    tone_style = f"bold {_ac}"
                except Exception:
                    tone_style = "bold #5f87d7"
            parts.append(f" {chip.text} ", style=tone_style)
            remediation = getattr(chip, "remediation", None)
            if remediation:
                parts.append(f" hint: {remediation} ", style="dim italic")

        if any(getattr(a, "payload_truncated", False) for a in summary.actions):
            parts.append(" ⚠ payload truncated ", style="bold " + _TONE_STYLES["warning"])

        actions_to_render = list(summary.actions)
        if summary.is_error and not any(a.kind == "retry" for a in actions_to_render):
            from hermes_cli.tui.tool_result_parse import Action as _Action
            actions_to_render.insert(0, _Action(
                label="retry",
                hotkey="r",
                kind="retry",
                payload=None,
            ))

        if summary.stderr_tail and not any(a.kind == "copy_err" for a in actions_to_render):
            from hermes_cli.tui.tool_result_parse import Action as _Action
            actions_to_render.append(_Action(
                label="copy err",
                hotkey="e",
                kind="copy_err",
                payload=None,
            ))

        self._content.update(parts)

        self._rebuild_action_buttons(summary, actions_to_render if not _is_streaming else [])
        self._rebuild_artifact_buttons(summary)

        if summary.stderr_tail:
            self._stderr_row.update(self._render_stderr(summary.stderr_tail))
            self.add_class("has-stderr")
        else:
            self._stderr_row.update("")
            self.remove_class("has-stderr")

        self._remediation_row.update("")
        self.remove_class("has-remediation")

    def _rebuild_chips(self) -> None:
        if self._last_summary is not None:
            self._render_footer(self._last_summary, self._last_promoted)

    def _rebuild_artifact_buttons(self, summary: "ResultSummaryV4") -> None:
        from hermes_cli.tui.tool_result_parse import _ARTIFACT_DISPLAY_CAP
        try:
            for btn in list(self._artifact_row.query(".--artifact-chip")):
                btn.remove()
        except Exception:
            pass
        try:
            for btn in list(self._artifact_row.query(".--artifact-overflow")):
                btn.remove()
        except Exception:
            pass
        try:
            for btn in list(self._artifact_row.query(".--artifact-collapse")):
                btn.remove()
        except Exception:
            pass

        if not summary.artifacts:
            self.remove_class("has-artifacts")
            return

        artifacts_to_show = (
            summary.artifacts
            if self._show_all_artifacts
            else summary.artifacts[:_ARTIFACT_DISPLAY_CAP]
        )
        buttons = []
        for artifact in artifacts_to_show:
            icon = _artifact_icon(artifact.kind)
            label = f"{icon} {artifact.label}"
            btn = _ArtifactButton(label, classes="--artifact-chip")
            btn._artifact_path = artifact.path_or_url  # type: ignore[attr-defined]
            btn._artifact_kind = artifact.kind          # type: ignore[attr-defined]
            btn._tooltip_text = artifact.path_or_url
            buttons.append(btn)

        if (
            not self._show_all_artifacts
            and getattr(summary, "artifacts_truncated", False)
        ):
            n_hidden = len(summary.artifacts) - _ARTIFACT_DISPLAY_CAP
            overflow_artifacts = summary.artifacts[_ARTIFACT_DISPLAY_CAP:]
            if any(a.kind == "url" for a in overflow_artifacts):
                overflow_tooltip = "press u to copy all URLs"
            else:
                overflow_tooltip = "press p to copy paths"
            overflow_btn = Button(f"+{n_hidden} more", classes="--artifact-overflow")
            overflow_btn._overflow_remediation = overflow_tooltip  # type: ignore[attr-defined]
            buttons.append(overflow_btn)

        if self._show_all_artifacts:
            collapse_btn = Button("↑ fewer", classes="--artifact-collapse")
            buttons.append(collapse_btn)

        if buttons:
            self._artifact_row.mount(*buttons)
        self.add_class("has-artifacts")

    def _rebuild_action_buttons(self, summary: "ResultSummaryV4", actions_to_render: list) -> None:
        from rich.text import Text as RichText
        action_row = getattr(self, "_action_row", None)
        if action_row is None:
            return
        try:
            for btn in list(action_row.query(".--action-chip")):
                btn.remove()
        except Exception:
            pass
        filtered = [a for a in actions_to_render if a.kind in _IMPLEMENTED_ACTIONS]
        if not filtered:
            self.remove_class("has-actions")
            return
        buttons = []
        for action in filtered:
            label = RichText(f"[{action.hotkey}] {action.label}", no_wrap=True)
            btn = Button(label, classes="--action-chip", name=action.kind)
            buttons.append(btn)
        if buttons:
            action_row.mount(*buttons)
        self.add_class("has-actions")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        if "--action-chip" in event.button.classes:
            kind = event.button.name
            panel = self.parent
            if panel is not None:
                method_name = ACTION_KIND_TO_PANEL_METHOD.get(kind)
                if method_name is None:
                    if getattr(panel, "is_mounted", False):
                        panel._flash_header("Action unavailable", tone="error")
                else:
                    handler = getattr(panel, method_name, None)
                    if handler is None:
                        if getattr(panel, "is_mounted", False):
                            panel._flash_header("Action unavailable", tone="error")
                    else:
                        try:
                            handler()
                        except Exception:
                            if getattr(panel, "is_mounted", False):
                                panel._flash_header("Action failed", tone="error")
                            raise
            event.stop()
            return
        if "--artifact-overflow" in event.button.classes:
            self._show_all_artifacts = True
            self._rebuild_chips()
            event.stop()
            return
        if "--artifact-collapse" in event.button.classes:
            self._show_all_artifacts = False
            self._rebuild_chips()
            event.stop()
            return
        if "--artifact-chip" in event.button.classes:
            path = getattr(event.button, "_artifact_path", None)
            if path:
                target = path if "://" in path else Path(path).resolve().as_uri()
                safe_open_url(
                    self,
                    target,
                    on_error=lambda exc: (
                        self.parent._flash_header(f"open failed: {exc}", tone="error")
                        if self.parent.is_mounted else None
                    ),
                )
            event.stop()

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        if crosses_threshold(self._last_resize_w, width, THRESHOLD_NARROW):
            self.set_class(width < THRESHOLD_NARROW, "compact")
        self._last_resize_w = width
