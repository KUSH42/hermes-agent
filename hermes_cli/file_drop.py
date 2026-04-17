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


IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".bmp", ".tiff", ".tif", ".svg", ".ico",
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
    kind: Literal["image", "linkable_text", "unsupported_binary", "invalid"]
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


def classify_dropped_file(path: Path, cwd: Path) -> DroppedFile:
    """Classify one dropped local path for TUI routing."""
    if not path.exists():
        return DroppedFile(path=path, kind="invalid", reason="file no longer exists")
    if not path.is_file():
        return DroppedFile(path=path, kind="invalid", reason="directories not supported")

    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    if suffix in IMAGE_EXTENSIONS or (mime or "").startswith("image/"):
        return DroppedFile(path=path, kind="image")

    if _looks_like_text_path(path):
        return DroppedFile(path=path, kind="linkable_text")

    return DroppedFile(path=path, kind="unsupported_binary", reason="unsupported file type")


def format_link_token(path: Path, cwd: Path) -> str:
    """Format a path as a quoted path token.

    No @ prefix — just the path, double-quoted if it contains spaces.
    """
    target = path
    if path.is_relative_to(cwd):
        target = path.relative_to(cwd)
    text = target.as_posix()
    if " " in text:
        return f'"{text}"'
    return text


_MAX_FILE_DROP_CHARS = 4096  # paste payloads longer than this are prose, not file drops
_MAX_FILE_DROP_LINES = 10  # drag-and-drop rarely drops more than a handful of files


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

    Accepts one or more newline-separated or space-separated local file paths /
    file:// URIs. Paths with spaces can be quoted with single or double quotes.
    Rejects mixed prose + path payloads so normal paste keeps working.
    """
    if not isinstance(text, str):
        return None
    # Early bail-out: long paste payloads are prose, not file drops.
    # Without this guard, each line triggers a path.exists() syscall,
    # hanging the TUI on multi-KB pastes.
    if len(text) > _MAX_FILE_DROP_CHARS:
        return None

    # Split on newlines first, then on spaces (respecting quotes)
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return None

    tokens: list[str] = []
    for line in raw_lines:
        # Always try quote-aware splitting first. This handles:
        # - space-separated: /a.py /b.txt → ['/a.py', '/b.txt']
        # - quoted with spaces: "/path/file name.py" → ['/path/file name.py']
        # - mixed: /a.py "/path with spaces/b.py" → ['/a.py', '/path with spaces/b.py']
        if '"' in line or "'" in line or " " in line:
            split = _split_quoted_paths(line)
            if len(split) > 1:
                # Multiple tokens — use split result
                tokens.extend(split)
            else:
                # Single token (unquoted path with spaces, or quoted single path)
                tokens.append(split[0] if split else line)
        else:
            tokens.append(line)

    if not tokens or len(tokens) > _MAX_FILE_DROP_LINES:
        return None

    paths: list[Path] = []
    for token in tokens:
        path = _path_from_text(token)
        if not path.exists():
            # Token doesn't exist as-is. If it came from splitting a line
            # with spaces but no quotes, the whole line might be one path
            # with spaces. Try the full original line (single-line case).
            if len(raw_lines) == 1 and " " in raw_lines[0]:
                full_path = _path_from_text(raw_lines[0])
                if full_path.exists():
                    return [full_path]
            return None
        paths.append(path)

    return paths or None


def detect_file_drop_text(user_input: str) -> FileDropMatch | None:
    """Detect a terminal-pasted file path prefix inside a prompt string."""
    if not isinstance(user_input, str):
        return None

    raw = user_input.strip()

    # Handle quoted paths: "/path/to/file.py" or '/path/to/file.py'
    if len(raw) >= 3 and raw[0] in ('"', "'"):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end > 0:
            candidate = raw[1:end]
            path = _path_from_text(candidate)
            if path.exists() and path.is_file():
                remainder = raw[end + 1:].strip()
                return FileDropMatch(
                    path=path,
                    is_image=path.suffix.lower() in IMAGE_EXTENSIONS
                    or (mimetypes.guess_type(str(path))[0] or "").startswith("image/"),
                    remainder=remainder,
                )

    if not raw.startswith(("/", "file://", "~")):
        return None

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
        return None

    remainder = raw[pos:].strip()
    return FileDropMatch(
        path=path,
        is_image=path.suffix.lower() in IMAGE_EXTENSIONS or (mimetypes.guess_type(str(path))[0] or "").startswith("image/"),
        remainder=remainder,
    )
