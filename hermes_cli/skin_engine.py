"""Hermes CLI skin/theme engine.

A data-driven skin system that lets users customize the CLI's visual appearance.
Skins are defined as YAML files in ~/.hermes/skins/ or as built-in presets.
No code changes are needed to add a new skin.

SKIN YAML SCHEMA
================

All fields are optional. Missing values inherit from the ``default`` skin.

.. code-block:: yaml

    # Required: skin identity
    name: mytheme                         # Unique skin name (lowercase, hyphens ok)
    description: Short description        # Shown in /skin listing

    # Colors: hex values for Rich markup (banner, UI, response box)
    colors:
      banner_border: "#CD7F32"            # Panel border color
      banner_title: "#FFD700"             # Panel title text color
      banner_accent: "#FFBF00"            # Section headers (Available Tools, etc.)
      banner_dim: "#B8860B"               # Dim/muted text (separators, labels)
      banner_text: "#FFF8DC"              # Body text (tool names, skill names)
      banner_warning: "#FF8C00"           # Warning glyph + count (⚠ N commits behind)
      banner_warning_dim: "#CD6500"       # Warning body text (run … to update)
      banner_key: "#FFD700"               # Key badge color (u dismiss, etc.)
      ui_accent: "#FFBF00"               # General UI accent
      ui_label: "#4dd0e1"                # UI labels
      ui_ok: "#4caf50"                   # Success indicators
      ui_error: "#ef5350"                # Error indicators
      ui_warn: "#ffa726"                 # Warning indicators
      prompt: "#FFF8DC"                  # Prompt text color
      input_rule: "#CD7F32"              # Input area horizontal rule
      response_border: "#FFD700"         # Response box border (ANSI)
      session_label: "#DAA520"           # Session label color
      session_border: "#8B8682"          # Session ID dim color
      rule_start: "#555555"              # TitledRule/PlainRule gradient start (bright end)
      rule_end: "#2A2A2A"                # TitledRule/PlainRule gradient end (fades to app-bg; MUST match app-bg)
      statusbar_bg: "#1a1a2e"            # Prompt_toolkit status bar background (ANSI mode only)
      error_color: "#E06C75"             # Context bar critical / TUI error indicator
      warning_color: "#FFA726"           # Context bar warning / TUI warning indicator
      caution_color: "#FFBF00"           # Context bar caution / TUI caution indicator

    # Spinner: customize the animated spinner during API calls
    spinner:
      style: dots                         # TUI prompt spinner: dots|bounce|grow|arrows|star|moon|pulse|clock|none
      waiting_faces:                      # Faces shown while waiting for API
        - "(⚔)"
        - "(⛨)"
      thinking_faces:                     # Faces shown during reasoning
        - "(⌁)"
        - "(<>)"
      thinking_verbs:                     # Verbs for spinner messages
        - "forging"
        - "plotting"
      wings:                              # Optional left/right spinner decorations
        - ["⟪⚔", "⚔⟫"]                  # Each entry is [left, right] pair
        - ["⟪▲", "▲⟫"]

    # Branding: text strings used throughout the CLI
    branding:
      agent_name: "Hermes Agent"          # Banner title, status display
      welcome: "Welcome message"          # Shown at CLI startup
      goodbye: "Goodbye! ⚕"              # Shown on exit
      response_label: " ⚕ Hermes "       # Response box header label
      prompt_symbol: "❯ "                # Input prompt symbol
      help_header: "(^_^)? Commands"      # /help header text

    # Tool prefix: character for tool output lines (default: ┊)
    tool_prefix: "┊"

    # Tool icons: override the default tool glyph for any tool.
    tool_icons:
      terminal: "󰆍"
      web_search: " "
      # Any tool not listed here uses its registry default

    # Banner art: Rich-markup strings (use |- or |2- YAML block scalars)
    # Lines must be padded to equal length with spaces before closing [/] tag.
    # banner_logo replaces the default ASCII logo text
    banner_logo: ""
    # banner_hero replaces the default caduceus art
    banner_hero: ""

    # Syntax highlighting color scheme
    syntax_scheme: monokai      # Named scheme from built-in list
                                # Options: hermes (default), monokai, dracula,
                                #   one-dark, github-dark, nord, catppuccin,
                                #   tokyo-night, gruvbox, solarized-dark

    # Token-level overrides on top of the named scheme (optional)
    syntax:
      keyword: "bold #FF79C6"  # Any logical token name from SYNTAX_SCHEMES keys
      comment: "italic dim green"

    # Diff renderer colors (hex for bg/fg; Rich style strings for line_number etc.)
    # All *_bg/*_fg values MUST be 6-digit hex (#RRGGBB)
    diff:
      deletion_bg: "#781414"
      addition_bg: "#145a14"
      deletion_fg: "#ffffff"
      addition_fg: "#ffffff"
      intra_del_bg: "#9b1c1c"
      intra_add_bg: "#166534"
      intra_del_fg: "#ff8080"
      intra_add_fg: "#80ff80"
      line_number: "dim"        # Rich style string
      hunk_header: "bold cyan"  # Rich style string
      filename: "bold bright_white"
      file_path_fg: "#B4A0FF"   # inline diff only (display.py)
      hunk_fg: "#787882"        # inline diff only (display.py)
      context_fg: "#969696"     # inline diff only (display.py)

    # Markdown rendering styles (Rich style strings, except bullets/blockquote_marker)
    markdown:
      link: "#58A6FF underline"
      code_span: "bright_white"
      heading_1: "bold bright_white"
      blockquote_marker: "▌"   # Unicode character, not a style
      bullets: ["•", "◦", "▸", "·"]  # List, not a style
      strike: "strike"          # Rich style name for ANSI SGR 9

    # Extended UI colors
    ui_ext:
      context_bar_normal: "#5f87d7"
      context_bar_warn: "#ffa726"
      context_bar_crit: "#ef5350"
      tool_error_prefix: "red"            # Tool error line prefix style
      tool_disabled: "red"                # Disabled tool style
      tool_lazy: "yellow"                 # Lazy-loaded tool style
      menu_cursor: ["fg_green", "bold"]   # List — prompt_toolkit style tuple
      menu_highlight: ["fg_green"]
      table_header: "bold"
      table_col_accent: "bold cyan"
      table_col_dim: "dim"
      panel_border: "cyan"

    # TUI Component Part variables — injected via ThemeManager into Textual CSS.
    # These override $var values declared in hermes.tcss.
    # Omitted keys fall back to COMPONENT_VAR_DEFAULTS in theme_manager.py.
    component_vars:
      app-bg: "#1E1E1E"                   # Global app background (Screen + HermesApp + chrome)
      cursor-color: "#FFF8DC"             # Input cursor glyph/block
      cursor-selection-bg: "#3A5A8C"      # Text selection highlight
      cursor-placeholder: "#555555"       # Placeholder text
      ghost-text-color: "#555555"         # Autocomplete ghost text (not $text-muted 60%)
      chevron-base: "#FFF8DC"             # Input chevron idle
      chevron-file: "#FFBF00"             # Input chevron file mode
      chevron-stream: "#6EA8D4"           # Input chevron streaming
      chevron-shell: "#A8D46E"            # Input chevron shell mode
      chevron-done: "#4CAF50"             # Input chevron done
      chevron-error: "#E06C75"            # Input chevron error
      fuzzy-match-color: "#FFD866"        # Autocomplete fuzzy match highlight
      status-running-color: "#FFBF00"     # StatusBar running indicator
      status-error-color: "#ef5350"       # StatusBar error
      status-warn-color: "#FFA726"        # StatusBar warning
      status-context-color: "#5f87d7"     # StatusBar context info
      running-indicator-hi-color: "#FFA726"  # Running indicator bright phase
      user-echo-bullet-color: "#FFBF00"   # User message bullet
      completion-empty-bg: "#2A2A2A"      # Completion list empty state
      rule-dim-color: "#888888"           # Rule separator dim text
      rule-bg-color: "#1E1E1E"            # Rule gradient endpoint (MUST match app-bg)
      rule-accent-color: "#FFD700"        # Rule accent (TitledRule title text)
      rule-accent-dim-color: "#CC9920"    # Rule accent dim variant
      primary-darken-3: "#4a7aaa"         # TitledRule idle glyph (dimmer than $primary)
      fps-hud-bg: "#1a1a2e"               # FPS counter background
      # SC-1 dim variants (tool-call render path)
      error-dim: "#8B2020"                # Exit-code / accessible error marker (dim)
      success-dim: "#1E5C1E"             # Exit-code ok chip (dim)
      warning-dim: "#5C4A00"             # Remediation hint text (dim)
      text-muted-dim: "#3A3A3A"          # Chevron placeholder / parse-fail context (double-dim)
      # SC-4 focused ToolPanel gutter
      tool-header-gutter-color: "#00bcd4" # Focused ToolPanel left gutter (cascade: $accent-interactive)
      # SC-2 per-tier tool header icon accents
      tool-tier-read-accent: "#0178D4"   # Read-category tool icon accent
      tool-tier-write-accent: "#0178D4"  # Write-category tool icon accent
      tool-tier-exec-accent: "#81C784"   # Exec-category tool icon accent (green)
      tool-tier-search-accent: "#0178D4" # Search-category tool icon accent
      tool-tier-shell-accent: "#81C784"  # Shell-category tool icon accent (green)
      tool-tier-browse-accent: "#0178D4" # Browse-category tool icon accent
      tool-tier-mcp-accent: "#9b59b6"    # MCP tool icon accent (purple)
      tool-tier-thinking-accent: "#0178D4" # Reasoning/thinking block accent
      tool-tier-tooling-accent: "#0178D4"  # Meta/sub-agent call block accent

USAGE
=====

.. code-block:: python

    from hermes_cli.skin_engine import get_active_skin, list_skins, set_active_skin

    skin = get_active_skin()
    print(skin.colors["banner_title"])    # "#FFD700"
    print(skin.get_branding("agent_name"))  # "Hermes Agent"

    set_active_skin("ares")               # Switch to built-in ares skin
    set_active_skin("mytheme")            # Switch to user skin from ~/.hermes/skins/

BUILT-IN SKINS
==============

- ``default`` — Classic Hermes gold/kawaii (the current look)
- ``ares``    — Crimson/bronze war-god theme with custom spinner wings
- ``mono``    — Clean grayscale monochrome
- ``slate``   — Cool blue developer-focused theme

USER SKINS
==========

Drop a YAML file in ``~/.hermes/skins/<name>.yaml`` following the schema above.
Activate with ``/skin <name>`` in the CLI or ``display.skin: <name>`` in config.yaml.
"""

