"""Helpers for terminal drag-and-drop / pasted file-path handling.

Terminal drag-and-drop commonly arrives as pasted text rather than a native
GUI drop event. Keep parsing and file-type policy here so prompt-toolkit and
the Textual TUI share the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
import mimetypes
import os
import shlex


IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".bmp", ".tiff", ".tif", ".svg", ".ico",
    ".heic", ".heif", ".avif",
})

LINKABLE_TEXT_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".sh", ".bash", ".zsh", ".fish",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".xml", ".csv",
    ".md", ".txt", ".rst",
    ".html", ".css", ".scss", ".sass", ".less",
    ".sql", ".tf",
})

LINKABLE_TEXT_FILENAMES = frozenset({
    "makefile",
    "dockerfile",
    "justfile",
})


@dataclass(frozen=True)
class DroppedFile:
    path: Path
    kind: Literal["image", "linkable_text", "unsupported_binary", "directory", "directory_rejected", "directory_glob", "invalid"]
    reason: str = ""


@dataclass(frozen=True)
class FileDropMatch:
    path: Path
    is_image: bool
    remainder: str = ""


def _decode_path_text(text: str) -> str:
    """Decode a pasted file path token from terminal text."""
    raw = text.strip()
    # Strip surrounding quotes (some terminals quote dropped paths)
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            return raw
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            return raw
        return unquote(parsed.path)
    return raw.replace("\\ ", " ")


def _path_from_text(text: str) -> Path:
    decoded = _decode_path_text(text)
    if decoded.startswith("~"):
        decoded = os.path.expanduser(decoded)
    return Path(decoded)


def _looks_like_text_path(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in LINKABLE_TEXT_FILENAMES:
        return True
    if suffix in LINKABLE_TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return False
    return mime.startswith("text/") or mime in {
        "application/json",
        "application/xml",
        "application/yaml",
        "text/yaml",
    }


def classify_dropped_file(path: Path, cwd: Path, *, allow_directory: bool = False) -> DroppedFile:
    """Classify one dropped local path for TUI routing."""
    if not path.exists():
        return DroppedFile(path=path, kind="invalid", reason="file no longer exists")
    if not path.is_file():
        if path.is_dir() and allow_directory:
            return DroppedFile(path=path, kind="directory_glob")
        return DroppedFile(path=path, kind="directory_rejected",
                           reason="drop a file, not a folder (use /index <dir>)")

    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    if suffix in IMAGE_EXTENSIONS or (mime or "").startswith("image/"):
        return DroppedFile(path=path, kind="image")

    if _looks_like_text_path(path):
        return DroppedFile(path=path, kind="linkable_text")

    return DroppedFile(path=path, kind="unsupported_binary", reason="unsupported file type")


def format_link_token(path: Path, cwd: Path) -> str:
    """Format a path as a shell-safe single-quoted token.

    Uses shlex.quote so paths with spaces, quotes, or other shell-special
    characters are always safe. Tokens are relative when under cwd.
    """
    target = path
    if path.is_relative_to(cwd):
        target = path.relative_to(cwd)
    return shlex.quote(target.as_posix())


_MAX_FILE_DROP_CHARS = 4096  # paste payloads longer than this are prose, not file drops
_MAX_FILE_DROP_LINES = 10  # drag-and-drop rarely drops more than a handful of files


@dataclass(frozen=True)
class DropResolution:
    paths: list[Path]
    remainder_text: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.paths


def _resolve_single_line(text: str) -> DropResolution:
    """Greedy-prefix path extraction for single-line inputs.

    Handles quoted paths and unquoted paths with spaces via longest-match.
    Returns DropResolution with at most one path and any remainder text.
    """
    if not isinstance(text, str):
        return DropResolution(paths=[], remainder_text="")

    raw = text.strip()
    if not raw:
        return DropResolution(paths=[], remainder_text=text)

    # Handle quoted paths: "/path/to/file.py" or '/path/to/file.py'
    if len(raw) >= 3 and raw[0] in ('"', "'"):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end > 0:
            candidate = raw[1:end]
            path = _path_from_text(candidate)
            if path.exists():
                remainder = raw[end + 1:].strip()
                return DropResolution(paths=[path], remainder_text=remainder)

    if not raw.startswith(("/", "file://", "~")):
        return DropResolution(paths=[], remainder_text=text)

    pos = 0
    while pos < len(raw):
        ch = raw[pos]
        if ch == "\\" and pos + 1 < len(raw) and raw[pos + 1] == " ":
            pos += 2
        elif ch == " ":
            break
        else:
            pos += 1

    first_token = raw[:pos]
    path = _path_from_text(first_token)
    if not path.exists() or not path.is_file():
        # Token stopped at first space; try greedily finding the longest
        # existing prefix to handle unquoted paths with spaces (e.g. macOS
        # screenshot names). Check the full raw string first, then each
        # space-terminated prefix from longest to shortest.
        candidates: list[tuple[int, str]] = [(len(raw), raw)]
        # Bound to 12 space positions to avoid O(N) stat syscalls on long prose pastes.
        space_positions = [i for i, c in enumerate(raw) if c == " "][:12]
        candidates.extend((sp, raw[:sp]) for sp in reversed(space_positions))
        found_path: Path | None = None
        found_pos: int = pos
        for end_pos, token in candidates:
            candidate = _path_from_text(token)
            if candidate.exists() and candidate.is_file():
                found_path = candidate
                found_pos = end_pos
                break  # longest match wins
        if found_path is None:
            return DropResolution(paths=[], remainder_text=text)
        path = found_path
        pos = found_pos

    remainder = raw[pos:].strip()
    return DropResolution(paths=[path], remainder_text=remainder)


def resolve_dropped_paths(text: str, *, multi_line: bool = True) -> DropResolution:
    """Single source of truth for drag-and-drop / pasted-path detection.

    multi_line=True  → split on newlines first (like parse_dragged_file_paste):
                        each line is a candidate path token.
    multi_line=False → treat the whole string as a single line (like
                        detect_file_drop_text): greedy-prefix recovery only.

    Returns a DropResolution with valid paths plus any leftover text that
    was not consumed. Caller decides whether to insert remainder as text or
    discard it.
    """
    if not isinstance(text, str):
        return DropResolution(paths=[], remainder_text="")

    if multi_line:
        if len(text) > _MAX_FILE_DROP_CHARS:
            return DropResolution(paths=[], remainder_text=text)

        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_lines:
            return DropResolution(paths=[], remainder_text=text)

        tokens: list[str] = []
        for line in raw_lines:
            if '"' in line or "'" in line or " " in line:
                split = _split_quoted_paths(line)
                if len(split) > 1:
                    tokens.extend(split)
                else:
                    tokens.append(split[0] if split else line)
            else:
                tokens.append(line)

        if not tokens or len(tokens) > _MAX_FILE_DROP_LINES:
            return DropResolution(paths=[], remainder_text=text)

        paths: list[Path] = []
        remainder_tokens: list[str] = []
        for token in tokens:
            path = _path_from_text(token)
            if path.exists():
                paths.append(path)
            else:
                # Token doesn't exist as-is. If it came from a single-line
                # payload with spaces but no quotes, try the full original line.
                if len(raw_lines) == 1 and " " in raw_lines[0]:
                    full_path = _path_from_text(raw_lines[0])
                    if full_path.exists():
                        return DropResolution(paths=[full_path], remainder_text="")
                remainder_tokens.append(token)

        remainder = " ".join(remainder_tokens)
        return DropResolution(paths=paths, remainder_text=remainder)

    else:
        # single-line mode: greedy-prefix recovery (like original detect_file_drop_text)
        return _resolve_single_line(text)


def _split_quoted_paths(text: str) -> list[str]:
    """Split text into path tokens, respecting single and double quotes.

    Handles:
      - space-separated: /a.py /b.txt
      - quoted with spaces: "/path/file name.py" '/other/file.txt'
      - mixed: /a.py "/path with spaces/b.py" /c.txt
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch in (" ", "\t"):
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
        i += 1
    if current:
        tokens.append("".join(current))
    return tokens


