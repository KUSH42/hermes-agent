"""SkillCandidate — immutable descriptor for a discovered skill."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    pass

# Body-prose extraction regexes (not YAML frontmatter keys).
_TRIGGER_RE = re.compile(
    r"^TRIGGER\s+when:\s*(.+?)(?=^DO NOT TRIGGER|^SKIP:|^##|\Z)",
    re.MULTILINE | re.DOTALL,
)
_NEGATIVE_RE = re.compile(
    r"^(?:DO NOT TRIGGER\s+when:|SKIP:)\s*(.+?)(?=^TRIGGER|^##|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_prose_list(text: str) -> list[str]:
    """Extract a list of phrases from body-prose captured text."""
    result = []
    for line in text.split("\n"):
        stripped = line.strip().lstrip("- ").lstrip("* ").strip()
        if stripped:
            result.append(stripped)
    return result


def _parse_trigger_phrases(body: str) -> list[str]:
    m = _TRIGGER_RE.search(body)
    if not m:
        return []
    try:
        return _parse_prose_list(m.group(1))
    except Exception:  # prose parse failed — return empty trigger list
        return []


def _parse_negative_phrases(body: str) -> list[str]:
    m = _NEGATIVE_RE.search(body)
    if not m:
        return []
    try:
        return _parse_prose_list(m.group(1))
    except Exception:  # prose parse failed — return empty negative list
        return []


def _classify_source(
    skill_md_path: str,
) -> Literal["hermes", "claude", "plugin", "user"]:
    """Classify a skill's source from its path."""
    try:
        p = Path(skill_md_path).expanduser().resolve()
        hermes_skills = Path("~/.hermes/skills").expanduser().resolve()
        claude_skills = Path("~/.claude/skills").expanduser().resolve()
        try:
            p.relative_to(hermes_skills)
            return "hermes"
        except ValueError:
            pass
        try:
            p.relative_to(claude_skills)
            return "claude"
        except ValueError:
            pass
        # Check external dirs
        try:
            from agent.skill_utils import get_external_skills_dirs
            for ext_dir in get_external_skills_dirs():
                try:
                    p.relative_to(Path(ext_dir).expanduser().resolve())
                    return "plugin"
                except ValueError:
                    pass
        except Exception:  # external skills dir resolution failed — treat as non-plugin
            pass
        return "user"
    except Exception:  # path resolution failed entirely — default to "user"
        return "user"


@dataclass(frozen=True)
class SkillCandidate:
    """Immutable descriptor for a TUI-visible skill."""

    name: str                        # bare name, e.g. "review-pr"
    description: str                 # YAML frontmatter `description:` key
    trigger_phrases: list[str]       # body prose: lines after "TRIGGER when:"
    do_not_trigger: list[str]        # body prose: "DO NOT TRIGGER when:" / "SKIP:"
    source: Literal["hermes", "claude", "plugin", "user"] = "user"
    enabled: bool = True

    @classmethod
    def from_skill_info(
        cls,
        name: str,
        info: dict,
    ) -> "SkillCandidate":
        """Build a SkillCandidate from a ``_skill_commands`` entry dict."""
        description = info.get("description", "") or ""
        skill_md_path = info.get("skill_md_path", "") or ""
        source = _classify_source(skill_md_path)
        enabled = True
        try:
            from hermes_cli.skills_config import SkillsConfig
            cfg = SkillsConfig.load()
            enabled = cfg.is_enabled(name)
        except Exception:
            pass

        # Parse body prose for trigger/negative phrases
        trigger: list[str] = []
        negative: list[str] = []
        try:
            content = Path(skill_md_path).read_text(encoding="utf-8")
            try:
                from tools.skills_tool import _parse_frontmatter
                _fm, body = _parse_frontmatter(content)
                # description from frontmatter wins over the scan-time fallback
                fm_desc = _fm.get("description", "") or ""
                if fm_desc:
                    description = fm_desc
            except Exception:  # frontmatter parse failed — use full content as body
                body = content
            trigger = _parse_trigger_phrases(body)
            negative = _parse_negative_phrases(body)
        except Exception:  # skill_md_path unreadable or parse failed — use empty trigger/negative
            pass

        return cls(
            name=name,
            description=description,
            trigger_phrases=trigger,
            do_not_trigger=negative,
            source=source,
            enabled=enabled,
        )
