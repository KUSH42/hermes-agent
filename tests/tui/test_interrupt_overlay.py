"""Tests for InterruptOverlay — canonical 7-kind interrupt overlay (R3 Phase B).

Coverage per spec §6 Phase B:
- present/resolve per kind (7)
- countdown drives auto-resolve (5 countdown kinds)
- queue FIFO when 2nd interrupt arrives while 1st visible (3)
- Approval diff_text panel (4)
- Sudo/Secret masked input + validator (4)
- NewSession form validation (3)
- MergeConfirm conflict display (2)
- urgency → border class (3)
- alias proxy works (4)
"""

from __future__ import annotations

import queue
import time

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.overlays import (
    ApprovalWidget,
    ClarifyWidget,
    InterruptKind,
    InterruptOverlay,
    MergeConfirmOverlay,
    NewSessionOverlay,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)
from hermes_cli.tui.overlays.interrupt import (
    InputSpec,
    InterruptChoice,
    InterruptPayload,
)


# ──────────────────────────────────────────────────────────────────────────
# App fixture
# ──────────────────────────────────────────────────────────────────────────


class _App(App):
    def compose(self) -> ComposeResult:
        yield InterruptOverlay(id="io")


def _make_payload(
    kind: InterruptKind,
    *,
    countdown_s: float | None = 30.0,
    title: str = "test",
    choices: list[InterruptChoice] | None = None,
    on_resolve=None,
    **extra,
) -> InterruptPayload:
    resolved = []
    if on_resolve is None:
        on_resolve = lambda v: resolved.append(v)  # noqa: E731
    payload = InterruptPayload(
        kind=kind,
        title=title,
        countdown_s=countdown_s,
        choices=choices or [],
        on_resolve=on_resolve,
        **extra,
    )
    payload._resolved = resolved  # type: ignore[attr-defined]
    return payload


# ──────────────────────────────────────────────────────────────────────────
# Presence & resolve per kind (7 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clarify_present_and_resolve():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.CLARIFY,
            title="Continue?",
            choices=[InterruptChoice("yes", "yes"), InterruptChoice("no", "no")],
        )
        ov.present(p)
        await pilot.pause()
        assert ov.current_kind == InterruptKind.CLARIFY
        assert ov.has_class("--visible")
        ov.confirm_choice()  # resolves selected (yes)
        await pilot.pause()
        assert p._resolved == ["yes"]
        assert ov.current_kind is None


@pytest.mark.asyncio
async def test_approval_present_and_resolve():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.APPROVAL,
            title="Run rm -rf?",
            choices=[
                InterruptChoice("once", "once"),
                InterruptChoice("deny", "deny"),
            ],
            diff_text="-a\n+b\n",
        )
        ov.present(p)
        await pilot.pause()
        assert ov.current_kind == InterruptKind.APPROVAL
        ov.confirm_choice()
        await pilot.pause()
        assert p._resolved == ["once"]


@pytest.mark.asyncio
async def test_sudo_present_and_resolve_via_input_submit():
    from textual.widgets import Input

    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.SUDO,
            title="password:",
            input_spec=InputSpec(masked=True, placeholder="…"),
        )
        ov.present(p)
        await pilot.pause()
        inp = ov.query_one("#sudo-input", Input)
        assert inp.password is True
        # Simulate Enter submission
        inp.value = "hunter2"
        await inp.action_submit()
        await pilot.pause()
        assert p._resolved == ["hunter2"]


@pytest.mark.asyncio
async def test_secret_present_and_resolve():
    from textual.widgets import Input

    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.SECRET,
            title="API key:",
            input_spec=InputSpec(masked=True, placeholder="…"),
        )
        ov.present(p)
        await pilot.pause()
        inp = ov.query_one("#secret-input", Input)
        inp.value = "sk-123"
        await inp.action_submit()
        await pilot.pause()
        assert p._resolved == ["sk-123"]


@pytest.mark.asyncio
async def test_undo_present_and_resolve():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.UNDO,
            title="Undo?",
            countdown_s=10.0,
            user_text="last user message",
            has_checkpoint=True,
            choices=[InterruptChoice("y", "y"), InterruptChoice("n", "n")],
        )
        ov.present(p)
        await pilot.pause()
        # Verify user_text rendered
        from textual.widgets import Static
        txt = str(ov.query_one("#undo-user-text", Static).renderable
                  if hasattr(ov.query_one("#undo-user-text", Static), "renderable")
                  else ov.query_one("#undo-user-text", Static).content)
        assert "last user message" in txt
        ov.confirm_choice()
        await pilot.pause()
        assert p._resolved == ["y"]


