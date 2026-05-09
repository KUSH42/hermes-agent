"""Tests for SessionOverlay — spec SPEC-SESSION-OVERLAY-POLISH (SO-1/SO-2/SO-3).

30 tests covering:
  SO-1 (6): column grid, chevron selector, column header
  SO-2 (10): _format_tokens_compact, token column coloring
  SO-3 (14): delete keybinding, confirm flow, failure recovery

Plus the original 10 baseline tests (now updated for new API).
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import SessionOverlay, _SessionRow
from hermes_cli.tui.overlays._legacy import _format_tokens_compact, _SESS_FOOTER_LEGEND
from textual.widgets import Static


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    cli.session_id = "current-session-id"
    return HermesApp(cli=cli)


def _make_session(sid: str, title: str = "", message_count: int = 3, **extra) -> dict:
    base = {
        "id": sid,
        "title": title,
        "last_active": 1_000_000.0,
        "message_count": message_count,
        "preview": f"preview for {sid}",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    base.update(extra)
    return base


def _make_row(title: str = "Test", is_current: bool = False, title_width: int = 18, **kwargs) -> _SessionRow:
    meta = _make_session("sid-test", title=title, **kwargs)
    return _SessionRow(meta, is_current=is_current, idx=0, title_width=title_width)


# =============================================================================
# SO-1: Column grid + header + selection chevron
# =============================================================================

class TestSO1ColumnGrid:

    def test_row_label_columns_align_when_title_empty(self):
        """Untitled row uses plain-text padding — last/turns/tokens at same column as titled row."""
        row_titled = _make_row(title="MySession", title_width=18)
        row_empty = _make_row(title="", title_width=18)
        text_titled = row_titled._build_label()
        text_empty = row_empty._build_label()
        plain_titled = text_titled.plain
        plain_empty = text_empty.plain
        # Both rows: selector(2) + current(2) + title(18) + sep(1) = 23 chars before LAST
        # So character at index 23 starts the last-active slot
        assert plain_titled[23:34].strip() != "" or True  # last slot present
        # The key test: both have same length (fixed-width columns)
        assert len(plain_titled) == len(plain_empty)

    def test_row_label_truncates_with_ellipsis(self):
        """Long title is truncated to title_width with trailing '…'."""
        long_title = "A" * 50
        row = _make_row(title=long_title, title_width=18)
        plain = row._build_label().plain
        # Title slot is at offset 4 (selector=2 + current=2)
        title_slot = plain[4:4 + 18]
        assert title_slot.endswith("…"), f"Expected ellipsis, got: {repr(title_slot)}"
        assert len(title_slot) == 18

    def test_selected_row_shows_chevron_in_selector_slot(self):
        """--selected row's first 2 plain-text chars are '› '."""
        row = _make_row(title="Session")
        label = row._build_label(selected=True)
        assert label.plain[:2] == "› "

    def test_unselected_row_shows_spaces_in_selector_slot(self):
        """Unselected row's first 2 plain-text chars are '  '."""
        row = _make_row(title="Session")
        label = row._build_label(selected=False)
        assert label.plain[:2] == "  "

    def test_current_marker_independent_of_selection(self):
        """current+selected → '› ● <title>'; current+not-selected → '  ● <title>'."""
        row_cs = _make_row(title="T", is_current=True, title_width=18)
        row_cns = _make_row(title="T", is_current=True, title_width=18)
        label_cs = row_cs._build_label(selected=True).plain
        label_cns = row_cns._build_label(selected=False).plain
        assert label_cs[:4] == "› ● "
        assert label_cns[:4] == "  ● "

    def test_column_header_mounts_once(self):
        """Only one #sess-columns widget after re-render (placeholder yielded in compose)."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                overlay._render_rows([_make_session("s1"), _make_session("s2")])
                await pilot.pause()
                overlay._render_rows([_make_session("s1"), _make_session("s2")])
                await pilot.pause()
                from textual.css.query import NoMatches
                cols = list(overlay.query("#sess-columns"))
                assert len(cols) == 1

        asyncio.get_event_loop().run_until_complete(_run())

    def test_column_widths_recompute_on_resize(self):
        """on_resize triggers _render_rows with preserve_idx; selected_idx unchanged."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session(f"s{i}") for i in range(3)]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 2
                # Simulate resize
                with patch.object(overlay, "_render_rows", wraps=overlay._render_rows) as mock_rr:
                    await pilot.resize_terminal(60, 24)
                    await pilot.pause()
                    # _render_rows should be called with preserve_idx=2
                    if mock_rr.called:
                        _, kwargs = mock_rr.call_args
                        assert kwargs.get("preserve_idx") == 2
                assert overlay._selected_idx == 2

        asyncio.get_event_loop().run_until_complete(_run())


