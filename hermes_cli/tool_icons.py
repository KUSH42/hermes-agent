"""Canonical tool icon mappings — one entry per tool, both glyph variants.

Shared by CLI, TUI, and registry code so glyphs live in one place.
Each tool has a nerd-font glyph (Material Design, Codicons, Devicons, Font Awesome)
and an ASCII-safe fallback for terminals without font support.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Icon:
    """A tool icon with both nerd-font and ASCII-safe glyphs."""

    nf: str    # nerd font glyph
    ascii: str # ASCII fallback

    def __bool__(self) -> bool:
        return bool(self.nf or self.ascii)


# ── Single source of truth ──────────────────────────────────────────────
TOOL_ICONS: dict[str, Icon] = {
    "browser_back": Icon(nf="", ascii="<"),
    "browser_click": Icon(nf="󰳽", ascii="*"),
    "browser_get_images": Icon(nf="󰋩", ascii="I"),
    "browser_navigate": Icon(nf="", ascii="B"),
    "browser_press": Icon(nf="󰌌", ascii="K"),
    "browser_press_key": Icon(nf="󰌌", ascii="K"),
    "browser_scroll": Icon(nf="", ascii="B"),
    "browser_snapshot": Icon(nf="󰄀", ascii="C"),
    "browser_type": Icon(nf="󰌌", ascii="K"),
    "browser_vision": Icon(nf="󰈈", ascii="V"),
    "clarify": Icon(nf="󰘥", ascii="?"),
    "cronjob": Icon(nf="󰅐", ascii="T"),
    "delegate_task": Icon(nf="󰘬", ascii="@"),
    "execute_code": Icon(nf="", ascii="P"),
    "grep": Icon(nf="", ascii=">"),
    "image_generate": Icon(nf="󰋩", ascii="I"),
    "memory": Icon(nf="", ascii="M"),
    "patch": Icon(nf="", ascii="~"),
    "process": Icon(nf="", ascii="*"),
    "read_file": Icon(nf="󰧮", ascii="R"),
    "search_files": Icon(nf="󰍉", ascii="?"),
    "send_message": Icon(nf="󰒊", ascii=">"),
    "session_search": Icon(nf="󰍉", ascii="?"),
    "skill_manage": Icon(nf="󰈳", ascii="S"),
    "skill_view": Icon(nf="󰈳", ascii="S"),
    "skills_list": Icon(nf="󰈳", ascii="S"),
    "bash":     Icon(nf="󰆍", ascii=">"),
    "terminal": Icon(nf="󰆍", ascii=">"),
    "text_to_speech": Icon(nf="󰕾", ascii="!"),
    "todo": Icon(nf="", ascii="T"),
    "vision_analyze": Icon(nf="󰈈", ascii="V"),
    "web_crawl": Icon(nf="", ascii="W"),
    "web_extract": Icon(nf="󰈙", ascii="D"),
    "web_search": Icon(nf="", ascii="?"),
    "write_file": Icon(nf="󰷈", ascii="W"),
}

# Short display names for tool headers (avoids clutter like "search_files").
DISPLAY_NAMES: dict[str, str] = {
    "execute_code":       "exec",
    "search_files":       "grep",
    "session_search":     "search",
    "read_file":          "read",
    "write_file":         "write",
    "web_search":         "web",
    "web_extract":        "extract",
    "web_crawl":          "crawl",
    "browser_navigate":   "nav",
    "browser_click":      "click",
    "browser_type":       "type",
    "browser_scroll":     "scroll",
    "browser_back":       "back",
    "browser_snapshot":   "snap",
    "browser_vision":     "vision",
    "browser_get_images": "images",
    "browser_press":      "press",
    "browser_press_key":  "press",
    "image_generate":     "img",
    "vision_analyze":     "vision",
    "delegate_task":      "delegate",
    "skills_list":        "skills",
    "skill_view":         "skill",
    "skill_manage":       "skill",
    "text_to_speech":     "tts",
    "send_message":       "send",
    "cronjob":            "cron",
}


def get_display_name(tool_name: str) -> str:
    """Return short display name for *tool_name* (for headers)."""
    return DISPLAY_NAMES.get(tool_name, tool_name)


# Fallback for unknown tools.
GENERIC_ICON = Icon(nf="", ascii="*")

# Backward compat — old dict names used by tests and direct imports.
NERD_FONT_TOOL_ICONS: dict[str, str] = {k: v.nf for k, v in TOOL_ICONS.items()}
ASCII_TOOL_ICONS: dict[str, str] = {k: v.ascii for k, v in TOOL_ICONS.items()}

GENERIC_NERD_FONT_TOOL_ICON = GENERIC_ICON.nf
GENERIC_ASCII_TOOL_ICON = GENERIC_ICON.ascii


def get_icon(tool_name: str) -> Icon:
    """Return the Icon for *tool_name*, or GENERIC_ICON."""
    return TOOL_ICONS.get(tool_name, GENERIC_ICON)


def get_default_tool_icon(tool_name: str, default: str = "") -> str:
    """Return nerd font glyph for *tool_name*, or *default*.  (backward compat)"""
    icon = TOOL_ICONS.get(tool_name)
    return icon.nf if icon else default


def get_ascii_tool_icon(tool_name: str, default: str = GENERIC_ASCII_TOOL_ICON) -> str:
    """Return ASCII-safe glyph for *tool_name*, or *default*.  (backward compat)"""
    icon = TOOL_ICONS.get(tool_name)
    return icon.ascii if icon else default