import functools
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)


# =============================================================================
# Syntax color schemes (logical token name → Rich style string)
# Keeping these in skin_engine.py avoids a circular import:
#   rich_output imports skin_engine; skin_engine must not import rich_output.
# =============================================================================

# MIT-licensed originals credited inline.
SYNTAX_SCHEMES: Dict[str, Dict[str, str]] = {
    "hermes": {
        # Hermes truecolor palette — warm gold/amber accent on dark terminal.
        # Identifiers (#E8E2D5) are warm off-white rather than terminal default
        # for consistent contrast regardless of terminal color scheme.
        "name":                "#E8E2D5",   # plain identifiers — warm off-white
        "keyword":             "bold #E8A838",  # amber-gold; distinct from strings
        "keyword_type":        "#6EC6C6",   # teal — type annotations / builtins
        "name_builtin":        "#6EC6C6",   # teal — len, print, etc.
        "name_class":          "bold #FFD700",  # bright gold — class definitions
        "name_function":       "bold #FFBF00",  # amber — function definitions
        "name_function_magic": "#C8A850",   # muted gold — __dunder__ methods
        "name_decorator":      "#E8844A",   # warm orange — @decorators
        "name_exception":      "#E05C5C",   # soft red — ExceptionClass
        "comment":             "italic #7A7060",  # warm grey — unobtrusive
        "string":              "#98C47A",   # sage green — string literals
        "string_doc":          "italic #7A9E60",  # darker sage — docstrings
        "string_escape":       "#C8A030",   # gold-amber — \n \t etc.
        "string_regex":        "#B8A060",   # muted amber — regex patterns
        "number":              "#C09A60",   # warm tan — numeric literals
        "operator":            "#A09880",   # warm grey — + - * /
        "operator_word":       "bold #E8A838",  # amber — and or not in
        "error":               "#E05C5C",   # soft red
        "diff_deleted":        "#F47070",   # rose-red — matches diff deletion_bg
        "diff_inserted":       "#7EC87E",   # sage-green — matches diff addition_bg
    },
    "monokai": {
        # Adapted from Wimer Hazenberg's Monokai (MIT). Background ref: #272822
        "keyword":             "bold #F92672",
        "keyword_type":        "#66D9EF",
        "name":                "#F8F8F2",
        "name_builtin":        "#66D9EF",
        "name_class":          "bold #A6E22E",
        "name_function":       "bold #A6E22E",
        "name_function_magic": "#66D9EF",
        "name_decorator":      "#FD971F",
        "name_exception":      "#F92672",
        "comment":             "#75715E",
        "string":              "#E6DB74",
        "string_doc":          "#E6DB74",
        "string_escape":       "#AE81FF",
        "string_regex":        "#E6DB74",
        "number":              "#AE81FF",
        "operator":            "#F92672",
        "operator_word":       "#F92672",
        "error":               "#F44747",
        "diff_deleted":        "#F92672",
        "diff_inserted":       "#A6E22E",
    },
    "dracula": {
        # Adapted from Zeno Rocha's Dracula (MIT). Background ref: #282A36
        "keyword":             "bold #FF79C6",
        "keyword_type":        "#8BE9FD",
        "name":                "#F8F8F2",
        "name_builtin":        "#50FA7B",
        "name_class":          "#50FA7B",
        "name_function":       "#50FA7B",
        "name_function_magic": "#50FA7B",
        "name_decorator":      "#FFB86C",
        "name_exception":      "#FF5555",
        "comment":             "italic #6272A4",
        "string":              "#F1FA8C",
        "string_doc":          "#F1FA8C",
        "string_escape":       "#FFB86C",
        "string_regex":        "#F1FA8C",
        "number":              "#BD93F9",
        "operator":            "#FF79C6",
        "operator_word":       "#FF79C6",
        "error":               "#FF5555",
        "diff_deleted":        "#FF5555",
        "diff_inserted":       "#50FA7B",
    },
    "one-dark": {
        # Adapted from Atom One Dark / One Dark Pro (MIT). Background ref: #282C34
        "keyword":             "bold #C678DD",
        "keyword_type":        "#E5C07B",
        "name":                "#ABB2BF",
        "name_builtin":        "#61AFEF",
        "name_class":          "bold #E5C07B",
        "name_function":       "bold #61AFEF",
        "name_function_magic": "#61AFEF",
        "name_decorator":      "#D19A66",
        "name_exception":      "#E06C75",
        "comment":             "italic #7F848E",
        "string":              "#98C379",
        "string_doc":          "#98C379",
        "string_escape":       "#D19A66",
        "string_regex":        "#98C379",
        "number":              "#D19A66",
        "operator":            "#56B6C2",
        "operator_word":       "#C678DD",
        "error":               "#E06C75",
        "diff_deleted":        "#E06C75",
        "diff_inserted":       "#98C379",
    },
    "github-dark": {
        # Adapted from GitHub Primer VSCode theme (MIT). Background ref: #0D1117
        "keyword":             "bold #FF7B72",
        "keyword_type":        "#79C0FF",
        "name":                "#C9D1D9",
        "name_builtin":        "#79C0FF",
        "name_class":          "bold #D0883B",
        "name_function":       "bold #79C0FF",
        "name_function_magic": "#79C0FF",
        "name_decorator":      "#D0883B",
        "name_exception":      "#FF7B72",
        "comment":             "italic #8B949E",
        "string":              "#A5D6FF",
        "string_doc":          "#A5D6FF",
        "string_escape":       "#79C0FF",
        "string_regex":        "#A5D6FF",
        "number":              "#79C0FF",
        "operator":            "#FF7B72",
        "operator_word":       "#FF7B72",
        "error":               "#FF7B72",
        "diff_deleted":        "#FF7B72",
        "diff_inserted":       "#3FB950",
    },
    "nord": {
        # Adapted from Arctic Ice Studio Nord (MIT). Background ref: #2E3440
        "keyword":             "#81A1C1",
        "keyword_type":        "#8FBCBB",
        "name":                "#D8DEE9",
        "name_builtin":        "#88C0D0",
        "name_class":          "bold #8FBCBB",
        "name_function":       "bold #88C0D0",
        "name_function_magic": "#88C0D0",
        "name_decorator":      "#D08770",
        "name_exception":      "#BF616A",
        "comment":             "italic #4C566A",
        "string":              "#A3BE8C",
        "string_doc":          "#A3BE8C",
        "string_escape":       "#EBCB8B",
        "string_regex":        "#A3BE8C",
        "number":              "#B48EAD",
        "operator":            "#81A1C1",
        "operator_word":       "#81A1C1",
        "error":               "#BF616A",
        "diff_deleted":        "#BF616A",
        "diff_inserted":       "#A3BE8C",
    },
    "catppuccin": {
        # Adapted from Catppuccin Mocha (MIT). Background ref: #1E1E2E
        "keyword":             "bold #CBA6F7",
        "keyword_type":        "#89B4FA",
        "name":                "#CDD6F4",
        "name_builtin":        "#89DCEB",
        "name_class":          "bold #A6E3A1",
        "name_function":       "bold #89B4FA",
        "name_function_magic": "#89DCEB",
        "name_decorator":      "#F9E2AF",
        "name_exception":      "#F38BA8",
        "comment":             "italic #6C7086",
        "string":              "#A6E3A1",
        "string_doc":          "#A6E3A1",
        "string_escape":       "#F9E2AF",
        "string_regex":        "#A6E3A1",
        "number":              "#FAB387",
        "operator":            "#89DCEB",
        "operator_word":       "#CBA6F7",
        "error":               "#F38BA8",
        "diff_deleted":        "#F38BA8",
        "diff_inserted":       "#A6E3A1",
    },
    "tokyo-night": {
        # Adapted from enkia/tokyo-night-vscode-theme (MIT). Background ref: #1A1B26
        "keyword":             "bold #BB9AF7",
        "keyword_type":        "#7AA2F7",
        "name":                "#C0CAF5",
        "name_builtin":        "#7AA2F7",
        "name_class":          "bold #0DB9D7",
        "name_function":       "bold #7AA2F7",
        "name_function_magic": "#7AA2F7",
        "name_decorator":      "#FF9E64",
        "name_exception":      "#F7768E",
        "comment":             "italic #51597D",
        "string":              "#9ECE6A",
        "string_doc":          "#9ECE6A",
        "string_escape":       "#89DDFF",
        "string_regex":        "#9ECE6A",
        "number":              "#FF9E64",
        "operator":            "#89DDFF",
        "operator_word":       "#BB9AF7",
        "error":               "#F7768E",
        "diff_deleted":        "#F7768E",
        "diff_inserted":       "#9ECE6A",
    },
    "gruvbox": {
        # Adapted from morhetz/gruvbox (MIT). Background ref: #282828
        "keyword":             "bold #FB4934",
        "keyword_type":        "#83A598",
        "name":                "#EBDBB2",
        "name_builtin":        "#83A598",
        "name_class":          "bold #B8BB26",
        "name_function":       "bold #B8BB26",
        "name_function_magic": "#83A598",
        "name_decorator":      "#FABD2F",
        "name_exception":      "#FB4934",
        "comment":             "italic #928374",
        "string":              "#B8BB26",
        "string_doc":          "#B8BB26",
        "string_escape":       "#FABD2F",
        "string_regex":        "#B8BB26",
        "number":              "#D3869B",
        "operator":            "#8EC07C",
        "operator_word":       "#FB4934",
        "error":               "#FB4934",
        "diff_deleted":        "#FB4934",
        "diff_inserted":       "#B8BB26",
    },
    "solarized-dark": {
        # Adapted from Ethan Schoonover's Solarized (MIT). Background ref: #002B36
        "keyword":             "bold #268BD2",
        "keyword_type":        "#268BD2",
        "name":                "#839496",
        "name_builtin":        "#2AA198",
        "name_class":          "bold #859900",
        "name_function":       "bold #859900",
        "name_function_magic": "#2AA198",
        "name_decorator":      "#CB4B16",
        "name_exception":      "#DC322F",
        "comment":             "italic #586E75",
        "string":              "#859900",
        "string_doc":          "#859900",
        "string_escape":       "#CB4B16",
        "string_regex":        "#2AA198",
        "number":              "#D33682",
        "operator":            "#268BD2",
        "operator_word":       "#268BD2",
        "error":               "#DC322F",
        "diff_deleted":        "#DC322F",
        "diff_inserted":       "#859900",
    },
}