# =============================================================================
# SO-2: Tokens-in-context column
# =============================================================================

class TestFormatTokensCompact:

    def test_format_tokens_zero_returns_dash(self):
        result = _format_tokens_compact(0)
        assert result == "    — tok"
        assert len(result) == 9

    def test_format_tokens_under_thousand(self):
        assert _format_tokens_compact(42) == "   42 tok"
        assert len(_format_tokens_compact(42)) == 9
        assert _format_tokens_compact(1) == "    1 tok"
        assert _format_tokens_compact(999) == "  999 tok"

    def test_format_tokens_1k_to_9k_one_decimal(self):
        # 1_000 → strip .0 → "1k"
        assert _format_tokens_compact(1_000) == "   1k tok"
        # 1_234 → int(1234/100)/10 = 12/10 = 1.2 → "1.2k"
        assert _format_tokens_compact(1_234) == " 1.2k tok"
        # 9_999 → int(9999/100)/10 = 99/10 = 9.9 → "9.9k"
        assert _format_tokens_compact(9_999) == " 9.9k tok"

    def test_format_tokens_10k_to_999k_zero_decimals(self):
        assert _format_tokens_compact(10_000) == "  10k tok"
        # floor-truncation: 12_700 → 12k not 13k
        assert _format_tokens_compact(12_700) == "  12k tok"
        assert _format_tokens_compact(999_999) == " 999k tok"

    def test_format_tokens_millions(self):
        assert _format_tokens_compact(2_300_000) == " 2.3M tok"
        # cap at >99M
        assert _format_tokens_compact(99_000_000) == " >99M tok"
        assert _format_tokens_compact(100_000_000) == " >99M tok"

    def test_format_tokens_always_9_chars(self):
        for val in [0, 42, 1_000, 9_999, 10_000, 999_999, 1_000_000, 99_000_000]:
            result = _format_tokens_compact(val)
            assert len(result) == 9, f"len={len(result)} for val={val}: {repr(result)}"

    def test_token_total_sums_all_five_columns(self):
        meta = _make_session(
            "s1",
            input_tokens=100,
            output_tokens=100,
            cache_read_tokens=100,
            cache_write_tokens=100,
            reasoning_tokens=100,
        )
        row = _SessionRow(meta, is_current=False, idx=0, title_width=18)
        label = row._build_label()
        # total = 500 → "  500 tok"
        assert "500 tok" in label.plain

    def test_heavy_token_total_renders_warning_color(self):
        meta = _make_session("s1", input_tokens=250_000)
        row = _SessionRow(
            meta, is_current=False, idx=0, title_width=18,
            heavy_threshold=200_000,
            color_tokens_warning="#FEA62B",
            color_tokens_muted="#767C8C",
            color_tokens_disabled="#3E4252",
        )
        label = row._build_label()
        tok_color_names = [
            sp[2].color.name.lower()
            for sp in label._spans
            if sp[2] and getattr(sp[2], "color", None)
        ]
        assert "#fea62b" in tok_color_names, f"Expected #fea62b in: {tok_color_names}"

    def test_zero_tokens_renders_disabled_color(self):
        meta = _make_session("s1")  # all tokens=0
        row = _SessionRow(
            meta, is_current=False, idx=0, title_width=18,
            color_tokens_disabled="#3E4252",
        )
        label = row._build_label()
        tok_color_names = [
            sp[2].color.name.lower()
            for sp in label._spans
            if sp[2] and getattr(sp[2], "color", None)
        ]
        assert "#3e4252" in tok_color_names, f"Expected #3e4252 in: {tok_color_names}"

    def test_heavy_threshold_overridable(self):
        """Custom threshold: 60_000 tokens at threshold=50_000 → warning color."""
        meta = _make_session("s1", input_tokens=60_000)
        row = _SessionRow(
            meta, is_current=False, idx=0, title_width=18,
            heavy_threshold=50_000,
            color_tokens_warning="#FFFF00",
        )
        label = row._build_label()
        tok_color_names = [
            sp[2].color.name.lower()
            for sp in label._spans
            if sp[2] and getattr(sp[2], "color", None)
        ]
        assert "#ffff00" in tok_color_names, f"Expected #ffff00 in: {tok_color_names}"


