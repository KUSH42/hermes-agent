"""Tests for bundled skin hero/logo gradient parity (HG-1 through HG-7)."""

import re
import yaml
from pathlib import Path

SKIN_DIR = Path(__file__).resolve().parents[2] / "hermes_cli" / "skins"
_COLOR_ALIAS_RE = re.compile(r"^\{colors\.(.+)\}$")
_MARKUP_RE = re.compile(r"\[(?:dim |bold )?#([0-9A-Fa-f]{6})\]")


def _load(name: str) -> dict:
    """Parse DESIGN.md YAML frontmatter; resolve {colors.X} aliases."""
    text = (SKIN_DIR / name / "DESIGN.md").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    data = yaml.safe_load(parts[1])
    raw_colors = data.get("colors", {})
    resolved = {}
    for k, v in raw_colors.items():
        if isinstance(v, str):
            m = _COLOR_ALIAS_RE.match(v)
            resolved[k] = raw_colors.get(m.group(1), v) if m else v
        else:
            resolved[k] = v
    data["colors"] = resolved
    return data


def _stops(markup: str) -> list:
    """Return uppercase hex strings (no '#') in source order."""
    return [h.upper() for h in _MARKUP_RE.findall(markup)]


def _luminance(hex6: str) -> float:
    """WCAG 2.1 relative luminance (0.0–1.0)."""
    r, g, b = int(hex6[0:2], 16) / 255, int(hex6[2:4], 16) / 255, int(hex6[4:6], 16) / 255

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _hero_rows(skin_name: str) -> list:
    """Return non-blank lines from banner_hero."""
    hero = _load(skin_name)["x-hermes"].get("banner_hero", "")
    return [l for l in hero.split("\n") if l.strip()]


def _logo_rows(skin_name: str) -> list:
    """Return non-blank lines from banner_logo."""
    logo = _load(skin_name)["x-hermes"].get("banner_logo", "")
    return [l for l in logo.split("\n") if l.strip()]


# ---------------------------------------------------------------------------
# Helpers smoke tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_stops_extracts_all_forms(self):
        markup = "[#FF0000]x[/] [dim #00FF00]y[/] [bold #0000FF]z[/]"
        assert _stops(markup) == ["FF0000", "00FF00", "0000FF"]

    def test_luminance_white_and_black(self):
        assert abs(_luminance("FFFFFF") - 1.0) < 1e-6
        assert abs(_luminance("000000") - 0.0) < 1e-6

    def test_load_resolves_color_aliases(self):
        data = _load("catppuccin")
        colors = data["colors"]
        # catppuccin banner-title = {colors.accent} = #cba6f7
        assert colors["banner-title"].startswith("#") or len(colors["banner-title"]) == 7
        assert "{colors." not in colors["banner-title"]
        assert "{colors." not in colors["banner-dim"]


# ---------------------------------------------------------------------------
# HG-1 — ares hero
# ---------------------------------------------------------------------------

class TestAresHero:
    def test_ares_hero_no_offpalette_tan(self):
        hero = _load("ares")["x-hermes"]["banner_hero"]
        assert "#C7A96B" not in hero, "off-palette tan still present in ares banner_hero"

    def test_ares_hero_uses_only_palette_stops(self):
        hero = _load("ares")["x-hermes"]["banner_hero"]
        allowed = {"F1E6CF", "DD4A3A", "C93C24", "9F1C1C", "6B1717"}
        actual = set(_stops(hero))
        assert actual <= allowed, f"off-palette stops in ares hero: {actual - allowed}"

    def test_ares_hero_monotonic_top_down_lightness(self):
        rows = _hero_rows("ares")
        # rows 1-10 (0-indexed 0-9); rows 11-14 excluded (foot/⚔/caption motifs)
        window = rows[:10]
        lums = []
        for row in window:
            hits = _stops(row)
            assert hits, f"row has no color stop: {row!r}"
            lums.append(_luminance(hits[0]))
        for i in range(1, len(lums)):
            assert lums[i] <= lums[i - 1] + 1e-6, (
                f"ares hero luminance not monotonic at row {i + 1}: "
                f"{lums[i - 1]:.4f} → {lums[i]:.4f}"
            )


