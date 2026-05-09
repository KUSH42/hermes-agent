"""Tests for PS-UN-1 resolve_dropped_paths and PS-UN-2 partial-success."""
from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_existing(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_text("content")
    return p


# ===========================================================================
# TestResolveDroppedPaths  (PS-UN-1 — 5 tests)
# ===========================================================================

class TestResolveDroppedPaths:

    def test_resolve_multi_line_yields_all_valid_paths(self, tmp_path):
        """Two valid paths on separate lines both appear in DropResolution.paths."""
        from hermes_cli.file_drop import resolve_dropped_paths

        a = _make_existing(tmp_path, "a.py")
        b = _make_existing(tmp_path, "b.txt")
        text = f"{a}\n{b}"

        resolution = resolve_dropped_paths(text, multi_line=True)
        assert resolution.paths == [a, b]
        assert resolution.remainder_text == ""
        assert not resolution.is_empty

    def test_resolve_single_line_with_quoted_path_extracts_correctly(self, tmp_path):
        """Quoted path with spaces resolves to one Path entry."""
        from hermes_cli.file_drop import resolve_dropped_paths

        p = tmp_path / "file with spaces.py"
        p.write_text("x")
        text = f'"{p}"'

        resolution = resolve_dropped_paths(text, multi_line=True)
        assert resolution.paths == [p]
        assert resolution.remainder_text == ""

    def test_resolve_partial_success_returns_paths_plus_remainder(self, tmp_path):
        """Mix of valid path and prose: valid path in paths, prose in remainder_text."""
        from hermes_cli.file_drop import resolve_dropped_paths

        a = _make_existing(tmp_path, "real.py")
        text = f"{a}\nbogus_token"

        resolution = resolve_dropped_paths(text, multi_line=True)
        assert a in resolution.paths
        assert "bogus_token" in resolution.remainder_text

    def test_resolve_no_paths_in_prose_returns_empty(self, tmp_path):
        """Pure prose input returns DropResolution with empty paths and full text as remainder."""
        from hermes_cli.file_drop import resolve_dropped_paths

        text = "some prose text that is definitely not a path"
        resolution = resolve_dropped_paths(text, multi_line=True)
        assert resolution.paths == []
        assert resolution.remainder_text == text
        assert resolution.is_empty

    def test_resolve_three_call_sites_agree_for_same_input(self, tmp_path):
        """For one valid path, shims parse_dragged_file_paste and detect_file_drop_text
        both agree with resolve_dropped_paths."""
        from hermes_cli.file_drop import (
            resolve_dropped_paths,
            parse_dragged_file_paste,
            detect_file_drop_text,
        )

        p = _make_existing(tmp_path, "match.py")
        text = str(p)

        resolution = resolve_dropped_paths(text, multi_line=True)
        shim_multi = parse_dragged_file_paste(text)
        shim_single = detect_file_drop_text(text)

        assert resolution.paths == [p]
        assert shim_multi == [p]
        assert shim_single is not None
        assert shim_single.path == p


# ===========================================================================
# TestPartialSuccess  (PS-UN-2 — 4 tests)
# ===========================================================================

class TestPartialSuccess:

    def test_paste_partial_success_inserts_paths_and_remainder_text(self, tmp_path):
        """FilesDropped carries both a valid path and the remainder string for
        mixed valid/invalid token paste."""
        from hermes_cli.file_drop import resolve_dropped_paths
        from hermes_cli.tui.input.widget import HermesInput

        a = _make_existing(tmp_path, "valid.py")
        text = f"{a}\nbogus_word"

        resolution = resolve_dropped_paths(text, multi_line=True)
        assert a in resolution.paths
        assert resolution.remainder_text != ""

        msg = HermesInput.FilesDropped(resolution.paths, resolution.remainder_text)
        assert msg.paths == resolution.paths
        assert msg.remainder_text == resolution.remainder_text

    def test_paste_no_paths_falls_through_to_normal_text_paste(self, tmp_path):
        """Pure prose paste: resolve_dropped_paths returns empty paths."""
        from hermes_cli.file_drop import resolve_dropped_paths

        text = "hello world this is plain text"
        resolution = resolve_dropped_paths(text, multi_line=True)
        assert resolution.is_empty
        assert resolution.remainder_text == text

    def test_paste_remainder_inserted_at_cursor_not_appended(self, tmp_path):
        """_insert_plain_text calls inp.insert_text (not value concat) when available."""
        from hermes_cli.tui.services.watchers import WatchersService

        mock_inp = MagicMock()
        mock_inp.insert_text = MagicMock()
        mock_inp.value = ""

        mock_app = MagicMock()
        mock_app.query_one.return_value = mock_inp

        svc = object.__new__(WatchersService)
        svc.app = mock_app

        svc._insert_plain_text("hello remainder")

        mock_inp.insert_text.assert_called_once_with("hello remainder")

    def test_files_dropped_message_remainder_defaults_to_empty(self, tmp_path):
        """Existing callers of FilesDropped(paths) work without passing remainder_text."""
        from hermes_cli.tui.input.widget import HermesInput

        p = _make_existing(tmp_path, "x.py")
        msg = HermesInput.FilesDropped([p])
        assert msg.paths == [p]
        assert msg.remainder_text == ""
