"""Standalone footer/body widget classes for ToolPanel."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual import work
from textual.timer import Timer

_log = logging.getLogger(__name__)

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
    "edit_args",
})

# Recovery action kinds — sorted first in the action row (ER-4).
# edit_args between retry and copy_err per concept §Hint priority.
_RECOVERY_KINDS: tuple[str, ...] = ("retry", "edit_args", "copy_err")
_RECOVERY_ORDER: dict[str, int] = {k: i for i, k in enumerate(_RECOVERY_KINDS)}

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
    "edit_args": "action_edit_args",
}


def _sort_actions_for_render(actions: "list") -> "list":
    """ER-4: recovery first (in _RECOVERY_ORDER), then non-F1 body, then F1 pinned last."""
    recovery = [a for a in actions if a.kind in _RECOVERY_KINDS]
    recovery.sort(key=lambda a: _RECOVERY_ORDER[a.kind])
    rest  = [a for a in actions if a.kind not in _RECOVERY_KINDS]
    f1    = [a for a in rest if a.kind == "help"]
    body  = [a for a in rest if a.kind != "help"]
    return recovery + body + f1


class _ArtifactButton(TooltipMixin, Button):
    """Artifact chip button with tooltip support for full path/URL."""


# Per-category collapsed action strip definitions.
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
    # Built per-call (not cached) so newly-registered tool categories
    # (MCP, dynamic) pick up affordances without invalidation hooks.
    try:
        return _build_collapsed_actions_map().get(category, [("?", "keys")])  # type: ignore[arg-type]
    except Exception:
        _log.exception("collapsed-action map build failed for %r", category)
        return [("?", "keys")]


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


_ACCENT_FALLBACK: str = "#5f87d7"  # used when CSS accent-interactive/primary vars are missing

_SLOW_DEADLINE_S: float = 0.25
_HARD_DEADLINE_S: float = 2.0


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
        self._slow_worker_active: bool = False
        self._hard_timer: "Timer | None" = None
        self._last_tier: "object | None" = None
        self._err_body_locked: bool = False
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

    def mount_static(self, widget: Widget) -> None:
        """ER-3: bypass renderer pipeline — unmount existing children and mount widget verbatim."""
        self.query("*").remove()
        self.mount(widget)
        self._err_body_locked = True

    def apply_density(self, tier: "object") -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier, DensityTier
        if self._err_body_locked:
            return
        if self._renderer is None:
            return
        self._last_tier = tier
        clamp = _clamp_for_tier(tier)  # type: ignore[arg-type]
        if clamp == 0:
            self.query("*").remove()
            return
        if tier == DensityTier.COMPACT:
            self._render_compact_body()
            return
        self._mount_body_with_deadline(tier)

    def _render_compact_body(self) -> None:
        self.query("*").remove()
        self.mount(Static(self._renderer.summary_line(), classes="compact-summary"))

    def _make_slow_placeholder(self, icon: str) -> Widget:
        w = Static(f"{icon}  rendering…")
        w.add_class("slow-placeholder")
        return w

    def _mount_body_with_deadline(self, tier: "object") -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier
        renderer = self._renderer
        clamp = _clamp_for_tier(tier)  # type: ignore[arg-type]
        start = time.monotonic()
        try:
            widget = renderer.build_widget(density=tier, clamp_rows=clamp)
        except Exception:
            _log.exception("renderer %s raised; falling back", type(renderer).__name__)
            from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
            from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
            _dummy_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)
            widget = FallbackRenderer(renderer.payload, _dummy_cls).build_widget(density=tier, clamp_rows=clamp)
        elapsed = time.monotonic() - start
        self.query("*").remove()
        self.mount(widget)
        if elapsed > _SLOW_DEADLINE_S:
            _log.warning(
                "renderer %s exceeded %.0fms on first build; future re-renders will use worker path",
                type(renderer).__name__, elapsed * 1000,
            )

    def _start_slow_render(self, tier: "object") -> None:
        renderer = self._renderer
        self.query("*").remove()
        self.mount(self._make_slow_placeholder(renderer.kind_icon))
        self._slow_worker_active = True
        self._render_in_worker(tier)
        self._hard_timer = self.set_timer(_HARD_DEADLINE_S, self._slow_kill)

    def _slow_kill(self) -> None:
        if not self._slow_worker_active:
            return
        self.app.workers.cancel_group(self, "slow-render")
        self._slow_worker_active = False
        _log.warning("renderer %s hard-deadline 2s exceeded; falling back",
                     type(self._renderer).__name__)
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        _dummy_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)
        fallback = FallbackRenderer(self._renderer.payload, _dummy_cls).build_widget(
            density=self._last_tier, clamp_rows=_clamp_for_tier(self._last_tier)  # type: ignore[arg-type]
        )
        self._swap_in_real_widget(fallback)

    @work(thread=True, exclusive=True, group="slow-render")
    def _render_in_worker(self, tier: "object") -> None:
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier
        renderer = self._renderer
        clamp = _clamp_for_tier(tier)  # type: ignore[arg-type]
        try:
            widget = renderer.build_widget(density=tier, clamp_rows=clamp)
        except Exception:
            _log.exception("worker render raised; falling back")
            from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
            from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
            _dummy_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)
            widget = FallbackRenderer(renderer.payload, _dummy_cls).build_widget(density=tier, clamp_rows=clamp)
        self._slow_worker_active = False
        self.app.call_from_thread(self._swap_in_real_widget, widget)

    def _swap_in_real_widget(self, widget: Widget) -> None:
        if not self._slow_worker_active:
            return
        if self._hard_timer:
            self._hard_timer.stop()
            self._hard_timer = None
        self._slow_worker_active = False
        self.query(".slow-placeholder").remove()
        self.mount(widget)


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
    FooterPane.compact > .artifact-row { display: none; }
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
    FooterPane > .action-row > .--action-chip.--recovery-action {
        color: $accent;
        text-style: bold;
    }
    FooterPane > .action-row > .--action-chip.--recovery-action:hover {
        color: $accent;
        background: $accent 20%;
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
            rs.chips or rs.actions or rs.artifacts
            or (rs.exit_code not in (None, 0))
        )

    def compose(self) -> ComposeResult:
        self._content = Static("", classes="footer-main")
        self._artifact_row = Horizontal(classes="artifact-row")
        self._action_row = Horizontal(classes="action-row")
        from hermes_cli.tui.diff_affordance import DiffAffordance
        self._diff_affordance = DiffAffordance()
        yield self._content
        yield self._artifact_row
        yield self._action_row
        yield self._diff_affordance

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
                    _ac = css.get("accent-interactive") or css.get("primary") or _ACCENT_FALLBACK
                    tone_style = f"bold {_ac}"
                except Exception as exc:
                    _log.debug("accent css lookup failed: %s", exc)
                    tone_style = f"bold {_ACCENT_FALLBACK}"
            parts.append(f" {chip.text} ", style=tone_style)
            remediation = getattr(chip, "remediation", None)
            if remediation:
                parts.append(f" hint: {remediation} ", style="dim italic")

        if any(getattr(a, "payload_truncated", False) for a in summary.actions):
            parts.append(" ⚠ payload truncated ", style="bold " + _TONE_STYLES["warning"])

        # P-4: recovery actions are injected at parse time (inject_recovery_actions in
        # tool_result_parse.py); render uses summary.actions directly without mutation.
        actions_to_render = list(summary.actions)

        self._content.update(parts)

        self._rebuild_action_buttons(summary, actions_to_render if not _is_streaming else [])
        self._rebuild_artifact_buttons(summary)

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
        from textual.css.query import NoMatches
        action_row = getattr(self, "_action_row", None)
        if action_row is None:
            return
        try:
            for btn in list(action_row.query(".--action-chip")):
                btn.remove()
        except NoMatches:
            pass  # no chips mounted yet — expected on first call
        filtered = [a for a in actions_to_render if a.kind in _IMPLEMENTED_ACTIONS]
        filtered = _sort_actions_for_render(filtered)
        if not filtered:
            self.remove_class("has-actions")
            return
        buttons = []
        for action in filtered:
            label = RichText(f"[{action.hotkey}] {action.label}", no_wrap=True)
            cls = "--action-chip"
            if action.kind in _RECOVERY_KINDS:
                cls += " --recovery-action"
            btn = Button(label, classes=cls, name=action.kind)
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
