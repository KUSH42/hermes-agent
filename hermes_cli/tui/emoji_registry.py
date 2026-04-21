"""
hermes_cli/tui/emoji_registry.py — Custom emoji registry and rendering.

Loads named emoji images from $HERMES_HOME/emojis/ and descriptions from
emojis.md. Used for system-prompt injection and :name: substitution in TUI
response and user-message rendering.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Supported image extensions (GIFs included; animated GIFs render frame-by-frame)
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# emojis.md line format: :name: - description
_MD_LINE_RE = re.compile(r"^:([a-zA-Z0-9_-]+):\s*-\s*(.+)$")


# ---------------------------------------------------------------------------
# EmojiEntry
# ---------------------------------------------------------------------------

@dataclass
class EmojiEntry:
    name: str                              # canonical name, lowercase for lookup
    path: Path                             # absolute path to image file
    description: str                       # from emojis.md; "" if not in md
    pil_image: Any = field(default=None)   # normalized first frame; None if PIL unavailable
    cell_width: int = 2                    # computed from aspect ratio; default 2×1
    cell_height: int = 1                   # always 1 (line-height constraint)
    n_frames: int = 1                      # >1 for animated GIFs; 1 for all others


# ---------------------------------------------------------------------------
# normalize_emoji
# ---------------------------------------------------------------------------

def normalize_emoji(
    path: Path,
    max_cell_width: int,
    max_cell_height: int,  # always clamped to 1
    cell_px_w: int,
    cell_px_h: int,
) -> "tuple[Any, int, int] | None":
    """Load and resize image to fit within cell budget.

    Returns (pil_image, cell_width, cell_height=1) or None if PIL unavailable.
    cell_height is always 1 regardless of max_cell_height.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    max_cell_height = 1  # enforce line-height constraint
    try:
        img = Image.open(path)
        img.seek(0)  # GIF: normalize to first frame
        img = img.convert("RGBA")
        px_w, px_h = img.size
        if cell_px_w <= 0:
            cell_px_w = 8
        if cell_px_h <= 0:
            cell_px_h = 16
        raw_cw = max(1, round(px_w / cell_px_w))
        raw_ch = max(1, round(px_h / cell_px_h))
        scale = min(max_cell_width / raw_cw, max_cell_height / raw_ch)
        cell_w = max(1, round(raw_cw * scale))
        cell_h = max(1, round(raw_ch * scale))
        cell_w = min(cell_w, max_cell_width)
        cell_h = min(cell_h, max_cell_height)
        target_px = (cell_w * cell_px_w, cell_h * cell_px_h)
        img = img.resize(target_px, Image.LANCZOS)
        return img, cell_w, cell_h
    except Exception:
        return None


def _cell_px() -> "tuple[int, int]":
    """Return (cell_width_px, cell_height_px). Falls back to (8, 16)."""
    try:
        from hermes_cli.tui.kitty_graphics import _cell_px as _kgcpx
        return _kgcpx()
    except Exception:
        return (8, 16)


# ---------------------------------------------------------------------------
# EmojiRegistry
# ---------------------------------------------------------------------------

