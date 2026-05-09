"""Tests for PS-UN-3 right-click paste OS clipboard fallback."""
from __future__ import annotations

import types
from unittest.mock import MagicMock, call, patch


def _make_context_menu_service(app):
    """Return a ContextMenuService instance wired to a stub app."""
    from hermes_cli.tui.services.context_menu import ContextMenuService

    svc = object.__new__(ContextMenuService)
    svc.app = app
    svc._paste_done = True
    return svc


def _make_stub_app(*, clipboard_text: str = "", inp_has_insert_text: bool = True):
    """Build a minimal stub app for context-menu paste tests."""
    mock_inp = MagicMock()
    if inp_has_insert_text:
        mock_inp.insert_text = MagicMock()
    else:
        del mock_inp.insert_text
        mock_inp.value = ""

    app = MagicMock()
    app.clipboard = clipboard_text
    app.query_one.return_value = mock_inp
    app._flash_hint = MagicMock()
    app.set_timer = MagicMock()
    app._clipboard_svc = MagicMock()

    return app, mock_inp


class TestPasteIntoInputOSClipboard:

    def test_right_click_paste_reads_app_clipboard_first(self):
        """When app.clipboard is non-empty, _clipboard_svc.read_text is never called."""
        app, mock_inp = _make_stub_app(clipboard_text="hello from app")
        svc = _make_context_menu_service(app)

        svc.paste_into_input()

        app._clipboard_svc.read_text.assert_not_called()
        mock_inp.insert_text.assert_called_once_with("hello from app")

    def test_right_click_paste_falls_back_to_os_clipboard_when_app_empty(self):
        """When app.clipboard is '', _clipboard_svc.read_text is called with _paste_text_into_input."""
        app, _ = _make_stub_app(clipboard_text="")
        svc = _make_context_menu_service(app)

        svc.paste_into_input()

        app._clipboard_svc.read_text.assert_called_once()
        callback_arg = app._clipboard_svc.read_text.call_args[0][0]
        assert callback_arg == svc._paste_text_into_input

    def test_right_click_paste_inserts_text_at_cursor(self):
        """_paste_text_into_input('hello') calls inp.insert_text('hello') and flashes hint."""
        app, mock_inp = _make_stub_app(clipboard_text="")
        svc = _make_context_menu_service(app)

        svc._paste_text_into_input("hello")

        mock_inp.insert_text.assert_called_once_with("hello")
        app._flash_hint.assert_called_once()
        hint_text = app._flash_hint.call_args[0][0]
        assert "pasted" in hint_text
        assert "5" in hint_text  # len("hello") == 5

    def test_right_click_paste_flashes_empty_hint_when_both_empty(self):
        """_paste_text_into_input('') flashes 'clipboard empty' hint and focuses input."""
        app, mock_inp = _make_stub_app(clipboard_text="")
        svc = _make_context_menu_service(app)

        svc._paste_text_into_input("")

        mock_inp.focus.assert_called()
        app._flash_hint.assert_called_once()
        assert "clipboard empty" in app._flash_hint.call_args[0][0]

    def test_right_click_paste_checking_hint_not_shown_on_fast_read(self):
        """_paste_done=True before the 50 ms timer fires suppresses the checking hint."""
        app, _ = _make_stub_app(clipboard_text="")
        svc = _make_context_menu_service(app)

        # Simulate: paste_into_input arms the timer, but callback fires before it
        svc.paste_into_input()

        # Capture the _show_checking closure that was passed to set_timer
        assert app.set_timer.called
        _delay, show_checking_fn = app.set_timer.call_args[0]

        # Mark paste as done (callback fired fast)
        svc._paste_done = True

        # Now the timer fires — hint should be suppressed
        app._flash_hint.reset_mock()
        show_checking_fn()
        app._flash_hint.assert_not_called()