# =============================================================================
# Default values for new skin sections
# =============================================================================

_DIFF_DEFAULTS: Dict[str, str] = {
    "deletion_bg":  "#781414",
    "addition_bg":  "#145a14",
    "deletion_fg":  "#ffffff",
    "addition_fg":  "#ffffff",
    "deletion_marker_fg": "#FF7B72",
    "addition_marker_fg": "#56D364",
    "intra_del_bg": "#9b1c1c",
    "intra_add_bg": "#166534",
    "intra_del_fg": "#ff8080",
    "intra_add_fg": "#80ff80",
    "line_number":  "dim",
    "separator":    "dim",
    "hunk_header":  "bold cyan",
    "filename":     "bold bright_white",
    "file_path_fg": "#B4A0FF",
    "hunk_fg":      "#787882",
    "context_fg":   "#969696",
}

_MARKDOWN_DEFAULTS: Dict[str, Any] = {
    "link":               "#58A6FF underline",
    "code_span":          "bright_white",
    "heading_1":          "bold bright_white",
    "heading_2":          "bold white",
    "heading_3":          "bold",
    "heading_4_6":        "bold dim",
    "blockquote":         "dim",
    "blockquote_marker":  "▌",
    "hr":                 "dim",
    "task_checked":       "bold #4caf50",
    "task_unchecked":     "dim",
    "strike":             "strike",
    "image_alt":          "dim",
    "bullets":            ["•", "◦", "▸", "·"],
    "ol_numeral":         "dim",
}

_UI_EXT_DEFAULTS: Dict[str, Any] = {
    "context_bar_normal": "#5f87d7",
    "context_bar_warn":   "#ffa726",
    "context_bar_crit":   "#ef5350",
    "tool_error_prefix":  "red",
    "tool_disabled":      "red",
    "tool_lazy":          "yellow",
    "menu_cursor":        ["fg_green", "bold"],
    "menu_highlight":     ["fg_green"],
    "table_header":       "bold",
    "table_col_accent":   "bold cyan",
    "table_col_dim":      "dim",
    "panel_border":       "cyan",
}

# =============================================================================
# Skin-switch invalidation callbacks
# =============================================================================

_invalidation_callbacks: List[Callable[[], None]] = []


def register_skin_callback(fn: Callable[[], None]) -> None:
    """Register a callable to be invoked after every skin switch.

    Use this to invalidate caches in modules that read skin values at startup
    (e.g. ANSI-string caches in rich_output.py, syntax formatter in display.py).
    skin_engine never imports those modules — callers register themselves.
    """
    _invalidation_callbacks.append(fn)


