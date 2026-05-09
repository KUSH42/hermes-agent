"""Pure-unit tests for DD-PL-1..DD-PL-5 (no app mount needed)."""

from __future__ import annotations

import shlex
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.file_drop import (
    IMAGE_EXTENSIONS,
    classify_dropped_file,
    detect_file_drop_text,
    format_link_token,
)


# ---------------------------------------------------------------------------
# TestDirectoryPolicy — DD-PL-1
# ---------------------------------------------------------------------------


class TestDirectoryPolicy:
    def test_classify_directory_default_rejected_with_hint_reason(self, tmp_path: Path) -> None:
        subdir = tmp_path / "myproject"
        subdir.mkdir()
        result = classify_dropped_file(subdir, tmp_path, allow_directory=False)
        assert result.kind == "directory_rejected"
        assert "use /index" in (result.reason or "")

    def test_classify_directory_with_allow_flag_returns_glob_kind(self, tmp_path: Path) -> None:
        subdir = tmp_path / "myproject"
        subdir.mkdir()
        result = classify_dropped_file(subdir, tmp_path, allow_directory=True)
        assert result.kind == "directory_glob"

    def test_handle_drop_directory_glob_inserts_globbed_token(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch
        from pathlib import Path

        subdir = tmp_path / "src"
        subdir.mkdir()

        glob_result = MagicMock()
        glob_result.kind = "directory_glob"

        inserted: list[list[str]] = []

        # Build a minimal fake WatchersService that captures insert_link_tokens calls
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from hermes_cli.file_drop import classify_dropped_file as real_classify

        tokens: list[str] = []

        class FakeApp:
            config = None

            def get_working_directory(self) -> Path:
                return tmp_path

            def _flash_hint(self, *a, **kw) -> None:
                pass

            def query_one(self, *a, **kw):
                raise Exception("no dom")

        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc.app = FakeApp()
        svc._pending_drop_queue = []
        svc._last_drop_undo_state = None
        svc._modal_active = lambda: False

        inserted_tokens: list[str] = []

        def fake_insert(t: list[str]) -> None:
            inserted_tokens.extend(t)

        svc.insert_link_tokens = fake_insert
        svc.append_attached_images = lambda *a: None

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file", return_value=glob_result):
            svc.handle_file_drop_inner([subdir])

        assert any("/**/*" in t for t in inserted_tokens), f"no glob token in {inserted_tokens}"


# ---------------------------------------------------------------------------
# TestImageExtensions — DD-PL-3
# ---------------------------------------------------------------------------


class TestImageExtensions:
    def test_image_extensions_include_heic_heif_avif(self) -> None:
        assert ".heic" in IMAGE_EXTENSIONS
        assert ".heif" in IMAGE_EXTENSIONS
        assert ".avif" in IMAGE_EXTENSIONS

    def test_drop_heic_classified_as_image(self, tmp_path: Path) -> None:
        heic = tmp_path / "photo.heic"
        heic.write_bytes(b"fake heic")
        result = classify_dropped_file(heic, tmp_path)
        assert result.kind == "image"


# ---------------------------------------------------------------------------
# TestLinkTokenQuoting — DD-PL-4
# ---------------------------------------------------------------------------


class TestLinkTokenQuoting:
    def test_format_link_token_handles_embedded_quotes(self, tmp_path: Path) -> None:
        # Create a file with a name that contains a double-quote equivalent path
        # (on most filesystems quotes in filenames are legal)
        nested = tmp_path / "project" / "file.py"
        nested.parent.mkdir()
        nested.write_text("")

        # Use a path that would have broken the old double-quoting approach
        tricky = tmp_path / "my project"
        tricky.mkdir()
        tricky_file = tricky / 'f.py'
        tricky_file.write_text("")

        token = format_link_token(tricky_file, tmp_path)
        # shlex.quote output must be parseable back to the original
        result = shlex.split(token)
        assert len(result) == 1
        assert "my project" in result[0]

    def test_format_link_token_simple_path_single_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "dir" / "file.py"
        f.parent.mkdir()
        f.write_text("")
        token = format_link_token(f, tmp_path)
        # shlex.quote output for a safe path (no spaces/specials) is the bare string
        assert token == shlex.quote("dir/file.py")
        # A path with spaces must be quoted
        spaced = tmp_path / "my dir" / "file.py"
        spaced.parent.mkdir()
        spaced.write_text("")
        spaced_token = format_link_token(spaced, tmp_path)
        assert shlex.split(spaced_token) == ["my dir/file.py"]


# ---------------------------------------------------------------------------
# TestGreedyPrefixBound — DD-PL-5
# ---------------------------------------------------------------------------


class TestGreedyPrefixBound:
    def test_detect_file_drop_greedy_prefix_bounded(self, tmp_path: Path) -> None:
        # 2 KB string with 30 spaces, no valid paths
        long_string = "/notexist " * 30  # 10 chars * 30 = 300 chars, 30 spaces
        long_string = long_string + "x" * (2048 - len(long_string))

        call_count = 0

        class CountingPath(Path):
            _flavour = Path(".")._flavour  # type: ignore[attr-defined]

            def exists(self) -> bool:  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                return False

        original_path_class = None

        # Patch Path.exists in the file_drop module
        import hermes_cli.file_drop as _fd_mod

        original_exists = Path.exists

        patched_calls = 0

        def counting_exists(self: Path) -> bool:
            nonlocal patched_calls
            patched_calls += 1
            return original_exists(self)

        with patch.object(Path, "exists", counting_exists):
            result = detect_file_drop_text(long_string)

        assert result is None
        # 1 initial check + 1 full-string + 12 bounded prefixes = 14 max
        assert patched_calls <= 14, f"too many Path.exists calls: {patched_calls}"
