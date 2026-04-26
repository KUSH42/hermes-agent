"""CU-1 — verify dead spinner plumbing has been removed."""
from __future__ import annotations


class TestSpinnerRemoval:
    def test_header_has_no_spinner_char_attribute(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        h = ToolHeader.__new__(ToolHeader)
        # Minimal init so the check is meaningful (not relying on __init__ running)
        assert not hasattr(ToolHeader, "_spinner_char"), \
            "_spinner_char class attr should not exist"
        # Also confirm instance created via normal __init__ has no attribute
        h2 = ToolHeader(label="x", line_count=0, tool_name="bash")
        assert not hasattr(h2, "_spinner_char"), \
            "_spinner_char instance attr should not exist after __init__"

    def test_header_has_no_spinner_identity_attribute(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        assert not hasattr(ToolHeader, "_spinner_identity"), \
            "_spinner_identity class attr should not exist"
        h = ToolHeader(label="x", line_count=0, tool_name="bash")
        assert not hasattr(h, "_spinner_identity"), \
            "_spinner_identity instance attr should not exist after __init__"

    def test_animation_module_exports_no_spinner_identity(self):
        import hermes_cli.tui.animation as a
        assert not hasattr(a, "SpinnerIdentity"), \
            "SpinnerIdentity should have been deleted from animation module"
        assert not hasattr(a, "make_spinner_identity"), \
            "make_spinner_identity should have been deleted from animation module"