def parse_dragged_file_paste(text: str) -> list[Path] | None:
    """Return file paths when a paste payload looks like terminal drag-and-drop.

    Thin shim over resolve_dropped_paths(multi_line=True). Preserves nil-on-any-miss
    semantics: returns None if any token failed to resolve (same behavior as before
    so existing callers are backward-compatible). Partial success is only
    accessible via resolve_dropped_paths directly.
    """
    resolution = resolve_dropped_paths(text, multi_line=True)
    if not resolution.paths:
        return None
    # Preserve nil-on-any-miss: if there are remainder tokens, some failed → return None.
    if resolution.remainder_text:
        return None
    return resolution.paths


def detect_file_drop_text(user_input: str) -> FileDropMatch | None:
    """Detect a terminal-pasted file path prefix inside a prompt string.

    Thin shim over resolve_dropped_paths(multi_line=False) packed into
    a FileDropMatch (backward-compatible return type with is_image field).
    """
    resolution = resolve_dropped_paths(user_input, multi_line=False)
    if not resolution.paths:
        return None
    path = resolution.paths[0]
    return FileDropMatch(
        path=path,
        is_image=path.is_file() and (
            path.suffix.lower() in IMAGE_EXTENSIONS
            or (mimetypes.guess_type(str(path))[0] or "").startswith("image/")
        ),
        remainder=resolution.remainder_text,
    )
