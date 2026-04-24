"""LC-1: verify _TOOL_CATEGORY deleted; classify_tool / spec_for still work."""

import hermes_cli.tui.tool_category as tc
from hermes_cli.tui.tool_category import ToolCategory, classify_tool, spec_for


class TestToolCategoryDictRemoved:
    def test_tool_category_dict_absent(self):
        assert not hasattr(tc, "_TOOL_CATEGORY")

    def test_classify_tool_still_works(self):
        assert classify_tool("bash") == ToolCategory.SHELL

    def test_spec_for_still_works(self):
        result = spec_for("read_file")
        assert result.category == ToolCategory.FILE