# ---------------------------------------------------------------------------
# HG-2 — poseidon hero
# ---------------------------------------------------------------------------

class TestPoseidonHero:
    def test_poseidon_hero_uses_only_palette_stops(self):
        hero = _load("poseidon")["x-hermes"]["banner_hero"]
        allowed = {"EAF7FF", "A9DFFF", "5DB8F5", "2A6FB9", "153C73"}
        actual = set(_stops(hero))
        assert actual <= allowed, f"off-palette stops in poseidon hero: {actual - allowed}"

    def test_poseidon_hero_trident_monotonic(self):
        rows = _hero_rows("poseidon")
        # rows 1-10 (0-indexed 0-9); rows 11-12 excluded (wave motif)
        window = rows[:10]
        lums = []
        for row in window:
            hits = _stops(row)
            assert hits, f"row has no color stop: {row!r}"
            lums.append(_luminance(hits[0]))
        for i in range(1, len(lums)):
            assert lums[i] <= lums[i - 1] + 1e-6, (
                f"poseidon hero luminance not monotonic at row {i + 1}: "
                f"{lums[i - 1]:.4f} → {lums[i]:.4f}"
            )

    def test_poseidon_hero_caption_dim(self):
        rows = _hero_rows("poseidon")
        last = rows[-1]
        assert "[dim #153C73]" in last, f"caption row not dim #153C73: {last!r}"


# ---------------------------------------------------------------------------
# HG-3 — charizard hero (palette lock, no edits)
# ---------------------------------------------------------------------------

class TestCharizardHeroLocked:
    def test_charizard_hero_palette_locked(self):
        hero = _load("charizard")["x-hermes"]["banner_hero"]
        expected = {"FFD39A", "F29C38", "E2832B", "C75B1D", "7A3511"}
        actual = set(_stops(hero))
        assert actual == expected, (
            f"charizard hero palette drifted. extra={actual - expected}, "
            f"missing={expected - actual}"
        )


# ---------------------------------------------------------------------------
# HG-4 — sisyphus hero
# ---------------------------------------------------------------------------

class TestSisyphusHero:
    def test_sisyphus_hero_no_offpalette_grey(self):
        hero = _load("sisyphus")["x-hermes"]["banner_hero"]
        assert "#656565" not in hero, "off-palette grey #656565 still present in sisyphus banner_hero"

    def test_sisyphus_hero_uses_only_palette_stops(self):
        hero = _load("sisyphus")["x-hermes"]["banner_hero"]
        allowed = {"F5F5F5", "E7E7E7", "D3D3D3", "B7B7B7", "919191", "4A4A4A"}
        actual = set(_stops(hero))
        assert actual <= allowed, f"off-palette stops in sisyphus hero: {actual - allowed}"

    def test_sisyphus_hero_monotonic_top_down_lightness(self):
        rows = _hero_rows("sisyphus")
        # rows 4-12 (0-indexed 3-11); rows 1-3 excluded (ascending arc)
        window = rows[3:12]
        lums = []
        for row in window:
            hits = _stops(row)
            assert hits, f"row has no color stop: {row!r}"
            lums.append(_luminance(hits[0]))
        for i in range(1, len(lums)):
            assert lums[i] <= lums[i - 1] + 1e-6, (
                f"sisyphus hero luminance not monotonic at position {i + 1}: "
                f"{lums[i - 1]:.4f} → {lums[i]:.4f}"
            )


# ---------------------------------------------------------------------------
# HG-5 — matrix (no-markup invariants)
# ---------------------------------------------------------------------------

_COLOR_MARKUP_RE = re.compile(r"\[(?:dim |bold )?#[0-9A-Fa-f]{6}\]")