def _syntax_bold_enabled() -> bool:
    """Return whether syntax token styles should keep bold emphasis."""
    try:
        from hermes_cli.config import load_config

        display = load_config().get("display", {})
        value = display.get("syntax_bold", True)
    except Exception:
        return True

    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _strip_bold(style: str) -> str:
    """Remove the standalone ``bold`` token from a Rich style string."""
    parts = [part for part in style.split() if part.lower() != "bold"]
    return " ".join(parts)


# =============================================================================
# Skin data structure
# =============================================================================

@dataclass
class SkinConfig:
    """Complete skin configuration."""
    name: str
    description: str = ""
    colors: Dict[str, str] = field(default_factory=dict)
    spinner: Dict[str, Any] = field(default_factory=dict)
    branding: Dict[str, str] = field(default_factory=dict)
    tool_prefix: str = "┊"
    tool_icons: Dict[str, str] = field(default_factory=dict)   # per-tool glyph overrides
    banner_logo: str = ""    # Rich-markup ASCII art logo (replaces HERMES_AGENT_LOGO)
    banner_hero: str = ""    # Rich-markup hero art (replaces HERMES_CADUCEUS)
    # New in theme-integration: syntax, diff, markdown, ui_ext, component_vars
    syntax_scheme: str = "hermes"
    syntax: Dict[str, str] = field(default_factory=dict)       # per-token overrides
    diff: Dict[str, str] = field(default_factory=dict)
    markdown: Dict[str, Any] = field(default_factory=dict)     # Any: lists + strings
    ui_ext: Dict[str, Any] = field(default_factory=dict)       # Any: lists + strings
    component_vars: Dict[str, str] = field(default_factory=dict)  # TUI CSS variable overrides

    def get_color(self, key: str, fallback: str = "") -> str:
        """Get a color value with fallback."""
        return self.colors.get(key, fallback)

    def get_spinner_list(self, key: str) -> List[str]:
        """Get a spinner list (faces, verbs, etc.)."""
        return self.spinner.get(key, [])

    def get_spinner_style(self) -> Optional[str]:
        """Return the TUI spinner style key for this skin, or None to use config default."""
        return self.spinner.get("style") or None

    def get_spinner_wings(self) -> List[Tuple[str, str]]:
        """Get spinner wing pairs, or empty list if none."""
        raw = self.spinner.get("wings", [])
        result = []
        for pair in raw:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                result.append((str(pair[0]), str(pair[1])))
        return result

    def get_branding(self, key: str, fallback: str = "") -> str:
        """Get a branding value with fallback."""
        return self.branding.get(key, fallback)

    def get_syntax_styles(self) -> Dict[str, str]:
        """Return merged syntax styles: named scheme + per-skin token overrides."""
        base = dict(SYNTAX_SCHEMES.get(self.syntax_scheme, SYNTAX_SCHEMES["hermes"]))
        base.update(self.syntax)  # per-skin overrides win
        if not _syntax_bold_enabled():
            base = {
                token: (_strip_bold(style) if isinstance(style, str) else style)
                for token, style in base.items()
            }
        return base

    def get_diff(self, key: str, fallback: str = "") -> str:
        """Return a diff color/style, falling back to _DIFF_DEFAULTS then fallback."""
        return self.diff.get(key, _DIFF_DEFAULTS.get(key, fallback))

    def get_markdown(self, key: str, fallback: Any = None) -> Any:
        """Return a markdown style/value, falling back to _MARKDOWN_DEFAULTS."""
        return self.markdown.get(key, _MARKDOWN_DEFAULTS.get(key, fallback))

    def get_ui_ext(self, key: str, fallback: Any = None) -> Any:
        """Return an extended UI style/value, falling back to _UI_EXT_DEFAULTS."""
        return self.ui_ext.get(key, _UI_EXT_DEFAULTS.get(key, fallback))


# =============================================================================
# Skin loading and management
# =============================================================================

_active_skin: Optional[SkinConfig] = None
_active_skin_name: str = "default"


def _skins_dir() -> Path:
    """User skins directory."""
    return get_hermes_home() / "skins"


def _bundled_skins_dir() -> Path:
    """Path to the skins/ dir bundled inside the hermes_cli package."""
    return Path(__file__).parent / "skins"


@functools.lru_cache(maxsize=1)
def _bundled_default_payload() -> "SkinPayload":
    """Load the bundled default DESIGN.md once; used as the base for legacy YAML."""
    return load_design_md_payload(_bundled_skins_dir() / "default" / "DESIGN.md")


def _load_skin_from_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """Load a skin definition from a YAML file."""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "name" in data:
            return data
    except Exception as e:
        logger.debug("Failed to load skin from %s: %s", path, e)
    return None


_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _validate_hex(value: str, key: str, default: str) -> str:
    """Return value if it's a valid 6-digit hex color, else fall back to default."""
    if isinstance(value, str) and _HEX_RE.match(value):
        return value
    logger.warning("skin: invalid hex color for diff.%s=%r, using default %r", key, value, default)
    return default


def _build_skin_config_from_yaml(data: Dict[str, Any]) -> SkinConfig:
    """Build a SkinConfig from a raw legacy-YAML dict.

    Defaults for missing keys are sourced from the bundled `default/DESIGN.md`
    (single source of truth, replaces the deleted `_BUILTIN_SKINS["default"]`).
    """
    default_payload = _bundled_default_payload()
    colors = dict(default_payload.colors)
    colors.update(data.get("colors", {}))
    spinner = dict(default_payload.spinner)
    spinner.update(data.get("spinner", {}))
    branding = dict(default_payload.branding)
    branding.update(data.get("branding", {}))

    # --- syntax_scheme: validate against known schemes ---
    syntax_scheme = data.get("syntax_scheme", "hermes")
    if not isinstance(syntax_scheme, str) or syntax_scheme not in SYNTAX_SCHEMES:
        logger.warning("skin: unknown syntax_scheme=%r, falling back to 'hermes'", syntax_scheme)
        syntax_scheme = "hermes"

    # --- syntax: unknown token keys are silently ignored ---
    raw_syntax = data.get("syntax", {})
    syntax: Dict[str, str] = {k: v for k, v in raw_syntax.items() if isinstance(k, str)} if isinstance(raw_syntax, dict) else {}

    # --- diff: validate hex color values ---
    raw_diff = data.get("diff", {})
    diff: Dict[str, str] = {}
    if isinstance(raw_diff, dict):
        for k, v in raw_diff.items():
            if not isinstance(k, str):
                continue
            # bg/fg keys must be valid hex; style keys (line_number, hunk_header…) pass through
            if k.endswith(("_bg", "_fg")):
                default_val = _DIFF_DEFAULTS.get(k, "")
                diff[k] = _validate_hex(str(v), k, default_val)
            else:
                diff[k] = str(v) if v is not None else ""

    # --- markdown: accept as-is (Rich validates style strings at render time) ---
    raw_md = data.get("markdown", {})
    markdown: Dict[str, Any] = dict(raw_md) if isinstance(raw_md, dict) else {}

    # --- ui_ext: menu_cursor / menu_highlight accepted as list or space-split string ---
    raw_ui_ext = data.get("ui_ext", {})
    ui_ext: Dict[str, Any] = {}
    if isinstance(raw_ui_ext, dict):
        for k, v in raw_ui_ext.items():
            if k in ("menu_cursor", "menu_highlight"):
                if isinstance(v, str):
                    v = v.split() or _UI_EXT_DEFAULTS.get(k, [])
                elif isinstance(v, list) and not v:
                    v = _UI_EXT_DEFAULTS.get(k, [])
            ui_ext[k] = v

    # --- component_vars: TUI CSS variable overrides (passed to ThemeManager) ---
    raw_cv = data.get("component_vars", {})
    component_vars: Dict[str, str] = {}
    if isinstance(raw_cv, dict):
        component_vars = {str(k): str(v) for k, v in raw_cv.items()}

    return SkinConfig(
        name=data.get("name", "unknown"),
        description=data.get("description", ""),
        colors=colors,
        spinner=spinner,
        branding=branding,
        tool_prefix=data.get("tool_prefix", default_payload.tool_prefix or "┊"),
        tool_icons=data.get("tool_icons", data.get("tool_emojis", {})),
        banner_logo=data.get("banner_logo", ""),
        banner_hero=data.get("banner_hero", ""),
        syntax_scheme=syntax_scheme,
        syntax=syntax,
        diff=diff,
        markdown=markdown,
        ui_ext=ui_ext,
        component_vars=component_vars,
    )