class EmojiRegistry:
    def __init__(
        self,
        emojis_dir: Path,
        md_path: "Path | None" = None,
        cfg: "dict | None" = None,
    ) -> None:
        self._emojis_dir = emojis_dir
        self._md_path = md_path
        self._cfg = cfg or {}
        self._entries: dict[str, EmojiEntry] = {}  # lowercase name → entry

    def load(self) -> None:
        """Scan emojis_dir + parse emojis.md. Runs normalize_emoji for each entry."""
        self._entries = {}

        # Parse emojis.md for descriptions
        descriptions: dict[str, str] = {}
        if self._md_path and self._md_path.exists():
            try:
                for line in self._md_path.read_text(encoding="utf-8").splitlines():
                    m = _MD_LINE_RE.match(line.strip())
                    if m:
                        descriptions[m.group(1).lower()] = m.group(2).strip()
            except Exception:
                pass

        # Scan directory
        if not self._emojis_dir.exists():
            return
        files: dict[str, Path] = {}
        try:
            for p in self._emojis_dir.iterdir():
                if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                    key = p.stem.lower()
                    files[key] = p
        except Exception:
            return

        max_cw = int(self._cfg.get("max_cell_width", 4))
        max_ch = 1  # always 1
        disk_cache = bool(self._cfg.get("disk_cache", True))
        cpw, cph = _cell_px()
        cache_dir = self._emojis_dir / ".cache"

        for key, path in files.items():
            desc = descriptions.get(key, "")
            n_frames = 1
            pil_image = None
            cell_w = 2
            cell_h = 1

            # Count GIF frames
            if path.suffix.lower() == ".gif":
                try:
                    from PIL import Image as _PILImage
                    _g = _PILImage.open(path)
                    n_frames = getattr(_g, "n_frames", 1)
                    _g.close()
                except Exception:
                    pass

            # Normalize (disk cache check)
            norm_result = None
            cache_path: "Path | None" = None
            if disk_cache:
                cache_name = f"{key}_{cell_w}x{cell_h}_{cpw}x{cph}.png"
                cache_path = cache_dir / cache_name
                if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
                    try:
                        from PIL import Image as _PILImage
                        _ci = _PILImage.open(cache_path).convert("RGBA")
                        # Infer cell dims from pixel size
                        _cw = max(1, round(_ci.width / cpw))
                        _ch = max(1, round(_ci.height / cph))
                        norm_result = (_ci, _cw, _ch)
                    except Exception:
                        pass

            if norm_result is None:
                norm_result = normalize_emoji(path, max_cw, max_ch, cpw, cph)
                if norm_result is not None and disk_cache:
                    # Compute correct cache path from actual cell dims
                    _, _cw2, _ch2 = norm_result
                    cache_name2 = f"{key}_{_cw2}x{_ch2}_{cpw}x{cph}.png"
                    cache_path2 = cache_dir / cache_name2
                    try:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        norm_result[0].save(str(cache_path2), format="PNG")
                    except Exception:
                        pass

            if norm_result is not None:
                pil_image, cell_w, cell_h = norm_result

            self._entries[key] = EmojiEntry(
                name=path.stem,
                path=path,
                description=desc,
                pil_image=pil_image,
                cell_width=cell_w,
                cell_height=cell_h,
                n_frames=n_frames,
            )

        # Cleanup orphaned cache entries
        if disk_cache and cache_dir.exists():
            try:
                live_stems = set(self._entries.keys())
                for cp in cache_dir.iterdir():
                    # Cache filenames start with the emoji stem
                    stem_part = cp.stem.split("_")[0]
                    if stem_part not in live_stems:
                        try:
                            cp.unlink()
                        except Exception:
                            pass
            except Exception:
                pass

    def reload_normalized(self, cell_px_w: int, cell_px_h: int) -> None:
        """Re-normalize all entries for new cell pixel dimensions. Call from worker thread."""
        max_cw = int(self._cfg.get("max_cell_width", 4))
        disk_cache = bool(self._cfg.get("disk_cache", True))
        cache_dir = self._emojis_dir / ".cache"
        for entry in self._entries.values():
            result = normalize_emoji(entry.path, max_cw, 1, cell_px_w, cell_px_h)
            if result is not None:
                entry.pil_image, entry.cell_width, entry.cell_height = result
                if disk_cache:
                    cache_name = f"{entry.name.lower()}_{entry.cell_width}x{entry.cell_height}_{cell_px_w}x{cell_px_h}.png"
                    try:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        entry.pil_image.save(str(cache_dir / cache_name), format="PNG")
                    except Exception:
                        pass

    def get(self, name: str) -> "EmojiEntry | None":
        return self._entries.get(name.lower())

    def all_entries(self) -> "list[EmojiEntry]":
        return list(self._entries.values())

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def system_prompt_block(self) -> str:
        if not self._entries:
            return ""
        lines = ["[Custom emojis available — use these in your responses by writing :name: exactly:]"]
        for entry in self._entries.values():
            desc = entry.description or "(no description)"
            lines.append(f":{entry.name}: \u2014 {desc}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AnimatedEmojiWidget
# ---------------------------------------------------------------------------

class AnimatedEmojiWidget:
    """Lazy import guard — actual class defined below after Textual import."""


def _build_animated_emoji_widget() -> "type":
    from textual.widget import Widget
    from textual.app import ComposeResult
    from textual import work

    class _AnimatedEmojiWidget(Widget):
        """Cycles through GIF frames at the GIF's native frame rate."""

        DEFAULT_CSS = """
        _AnimatedEmojiWidget {
            height: 1;
            width: auto;
        }
        """

        def __init__(self, entry: EmojiEntry, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._entry = entry
            self._frames: list[Any] = []
            self._delays: list[float] = []
            self._current_frame: int = 0
            self._img: Any = None

        def compose(self) -> "ComposeResult":
            from hermes_cli.tui.widgets import InlineImage
            self._img = InlineImage(max_rows=self._entry.cell_height)
            yield self._img

        @work(thread=True)
        def on_mount(self) -> None:
            frames: list[Any] = []
            delays: list[float] = []
            try:
                from PIL import Image as _PILImage
                gif = _PILImage.open(self._entry.path)
                for i in range(getattr(gif, "n_frames", 1)):
                    gif.seek(i)
                    frames.append(gif.convert("RGBA").copy())
                    delay_ms = gif.info.get("duration", 100)
                    delays.append(max(0.02, delay_ms / 1000.0))
                gif.close()
            except Exception:
                pass
            self._frames = frames
            self._delays = delays
            self.call_from_thread(self._start_animation)

        def _start_animation(self) -> None:
            from hermes_cli.tui.kitty_graphics import get_caps, GraphicsCap
            cap = get_caps()
            if not self._frames or len(self._frames) <= 1 or cap in (GraphicsCap.HALFBLOCK, GraphicsCap.NONE):
                if self._img is not None:
                    self._img.image = self._entry.path
                return
            if self._img is not None:
                self._img.image = self._frames[0]
            if len(self._frames) > 1:
                self.set_timer(self._delays[0], self._advance_frame)

        def _advance_frame(self) -> None:
            self._current_frame = (self._current_frame + 1) % max(len(self._frames), 1)
            if self._img is not None and self._frames:
                self._img.image = self._frames[self._current_frame]
            delay = self._delays[self._current_frame] if self._delays else 0.1
            self.set_timer(delay, self._advance_frame)

    _AnimatedEmojiWidget.__name__ = "AnimatedEmojiWidget"
    _AnimatedEmojiWidget.__qualname__ = "AnimatedEmojiWidget"
    return _AnimatedEmojiWidget


_AnimatedEmojiWidgetClass: "type | None" = None


def get_animated_emoji_widget_class() -> "type":
    global _AnimatedEmojiWidgetClass
    if _AnimatedEmojiWidgetClass is None:
        _AnimatedEmojiWidgetClass = _build_animated_emoji_widget()
    return _AnimatedEmojiWidgetClass
