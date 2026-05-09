"""Tests for drawbraille-fg skin palette token (DRAWSKIN-1)."""
from unittest.mock import MagicMock

from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer
from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg, _cfg_from_mapping


class TestDrawilleSkinPalette:
    def _make_app(self, css_vars: dict) -> MagicMock:
        app = MagicMock()
        app.get_css_variables.return_value = css_vars
        return app

    def test_drawille_fg_reads_skin_token(self):
        renderer = DrawbrailleRenderer()
        app = self._make_app({"drawbraille-fg": "#aabbcc"})
        renderer.resolve_colors("$drawbraille-fg", "$primary", [], app)
        assert renderer._resolved_color == "#aabbcc"

    def test_drawille_fg_fallback_on_missing_var(self):
        renderer = DrawbrailleRenderer()
        app = self._make_app({})
        renderer.resolve_colors("$drawbraille-fg", "$primary", [], app)
        assert renderer._resolved_color == "#00d7ff"

    def test_drawille_fg_no_hardcoded_hex_in_defaults(self):
        import ast, inspect, re
        source = inspect.getsource(DrawbrailleOverlayCfg)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                target = node.target
                if isinstance(target, ast.Name) and target.id == "color":
                    if isinstance(node.value, ast.Constant):
                        val = node.value.value
                        assert val == "$drawbraille-fg", (
                            f"color default is {val!r}, expected '$drawbraille-fg'"
                        )
                        assert not re.match(r"#[0-9a-fA-F]{6}", val), (
                            "color default must not be a bare hex literal"
                        )

    def test_drawille_cfg_from_mapping_default(self):
        cfg = _cfg_from_mapping({})
        assert cfg.color == "$drawbraille-fg"