@pytest.mark.asyncio
async def test_new_session_present_shows_form():
    from textual.widgets import Input

    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.NEW_SESSION,
            title="New Session",
            countdown_s=None,
            input_spec=InputSpec(placeholder="feat/foo"),
        )
        ov.present(p)
        await pilot.pause()
        # Form present
        assert ov.query_one("#ns-branch-input", Input) is not None
        assert ov.current_kind == InterruptKind.NEW_SESSION


@pytest.mark.asyncio
async def test_merge_confirm_present_shows_strategy():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.MERGE_CONFIRM,
            title="Merge session: abc",
            countdown_s=None,
            session_id="abc",
            diff_stat="3 files changed",
        )
        ov.present(p)
        await pilot.pause()
        from textual.widgets import Button
        assert ov.query_one("#mg-squash", Button) is not None
        assert ov.current_kind == InterruptKind.MERGE_CONFIRM


# ──────────────────────────────────────────────────────────────────────────
# Countdown drives auto-resolve (5 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_countdown_expiry_cancels_clarify():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.CLARIFY,
            countdown_s=0.001,  # immediate expiry
            choices=[InterruptChoice("a", "a")],
        )
        ov.present(p)
        # Force deadline in the past and tick.
        p.deadline = time.monotonic() - 1
        ov._tick_countdown()
        await pilot.pause()
        assert p._resolved == [""]  # empty string = cancel/timeout


@pytest.mark.asyncio
async def test_countdown_expiry_approval():
    """APPROVAL never auto-dismisses via countdown — only CLARIFY does."""
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.APPROVAL,
            countdown_s=0.001,
            choices=[InterruptChoice("deny", "deny")],
        )
        ov.present(p)
        p.deadline = time.monotonic() - 1
        ov._tick_countdown()
        await pilot.pause()
        assert p._resolved == []  # APPROVAL does not auto-dismiss


@pytest.mark.asyncio
async def test_countdown_expiry_sudo():
    """SUDO never auto-dismisses via countdown — only CLARIFY does."""
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(InterruptKind.SUDO, countdown_s=0.001)
        ov.present(p)
        p.deadline = time.monotonic() - 1
        ov._tick_countdown()
        await pilot.pause()
        assert p._resolved == []  # SUDO does not auto-dismiss


@pytest.mark.asyncio
async def test_countdown_expiry_secret():
    """SECRET never auto-dismisses via countdown — only CLARIFY does."""
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(InterruptKind.SECRET, countdown_s=0.001)
        ov.present(p)
        p.deadline = time.monotonic() - 1
        ov._tick_countdown()
        await pilot.pause()
        assert p._resolved == []  # SECRET does not auto-dismiss


@pytest.mark.asyncio
async def test_countdown_expiry_undo():
    """UNDO never auto-dismisses via countdown — only CLARIFY does."""
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.UNDO, countdown_s=0.001,
            choices=[InterruptChoice("y", "y"), InterruptChoice("n", "n")],
        )
        ov.present(p)
        p.deadline = time.monotonic() - 1
        ov._tick_countdown()
        await pilot.pause()
        assert p._resolved == []  # UNDO does not auto-dismiss


# ──────────────────────────────────────────────────────────────────────────
# FIFO queue (3 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_second_interrupt_queues_behind_first():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p1 = _make_payload(
            InterruptKind.CLARIFY, title="first",
            choices=[InterruptChoice("a", "a")],
        )
        p2 = _make_payload(
            InterruptKind.CLARIFY, title="second",
            choices=[InterruptChoice("b", "b")],
        )
        ov.present(p1)
        ov.present(p2)  # should queue (no replace)
        await pilot.pause()
        assert ov.current_kind == InterruptKind.CLARIFY
        assert ov._current_payload is p1
        assert len(ov._queue) == 1


@pytest.mark.asyncio
async def test_queue_advances_on_resolve():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p1 = _make_payload(
            InterruptKind.CLARIFY, title="first",
            choices=[InterruptChoice("a", "a")],
        )
        p2 = _make_payload(
            InterruptKind.CLARIFY, title="second",
            choices=[InterruptChoice("b", "b")],
        )
        ov.present(p1)
        ov.present(p2)
        await pilot.pause()
        ov.confirm_choice()
        await pilot.pause()
        assert p1._resolved == ["a"]
        assert ov._current_payload is p2