def _resolve_skin_path(name: str) -> Optional[Path]:
    """Resolve a skin name to a DESIGN.md or .yaml file.

    Order (DM-B precedence):
    1. <HERMES_HOME>/skins/<name>/DESIGN.md  (gated by _design_md_discovery_enabled)
    2. <HERMES_HOME>/skins/<name>.yaml
    3. <hermes_cli/skins>/<name>/DESIGN.md   (bundled — NOT gated; bundled skins
       are unconditional since they replace the in-memory _BUILTIN_SKINS dict)
    Returns None only when the name is not known anywhere.
    """
    skins_path = _skins_dir()
    if _design_md_discovery_enabled():
        dm = skins_path / name / "DESIGN.md"
        if dm.is_file():
            return dm
    yaml_path = skins_path / f"{name}.yaml"
    if yaml_path.is_file():
        return yaml_path
    bundled_dm = _bundled_skins_dir() / name / "DESIGN.md"
    if bundled_dm.is_file():
        return bundled_dm
    return None


# Back-compat alias for out-of-tree consumers (plugins, in-flight branches that
# imported the private symbol). All in-tree callers use the new name. Remove
# in a follow-up cleanup PR after a deprecation cycle.
_resolve_user_skin_path = _resolve_skin_path


def _emit_yaml_deprecation_warning(path: Path, name: str, *, source_kind: str) -> None:
    """DM-K1 warning: user YAML-only loads after Phase 4 release."""
    if source_kind != "user":
        return
    if not _YAML_DEPRECATED_SINCE:
        return
    target_dir = path.parent / name
    msg = (
        f"{path} is deprecated; move it to {target_dir / 'DESIGN.md'}."
    )
    import warnings as _warnings
    _warnings.warn(msg, DeprecationWarning, stacklevel=3)


def list_skins() -> List[Dict[str, str]]:
    """List all available skins (bundled + user-installed).

    Returns list of {"name": ..., "description": ..., "source": "builtin"|"user"}.
    Order: bundled skins first (sorted by name), then user-only skins (sorted by name).
    A user-installed override of a bundled name keeps the bundled position but is
    reported with source="user" (user-wins de-dup).
    """
    result: List[Dict[str, str]] = []
    seen: set = set()

    # 1) Bundled DESIGN.md skins (sorted by name).
    bundled = _bundled_skins_dir()
    if bundled.is_dir():
        for sub in sorted(bundled.iterdir()):
            if not sub.is_dir():
                continue
            dm = sub / "DESIGN.md"
            if not dm.is_file():
                continue
            try:
                payload = load_design_md_payload(dm)
            except SkinError as exc:
                logger.warning("skin: failed to read bundled %s: %s", dm, exc)
                continue
            seen.add(payload.name)
            # Check if user has overridden this bundled name.
            user_path = _skins_dir() / payload.name / "DESIGN.md"
            user_yaml = _skins_dir() / f"{payload.name}.yaml"
            source = "user" if (
                (_design_md_discovery_enabled() and user_path.is_file())
                or user_yaml.is_file()
            ) else "builtin"
            result.append({
                "name": payload.name,
                "description": payload.description,
                "source": source,
            })

    # 2) User-only skins under HERMES_HOME (not shadowing a bundled name).
    skins_path = _skins_dir()
    if not skins_path.is_dir():
        return result

    user_only: List[Dict[str, str]] = []

    if _design_md_discovery_enabled():
        for sub in sorted(skins_path.iterdir()):
            if not sub.is_dir():
                continue
            dm = sub / "DESIGN.md"
            if not dm.is_file():
                continue
            try:
                payload = load_design_md_payload(dm)
            except SkinError as exc:
                logger.warning("skin: failed to read %s: %s", dm, exc)
                continue
            if payload.name in seen:
                continue
            seen.add(payload.name)
            user_only.append({
                "name": payload.name,
                "description": payload.description,
                "source": "user",
            })

    for f in sorted(skins_path.glob("*.yaml")):
        data = _load_skin_from_yaml(f)
        if not data:
            continue
        skin_name = data.get("name", f.stem)
        if skin_name in seen:
            continue
        seen.add(skin_name)
        user_only.append({
            "name": skin_name,
            "description": data.get("description", ""),
            "source": "user",
        })

    result.extend(user_only)
    return result


def load_skin(name: str) -> SkinConfig:
    """Load a skin by name with DESIGN.md precedence.

    Resolution order:
    1. <HERMES_HOME>/skins/<name>/DESIGN.md  (if discovery enabled)
    2. <HERMES_HOME>/skins/<name>.yaml       (emits DeprecationWarning post-Phase-4)
    3. <hermes_cli/skins>/<name>/DESIGN.md   (bundled — replaces _BUILTIN_SKINS)
    4. Bundled `default/DESIGN.md`           (last-resort fallback)

    Malformed DESIGN.md raises SkinError and does **not** silently fall through
    (DM-B precedence rule).
    """
    path = _resolve_skin_path(name)
    if path is None:
        logger.warning("Skin '%s' not found, falling back to bundled default", name)
        path = _bundled_skins_dir() / "default" / "DESIGN.md"

    if path.name == "DESIGN.md":
        payload = load_design_md_payload(path)
        return skin_config_from_payload(payload)

    # Legacy YAML path
    _emit_yaml_deprecation_warning(path, name, source_kind="user")
    data = _load_skin_from_yaml(path)
    if not data:
        # YAML parse failure → fall through to bundled default
        fallback = _bundled_skins_dir() / "default" / "DESIGN.md"
        return skin_config_from_payload(load_design_md_payload(fallback))
    return _build_skin_config_from_yaml(data)


def get_active_skin() -> SkinConfig:
    """Get the currently active skin config (cached)."""
    global _active_skin
    if _active_skin is None:
        _active_skin = load_skin(_active_skin_name)
    return _active_skin


def set_active_skin(name: str) -> SkinConfig:
    """Switch the active skin. Returns the new SkinConfig."""
    global _active_skin, _active_skin_name
    _active_skin_name = name
    _active_skin = load_skin(name)
    for fn in _invalidation_callbacks:
        try:
            fn()
        except Exception:
            pass
    return _active_skin


def get_active_skin_name() -> str:
    """Get the name of the currently active skin."""
    return _active_skin_name


def init_skin_from_config(config: dict) -> None:
    """Initialize the active skin from CLI config at startup.

    Call this once during CLI init with the loaded config dict.
    """
    display = config.get("display", {})
    if not isinstance(display, dict):
        display = {}
    skin_name = display.get("skin", "default")
    if isinstance(skin_name, str) and skin_name.strip():
        set_active_skin(skin_name.strip())
    else:
        set_active_skin("default")


# =============================================================================
# Convenience helpers for CLI modules
# =============================================================================


def get_active_prompt_symbol(fallback: str = "❯ ") -> str:
    """Get the interactive prompt symbol from the active skin."""
    try:
        return get_active_skin().get_branding("prompt_symbol", fallback)
    except Exception:
        return fallback



def get_active_help_header(fallback: str = "(^_^)? Available Commands") -> str:
    """Get the /help header from the active skin."""
    try:
        return get_active_skin().get_branding("help_header", fallback)
    except Exception:
        return fallback



