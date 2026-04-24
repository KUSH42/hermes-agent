"""InterruptOverlay — canonical interrupt fan-in for R3 Phase B.

Replaces 7 legacy interrupt widgets (ClarifyWidget, ApprovalWidget, SudoWidget,
SecretWidget, UndoConfirmOverlay, NewSessionOverlay, MergeConfirmOverlay)
with a single variant-dispatched pre-mounted overlay.

Spec: /home/xush/.hermes/2026-04-22-tui-v2-R3-overlay-consolidation-spec.md §2.2 / §4.2.

Design:
- Single pre-mounted ``InterruptOverlay`` with ``current_kind: InterruptKind | None``
  reactive. ``present(payload, replace=False)`` is the entry point. When another
  payload is active, new ones queue FIFO unless ``replace=True``.
- ``countdown_s is None`` → no countdown strip; the 2 session-flow kinds
  (NEW_SESSION / MERGE_CONFIRM) skip the tick path entirely.
- Urgency → border class mapping (``--urgency-info|warn|danger``).
- Variant rendering is dispatched to ``_render_<kind>()`` methods which mount
  kind-specific child widgets into the ``#interrupt-body`` container. Old
  per-variant state (diff panel, masked input, session form, merge buttons)
  is preserved verbatim in the variant renderers.

NEW_SESSION and MERGE_CONFIRM use ``countdown_s=None`` intentionally. These
are user-initiated flows (invoked by the user pressing a session button), not
agent-driven interrupts, so there is no agent-side timeout. Timed countdowns
are only appropriate for prompts the agent is blocked on.
"""

from __future__ import annotations

import queue
import time as _time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from hermes_cli.tui.animation import lerp_color
from hermes_cli.tui.widgets.renderers import CopyableRichLog

if TYPE_CHECKING:
    from hermes_cli.tui.state import (
        ChoiceOverlayState,
        SecretOverlayState,
        UndoOverlayState,
    )


# ── InterruptKind ────────────────────────────────────────────────────────────


class InterruptKind(str, Enum):
    """Variant discriminator for InterruptOverlay.

    Inherits ``str`` (StrEnum-equivalent for py<3.11 compat) — compared by
    string value so ``_AliasMeta`` can match on plain strings.
    """

    CLARIFY = "clarify"
    APPROVAL = "approval"
    SUDO = "sudo"
    SECRET = "secret"
    UNDO = "undo"
    NEW_SESSION = "new-session"
    MERGE_CONFIRM = "merge-confirm"


_COUNTDOWN_ALLOWED: frozenset["InterruptKind"] = frozenset({InterruptKind.CLARIFY})

# ── Payload dataclasses ─────────────────────────────────────────────────────


@dataclass
class InterruptChoice:
    """A single selectable option in an interrupt."""

    id: str
    label: str
    is_primary: bool = False
    is_destructive: bool = False


@dataclass
class InputSpec:
    """Input field spec for SUDO / SECRET / NEW_SESSION kinds."""

    masked: bool = False
    placeholder: str = ""
    max_len: int = 0
    validator: Callable[[str], "str | None"] | None = None


@dataclass
class InterruptPayload:
    """Variant-dispatched payload for InterruptOverlay.present()."""

    kind: InterruptKind
    title: str = ""
    subtitle: str = ""
    countdown_s: float | None = None
    urgency: str = "info"  # "info" | "warn" | "danger"
    choices: list[InterruptChoice] = field(default_factory=list)
    selected: int = 0
    diff_text: str | None = None
    input_spec: InputSpec | None = None
    # Kind-specific extras
    user_text: str = ""           # UNDO echo
    has_checkpoint: bool = False  # UNDO
    session_id: str = ""          # MERGE_CONFIRM
    diff_stat: str = ""           # MERGE_CONFIRM
    # Callback. str="" means cancelled / timed out.
    on_resolve: Callable[[str], None] | None = None
    # Deadline epoch (set by present() if countdown_s is not None).
    deadline: float = 0.0
    # C-1: snapshot of remaining seconds when preempted; -1 = fresh (not preempted)
    _remaining_on_preempt: int = field(default=-1, init=False, repr=False)

    @property
    def remaining(self) -> int:
        if self.deadline <= 0:
            return 0
        return max(0, int(self.deadline - _time.monotonic()))

    @property
    def expired(self) -> bool:
        if self.deadline <= 0:
            return False
        return _time.monotonic() >= self.deadline


