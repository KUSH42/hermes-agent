"""Phase D tests: InputSection category dispatch table.

12 tests covering _build_text() for each category and class toggling.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from hermes_cli.tui.tool_category import ToolCategory
from hermes_cli.tui.input_section import InputSection


# ---------------------------------------------------------------------------
# _build_text tests (pure logic — no app needed)
# ---------------------------------------------------------------------------


def _section(cat: ToolCategory, args: dict) -> InputSection:
    s = InputSection(category=cat, args=args)
    return s


def test_shell_category_builds_command_text():
    s = _section(ToolCategory.SHELL, {"command": "ls -la /tmp"})
    assert s._build_text() == "ls -la /tmp"


def test_shell_category_uses_cmd_fallback():
    s = _section(ToolCategory.SHELL, {"cmd": "echo hello"})
    assert s._build_text() == "echo hello"


def test_read_category_builds_path_text():
    s = _section(ToolCategory.FILE, {"path": "/etc/hosts"})
    assert s._build_text() == "/etc/hosts"


def test_read_category_with_range():
    s = _section(
        ToolCategory.FILE,
        {"path": "/etc/hosts", "offset": 10, "limit": 50},
    )
    assert s._build_text() == "/etc/hosts:10-50"


def test_grep_category_builds_query_root():
    s = _section(ToolCategory.SEARCH, {"pattern": "TODO", "path": "/src"})
    text = s._build_text()
    assert "TODO" in text
    assert "/src" in text


def test_grep_category_query_only():
    s = _section(ToolCategory.SEARCH, {"query": "import re"})
    assert s._build_text() == "import re"


def test_write_category_builds_path_only():
    # FILE category for write operations — no diff = just path
    s = _section(ToolCategory.FILE, {"file_path": "/tmp/out.txt"})
    assert s._build_text() == "/tmp/out.txt"


def test_edit_category_builds_path_hunks():
    diff_content = "--- a\n+++ b\n@@ -1,2 +1,3 @@\n line\n+new\n@@ -5,1 +6,1 @@\n old\n+new"
    s = _section(ToolCategory.FILE, {"path": "/src/main.py", "diff": diff_content})
    text = s._build_text()
    assert "/src/main.py" in text
    # diff has 2 @@ markers → 2 hunks reported
    assert "2 hunks" in text


def test_fetch_category_builds_method_url():
    s = _section(ToolCategory.WEB, {"method": "POST", "url": "https://api.example.com/v1"})
    assert s._build_text() == "POST https://api.example.com/v1"


def test_fetch_category_default_method():
    s = _section(ToolCategory.WEB, {"url": "https://example.com"})
    assert s._build_text().startswith("GET ")


def test_execute_code_returns_empty_string():
    s = _section(ToolCategory.CODE, {"code": "print('hello')"})
    assert s._build_text() == ""


def test_unknown_category_returns_empty():
    s = _section(ToolCategory.UNKNOWN, {"something": "value"})
    assert s._build_text() == ""


def test_should_show_false_for_execute_code():
    assert InputSection.should_show(ToolCategory.CODE) is False


def test_should_show_false_for_unknown():
    assert InputSection.should_show(ToolCategory.UNKNOWN) is False


def test_should_show_true_for_shell():
    assert InputSection.should_show(ToolCategory.SHELL) is True


def test_should_show_true_for_file():
    assert InputSection.should_show(ToolCategory.FILE) is True


@pytest.mark.asyncio
async def test_refresh_content_adds_class():
    """refresh_content with non-empty text adds -has-input class."""
    from unittest.mock import AsyncMock, patch

    app_mock = MagicMock()
    s = InputSection(category=ToolCategory.SHELL, args={})
    # Manually set up _content mock without mounting
    content_mock = MagicMock()
    s._content = content_mock
    s._classes = set()  # simulate CSS classes

    # Patch add_class / remove_class for inspection
    added = []
    removed = []
    s.add_class = lambda *a: added.extend(a)
    s.remove_class = lambda *a: removed.extend(a)

    s.refresh_content({"command": "ls"})
    assert "-has-input" in added


@pytest.mark.asyncio
async def test_refresh_content_removes_class_when_empty():
    """refresh_content with empty result removes -has-input class."""
    s = InputSection(category=ToolCategory.CODE, args={})
    content_mock = MagicMock()
    s._content = content_mock

    removed = []
    added = []
    s.add_class = lambda *a: added.extend(a)
    s.remove_class = lambda *a: removed.extend(a)

    s.refresh_content({"code": "print()"})  # CODE → empty string
    assert "-has-input" in removed
    assert "-has-input" not in added