def get_active_goodbye(fallback: str = "Goodbye! ⚕") -> str:
    """Get the goodbye line from the active skin."""
    try:
        return get_active_skin().get_branding("goodbye", fallback)
    except Exception:
        return fallback



def get_prompt_toolkit_style_overrides() -> Dict[str, str]:
    """Return prompt_toolkit style overrides derived from the active skin.

    These are layered on top of the CLI's base TUI style so /skin can refresh
    the live prompt_toolkit UI immediately without rebuilding the app.
    """
    try:
        skin = get_active_skin()
    except Exception:
        return {}

    prompt = skin.get_color("prompt", "#FFF8DC")
    input_rule = skin.get_color("input_rule", "#CD7F32")
    title = skin.get_color("banner_title", "#FFD700")
    text = skin.get_color("banner_text", prompt)
    dim = skin.get_color("banner_dim", "#555555")
    label = skin.get_color("ui_label", title)
    warn = skin.get_color("ui_warn", "#FF8C00")
    error = skin.get_color("ui_error", "#FF6B6B")

    accent = skin.get_color("ui_accent", title)
    ok = skin.get_color("ui_ok", "#8FBC8F")
    # Accept both naming conventions; skin_engine historically used "statusbar_bg"
    # but skins and tests use "status_bar_bg".
    _sb_bg_raw = skin.get_color("status_bar_bg") or skin.get_color("statusbar_bg")
    sb_bg = _sb_bg_raw or "#1a1a2e"
    sb_text = skin.get_color("status_bar_text") or text
    sb_strong = skin.get_color("status_bar_strong") or accent
    sb_critical = skin.get_color("status_bar_critical") or error
    vs_bg = skin.get_color("voice_status_bg") or sb_bg

    return {
        "input-area": prompt,
        "placeholder": f"{dim} italic",
        "prompt": prompt,
        "prompt-working": f"{dim} italic",
        "hint": f"{dim} italic",
        "input-rule": input_rule,
        "image-badge": f"{label} bold",
        "status-bar": f"bg:{sb_bg} {sb_text}",
        "status-bar-strong": f"bg:{sb_bg} {sb_strong} bold",
        "status-bar-dim": f"bg:{sb_bg} {dim}",
        "status-bar-good": f"bg:{sb_bg} {ok} bold",
        "status-bar-warn": f"bg:{sb_bg} {warn} bold",
        "status-bar-bad": f"bg:{sb_bg} {warn} bold",
        "status-bar-critical": f"bg:{sb_bg} {sb_critical} bold",
        "voice-status": f"bg:{vs_bg} {label}",
        "voice-status-recording": f"bg:{vs_bg} {error} bold",
        "completion-menu": f"bg:#1a1a2e {text}",
        "completion-menu.completion": f"bg:#1a1a2e {text}",
        "completion-menu.completion.current": f"bg:#333355 {title}",
        "completion-menu.meta.completion": f"bg:#1a1a2e {dim}",
        "completion-menu.meta.completion.current": f"bg:#333355 {label}",
        "clarify-border": input_rule,
        "clarify-title": f"{title} bold",
        "clarify-question": f"{text} bold",
        "clarify-choice": dim,
        "clarify-selected": f"{title} bold",
        "clarify-active-other": f"{title} italic",
        "clarify-countdown": input_rule,
        "sudo-prompt": f"{error} bold",
        "sudo-border": input_rule,
        "sudo-title": f"{error} bold",
        "sudo-text": text,
        "approval-border": input_rule,
        "approval-title": f"{warn} bold",
        "approval-desc": f"{text} bold",
        "approval-cmd": f"{dim} italic",
        "approval-choice": dim,
        "approval-selected": f"{title} bold",
    }


# =============================================================================
# DESIGN.md skin payload (DM-A / DM-C)
# =============================================================================

import re as _re_dm
import os as _os_dm
from dataclasses import dataclass as _dataclass_dm

# Re-export SkinError so DESIGN.md loader callers can catch from skin_engine.
from hermes_cli.tui.skin_loader import SkinError  # noqa: E402

# Standard DESIGN.md top-level keys we accept (anything else under root is rejected
# by validate_design_md_payload as Hermes-foreign — must move under x-hermes).
_DESIGN_MD_STANDARD_TOP_KEYS: frozenset = frozenset({
    "version", "name", "description", "colors", "typography", "rounded",
    "spacing", "components", "x-hermes",
})

# Keys allowed directly under x-hermes (the Hermes namespace).
_X_HERMES_ALLOWED_KEYS: frozenset = frozenset({
    "schema", "semantic", "component-vars", "syntax", "diff", "markdown",
    "spinner", "branding", "tool_prefix", "tool_icons", "banner_logo",
    "banner_hero", "vars", "stream_effect", "colors",
})

# Whether DESIGN.md directory discovery is on by default. Phase 4 flipped this
# from False → True. Env var HERMES_DESIGN_MD_SKINS=0 still disables.
_DESIGN_MD_DISCOVERY_DEFAULT: bool = True

# Phase 4 release marker for DM-K2 deprecation gate. Set to the version that ships
# the YAML deprecation warning. Used by _yaml_removal_unblocked().
_YAML_DEPRECATED_SINCE: str = "0.8.0"

# Whether authoring docs primarily reference DESIGN.md (Phase 3 set this to True
# alongside the skill/skin-reference doc updates). DM-K2 gate item.
_AUTHORING_DOCS_PRIMARY_DESIGN_MD: bool = True

BUNDLED_SKIN_NAMES: Tuple[str, ...] = (
    "default", "ares", "mono", "slate", "poseidon", "sisyphus", "charizard",
    "matrix", "catppuccin", "solarized-dark", "tokyo-night",
)


def _design_md_discovery_enabled() -> bool:
    """True if DESIGN.md directory discovery is active (env var or default)."""
    raw = _os_dm.environ.get("HERMES_DESIGN_MD_SKINS")
    if raw is None:
        return _DESIGN_MD_DISCOVERY_DEFAULT
    return raw.strip().lower() in ("1", "true", "yes", "on")