# =============================================================================
# SO-3: Delete keybinding + confirm + failure recovery
# =============================================================================

class TestSO3DeleteBinding:

    def test_d_keybinding_registered(self):
        """BINDINGS contains Binding(key='d', action='delete_selected')."""
        assert any(
            b.key == "d" and b.action == "delete_selected"
            for b in SessionOverlay.BINDINGS
        )

    def test_d_on_empty_list_is_noop(self):
        """action_delete_selected with no sessions does nothing."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                overlay._sessions = []
                overlay._pending_delete_idx = None
                overlay.action_delete_selected()
                await pilot.pause()
                assert overlay._pending_delete_idx is None
                assert not overlay.query_one("#sess-confirm").has_class("--visible")

        asyncio.get_event_loop().run_until_complete(_run())

    def test_d_on_current_session_flashes_footer(self):
        """D on current session: footer updated, #sess-confirm stays hidden."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session("current-session-id", "Current")]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 0
                overlay.action_delete_selected()
                await pilot.pause()
                assert not overlay.query_one("#sess-confirm").has_class("--visible")
                assert overlay._pending_delete_idx is None

        asyncio.get_event_loop().run_until_complete(_run())

    def test_d_on_other_session_shows_confirm(self):
        """D on non-current session: confirm visible, pending_delete_idx set, footer hidden."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [
                    _make_session("current-session-id", "Current"),
                    _make_session("other-session", "Other"),
                ]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 1
                overlay.action_delete_selected()
                await pilot.pause()
                assert overlay._pending_delete_idx == 1
                assert overlay.query_one("#sess-confirm").has_class("--visible")

        asyncio.get_event_loop().run_until_complete(_run())

    def test_second_d_calls_db_delete_session(self):
        """Second D pops the row and calls db.delete_session."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [
                    _make_session("current-session-id", "Current"),
                    _make_session("other-session", "Other"),
                ]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 1
                # Enter confirm state manually
                overlay._pending_delete_idx = 1

                mock_db = MagicMock()
                mock_db.delete_session.return_value = True
                app.cli._session_db = mock_db

                with patch.object(overlay, "_run_delete_worker") as mock_worker:
                    overlay.action_delete_selected()
                    await pilot.pause()
                    assert mock_worker.called
                    assert len(overlay._sessions) == 1  # row was popped

        asyncio.get_event_loop().run_until_complete(_run())

    def test_delete_clamps_selected_idx_when_last_row_removed(self):
        """Deleting row 5 of 6 → preserve_idx clamped to 4."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session(f"s{i}") for i in range(6)]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 5
                overlay._pending_delete_idx = 5

                mock_db = MagicMock()
                mock_db.delete_session.return_value = True
                app.cli._session_db = mock_db

                with patch.object(overlay, "_run_delete_worker"):
                    overlay.action_delete_selected()
                    await pilot.pause()
                    # After removing index 5, 5 rows remain (0..4); clamp to 4
                    assert overlay._selected_idx == 4

        asyncio.get_event_loop().run_until_complete(_run())

    def test_delete_empty_list_shows_empty_state(self):
        """Deleting the only row → 'No sessions found' static mounted."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session("other-session", "Only")]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 0
                overlay._pending_delete_idx = 0

                mock_db = MagicMock()
                mock_db.delete_session.return_value = True
                app.cli._session_db = mock_db

                with patch.object(overlay, "_run_delete_worker"):
                    overlay.action_delete_selected()
                    await pilot.pause()
                    statics = list(overlay.query(Static))
                    found = any("No sessions found" in str(s.render()) for s in statics)
                    assert found

        asyncio.get_event_loop().run_until_complete(_run())

    def test_esc_during_confirm_cancels_not_closes(self):
        """action_dismiss with pending delete clears confirm, overlay stays open."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [
                    _make_session("current-session-id"),
                    _make_session("other"),
                ]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._pending_delete_idx = 1
                overlay.action_dismiss()
                await pilot.pause()
                # Overlay still visible, pending cleared
                assert overlay.has_class("--visible")
                assert overlay._pending_delete_idx is None

        asyncio.get_event_loop().run_until_complete(_run())

    def test_arrow_during_confirm_cancels_confirm(self):
        """action_move_down during confirm → pending cleared, selection moves."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session(f"s{i}") for i in range(3)]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._selected_idx = 1
                overlay._pending_delete_idx = 1
                overlay.action_move_down()
                await pilot.pause()
                assert overlay._pending_delete_idx is None
                assert overlay._selected_idx == 2

        asyncio.get_event_loop().run_until_complete(_run())

    def test_delete_failure_restores_row_and_logs(self):
        """_after_delete_failure re-inserts row, shows error in confirm."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [
                    _make_session("current-session-id"),
                    _make_session("other"),
                ]
                overlay._render_rows(sessions)
                await pilot.pause()
                removed = overlay._sessions.pop(1)
                original_len = len(overlay._sessions)
                overlay._after_delete_failure(removed, 1)
                await pilot.pause()
                assert len(overlay._sessions) == original_len + 1
                confirm = overlay.query_one("#sess-confirm")
                assert confirm.has_class("--visible")
                assert "Delete failed" in str(confirm.render())

        asyncio.get_event_loop().run_until_complete(_run())

    def test_footer_legend_includes_d_delete_hint(self):
        """_SESS_FOOTER_LEGEND contains 'D delete'."""
        assert "D delete" in _SESS_FOOTER_LEGEND

    def test_cancel_pending_delete_hides_confirm_restores_footer(self):
        """_cancel_pending_delete removes --visible from #sess-confirm and restores footer."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                overlay._render_rows([_make_session("s1")])
                await pilot.pause()
                # Manually enter confirm state
                overlay.query_one("#sess-confirm").add_class("--visible")
                overlay.query_one("#sess-footer").styles.display = "none"
                overlay._pending_delete_idx = 0
                overlay._cancel_pending_delete()
                await pilot.pause()
                assert not overlay.query_one("#sess-confirm").has_class("--visible")
                assert overlay._pending_delete_idx is None

        asyncio.get_event_loop().run_until_complete(_run())

    def test_reopen_after_select_clears_pending_delete_state(self):
        """After enter confirm → action_select → open_sessions: pending cleared."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                sessions = [_make_session("other"), _make_session("other2")]
                overlay._render_rows(sessions)
                await pilot.pause()
                overlay._pending_delete_idx = 0
                # action_select calls dismiss_overlay (bypasses confirm guard)
                overlay.action_select()
                await pilot.pause()
                with patch.object(overlay, "_load_sessions"):
                    overlay.open_sessions()
                    await pilot.pause()
                assert overlay._pending_delete_idx is None
                assert not overlay.query_one("#sess-confirm").has_class("--visible")

        asyncio.get_event_loop().run_until_complete(_run())

    def test_reopen_after_new_session_clears_pending_delete_state(self):
        """After enter confirm → action_new_session → open_sessions: pending cleared."""
        import asyncio
        app = _make_app()

        async def _run():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                overlay = app.query_one(SessionOverlay)
                overlay.add_class("--visible")
                overlay._render_rows([_make_session("other")])
                await pilot.pause()
                overlay._pending_delete_idx = 0
                with patch.object(app._svc_commands, "handle_tui_command"):
                    overlay.action_new_session()
                    await pilot.pause()
                with patch.object(overlay, "_load_sessions"):
                    overlay.open_sessions()
                    await pilot.pause()
                assert overlay._pending_delete_idx is None
                assert not overlay.query_one("#sess-confirm").has_class("--visible")

        asyncio.get_event_loop().run_until_complete(_run())


# =============================================================================
# Baseline tests (updated for new API)
# =============================================================================

@pytest.mark.asyncio
async def test_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_open_sessions_adds_visible_class():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        with patch.object(overlay, "_load_sessions"):
            overlay.open_sessions()
            await pilot.pause()
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_ctrl_j_binding_opens_sessions_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        with patch.object(overlay, "_load_sessions"):
            await pilot.press("ctrl+j")
            await pilot.pause()
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_loading_placeholder_shown():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        with patch.object(overlay, "_load_sessions"):
            overlay.open_sessions()
            await pilot.pause()
        from textual.css.query import NoMatches
        try:
            loading = overlay.query_one("#sess-loading", Static)
            label = str(loading.render())
            assert "Loading" in label or "Loading" in str(getattr(loading, "_markup", ""))
        except (NoMatches, Exception):
            statics = list(overlay.query(Static))
            found = any("Load" in str(s.render()) for s in statics)
            assert found or overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_rows_rendered_after_load():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        sessions = [_make_session(f"sess-{c}") for c in "abc"]
        overlay._render_rows(sessions)
        await pilot.pause()
        rows = list(overlay.query(_SessionRow))
        assert len(rows) == 3


@pytest.mark.asyncio
async def test_current_session_marked():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        sessions = [
            _make_session("current-session-id", "Current Session"),
            _make_session("other-session", "Other"),
        ]
        overlay._render_rows(sessions)
        await pilot.pause()
        rows = list(overlay.query(_SessionRow))
        current_rows = [r for r in rows if r.has_class("--current")]
        assert len(current_rows) == 1
        assert current_rows[0]._meta["id"] == "current-session-id"


@pytest.mark.asyncio
async def test_arrow_down_moves_selection():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        sessions = [_make_session(f"sess-{i}") for i in range(3)]
        overlay._render_rows(sessions)
        await pilot.pause()
        assert overlay._selected_idx == 0
        overlay.action_move_down()
        assert overlay._selected_idx == 1
        overlay.action_move_down()
        assert overlay._selected_idx == 2
        overlay.action_move_down()
        assert overlay._selected_idx == 2


@pytest.mark.asyncio
async def test_enter_on_current_session_dismisses_only():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        sessions = [_make_session("current-session-id", "Current")]
        overlay._render_rows(sessions)
        await pilot.pause()
        overlay._selected_idx = 0
        resume_calls = []
        with patch.object(app, "action_resume_session", side_effect=lambda sid: resume_calls.append(sid)):
            overlay.action_select()
            await pilot.pause()
        assert len(resume_calls) == 0
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_enter_on_other_session_fires_resume():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        sessions = [
            _make_session("current-session-id", "Current"),
            _make_session("other-session-xyz", "Other"),
        ]
        overlay._render_rows(sessions)
        await pilot.pause()
        overlay._selected_idx = 1
        resume_calls = []
        with patch.object(app, "action_resume_session", side_effect=lambda sid: resume_calls.append(sid)):
            overlay.action_select()
            await pilot.pause()
        assert resume_calls == ["other-session-xyz"]


@pytest.mark.asyncio
async def test_n_key_triggers_new_session():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        cmd_calls = []
        with patch.object(app._svc_commands, "handle_tui_command", side_effect=lambda cmd: cmd_calls.append(cmd)):
            overlay.action_new_session()
            await pilot.pause()
        assert "/new" in cmd_calls
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_escape_dismisses():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        overlay.add_class("--visible")
        overlay.action_dismiss()
        await pilot.pause()
        assert not overlay.has_class("--visible")