@pytest.mark.asyncio
async def test_preempt_pushes_current_to_front():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p1 = _make_payload(
            InterruptKind.APPROVAL, title="approval",
            choices=[InterruptChoice("once", "once")],
        )
        p2 = _make_payload(
            InterruptKind.UNDO, title="undo",
            choices=[InterruptChoice("y", "y"), InterruptChoice("n", "n")],
        )
        ov.present(p1)
        ov.present(p2, preempt=True)
        await pilot.pause()
        assert ov._current_payload is p2
        assert ov._queue[0] is p1


# ──────────────────────────────────────────────────────────────────────────
# Approval diff panel (4 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_diff_log_present_when_diff_text():
    from hermes_cli.tui.widgets.renderers import CopyableRichLog
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, title="q", diff_text="-x\n+y\n",
            choices=[InterruptChoice("once", "once")],
        ))
        await pilot.pause()
        # diff log widget is present
        assert ov.query_one("#approval-diff", CopyableRichLog) is not None


@pytest.mark.asyncio
async def test_approval_diff_log_hidden_when_no_diff():
    from hermes_cli.tui.widgets.renderers import CopyableRichLog
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, title="q", diff_text=None,
            choices=[InterruptChoice("once", "once")],
        ))
        await pilot.pause()
        dl = ov.query_one("#approval-diff", CopyableRichLog)
        assert dl.display is False


@pytest.mark.asyncio
async def test_approval_diff_log_scrollable():
    from hermes_cli.tui.widgets.renderers import CopyableRichLog
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, title="q", diff_text="line\n" * 50,
            choices=[InterruptChoice("once", "once")],
        ))
        await pilot.pause()
        dl = ov.query_one("#approval-diff", CopyableRichLog)
        # CopyableRichLog / RichLog can scroll_up/down without error.
        dl.scroll_down()
        dl.scroll_up()


@pytest.mark.asyncio
async def test_approval_choices_row_rendered():
    from textual.widgets import Static
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, title="q", diff_text=None,
            choices=[
                InterruptChoice("once", "once"),
                InterruptChoice("deny", "deny"),
            ],
        ))
        await pilot.pause()
        st = ov.query_one("#approval-choices", Static)
        rendered = st.renderable if hasattr(st, "renderable") else st.content
        s = str(rendered)
        assert "once" in s
        assert "deny" in s


# ──────────────────────────────────────────────────────────────────────────
# Sudo/Secret masked input + validator (4 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sudo_input_masked_by_default():
    from textual.widgets import Input
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.SUDO, title="pw",
            input_spec=InputSpec(masked=True),
        ))
        await pilot.pause()
        assert ov.query_one("#sudo-input", Input).password is True


@pytest.mark.asyncio
async def test_secret_input_masked_by_default():
    from textual.widgets import Input
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.SECRET, title="key",
            input_spec=InputSpec(masked=True),
        ))
        await pilot.pause()
        assert ov.query_one("#secret-input", Input).password is True


@pytest.mark.asyncio
async def test_sudo_validator_error_keeps_overlay_open():
    from textual.widgets import Input
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.SUDO, title="pw",
            input_spec=InputSpec(
                masked=True,
                validator=lambda v: "too short" if len(v) < 3 else None,
            ),
        )
        ov.present(p)
        await pilot.pause()
        inp = ov.query_one("#sudo-input", Input)
        inp.value = "ab"
        await inp.action_submit()
        await pilot.pause()
        # validator error → not resolved
        assert p._resolved == []
        assert ov.current_kind == InterruptKind.SUDO


@pytest.mark.asyncio
async def test_sudo_validator_pass_resolves():
    from textual.widgets import Input
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        p = _make_payload(
            InterruptKind.SUDO, title="pw",
            input_spec=InputSpec(
                masked=True,
                validator=lambda v: None,
            ),
        )
        ov.present(p)
        await pilot.pause()
        inp = ov.query_one("#sudo-input", Input)
        inp.value = "longenough"
        await inp.action_submit()
        await pilot.pause()
        assert p._resolved == ["longenough"]


# ──────────────────────────────────────────────────────────────────────────
# NewSession form validation (3 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_session_create_requires_branch():
    from textual.widgets import Input, Static
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.NEW_SESSION, title="New Session", countdown_s=None,
            input_spec=InputSpec(placeholder="feat/foo"),
        ))
        await pilot.pause()
        # Empty branch → error
        ov._do_new_session_create()
        await pilot.pause()
        err = ov.query_one("#ns-error", Static)
        rendered = str(err.renderable if hasattr(err, "renderable") else err.content)
        assert "required" in rendered.lower()


