from hermes_cli.tui.overlays._legacy import ToolPanelHelpOverlay


class TestChipLegend:
    def test_bindings_table_has_header_chips_heading(self):
        assert "Header chips" in ToolPanelHelpOverlay._BINDINGS_TABLE

    def test_bindings_table_has_phase_chips(self):
        t = ToolPanelHelpOverlay._BINDINGS_TABLE
        for chip in ("…STARTING", "STREAMING", "…FINALIZING", "DONE", "CANCELLED", "ERR"):
            assert chip in t, f"Missing chip: {chip!r}"

    def test_bindings_table_has_duration_chip(self):
        t = ToolPanelHelpOverlay._BINDINGS_TABLE
        assert "2m 3s" in t
        assert "elapsed time" in t

    def test_bindings_table_has_density_chips(self):
        t = ToolPanelHelpOverlay._BINDINGS_TABLE
        for chip in ("HERO", "TRACE", "COMPACT"):
            assert chip in t, f"Missing density chip: {chip!r}"

    def test_original_bindings_preserved(self):
        t = ToolPanelHelpOverlay._BINDINGS_TABLE
        for key in ("Enter", "j / k", "r", "?"):
            assert key in t, f"Original binding missing: {key!r}"

    def test_default_css_has_overflow_y_auto(self):
        assert "overflow-y: auto" in ToolPanelHelpOverlay.DEFAULT_CSS
