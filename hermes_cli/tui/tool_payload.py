"""ToolPayload, ResultKind, ClassificationResult — Phase B stub.

Full ToolPayload pipeline (streaming, ANSI, etc.) lands in Phase C.
For Phase B: ResultKind + ClassificationResult + minimal ToolPayload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResultKind(str, Enum):
    TEXT   = "text"    # default; FallbackRenderer
    CODE   = "code"
    DIFF   = "diff"
    SEARCH = "search"
    LOG    = "log"
    JSON   = "json"
    TABLE  = "table"
    BINARY = "binary"
    EMPTY  = "empty"


@dataclass(frozen=True)
class ClassificationResult:
    kind: ResultKind
    confidence: float   # 0.0–1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolPayload:
    tool_name: str
    category: Any
    args: dict[str, Any]
    input_display: str | None       # pre-rendered input line
    output_raw: str                 # full stdout after cwd-strip
    stderr_raw: str | None = None
    exit_code: int | None = None
    streaming: bool = False
    started_at: float = 0.0
    finished_at: float | None = None
    ansi: bool = False
    line_count: int = 0             # populated at finalize
