"""tool_blocks subpackage — re-exports every public name from the original flat module.

All importers that previously used ``from hermes_cli.tui.tool_blocks import X``
or ``from .tool_blocks import X`` continue to work unchanged.
"""
from ._shared import (
    # Constants
    COLLAPSE_THRESHOLD,
    _VISIBLE_CAP,
    _LINE_BYTE_CAP,
    _PAGE_SIZE,
    _SPINNER_FRAMES,
    _GUTTER_FALLBACK,
    _FILE_TOOL_NAMES,
    _URL_SCHEMES,
    _DIFF_PATH_RE,
    _DIFF_OLD_RE,
    _DIFF_NEW_RE,
    _DIFF_HEADER_RE,
    _DIFF_ARROW_RE,
    _IMAGE_EXTS,
    _MEDIA_LINE_RE,
    _MEDIA_EXTRACT_RE,
    _CODE_EXT_MAP,
    _AGENT_PRIMARY_ARGS,
    _AGENT_MAX_CELLS,
    _TRUNCATION_MARGIN,
    _DIFF_ADD_FALLBACK,
    _DIFF_DEL_FALLBACK,
    _RUNNING_FALLBACK,
    _VISIBLE_DIFF_ROW_RE,
    _LINK_URL_RE,
    _LINK_PATH_RE,
    _LINK_TRAIL_RE,
    # Dataclass
    ToolHeaderStats,
    # Message
    ImageMounted,
    # Widget
    OmissionBar,
    # Helper functions
    _linkify_text,
    _first_link,
    _build_args_row_text,
    _extract_image_path,
    _code_lang,
    _word_diff,
    _safe_cell_width,
    _secondary_args_text,
    _format_duration_v4,
    _count_visible_diff_rows,
    header_label_v4,
)
from ._header import (
    ToolHeader,
    ToolBodyContainer,
)
from ._block import ToolBlock
from ._streaming import (
    ToolTail,
    StreamingToolBlock,
)

# Re-export _strip_ansi (imported from hermes_cli.tui.widgets by original module)
from hermes_cli.tui.widgets import _strip_ansi

__all__ = [
    # Constants
    "COLLAPSE_THRESHOLD",
    "_VISIBLE_CAP",
    "_LINE_BYTE_CAP",
    "_PAGE_SIZE",
    "_SPINNER_FRAMES",
    "_GUTTER_FALLBACK",
    "_FILE_TOOL_NAMES",
    "_URL_SCHEMES",
    "_DIFF_PATH_RE",
    "_DIFF_OLD_RE",
    "_DIFF_NEW_RE",
    "_DIFF_HEADER_RE",
    "_DIFF_ARROW_RE",
    "_IMAGE_EXTS",
    "_MEDIA_LINE_RE",
    "_MEDIA_EXTRACT_RE",
    "_CODE_EXT_MAP",
    "_AGENT_PRIMARY_ARGS",
    "_AGENT_MAX_CELLS",
    "_TRUNCATION_MARGIN",
    "_DIFF_ADD_FALLBACK",
    "_DIFF_DEL_FALLBACK",
    "_RUNNING_FALLBACK",
    "_VISIBLE_DIFF_ROW_RE",
    "_LINK_URL_RE",
    "_LINK_PATH_RE",
    "_LINK_TRAIL_RE",
    # Dataclass
    "ToolHeaderStats",
    # Message
    "ImageMounted",
    # Widgets
    "OmissionBar",
    "ToolHeader",
    "ToolBodyContainer",
    "ToolBlock",
    "ToolTail",
    "StreamingToolBlock",
    # Helper functions
    "_linkify_text",
    "_first_link",
    "_build_args_row_text",
    "_extract_image_path",
    "_code_lang",
    "_word_diff",
    "_safe_cell_width",
    "_secondary_args_text",
    "_format_duration_v4",
    "_count_visible_diff_rows",
    "header_label_v4",
    "_strip_ansi",
]