class TestMatrixNoMarkup:
    def test_matrix_hero_has_no_color_markup(self):
        hero = _load("matrix")["x-hermes"].get("banner_hero", "")
        assert not _COLOR_MARKUP_RE.search(hero), (
            "matrix banner_hero has hardcoded color markup — would defeat render gradient"
        )

    def test_matrix_logo_has_no_color_markup(self):
        logo = _load("matrix")["x-hermes"].get("banner_logo", "")
        assert not _COLOR_MARKUP_RE.search(logo), (
            "matrix banner_logo has hardcoded color markup — would defeat render gradient"
        )


# ---------------------------------------------------------------------------
# HG-6 — banner_logo 3-band gradient (ares, charizard, poseidon, sisyphus)
# ---------------------------------------------------------------------------

_LOGO_PALETTES = {
    "ares":      {"C7A96B", "DD4A3A", "6B1717"},
    "charizard": {"FFD39A", "F29C38", "7A3511"},
    "poseidon":  {"A9DFFF", "5DB8F5", "153C73"},
    "sisyphus":  {"F5F5F5", "E7E7E7", "4A4A4A"},
}


class TestBannerLogos:
    def test_ares_logo_three_band_gradient(self):
        logo = _load("ares")["x-hermes"]["banner_logo"]
        actual = set(_stops(logo))
        assert _LOGO_PALETTES["ares"] <= actual

    def test_charizard_logo_three_band_gradient(self):
        logo = _load("charizard")["x-hermes"]["banner_logo"]
        actual = set(_stops(logo))
        assert _LOGO_PALETTES["charizard"] <= actual

    def test_poseidon_logo_three_band_gradient(self):
        logo = _load("poseidon")["x-hermes"]["banner_logo"]
        actual = set(_stops(logo))
        assert _LOGO_PALETTES["poseidon"] <= actual

    def test_sisyphus_logo_three_band_gradient(self):
        logo = _load("sisyphus")["x-hermes"]["banner_logo"]
        actual = set(_stops(logo))
        assert _LOGO_PALETTES["sisyphus"] <= actual

    def test_logos_no_offpalette_stops(self):
        for skin, palette in _LOGO_PALETTES.items():
            logo = _load(skin)["x-hermes"]["banner_logo"]
            actual = set(_stops(logo))
            assert actual <= palette, (
                f"{skin} banner_logo has off-palette stops: {actual - palette}"
            )

    def test_logos_bold_preserved(self):
        for skin in _LOGO_PALETTES:
            rows = _logo_rows(skin)
            for i, row in enumerate(rows):
                assert "[bold #" in row, (
                    f"{skin} banner_logo row {i + 1} missing bold: {row!r}"
                )


# ---------------------------------------------------------------------------
# HG-7 — fallback skins gradient sanity gate
# ---------------------------------------------------------------------------

_FALLBACK_SKINS = ["hermes", "catppuccin", "mono", "slate", "solarized-dark", "tokyo-night"]


class TestFallbackSkinsGate:
    def test_fallback_skins_have_distinct_banner_lerp_stops(self):
        for skin in _FALLBACK_SKINS:
            colors = _load(skin)["colors"]
            accent = colors.get("banner-accent", "")
            text = colors.get("banner-text", "")
            dim = colors.get("banner-dim", "")
            for var in (accent, text, dim):
                assert var and re.match(r"^#[0-9A-Fa-f]{6}$", var), (
                    f"{skin} has non-hex banner var: {var!r}"
                )
            assert accent.upper() != text.upper(), f"{skin}: banner-accent == banner-text"
            assert accent.upper() != dim.upper(), f"{skin}: banner-accent == banner-dim"
            assert text.upper() != dim.upper(), f"{skin}: banner-text == banner-dim"

    def test_fallback_skins_have_no_banner_hero(self):
        for skin in _FALLBACK_SKINS:
            colors = _load(skin)["x-hermes"]
            assert "banner_hero" not in colors, (
                f"{skin} unexpectedly has banner_hero — would disable the render lerp"
            )
