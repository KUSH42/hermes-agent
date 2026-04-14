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

    if " " in path.name or " " in str(path.relative_to(cwd) if path.is_relative_to(cwd) else path):
        if _looks_like_text_path(path):
            return DroppedFile(path=path, kind="invalid", reason="spaces not supported in @path yet")

    if _looks_like_text_path(path):
        return DroppedFile(path=path, kind="linkable_text")

    return DroppedFile(path=path, kind="unsupported_binary", reason="unsupported file type")


def format_link_token(path: Path, cwd: Path) -> str:
    """Format a path as a Hermes `@path` token."""
    target = path
    if path.is_relative_to(cwd):
        target = path.relative_to(cwd)
    text = target.as_posix()
    if " " in text:
        raise ValueError("spaces not supported in @path yet")
    return f"@{text}"


_MAX_FILE_DROP_CHARS = 4096  # paste payloads longer than this are prose, not file drops
_MAX_FILE_DROP_LINES = 10  # drag-and-drop rarely drops more than a handful of files


def parse_dragged_file_paste(text: str) -> list[Path] | None:
    """Return file paths when a paste payload looks like terminal drag-and-drop.

    Accepts one or more newline-separated local file paths / file:// URIs.
    Rejects mixed prose + path payloads so normal paste keeps working.
    """
    if not isinstance(text, str):
        return None
    # Early bail-out: long paste payloads are prose, not file drops.
    # Without this guard, each line triggers a path.exists() syscall,
    # hanging the TUI on multi-KB pastes.
    if len(text) > _MAX_FILE_DROP_CHARS:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) > _MAX_FILE_DROP_LINES:
        return None

    paths: list[Path] = []
    for line in lines:
        path = _path_from_text(line)
        if not path.exists():
            return None
        paths.append(path)

    return paths or None


def detect_file_drop_text(user_input: str) -> FileDropMatch | None:
    """Detect a terminal-pasted file path prefix inside a prompt string."""
    if not isinstance(user_input, str) or not user_input.startswith(("/", "file://", "~")):
        return None

    raw = user_input
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