@pytest.mark.asyncio
async def test_new_session_base_button_selection():
    from textual.widgets import Button
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.NEW_SESSION, title="New Session", countdown_s=None,
        ))
        await pilot.pause()
        # Default base "current"
        assert ov._ns_base == "current"
        # Press main button via on_button_pressed
        from textual.widgets import Button as _Btn

        class _Evt:
            button = ov.query_one("#ns-base-main", Button)
            def stop(self): pass
        ov.on_button_pressed(_Evt())
        assert ov._ns_base == "main"


@pytest.mark.asyncio
async def test_new_session_cancel_dismisses():
    from textual.widgets import Button
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.NEW_SESSION, title="New Session", countdown_s=None,
        ))
        await pilot.pause()

        class _Evt:
            button = ov.query_one("#ns-cancel", Button)
            def stop(self): pass
        ov.on_button_pressed(_Evt())
        await pilot.pause()
        assert ov.current_kind is None


# ──────────────────────────────────────────────────────────────────────────
# MergeConfirm conflict/diff (2 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_confirm_diff_stat_displayed():
    from textual.widgets import Static
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.MERGE_CONFIRM, title="merge",
            countdown_s=None, session_id="sess1",
            diff_stat="foo.py | 3 ++-",
        ))
        await pilot.pause()
        body = ov.query_one("#merge-body", Static)
        s = str(body.renderable if hasattr(body, "renderable") else body.content)
        assert "foo.py" in s


@pytest.mark.asyncio
async def test_merge_confirm_strategy_selection():
    from textual.widgets import Button
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.MERGE_CONFIRM, title="merge",
            countdown_s=None, session_id="sess1", diff_stat="(none)",
        ))
        await pilot.pause()
        assert ov._merge_strategy == "squash"

        class _Evt:
            button = ov.query_one("#mg-rebase", Button)
            def stop(self): pass
        ov.on_button_pressed(_Evt())
        assert ov._merge_strategy == "rebase"


# ──────────────────────────────────────────────────────────────────────────
# Urgency → border class (3 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_urgency_info_sets_info_class():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.CLARIFY, urgency="info",
            choices=[InterruptChoice("a", "a")],
        ))
        await pilot.pause()
        assert ov.has_class("--urgency-info")
        assert not ov.has_class("--urgency-warn")


@pytest.mark.asyncio
async def test_urgency_warn_sets_warn_class():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, urgency="warn",
            choices=[InterruptChoice("a", "a")],
        ))
        await pilot.pause()
        assert ov.has_class("--urgency-warn")


@pytest.mark.asyncio
async def test_urgency_danger_sets_danger_class():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL, urgency="danger",
            choices=[InterruptChoice("a", "a")],
        ))
        await pilot.pause()
        assert ov.has_class("--urgency-danger")


# ──────────────────────────────────────────────────────────────────────────
# Alias proxies (4 tests)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_query_one_returns_canonical():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        # query_one(ClarifyWidget) must resolve to the canonical overlay.
        via_alias = pilot.app.query_one(ClarifyWidget)
        assert via_alias is ov


@pytest.mark.asyncio
async def test_isinstance_clarify_matches_only_in_clarify_mode():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.CLARIFY,
            choices=[InterruptChoice("a", "a")],
        ))
        await pilot.pause()
        assert isinstance(ov, ClarifyWidget)
        assert not isinstance(ov, ApprovalWidget)


@pytest.mark.asyncio
async def test_isinstance_approval_matches_only_in_approval_mode():
    async with _App().run_test() as pilot:
        ov = pilot.app.query_one(InterruptOverlay)
        ov.present(_make_payload(
            InterruptKind.APPROVAL,
            choices=[InterruptChoice("once", "once")],
        ))
        await pilot.pause()
        assert isinstance(ov, ApprovalWidget)
        assert not isinstance(ov, SudoWidget)


@pytest.mark.asyncio
async def test_alias_resolves_all_seven_interrupt_names():
    # All 7 alias names are importable and resolve via _AliasMeta.
    for cls in (
        ClarifyWidget,
        ApprovalWidget,
        SudoWidget,
        SecretWidget,
        UndoConfirmOverlay,
        NewSessionOverlay,
        MergeConfirmOverlay,
    ):
        assert cls.__name__ in InterruptOverlay._css_type_names
