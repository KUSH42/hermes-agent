"""Invariant tests for skin payload / COMPONENT_VAR_DEFAULTS."""
import re

from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS


class TestSkinPayloadInvariants:
    def test_drawbraille_fg_token_required(self):
        assert "drawbraille-fg" in COMPONENT_VAR_DEFAULTS, (
            "drawbraille-fg must be present in COMPONENT_VAR_DEFAULTS"
        )
        value = COMPONENT_VAR_DEFAULTS["drawbraille-fg"]
        assert re.match(r"^#[0-9a-fA-F]{6}$", value), (
            f"drawbraille-fg default must be a bare 6-digit hex literal, got {value!r}"
        )
