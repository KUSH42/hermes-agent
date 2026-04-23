"""State → InterruptPayload adapters (R3 Phase B).

Keeps the existing `ChoiceOverlayState` / `SecretOverlayState` /
`UndoOverlayState` wire formats (agent-side depends on them) and converts
them to `InterruptPayload` instances at the overlay boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hermes_cli.tui.overlays.interrupt import (
    InputSpec,
    InterruptChoice,
    InterruptKind,
    InterruptPayload,
)

if TYPE_CHECKING:
    from hermes_cli.tui.state import (
        ChoiceOverlayState,
        SecretOverlayState,
        UndoOverlayState,
    )


def _choices_from_state(state: "ChoiceOverlayState") -> list[InterruptChoice]:
    choices = [InterruptChoice(id=c, label=c) for c in state.choices]
    # F-2: first-char collision check so accelerators are unambiguous
    if __debug__ and choices:
        firsts = [c.id[:1] for c in choices if c.id]
        assert len(firsts) == len(set(firsts)), \
            f"Choice id first-char collision: {[c.id for c in choices]}"
    return choices


def _make_on_resolve(
    state_attr: str,
    app: Any,
    state: Any,
    timeout_value: Any = None,
    cancel_value: Any = None,
):
    """Build an on_resolve callback that puts value on the state queue and clears reactive.

    ``"__cancel__"`` ⇒ explicit escape; uses ``cancel_value``.
    Empty string ⇒ countdown timeout; uses ``timeout_value``.
    """

    def _on_resolve(value: str) -> None:
        try:
            if value == "__cancel__":
                state.response_queue.put(cancel_value)
            elif value == "":
                state.response_queue.put(timeout_value)
            else:
                state.response_queue.put(value)
        except Exception:
            pass
        try:
            setattr(app, state_attr, None)
        except Exception:
            pass

    return _on_resolve


def _adopt_state_deadline(p: InterruptPayload, state: Any) -> InterruptPayload:
    """Adopt the legacy state's epoch deadline so countdown expiry semantics match.

    Also rebases countdown_s to state.remaining so the bar ratio reflects
    remaining time, not the original full duration (C-1 fix).
    """
    try:
        p.deadline = float(state.deadline)
        # Rebase countdown_s to remaining so bar ratio is correct for partially-elapsed prompts.
        remaining = getattr(state, "remaining", None)
        if remaining is not None and remaining > 0:
            p.countdown_s = float(remaining)
    except Exception:
        pass
    return p


def make_clarify_payload(app: Any, state: "ChoiceOverlayState") -> InterruptPayload:
    countdown = max(1, int(state.remaining))
    p = InterruptPayload(
        kind=InterruptKind.CLARIFY,
        title=state.question or "",
        subtitle="",
        countdown_s=float(countdown),
        urgency="info",
        choices=_choices_from_state(state),
        selected=int(state.selected or 0),
        on_resolve=_make_on_resolve("clarify_state", app, state, timeout_value=None),
    )
    p._linked_state = state  # type: ignore[attr-defined]
    return _adopt_state_deadline(p, state)


def make_approval_payload(app: Any, state: "ChoiceOverlayState") -> InterruptPayload:
    countdown = max(1, int(state.remaining))
    p = InterruptPayload(
        kind=InterruptKind.APPROVAL,
        title=state.question or "",
        subtitle="",
        countdown_s=float(countdown),
        urgency="warn",
        choices=_choices_from_state(state),
        selected=int(state.selected or 0),
        diff_text=state.diff_text,
        on_resolve=_make_on_resolve(
            "approval_state", app, state, timeout_value="deny", cancel_value=None
        ),
    )
    p._linked_state = state  # type: ignore[attr-defined]
    return _adopt_state_deadline(p, state)


def make_sudo_payload(app: Any, state: "SecretOverlayState") -> InterruptPayload:
    countdown = max(1, int(state.remaining))
    p = InterruptPayload(
        kind=InterruptKind.SUDO,
        title=state.prompt or "",
        subtitle="",
        countdown_s=float(countdown),
        urgency="warn",
        input_spec=InputSpec(masked=True, placeholder="enter passphrase…"),
        on_resolve=_make_on_resolve("sudo_state", app, state, timeout_value=None),
    )
    return _adopt_state_deadline(p, state)


def make_secret_payload(app: Any, state: "SecretOverlayState") -> InterruptPayload:
    countdown = max(1, int(state.remaining))
    p = InterruptPayload(
        kind=InterruptKind.SECRET,
        title=state.prompt or "",
        subtitle="",
        countdown_s=float(countdown),
        urgency="warn",  # D-1: secret prompts are as sensitive as sudo
        input_spec=InputSpec(masked=True, placeholder="enter secret value…"),
        on_resolve=_make_on_resolve(
            "secret_state", app, state, timeout_value=None
        ),
    )
    return _adopt_state_deadline(p, state)


def make_undo_payload(app: Any, state: "UndoOverlayState") -> InterruptPayload:
    countdown = max(1, int(state.remaining))
    p = InterruptPayload(
        kind=InterruptKind.UNDO,
        title="Undo last turn?",
        subtitle="",
        countdown_s=float(countdown),
        urgency="warn",
        choices=[
            InterruptChoice(id="y", label="y", is_primary=True),
            InterruptChoice(id="n", label="n"),
        ],
        user_text=state.user_text or "",
        has_checkpoint=bool(state.has_checkpoint),
        on_resolve=_make_on_resolve(
            "undo_state", app, state, timeout_value="cancel"
        ),
    )
    return _adopt_state_deadline(p, state)


def make_new_session_payload() -> InterruptPayload:
    """Session-flow — NewSession form. No state dataclass; form drives action."""
    return InterruptPayload(
        kind=InterruptKind.NEW_SESSION,
        title="New Session",
        subtitle="",
        countdown_s=None,
        urgency="info",
        input_spec=InputSpec(masked=False, placeholder="feat/my-feature"),
        on_resolve=None,
    )


def make_merge_confirm_payload(session_id: str, diff_stat: str) -> InterruptPayload:
    return InterruptPayload(
        kind=InterruptKind.MERGE_CONFIRM,
        title=f"Merge session: {session_id}",
        subtitle="",
        countdown_s=None,
        urgency="warn",
        session_id=session_id,
        diff_stat=diff_stat or "(no diff)",
        on_resolve=None,
    )


__all__ = [
    "make_approval_payload",
    "make_clarify_payload",
    "make_merge_confirm_payload",
    "make_new_session_payload",
    "make_secret_payload",
    "make_sudo_payload",
    "make_undo_payload",
]
