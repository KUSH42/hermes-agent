"""Tests for hermes_cli/tui/skin_loader.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.skin_loader import SkinError, load_skin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "skin.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_yaml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "skin.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Phase 1 tests
# ---------------------------------------------------------------------------

def test_semantic_fan_out(tmp_path: Path) -> None:
    """fg in input maps to both 'foreground' and 'text' outputs."""
    p = _write_json(tmp_path, {"fg": "#ffffff"})
    result = load_skin(p)
    assert result["foreground"] == "#ffffff"
    assert result["text"] == "#ffffff"


def test_raw_vars_win_on_conflict(tmp_path: Path) -> None:
    """vars: { primary: ... } beats semantic accent when both supply primary."""
    p = _write_json(tmp_path, {
        "accent": "#aabbcc",
        "vars": {"primary": "#112233"},
    })
    result = load_skin(p)
    # raw vars is pass 1; semantic is pass 2 with setdefault → raw wins
    assert result["primary"] == "#112233"
    # accent still fans out to other targets it owns
    assert result["accent"] == "#aabbcc"


def test_yaml_and_json_parity(tmp_path: Path) -> None:
    """Same content in JSON and YAML yields identical dicts."""
    data = {"fg": "#aabbcc", "bg": "#001122", "accent": "#ff0000"}
    json_path = _write_json(tmp_path, data)

    yaml_text = "fg: '#aabbcc'\nbg: '#001122'\naccent: '#ff0000'\n"
    yaml_path = _write_yaml(tmp_path, yaml_text)

    assert load_skin(json_path) == load_skin(yaml_path)


def test_invalid_top_level_raises(tmp_path: Path) -> None:
    """A top-level JSON array raises SkinError."""
    p = tmp_path / "bad.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(SkinError):
        load_skin(p)


def test_glass_keys_preserved(tmp_path: Path) -> None:
    """glass-tint passes through untouched (not in semantic map, not prefixed)."""
    p = _write_json(tmp_path, {"glass-tint": "rgba(0,0,0,0.4)"})
    result = load_skin(p)
    assert result["glass-tint"] == "rgba(0,0,0,0.4)"


def test_yaml_lazy_import(tmp_path: Path) -> None:
    """JSON-only load does not import yaml."""
    # Remove yaml from sys.modules to verify it's not imported as a side effect
    yaml_mod = sys.modules.pop("yaml", None)
    try:
        p = _write_json(tmp_path, {"fg": "#fff"})
        load_skin(p)
        assert "yaml" not in sys.modules
    finally:
        if yaml_mod is not None:
            sys.modules["yaml"] = yaml_mod


@pytest.mark.asyncio
async def test_apply_skin_updates_css_vars(tmp_path: Path) -> None:
    """apply_skin(path) injects CSS variables into a mounted HermesApp."""
    from hermes_cli.tui.app import HermesApp

    p = _write_json(tmp_path, {"accent": "#ff6600"})

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin(p)
        await pilot.pause()
        css_vars = app.get_css_variables()
        # accent fans out to "primary"
        assert "primary" in css_vars
        assert css_vars["primary"] == "#ff6600"
