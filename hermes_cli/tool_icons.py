"""Canonical tool icon mappings and fallbacks.

Shared by CLI, TUI, and registry code so nerd font glyphs live in one place.
"""

from __future__ import annotations

# Preferred nerd font glyphs for common Hermes tools.
#
# Codicons are used when they are precise. Material Design icons fill gaps where
# Codicons are too sparse for file- and workflow-specific cases.
NERD_FONT_TOOL_ICONS: dict[str, str] = {
    "terminal": "",              # cod-terminal_bash
    "read_file": "󰧮",             # md-file_document_outline
    "write_file": "󰷈",            # md-file_document_edit
    "patch": "",                 # cod-replace
    "search_files": "󰱼",         # md-file_search
    "web_search": "",            # cod-search
    "web_extract": "󰈙",          # md-file_document
    "web_crawl": "",            # cod-globe
    "browser_navigate": "",      # cod-browser
    "browser_click": "󰳽",        # md-cursor_default_click
    "browser_type": "󰌌",         # md-keyboard
    "browser_scroll": "",        # cod-globe
    "browser_back": "",          # cod-arrow_left
    "browser_press_key": "󰌌",    # md-keyboard
    "browser_snapshot": "󰄀",     # md-camera
    "browser_press": "󰌌",        # md-keyboard
    "browser_get_images": "󰋩",   # md-image
    "browser_vision": "󰈈",       # md-eye
    "image_generate": "󰋩",       # md-image
    "vision_analyze": "󰈈",       # md-eye
    "execute_code": "",         # nf-dev-python U+E235
    "delegate_task": "󰘬",        # md-source_branch
    "skills_list": "",          # cod-book
    "skill_view": "",           # cod-book
    "skill_manage": "",         # cod-book
    "clarify": "󰘥",             # md-help_circle_outline
    "process": "",              # cod-settings_gear
    "cronjob": "󰅐",              # md-clock_outline
    "memory": "",               # cod-notebook
    "todo": "",                 # cod-notebook
    "text_to_speech": "󰕾",      # md-volume_high
    "send_message": "󰒊",        # md-send
}

# ASCII-safe fallbacks for terminals without nerd font support.
ASCII_TOOL_ICONS: dict[str, str] = {
    "terminal": ">",
    "read_file": "R",
    "write_file": "W",
    "patch": "~",
    "search_files": "?",
    "web_search": "?",
    "web_extract": "D",
    "web_crawl": "W",
    "browser_navigate": "B",
    "browser_click": "*",
    "browser_type": "K",
    "browser_scroll": "B",
    "browser_back": "<",
    "browser_snapshot": "C",
    "browser_press": "K",
    "browser_get_images": "I",
    "browser_vision": "V",
    "browser_press_key": "K",
    "image_generate": "I",
    "vision_analyze": "V",
    "execute_code": "P",
    "delegate_task": "@",
    "skills_list": "S",
    "skill_view": "S",
    "skill_manage": "S",
    "clarify": "?",
    "process": "*",
    "cronjob": "T",
    "memory": "M",
    "todo": "T",
    "text_to_speech": "!",
    "send_message": ">",
}

GENERIC_NERD_FONT_TOOL_ICON = ""  # cod-tools
GENERIC_ASCII_TOOL_ICON = "*"


def get_default_tool_icon(tool_name: str, default: str = "") -> str:
    """Return canonical nerd font glyph for *tool_name*, or *default*."""
    return NERD_FONT_TOOL_ICONS.get(tool_name, default)


def get_ascii_tool_icon(tool_name: str, default: str = GENERIC_ASCII_TOOL_ICON) -> str:
    """Return ASCII-safe glyph for *tool_name*, or *default*."""
    return ASCII_TOOL_ICONS.get(tool_name, default)