# ── InterruptOverlay ─────────────────────────────────────────────────────────


_URGENCY_CLASSES = {
    "info":   "--urgency-info",
    "warn":   "--urgency-warn",
    "danger": "--urgency-danger",
}

_MAX_QUEUE_DEPTH = 8


class InterruptOverlay(Widget, can_focus=True):
    """Single pre-mounted overlay fan-in for all 7 interrupt kinds."""

    DEFAULT_CSS = """
    InterruptOverlay {
        layer: interrupt;
        dock: top;
        display: none;
        height: auto;
        max-height: 30;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 20%;
        border-title-align: left;
        border-title-color: $accent;
    }
    InterruptOverlay.--visible { display: block; }
    InterruptOverlay.--urgency-info { border: tall $primary 20%; }
    InterruptOverlay.--urgency-warn { border: tall $warning 40%; }
    InterruptOverlay.--urgency-danger { border: tall $error 60%; }
    InterruptOverlay.--flash-replace { border: tall $warning 80%; }

    InterruptOverlay #interrupt-body { height: auto; }
    InterruptOverlay #interrupt-countdown { height: 1; color: $text-muted; }

    InterruptOverlay #approval-diff {
        height: auto;
        max-height: 16;
        overflow-y: auto;
        border: tall $primary 15%;
        padding: 0 1;
    }
    InterruptOverlay #approval-diff.--hidden { display: none; }
    InterruptOverlay #approval-diff:focus {
        border: tall $accent 80%;
    }
    InterruptOverlay #approval-diff-hint {
        height: 1;
        color: $text-muted;
        display: none;
    }
    InterruptOverlay.--diff-hint-visible #approval-diff-hint {
        display: block;
    }

    InterruptOverlay #ns-error { color: $error; height: 1; }
    InterruptOverlay #ns-base-row, InterruptOverlay #ns-buttons,
    InterruptOverlay #merge-strategy-row, InterruptOverlay #merge-buttons { height: 3; }
    InterruptOverlay #merge-body { height: auto; max-height: 12; overflow-y: auto; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", priority=True, show=False),
        Binding("ctrl+shift+escape", "drain_queue", "Dismiss all", priority=True, show=False),
    ]

    current_kind: reactive["InterruptKind | None"] = reactive(None, repaint=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # FIFO queue of pending payloads.
        self._queue: list[InterruptPayload] = []
        self._current_payload: InterruptPayload | None = None
        self._countdown_timer: Any = None
        self._dismiss_timer: Any = None
        # Track peek state for sudo/secret variants.
        self._unmasked: bool = False
        # Selected index for CLARIFY / APPROVAL / UNDO. Mirrors payload.selected.
        # Merge flow strategy selection.
        self._merge_strategy: str = "squash"
        self._ns_base: str = "current"
        # G-1: block inflight Enter after same-kind replace
        self._enter_blocked_until: float = 0.0
        # A-2: double-Enter guard for destructive approval choices
        self._confirm_destructive_id: str | None = None
        self._confirm_destructive_timer: Any = None

    def compose(self) -> ComposeResult:
        # Single body container; variant renderers mount children into it.
        yield Vertical(id="interrupt-body")
        yield Static("", id="interrupt-countdown")

    # ── Public API ──────────────────────────────────────────────────────────

    def present(
        self,
        payload: "InterruptPayload",
        *,
        replace: bool = False,
        preempt: bool = False,
    ) -> None:
        """Show a payload, queueing if another is already visible.

        - ``replace=False`` (default): if an interrupt is already current,
          append to the FIFO queue.
        - ``replace=True``: swap same-kind payload in place (§7.3 mid-flow
          mutation). If current kind differs, behaves like ``preempt=True``.
        - ``preempt=True``: push current to front of queue, activate new;
          current resumes when the new one resolves.
        """
        if self._current_payload is None:
            self._activate(payload)
            return
        if replace and self._current_payload.kind == payload.kind:
            self._teardown_current(resolve=False, value=None)
            # G-1: signal content change and eat inflight Enter
            payload.selected = 0
            self._enter_blocked_until = _time.monotonic() + 0.25
            self._flash_replace_border()
            try:
                self.call_after_refresh(self._activate, payload)
            except Exception:
                self._activate(payload)
            return
        if replace or preempt:
            prior = self._current_payload
            # C-1: snapshot remaining so resume can rebase instead of using stale epoch
            prior._remaining_on_preempt = max(0, prior.remaining)
            prior.deadline = 0  # force re-deadline on activate
            self._teardown_current(resolve=False, value=None)
            self._queue.insert(0, prior)
            try:
                self.call_after_refresh(self._activate, payload)
            except Exception:
                self._activate(payload)
            return
        # C-3: cap queue depth to _MAX_QUEUE_DEPTH, drop oldest if over limit
        if len(self._queue) >= _MAX_QUEUE_DEPTH:
            dropped = self._queue.pop(0)
            try:
                import logging
                logging.getLogger(__name__).warning(
                    "InterruptOverlay queue cap hit; dropped %s", dropped.kind
                )
            except Exception:
                pass
        self._queue.append(payload)

    def dismiss_current(self, value: str | None = "") -> None:
        """Resolve the current payload (empty ⇒ cancel) and advance the queue."""
        self._teardown_current(resolve=True, value=value)
        if self._queue:
            nxt = self._queue.pop(0)
            # Defer activation to let the AwaitRemove for teardown complete;
            # otherwise remounting same-id children raises DuplicateIds.
            try:
                self.call_after_refresh(self._activate, nxt)
            except Exception:
                self._activate(nxt)

    def action_dismiss(self) -> None:  # BINDINGS
        self.dismiss_current("__cancel__")

    def hide_if_kind(self, kind: "InterruptKind") -> None:
        """Tear down without resolving (used when external state becomes None).

        If ``current_kind`` matches, hide the overlay without invoking the
        payload's ``on_resolve`` (caller already resolved). Advances the
        FIFO queue if entries are waiting.
        """
        if self._current_payload is None:
            return
        if self._current_payload.kind != kind:
            return
        self._teardown_current(resolve=False, value=None)
        if self._queue:
            nxt = self._queue.pop(0)
            try:
                self.call_after_refresh(self._activate, nxt)
            except Exception:
                self._activate(nxt)

    # ── Activation / teardown ───────────────────────────────────────────────

    def _activate(self, payload: "InterruptPayload") -> None:
        self._current_payload = payload
        if payload.countdown_s is not None and payload.countdown_s > 0:
            if payload.deadline <= 0:
                # C-1: use preempted remaining, not stale full countdown_s
                if payload._remaining_on_preempt >= 0:
                    effective = max(1, payload._remaining_on_preempt)
                else:
                    effective = float(payload.countdown_s)
                payload.deadline = _time.monotonic() + effective
                payload._remaining_on_preempt = -1  # reset sentinel

        # Reset selection / strategy defaults per-kind.
        self._unmasked = False
        self._merge_strategy = "squash"
        self._ns_base = "current"

        # Visibility + border urgency.
        self.add_class("--visible")
        self.display = True
        for urg_cls in _URGENCY_CLASSES.values():
            self.remove_class(urg_cls)
        self.add_class(_URGENCY_CLASSES.get(payload.urgency, "--urgency-info"))

        # Border title reactives — only safe when mounted.
        if self.is_mounted:
            try:
                self.border_title = payload.title or ""
                # C-2: show queue depth in subtitle
                depth = len(self._queue)
                if depth > 0:
                    self.border_subtitle = f"+{depth} queued"
                else:
                    self.border_subtitle = payload.subtitle or ""
            except Exception:
                pass

        self.current_kind = payload.kind
        self._render_current()

        # Grab focus so the user can immediately act on the prompt, even if
        # another overlay (AnimConfigPanel, workspace, etc.) previously held
        # focus. InterruptOverlay sits on the dedicated `interrupt` CSS layer
        # above `overlay`, so it visually paints on top too.
        try:
            self.call_after_refresh(self.focus)
        except Exception:
            try:
                self.focus()
            except Exception:
                pass

        # Start countdown timer if applicable (CLARIFY only — APPROVAL/SUDO/SECRET never auto-dismiss).
        self._stop_countdown_timer()
        if (
            payload.countdown_s is not None
            and payload.countdown_s > 0
            and payload.kind in _COUNTDOWN_ALLOWED
        ):
            try:
                self._countdown_timer = self.set_interval(
                    1.0, self._tick_countdown
                )
            except Exception:
                self._countdown_timer = None
            self._refresh_countdown_display()
        else:
            try:
                self.query_one("#interrupt-countdown", Static).update("")
            except NoMatches:
                pass

    def _teardown_current(
        self, *, resolve: bool, value: str | None
    ) -> None:
        """Resolve and tear down the current payload."""
        payload = self._current_payload
        self._stop_countdown_timer()
        self._stop_dismiss_timer()
        if payload is not None and resolve and payload.on_resolve is not None:
            try:
                payload.on_resolve(value if value is not None else "")
            except Exception:
                pass
        # Clear body children.
        try:
            body = self.query_one("#interrupt-body", Vertical)
            for child in list(body.children):
                try:
                    child.remove()
                except Exception:
                    pass
        except NoMatches:
            pass
        try:
            self.query_one("#interrupt-countdown", Static).update("")
        except NoMatches:
            pass
        self._current_payload = None
        self._clear_destructive_confirm()   # sees _current_payload=None → skips refresh
        self._enter_blocked_until = 0.0     # prevent block bleeding to next payload
        self.current_kind = None
        self.remove_class("--visible", "--diff-hint-visible")
        for urg_cls in _URGENCY_CLASSES.values():
            self.remove_class(urg_cls)
        self.display = False

    # ── Countdown ──────────────────────────────────────────────────────────

    def _stop_countdown_timer(self) -> None:
        t = self._countdown_timer
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        self._countdown_timer = None

    def _stop_dismiss_timer(self) -> None:
        t = self._dismiss_timer
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        self._dismiss_timer = None

    def _tick_countdown(self) -> None:
        payload = self._current_payload
        if payload is None or payload.countdown_s is None:
            self._stop_countdown_timer()
            return
        if payload.kind not in _COUNTDOWN_ALLOWED:
            self._stop_countdown_timer()
            return
        # E-1: escalate border urgency when ≤3s remaining
        remaining = payload.remaining
        if remaining <= 3 and not self.has_class("--urgency-danger"):
            self.add_class("--urgency-danger")
        self._refresh_countdown_display()
        if payload.expired:
            # Timeout ⇒ cancel.
            self.dismiss_current("")

    def _refresh_countdown_display(self) -> None:
        payload = self._current_payload
        if payload is None or payload.countdown_s is None:
            return
        try:
            w = self.query_one("#interrupt-countdown", Static)
        except NoMatches:
            return
        total = max(1, int(payload.countdown_s or 1))
        remaining = payload.remaining
        bar_width = max(10, getattr(self.content_size, "width", 40) or 40)
        w.update(self._build_countdown_strip(remaining, total, bar_width))

    @staticmethod
    def _build_countdown_strip(remaining: int, total: int, width: int) -> Text:
        import os as _os
        from rich.style import Style
        no_unicode = _os.environ.get("HERMES_NO_UNICODE", "")

        if remaining > 5:
            bar_color = "#5f87d7"
        elif remaining > 1:
            t = (5.0 - remaining) / 4.0
            bar_color = lerp_color("#5f87d7", "#FFA726", t)
        else:
            bar_color = "#ef5350"

        label = f"{remaining:>2}s"
        label_width = len(label) + 1
        bar_width = max(8, width - label_width)

        result = Text()
        if not no_unicode:
            if remaining <= 1:
                result.append("⚠⚠ ", Style(color="#ef5350", bold=True))
            elif remaining <= 3:
                result.append("⚠ ", Style(color="#FFA726", bold=True))

        ratio = min(1.0, remaining / max(1, total))
        filled = int(bar_width * ratio)
        meniscus = min(3, filled)
        heavy = max(0, filled - meniscus)
        empty = max(0, bar_width - filled)
        if heavy:
            result.append("▓" * heavy, Style(color=bar_color))
        if meniscus:
            result.append("▒" * meniscus, Style(color=bar_color))
        if empty:
            result.append("░" * empty, Style(color="#6e6e6e"))
        result.append(f" {label}", Style(color="#6e6e6e"))
        return result

    # ── Variant rendering ───────────────────────────────────────────────────

    def _render_current(self) -> None:
        payload = self._current_payload
        if payload is None:
            return
        try:
            body = self.query_one("#interrupt-body", Vertical)
        except NoMatches:
            return
        # Clear body.
        for child in list(body.children):
            try:
                child.remove()
            except Exception:
                pass
        kind = payload.kind
        renderer = {
            InterruptKind.CLARIFY: self._render_clarify,
            InterruptKind.APPROVAL: self._render_approval,
            InterruptKind.SUDO: self._render_sudo,
            InterruptKind.SECRET: self._render_secret,
            InterruptKind.UNDO: self._render_undo,
            InterruptKind.NEW_SESSION: self._render_new_session,
            InterruptKind.MERGE_CONFIRM: self._render_merge_confirm,
        }.get(kind)
        if renderer is not None:
            renderer(body, payload)

    def _render_choice_row(self, payload: "InterruptPayload") -> str:
        parts: list[str] = []
        for i, c in enumerate(payload.choices):
            label = c.label or c.id
            if i == payload.selected:
                parts.append(f"[bold #FFD700]\\[ {label} ←\\][/bold #FFD700]")
            else:
                parts.append(f"[dim]\\[ {label} \\][/dim]")
        return "     " + "  ".join(parts)

    def _refresh_choice_static(self, sel_id: str) -> None:
        payload = self._current_payload
        if payload is None:
            return
        try:
            st = self.query_one(f"#{sel_id}", Static)
            st.update(self._render_choice_row(payload))
        except NoMatches:
            pass

    # ── CLARIFY ─────────────────────────────────────────────────────────────

    def _render_clarify(self, body: Vertical, payload: "InterruptPayload") -> None:
        body.mount(Static(f"[dim]?[/dim]  {payload.title}", id="clarify-question"))
        body.mount(Static(self._render_choice_row(payload), id="clarify-choices"))

    # ── APPROVAL ────────────────────────────────────────────────────────────

    def _render_approval(self, body: Vertical, payload: "InterruptPayload") -> None:
        body.mount(Static(f"[dim]![/dim]  {payload.title}", id="approval-question"))
        diff_log = CopyableRichLog(
            id="approval-diff", highlight=False, max_lines=40, wrap=False
        )
        body.mount(diff_log)
        body.mount(Static("  [Tab] scroll diff · [Enter] confirm selection", id="approval-diff-hint"))
        # Defer render; diff_log needs to be mounted first.
        self.call_after_refresh(self._populate_approval_diff)
        body.mount(Static(self._render_choice_row(payload), id="approval-choices"))

    def _populate_approval_diff(self) -> None:
        payload = self._current_payload
        if payload is None:
            return
        try:
            diff_log = self.query_one("#approval-diff", CopyableRichLog)
        except NoMatches:
            return
        if not payload.diff_text:
            diff_log.display = False
            return
        diff_log.display = True
        diff_log.clear()
        try:
            from hermes_cli.tui.body_renderers.diff import DiffRenderer
            from hermes_cli.tui.tool_payload import (
                ClassificationResult,
                ResultKind,
                ToolPayload,
            )
            tp = ToolPayload(
                tool_name="diff",
                category=None,
                args={},
                input_display=None,
                output_raw=payload.diff_text,
            )
            cls_r = ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)
            renderable = DiffRenderer(tp, cls_r).build()
            if renderable is not None:
                diff_log.write(renderable)
        except Exception:
            # Fallback to plain text.
            for line in (payload.diff_text or "").splitlines():
                diff_log.write(line)
        # B-1: show scroll hint when diff is long
        total_lines = len((payload.diff_text or "").splitlines())
        if total_lines > 16:
            diff_log.add_class("--scrollable")
            # Show hint via overlay class (no CSS sibling combinator in Textual 8.x)
            self.add_class("--diff-hint-visible")

    # ── SUDO / SECRET ───────────────────────────────────────────────────────

    def _render_sudo(self, body: Vertical, payload: "InterruptPayload") -> None:
        self._render_masked_input(body, payload, prefix="sudo", marker="#")

    def _render_secret(self, body: Vertical, payload: "InterruptPayload") -> None:
        self._render_masked_input(body, payload, prefix="secret", marker="*")

    def _render_masked_input(
        self, body: Vertical, payload: "InterruptPayload", *, prefix: str, marker: str
    ) -> None:
        spec = payload.input_spec or InputSpec(masked=True, placeholder="enter value…")
        body.mount(Static(f"[dim]{marker}[/dim]  {payload.title}", id=f"{prefix}-prompt"))
        inp = Input(
            password=bool(spec.masked),
            placeholder=spec.placeholder or "enter value…",
            id=f"{prefix}-input",
        )
        body.mount(inp)
        self.call_after_refresh(inp.focus)
        import os as _os
        _sep = "·" if not _os.environ.get("HERMES_NO_UNICODE") else "-"
        body.mount(Static(
            f"[dim]Alt+P reveal temporarily {_sep} Enter submit {_sep} Esc cancel[/dim]",
            id=f"{prefix}-hint",
        ))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        payload = self._current_payload
        if payload is None:
            return
        if payload.kind not in (InterruptKind.SUDO, InterruptKind.SECRET):
            return
        value = event.value
        # Validator errors: cancel/keep; let resolver caller decide.
        spec = payload.input_spec
        if spec is not None and spec.validator is not None:
            err = spec.validator(value)
            if err:
                # Show error via countdown strip slot and keep overlay open.
                try:
                    self.query_one("#interrupt-countdown", Static).update(
                        f"[red]{err}[/red]"
                    )
                except NoMatches:
                    pass
                return
        self.dismiss_current(value)

    def on_key(self, event: Any) -> None:
        payload = self._current_payload
        if payload is None:
            return
        # Masked-input peek (Alt+P) — sudo / secret only.
        if payload.kind in (InterruptKind.SUDO, InterruptKind.SECRET):
            if event.key == "alt+p":
                prefix = "sudo" if payload.kind == InterruptKind.SUDO else "secret"
                try:
                    inp = self.query_one(f"#{prefix}-input", Input)
                    self._unmasked = not self._unmasked
                    inp.password = not self._unmasked
                    if self._unmasked:
                        self.add_class("--unmasked")
                    else:
                        self.remove_class("--unmasked")
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # F-2: single-char accelerators for choice-driven kinds
        if payload.kind in (
            InterruptKind.UNDO, InterruptKind.CLARIFY, InterruptKind.APPROVAL
        ) and len(event.key) == 1 and event.key.isalpha():
            for choice in payload.choices:
                # Match on full id OR first char of id
                if event.key == choice.id or event.key == choice.id[:1]:
                    self.dismiss_current(choice.id)
                    event.prevent_default()
                    return

    def on_blur(self, event: Any) -> None:  # type: ignore[override]
        payload = self._current_payload
        if payload is None:
            return
        if payload.kind in (InterruptKind.SUDO, InterruptKind.SECRET):
            prefix = "sudo" if payload.kind == InterruptKind.SUDO else "secret"
            try:
                self.query_one(f"#{prefix}-input", Input).password = True
            except NoMatches:
                pass
            self.remove_class("--unmasked")
            self._unmasked = False

    # ── UNDO ────────────────────────────────────────────────────────────────

    def _render_undo(self, body: Vertical, payload: "InterruptPayload") -> None:
        body.mount(Static("[dim]<[/dim]  Undo last turn?", id="undo-header"))
        echo_raw = payload.user_text or ""
        echo = echo_raw[:80] + "…" if len(echo_raw) > 80 else echo_raw
        body.mount(
            Static(
                "     This will remove the assistant's last response and re-queue:\n"
                f'     [dim italic]"{echo}"[/dim italic]',
                id="undo-user-text",
            )
        )
        cp_text = (
            "     [dim]+ filesystem checkpoint revert[/dim]"
            if payload.has_checkpoint else ""
        )
        body.mount(Static(cp_text, id="undo-has-checkpoint"))
        body.mount(
            Static(
                "     [bold]\\[y][/bold] Undo and retry    [bold]\\[n][/bold] Cancel"
                "\n     [dim]Press y/n or use Arrow + Enter[/dim]",
                id="undo-choices",
            )
        )

    # ── NEW_SESSION ─────────────────────────────────────────────────────────

    def _render_new_session(self, body: Vertical, payload: "InterruptPayload") -> None:
        body.mount(Static("[bold]New Session[/bold]", id="ns-title"))
        body.mount(Static("Branch name:", id="ns-branch-label"))
        spec = payload.input_spec or InputSpec(placeholder="feat/my-feature")
        inp = Input(placeholder=spec.placeholder or "feat/my-feature", id="ns-branch-input")
        body.mount(inp)
        # Deferred one extra tick so this fires after _activate's call_after_refresh(self.focus).
        # _activate queues self.focus in the same sync turn; by nesting here, inp.focus
        # lands on the following refresh and wins.
        self.call_after_refresh(lambda: self.call_after_refresh(inp.focus))
        body.mount(Static("Base:", id="ns-base-label"))
        base_row = Horizontal(id="ns-base-row")
        body.mount(base_row)
        base_row.mount(
            Button("● current branch", id="ns-base-current", classes="--selected-base")
        )
        base_row.mount(Button("○ main", id="ns-base-main"))
        body.mount(Static("", id="ns-error"))
        btns = Horizontal(id="ns-buttons")
        body.mount(btns)
        btns.mount(Button("[ Create ]", id="ns-create", variant="primary"))
        btns.mount(Button("[ Cancel ]", id="ns-cancel"))

    # ── MERGE_CONFIRM ───────────────────────────────────────────────────────

    def _render_merge_confirm(
        self, body: Vertical, payload: "InterruptPayload"
    ) -> None:
        body.mount(
            Static(
                f"[bold]Merge session:[/bold] {payload.session_id}",
                id="merge-title",
            )
        )
        body.mount(Static(payload.diff_stat or "(no diff)", id="merge-body"))
        strat = Horizontal(id="merge-strategy-row")
        body.mount(strat)
        strat.mount(Button("Merge commit", id="mg-merge"))
        strat.mount(
            Button("● Squash", id="mg-squash", classes="--selected-strategy")
        )
        strat.mount(Button("Rebase", id="mg-rebase"))
        btns = Horizontal(id="merge-buttons")
        body.mount(btns)
        btns.mount(
            Button("[ Merge + close session ]", id="mg-confirm", variant="primary")
        )
        btns.mount(Button("[ Merge only ]", id="mg-merge-only"))
        btns.mount(Button("[ Cancel ]", id="mg-cancel"))

    # ── Button routing (NEW_SESSION / MERGE_CONFIRM) ────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        payload = self._current_payload
        if payload is None:
            return
        btn_id = event.button.id or ""
        if payload.kind == InterruptKind.NEW_SESSION:
            if btn_id == "ns-cancel":
                event.stop()
                self.dismiss_current("")
            elif btn_id == "ns-base-current":
                event.stop()
                self._ns_base = "current"
                self._refresh_base_row()
            elif btn_id == "ns-base-main":
                event.stop()
                self._ns_base = "main"
                self._refresh_base_row()
            elif btn_id == "ns-create":
                event.stop()
                self._do_new_session_create()
        elif payload.kind == InterruptKind.MERGE_CONFIRM:
            if btn_id == "mg-cancel":
                event.stop()
                self.dismiss_current("")
            elif btn_id in ("mg-merge", "mg-squash", "mg-rebase"):
                event.stop()
                self._merge_strategy = btn_id[len("mg-"):]
                self._refresh_strategy_row()
            elif btn_id == "mg-confirm":
                event.stop()
                self._run_merge(payload, close_on_success=True)
            elif btn_id == "mg-merge-only":
                event.stop()
                self._run_merge(payload, close_on_success=False)

    def _set_error(self, msg: str) -> None:
        """Session-flow error display (used by async _create_new_session)."""
        try:
            self.query_one("#ns-error", Static).update(msg)
        except NoMatches:
            pass

    def _flash_replace_border(self) -> None:
        """Briefly add --flash-replace class so the border pulses on same-kind swap."""
        if getattr(self, "app", None) and self.app.has_class("reduced-motion"):
            return
        self.add_class("--flash-replace")
        try:
            self.set_timer(0.3, lambda: self.remove_class("--flash-replace"))
        except Exception:
            self.remove_class("--flash-replace")

    def _refresh_base_row(self) -> None:
        """Update NEW_SESSION base buttons to reflect self._ns_base."""
        for btn_id, value in (("ns-base-current", "current"), ("ns-base-main", "main")):
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                is_sel = (self._ns_base == value)
                label = ("● " if is_sel else "○ ") + ("current branch" if value == "current" else "main")
                btn.label = label
                if is_sel:
                    btn.add_class("--selected-base")
                else:
                    btn.remove_class("--selected-base")
            except Exception:
                pass

    def _refresh_strategy_row(self) -> None:
        """Update MERGE_CONFIRM strategy buttons to reflect self._merge_strategy."""
        strategy_map = {
            "mg-merge":  "merge",
            "mg-squash": "squash",
            "mg-rebase": "rebase",
        }
        label_map = {"merge": "Merge commit", "squash": "Squash", "rebase": "Rebase"}
        for btn_id, value in strategy_map.items():
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                is_sel = (self._merge_strategy == value)
                btn.label = ("● " if is_sel else "○ ") + label_map[value]
                if is_sel:
                    btn.add_class("--selected-strategy")
                else:
                    btn.remove_class("--selected-strategy")
            except Exception:
                pass

    def _clear_destructive_confirm(self) -> None:
        self._confirm_destructive_id = None
        if self._confirm_destructive_timer is not None:
            try:
                self._confirm_destructive_timer.stop()
            except Exception:
                pass
        self._confirm_destructive_timer = None
        # Restore countdown strip (will re-render on next tick)
        if self._current_payload is not None:
            self._refresh_countdown_display()

    def action_drain_queue(self) -> None:
        """Resolve all queued payloads with their timeout_value and hide the overlay."""
        while self._queue:
            queued = self._queue.pop(0)
            if queued.on_resolve is not None:
                try:
                    queued.on_resolve("")  # "" = timeout_value (safest: deny for approval)
                except Exception:
                    pass
        self.dismiss_current("__cancel__")  # resolve the active one too

    def _do_new_session_create(self) -> None:
        try:
            branch = self.query_one("#ns-branch-input", Input).value.strip()
        except NoMatches:
            branch = ""
        if not branch:
            self._set_error("Branch name required.")
            return
        try:
            self.app._svc_sessions.create_new_session(branch, self._ns_base, self)  # type: ignore[attr-defined]
        except Exception as exc:
            self._set_error(str(exc))

    def _run_merge(
        self, payload: "InterruptPayload", *, close_on_success: bool
    ) -> None:
        try:
            self.app._svc_sessions.run_merge(  # type: ignore[attr-defined]
                payload.session_id,
                self._merge_strategy,
                close_on_success=close_on_success,
                overlay=self,
            )
        except Exception:
            pass

    # ── Choice navigation (used by _app_key_handler) ────────────────────────

    def select_choice(self, delta: int) -> None:
        """Move choice selection by delta (-1 up, +1 down). No-op if no choices."""
        payload = self._current_payload
        if payload is None or not payload.choices:
            return
        new_sel = max(0, min(len(payload.choices) - 1, payload.selected + delta))
        if new_sel == payload.selected:
            return
        payload.selected = new_sel
        # Mirror selection to linked legacy state (backward-compat for tests
        # that assert on ChoiceOverlayState.selected after arrow keys).
        linked = getattr(payload, "_linked_state", None)
        if linked is not None:
            try:
                linked.selected = new_sel
            except Exception:
                pass
        sel_id = {
            InterruptKind.CLARIFY: "clarify-choices",
            InterruptKind.APPROVAL: "approval-choices",
            InterruptKind.UNDO: "undo-choices",
        }.get(payload.kind)
        if sel_id is not None:
            self._refresh_choice_static(sel_id)

    def confirm_choice(self) -> None:
        """Resolve the currently-selected choice."""
        # G-1: ignore inflight Enter that was queued before a replace
        if _time.monotonic() < self._enter_blocked_until:
            return
        payload = self._current_payload
        if payload is None or not payload.choices:
            self.dismiss_current("")
            return
        chosen = payload.choices[payload.selected]
        # A-2: double-Enter guard for destructive choices
        if chosen.id in {"always", "session"} and payload.kind == InterruptKind.APPROVAL:
            if self._confirm_destructive_id != chosen.id:
                self._confirm_destructive_id = chosen.id
                if self._confirm_destructive_timer is not None:
                    try:
                        self._confirm_destructive_timer.stop()
                    except Exception:
                        pass
                self._confirm_destructive_timer = self.set_timer(
                    1.5, self._clear_destructive_confirm
                )
                # Show confirmation prompt in countdown strip
                try:
                    self.query_one("#interrupt-countdown", Static).update(
                        f"[bold yellow]⚠ Press Enter again to confirm '{chosen.id}'[/bold yellow]"
                    )
                except Exception:
                    pass
                return
        self._clear_destructive_confirm()
        self.dismiss_current(chosen.id)


# ── Alias registration ─────────────────────────────────────────────────────

# Register the alias names into InterruptOverlay's _css_type_names so
# `query_one(ClarifyWidget)` etc. resolve to the canonical instance.
from hermes_cli.tui.overlays._aliases import register_interrupt_aliases  # noqa: E402

register_interrupt_aliases(InterruptOverlay)


__all__ = [
    "InterruptChoice",
    "InterruptKind",
    "InterruptOverlay",
    "InterruptPayload",
    "InputSpec",
]