@_dataclass_dm(frozen=True)
class SkinPayload:
    """Normalized skin data shared by both DESIGN.md and legacy YAML loaders.

    The runtime materializes this into a SkinConfig (skin_engine) and a
    (css_vars, component_vars) tuple (theme_manager) without touching the
    on-disk format again.
    """
    name: str
    description: str
    css_vars: Dict[str, str]
    component_vars: Dict[str, str]
    colors: Dict[str, str]
    spinner: Dict[str, Any]
    branding: Dict[str, str]
    syntax_scheme: str
    syntax: Dict[str, str]
    diff: Dict[str, str]
    markdown: Dict[str, Any]
    tool_prefix: str
    tool_icons: Dict[str, str]
    banner_logo: str
    banner_hero: str

    def to_loader_tuple(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Compatibility tuple for ThemeManager._load_path()."""
        return dict(self.css_vars), dict(self.component_vars)


# ---- DESIGN.md front-matter parsing ----------------------------------------


_FRONTMATTER_RE = _re_dm.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", _re_dm.DOTALL)
_TOKEN_REF_RE = _re_dm.compile(r"\{([a-zA-Z0-9._-]+)\}")


def _parse_frontmatter(text: str, source: str) -> Dict[str, Any]:
    """Extract YAML front matter from a DESIGN.md text body."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkinError(f"{source}: missing YAML front matter (--- ... ---)")
    import yaml
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkinError(f"{source}: invalid YAML front matter: {exc}") from exc
    if not isinstance(data, dict):
        raise SkinError(f"{source}: front matter must be a mapping")
    return data


def _resolve_token_ref(value: Any, refs: Dict[str, Any], source: str, path_label: str) -> Any:
    """Resolve {dotted.path} refs in a string value against the merged refs dict.

    Refs may chain (e.g. banner-title: "{colors.accent}", colors.accent: "#abc").
    Limited to 8 expansion passes to catch cycles.
    """
    if not isinstance(value, str):
        return value
    seen: set = set()
    cur = value
    for _ in range(8):
        m = _TOKEN_REF_RE.search(cur)
        if not m:
            return cur
        full = m.group(0)
        if full in seen:
            raise SkinError(f"{source}.{path_label}: cyclic token reference {full!r}")
        seen.add(full)
        ref_path = m.group(1)
        target = _lookup_ref(refs, ref_path)
        if target is None:
            raise SkinError(
                f"{source}.{path_label}: unresolved token reference {full!r}"
            )
        if not isinstance(target, str):
            raise SkinError(
                f"{source}.{path_label}: token {full!r} points to non-string"
            )
        cur = cur.replace(full, target)
    raise SkinError(f"{source}.{path_label}: token reference expansion exceeded depth limit")


def _lookup_ref(refs: Dict[str, Any], dotted: str) -> Any:
    parts = dotted.split(".")
    node: Any = refs
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return None
    return node


def validate_design_md_payload(frontmatter: Dict[str, Any], *, source: str = "<DESIGN.md>") -> None:
    """In-process Hermes validator for DESIGN.md front matter.

    Rejects:
    - non-mapping top level
    - unknown top-level keys outside DESIGN.md standard set
    - non-string color values (after token-ref resolution skipped here — caller
      runs separate stage)
    - lists under components.* (Hermes arrays must move to x-hermes.*)
    - unknown keys directly under x-hermes
    - duplicate color keys appearing under both colors.* and x-hermes.colors.*
      (DM-G fan-out rule)
    """
    if not isinstance(frontmatter, dict):
        raise SkinError(f"{source}: front matter must be a mapping")

    for k in frontmatter:
        if k not in _DESIGN_MD_STANDARD_TOP_KEYS:
            raise SkinError(
                f"{source}: unknown top-level key {k!r} (must move under x-hermes.*)"
            )

    components = frontmatter.get("components", {}) or {}
    if not isinstance(components, dict):
        raise SkinError(f"{source}.components: must be a mapping")
    for comp_name, comp_val in components.items():
        if not isinstance(comp_val, dict):
            raise SkinError(
                f"{source}.components.{comp_name}: must be a mapping, got {type(comp_val).__name__}"
            )
        for prop, prop_val in comp_val.items():
            if isinstance(prop_val, list):
                raise SkinError(
                    f"{source}.components.{comp_name}: array values are Hermes-only; "
                    f"move to x-hermes.{comp_name}"
                )

    x_hermes = frontmatter.get("x-hermes", {}) or {}
    if not isinstance(x_hermes, dict):
        raise SkinError(f"{source}.x-hermes: must be a mapping")
    for k in x_hermes:
        if k not in _X_HERMES_ALLOWED_KEYS:
            raise SkinError(f"{source}.x-hermes.{k}: unknown extension key")

    # Duplicate-color check (DM-G fan-out rule)
    std_colors = frontmatter.get("colors", {}) or {}
    xh_colors = x_hermes.get("colors", {}) or {}
    if isinstance(std_colors, dict) and isinstance(xh_colors, dict):
        dups = set(std_colors.keys()) & set(xh_colors.keys())
        if dups:
            raise SkinError(
                f"{source}: duplicate color keys across colors.* and x-hermes.colors.*: "
                f"{sorted(dups)}"
            )


def _resolve_all_refs(value: Any, refs: Dict[str, Any], source: str, label: str) -> Any:
    """Recursively resolve token refs in nested dict/list/str."""
    if isinstance(value, str):
        return _resolve_token_ref(value, refs, source, label)
    if isinstance(value, dict):
        return {k: _resolve_all_refs(v, refs, source, f"{label}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_all_refs(v, refs, source, f"{label}[{i}]") for i, v in enumerate(value)]
    return value


def load_design_md_payload(path: Path, *, source: Optional[str] = None) -> SkinPayload:
    """Parse a DESIGN.md file into a SkinPayload.

    Steps: read text → extract YAML front matter → validate structure →
    resolve token refs → fan colors out to css_vars → emit component_vars
    from x-hermes.component-vars → assemble SkinPayload.

    Raises SkinError on any structural or reference failure.
    """
    src = source or str(path)
    text = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text, src)
    validate_design_md_payload(fm, source=src)

    # Build resolution context (colors only — refs target colors.*)
    refs: Dict[str, Any] = {"colors": dict(fm.get("colors", {}) or {})}
    fm = _resolve_all_refs(fm, refs, src, "")

    name = str(fm.get("name", "") or "")
    if not name:
        raise SkinError(f"{src}: 'name' is required")
    description = str(fm.get("description", "") or "")

    std_colors: Dict[str, Any] = fm.get("colors", {}) or {}
    x_hermes: Dict[str, Any] = fm.get("x-hermes", {}) or {}

    # ---- semantic fan-out (parent DM-A mapping) ----
    # Defer to skin_loader._SEMANTIC_MAP for the canonical fan-out list.
    from hermes_cli.tui.skin_loader import _SEMANTIC_MAP, _GLASS_KEYS

    css_vars: Dict[str, str] = {}
    skin_colors: Dict[str, str] = {}

    semantic_keys = {
        "foreground": "fg", "background": "bg", "accent": "accent",
        "accent-dim": "accent-dim", "success": "success", "warning": "warning",
        "error": "error", "muted": "muted", "border": "border",
        "selection": "selection",
    }

    # x-hermes.semantic overrides standard colors mapping
    semantic_overrides: Dict[str, str] = {}
    for k, v in (x_hermes.get("semantic", {}) or {}).items():
        if isinstance(v, str):
            semantic_overrides[str(k)] = v

    for design_key, semantic_key in semantic_keys.items():
        v = semantic_overrides.get(semantic_key, std_colors.get(design_key))
        if not isinstance(v, str):
            continue
        for target in _SEMANTIC_MAP.get(semantic_key, ()):
            css_vars.setdefault(target, v)

    # Glass keys (hyphenated identical names)
    for gk in _GLASS_KEYS:
        v = std_colors.get(gk) or semantic_overrides.get(gk)
        if isinstance(v, str):
            css_vars.setdefault(gk, v)

    # Banner / ui / prompt / etc colors: hyphen→underscore for SkinConfig.colors.
    # Skip pure semantic / glass tokens — those are CSS-var-only (parity with
    # legacy YAML which keeps banner_*/ui_*/prompt under `colors:` and the
    # semantic keys at top level).
    _SEMANTIC_COLOR_KEYS = set(semantic_keys.keys()) | set(_GLASS_KEYS)
    for k, v in std_colors.items():
        if not isinstance(v, str) or k in _SEMANTIC_COLOR_KEYS:
            continue
        underscore_key = k.replace("-", "_")
        skin_colors[underscore_key] = v
    # x-hermes.colors merges in (validated non-duplicate above)
    for k, v in (x_hermes.get("colors", {}) or {}).items():
        if isinstance(v, str):
            skin_colors[k.replace("-", "_")] = v

    # ---- x-hermes.vars → css_vars passthrough (parity with legacy `vars:`) ----
    for k, v in (x_hermes.get("vars", {}) or {}).items():
        if isinstance(v, (str, int, float)):
            css_vars.setdefault(str(k), str(v))

    # ---- component_vars from x-hermes.component-vars ----
    component_vars: Dict[str, str] = {}
    for k, v in (x_hermes.get("component-vars", {}) or {}).items():
        component_vars[str(k)] = "" if v is None else str(v)

    # ---- syntax / diff / markdown / spinner / branding ----
    syntax_block: Dict[str, Any] = x_hermes.get("syntax", {}) or {}
    syntax_scheme = str(syntax_block.get("scheme", "hermes") or "hermes")
    syntax_overrides = {
        str(k): str(v) for k, v in (syntax_block.get("overrides", {}) or {}).items()
        if isinstance(v, (str, int, float))
    }
    # Mirror syntax_scheme into component_vars (DM-D)
    component_vars.setdefault("syntax-scheme", syntax_scheme)

    diff = {str(k): "" if v is None else str(v) for k, v in (x_hermes.get("diff", {}) or {}).items()}
    markdown = dict(x_hermes.get("markdown", {}) or {})
    spinner = dict(x_hermes.get("spinner", {}) or {})
    branding = {str(k): "" if v is None else str(v) for k, v in (x_hermes.get("branding", {}) or {}).items()}
    tool_prefix = str(x_hermes.get("tool_prefix", "┊") or "┊")
    tool_icons = {str(k): "" if v is None else str(v) for k, v in (x_hermes.get("tool_icons", {}) or {}).items()}
    banner_logo = str(x_hermes.get("banner_logo", "") or "")
    banner_hero = str(x_hermes.get("banner_hero", "") or "")

    return SkinPayload(
        name=name,
        description=description,
        css_vars=css_vars,
        component_vars=component_vars,
        colors=skin_colors,
        spinner=spinner,
        branding=branding,
        syntax_scheme=syntax_scheme,
        syntax=syntax_overrides,
        diff=diff,
        markdown=markdown,
        tool_prefix=tool_prefix,
        tool_icons=tool_icons,
        banner_logo=banner_logo,
        banner_hero=banner_hero,
    )


def load_legacy_skin_payload(path: Path) -> SkinPayload:
    """Wrap legacy YAML/JSON skin loaders into a SkinPayload.

    Uses the existing skin_loader.load_skin_full for css_vars/component_vars
    parity, and reads the raw dict for SkinConfig fields (spinner, diff, etc.).

    Raises SkinError when DM-K3 removal mode is active (legacy YAML is gone).
    """
    if _DESIGN_MD_REMOVAL_ACTIVE:
        raise SkinError(
            f"{path}: legacy YAML/JSON skin loading was removed in the DESIGN.md migration "
            f"(see docs/migration-yaml-to-design-md.md)"
        )
    from hermes_cli.tui.skin_loader import load_skin_full
    css_vars, component_vars = load_skin_full(path)

    # Read the raw dict for the rest of the fields
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yml", ".yaml"):
        import yaml
        data = yaml.safe_load(text) or {}
    else:
        import json
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SkinError(f"{path}: top level must be a mapping")

    name = str(data.get("name", path.stem))
    description = str(data.get("description", ""))
    skin_colors: Dict[str, str] = {}
    for k, v in (data.get("colors", {}) or {}).items():
        if isinstance(v, str):
            skin_colors[str(k)] = v

    spinner = dict(data.get("spinner", {}) or {})
    branding = {str(k): str(v) for k, v in (data.get("branding", {}) or {}).items()}
    syntax_scheme = str(data.get("syntax_scheme", "hermes") or "hermes")
    syntax = {str(k): str(v) for k, v in (data.get("syntax", {}) or {}).items() if isinstance(v, (str, int, float))}
    diff = {str(k): str(v) for k, v in (data.get("diff", {}) or {}).items() if v is not None}
    markdown = dict(data.get("markdown", {}) or {})
    tool_prefix = str(data.get("tool_prefix", "┊") or "┊")
    tool_icons = {str(k): str(v) for k, v in (data.get("tool_icons", {}) or {}).items()}
    banner_logo = str(data.get("banner_logo", "") or "")
    banner_hero = str(data.get("banner_hero", "") or "")

    return SkinPayload(
        name=name,
        description=description,
        css_vars=css_vars,
        component_vars=component_vars,
        colors=skin_colors,
        spinner=spinner,
        branding=branding,
        syntax_scheme=syntax_scheme,
        syntax=syntax,
        diff=diff,
        markdown=markdown,
        tool_prefix=tool_prefix,
        tool_icons=tool_icons,
        banner_logo=banner_logo,
        banner_hero=banner_hero,
    )


def load_skin_payload(path: Path) -> SkinPayload:
    """Dispatch to DESIGN.md or legacy YAML/JSON loader by file shape."""
    if path.name == "DESIGN.md":
        return load_design_md_payload(path)
    suffix = path.suffix.lower()
    if suffix in (".yml", ".yaml", ".json"):
        return load_legacy_skin_payload(path)
    # Fallback: treat unknown extensions as legacy if they parse
    return load_legacy_skin_payload(path)


_DESIGN_MD_REMOVAL_ACTIVE: bool = False  # DM-K3 — flips when legacy YAML is removed


def _yaml_removal_unblocked(current_version: str, *, repo_root: Optional[Path] = None) -> Tuple[bool, List[str]]:
    """DM-K2 deprecation gate.

    Returns (allowed, reasons). Removal is allowed iff every gate passes.
    """
    reasons: List[str] = []
    repo = repo_root or Path(__file__).resolve().parents[1]

    # 1) Strict version greater-than the deprecation marker.
    try:
        from packaging.version import Version  # type: ignore
        if not _YAML_DEPRECATED_SINCE:
            reasons.append("warning release not shipped (_YAML_DEPRECATED_SINCE unset)")
        elif not (Version(current_version) > Version(_YAML_DEPRECATED_SINCE)):
            reasons.append(
                f"warning release not yet superseded "
                f"(current={current_version} <= since={_YAML_DEPRECATED_SINCE}; strict greater-than required)"
            )
    except ImportError:
        # packaging always present in the project but be defensive
        reasons.append("packaging.version unavailable; cannot verify release marker")

    # 2) Bundled DESIGN.md complete.
    bundled = _bundled_skins_dir()
    missing = [n for n in BUNDLED_SKIN_NAMES if not (bundled / n / "DESIGN.md").is_file()]
    if missing:
        reasons.append(f"bundled DESIGN.md missing for: {missing}")

    # 3) Default discovery flipped.
    if not _DESIGN_MD_DISCOVERY_DEFAULT:
        reasons.append("_DESIGN_MD_DISCOVERY_DEFAULT must be True")

    # 4) Authoring docs migrated.
    if not _AUTHORING_DOCS_PRIMARY_DESIGN_MD:
        reasons.append("_AUTHORING_DOCS_PRIMARY_DESIGN_MD must be True")

    # 5) Migration notes present.
    if not (repo / "docs" / "migration-yaml-to-design-md.md").exists():
        reasons.append("docs/migration-yaml-to-design-md.md missing")

    return (not reasons, reasons)


def design_md_lint_argv(design_md_path: Path) -> List[str]:
    """DM-J1 CI lint argv. Pure builder — does NOT spawn subprocess."""
    return ["npx", "-y", "@google/design.md", "lint", "--format", "json", str(design_md_path)]


def design_md_dtcg_export_path(skin_dir: Path) -> Path:
    """DM-J2 DTCG export artifact path: <skin_dir>/tokens.dtcg.json.

    Hermes runtime never reads this artifact. Future docs/site consumers
    require a separate spec.
    """
    return skin_dir / "tokens.dtcg.json"


def skin_config_from_payload(payload: SkinPayload) -> SkinConfig:
    """Materialize a SkinConfig from a SkinPayload (used for DESIGN.md path)."""
    # Validate / coerce syntax_scheme
    scheme = payload.syntax_scheme
    if scheme not in SYNTAX_SCHEMES:
        logger.warning("skin: unknown syntax_scheme=%r, falling back to 'hermes'", scheme)
        scheme = "hermes"
    return SkinConfig(
        name=payload.name,
        description=payload.description,
        colors=dict(payload.colors),
        spinner=dict(payload.spinner),
        branding=dict(payload.branding),
        tool_prefix=payload.tool_prefix,
        tool_icons=dict(payload.tool_icons),
        banner_logo=payload.banner_logo,
        banner_hero=payload.banner_hero,
        syntax_scheme=scheme,
        syntax=dict(payload.syntax),
        diff=dict(payload.diff),
        markdown=dict(payload.markdown),
        ui_ext={},
        component_vars=dict(payload.component_vars),
    )
