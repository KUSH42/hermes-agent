from hermes_cli.tui.overlays._legacy import ToolPanelHelpOverlay


class TestChipLegend:
    def test_bindings_table_has_header_chips_heading(self):
        assert "Header chips" in ToolPanelHelpOverlay._build_table()

    def test_bindings_table_has_phase_chips(self):
        t = ToolPanelHelpOverlay._build_table()
        for chip in ("…STARTING", "STREAMING", "…FINALIZING", "DONE", "CANCELLED", "ERR"):
            assert chip in t, f"Missing chip: {chip!r}"

    def test_bindings_table_has_duration_chip(self):
        t = ToolPanelHelpOverlay._build_table()
        assert "2m 3s" in t
        assert "elapsed time" in t

    def test_bindings_table_has_density_chips(self):
        t = ToolPanelHelpOverlay._build_table()
        for chip in ("HERO", "TRACE", "COMPACT"):
            assert chip in t, f"Missing density chip: {chip!r}"

    def test_actual_bindings_in_table(self):
        t = ToolPanelHelpOverlay._build_table()
        # Key bindings that must appear (from ToolPanel.BINDINGS)
        for key in ("Enter", "y", "F1", "Shift+D"):
            assert key in t, f"Binding missing from table: {key!r}"

    def test_default_css_has_overflow_y_auto(self):
        assert "overflow-y: auto" in ToolPanelHelpOverlay.DEFAULT_CSS
