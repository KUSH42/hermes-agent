"""Welcome banner, ASCII art, skills summary, and update check for the CLI.

Pure display functions with no HermesCLI state dependency.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from hermes_constants import get_hermes_home
from typing import Dict, List, Optional

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hermes_cli.tui.animation import lerp_color
from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI

logger = logging.getLogger(__name__)
_HERO_CACHE: dict[str, tuple[str, int]] = {}


# =========================================================================
# ANSI building blocks for conversation display
# =========================================================================

_GOLD = "\033[1;38;2;255;215;0m"  # True-color #FFD700 bold
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RST = "\033[0m"


def _normalize_ansi_c1(text: str) -> str:
    """Normalize 8-bit C1 CSI controls to standard ESC-prefixed ANSI."""
    if "\x9b" not in text:
        return text
    return text.replace("\x9b", "\x1b[")


def cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's renderer."""
    _pt_print(_PT_ANSI(_normalize_ansi_c1(text)))


# =========================================================================
# Skin-aware color helpers
# =========================================================================

def _skin_color(key: str, fallback: str) -> str:
    """Get a color from the active skin, or return fallback."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        return get_active_skin().get_color(key, fallback)
    except Exception:
        return fallback


def _skin_branding(key: str, fallback: str) -> str:
    """Get a branding string from the active skin, or return fallback."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        return get_active_skin().get_branding(key, fallback)
    except Exception:
        return fallback


# =========================================================================
# ASCII Art & Branding
# =========================================================================

from hermes_cli import __version__ as VERSION, __release_date__ as RELEASE_DATE

HERMES_AGENT_LOGO = """[#FFD700]██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
[#FFD700]██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
[#FFBF00]███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]
[#FFBF00]██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]
[#CD7F32]██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]
[#CD7F32]╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]"""

HERMES_CADUCEUS = """[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀[/]
[#FFBF00]⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀[/]
[#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⡿⠛⢁⡈⠛⢿⣿⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣦⣤⣈⠁⢠⣴⣿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠻⢿⣿⣦⡉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⣦⣈⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣴⠦⠈⠙⠿⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣤⡈⠁⢤⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠑⢶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠁⢰⡆⠈⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⠈⣡⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]"""

COMPACT_BANNER = """
[bold #FFD700]╔══════════════════════════════════════════════════════════════╗[/]
[bold #FFD700]║[/]  [#FFBF00]⚕ NOUS HERMES[/] [dim #B8860B]- AI Agent Framework[/]              [bold #FFD700]║[/]
[bold #FFD700]║[/]  [#CD7F32]Messenger of the Digital Gods[/]    [dim #B8860B]Nous Research[/]   [bold #FFD700]║[/]
[bold #FFD700]╚══════════════════════════════════════════════════════════════╝[/]
"""


def resolve_banner_logo_assets() -> tuple[str, str]:
    """Return startup banner logo as (Rich-markup text, plain text)."""
    try:
        from hermes_cli.skin_engine import get_active_skin, get_active_skin_name
        skin = get_active_skin()
        markup_logo = (
            skin.banner_logo
            if hasattr(skin, "banner_logo") and skin.banner_logo
            else HERMES_AGENT_LOGO
        )
        markup_logo = _recover_multiline_user_skin_art(
            get_active_skin_name(), "banner_logo", markup_logo
        )
    except Exception:
        markup_logo = HERMES_AGENT_LOGO
    try:
        plain_logo = Text.from_markup(markup_logo).plain
    except Exception:
        plain_logo = markup_logo
    return markup_logo, plain_logo


def resolve_banner_hero_assets() -> tuple[str, str]:
    """Return caduceus hero art as (Rich-markup text, plain text).

    The hero is the animated target for startup_text_effect.
    Falls back to skin's banner_hero if set.
    """
    try:
        from hermes_cli.skin_engine import get_active_skin, get_active_skin_name
        skin = get_active_skin()
        markup_hero = (
            skin.banner_hero
            if hasattr(skin, "banner_hero") and skin.banner_hero
            else HERMES_CADUCEUS
        )
        markup_hero = _recover_multiline_user_skin_art(
            get_active_skin_name(), "banner_hero", markup_hero
        )
    except Exception:
        markup_hero = HERMES_CADUCEUS
    try:
        plain_hero = Text.from_markup(markup_hero).plain
    except Exception:
        plain_hero = markup_hero
    return markup_hero, plain_hero


def _invalidate_hero_cache() -> None:
    """Clear cached hero widths after a skin switch or reload."""
    _HERO_CACHE.clear()


def get_cached_hero_width() -> tuple[str, int]:
    """Return cached plain hero text and width for the active skin."""
    try:
        from hermes_cli.skin_engine import get_active_skin_name

        key = get_active_skin_name() or ""
    except Exception:
        # Banner width caching must stay usable before skin engine init settles.
        key = ""
    cached = _HERO_CACHE.get(key)
    if cached is not None:
        return cached
    _, plain = resolve_banner_hero_assets()
    width = max((len(line) for line in plain.splitlines()), default=30)
    _HERO_CACHE[key] = (plain, width)
    return _HERO_CACHE[key]


def _hex_luminance(hex6: str) -> float:
    h = hex6.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hero_gradient_direction() -> str:
    """Return the active skin's TTE final_gradient_direction name, or 'RADIAL'."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        tte = get_active_skin().get_startup_tte() or {}
        params = tte.get("params") or {}
        d = params.get("final_gradient_direction")
        if isinstance(d, str) and d.strip():
            return d.strip().upper()
    except Exception:
        pass
    return "RADIAL"


def _hero_gradient_stops() -> list[str] | None:
    """Return active skin's TTE final_gradient_stops for hero coloring (mirror tail
    trimmed so the hero ramp stays monotonic), or None."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        tte = get_active_skin().get_startup_tte() or {}
        params = tte.get("params") or {}
        stops = params.get("final_gradient_stops")
        if not isinstance(stops, (list, tuple)) or len(stops) < 2:
            return None
        stops = [str(s) for s in stops]
        # Trim mirror tail (e.g. ares laser-bounce ramp E8…→6B…→9A…→B8…):
        # cut once the direction reverses *significantly* (>10% of the total
        # luminance span), so palettes with minor non-monotonic nuance like
        # tokyo-night a48ee8→7aa2f7 are kept intact.
        lums = [_hex_luminance(s) for s in stops]
        span = max(lums) - min(lums)
        threshold = span * 0.10 if span > 0 else 0
        decreasing = lums[1] < lums[0]
        cut = len(stops)
        for i in range(2, len(lums)):
            delta = lums[i] - lums[i - 1]
            if decreasing and delta > threshold:
                cut = i
                break
            if not decreasing and -delta > threshold:
                cut = i
                break
        return stops[:cut]
    except Exception:
        return None


def _interp_stops(stops: list[str], t: float) -> str:
    """Linear-interpolate hex stops at parameter t in [0, 1]."""
    if t <= 0.0:
        return stops[0]
    if t >= 1.0:
        return stops[-1]
    n = len(stops) - 1
    pos = t * n
    seg = int(pos)
    frac = pos - seg
    return lerp_color(stops[seg], stops[seg + 1], frac)


def _is_blank_glyph(ch: str) -> bool:
    return ch == " " or ch == "⠀"


def _tte_gradient_t(
    row: int,
    col: int,
    row_top: int,
    row_bot: int,
    col_min: int,
    col_max: int,
    direction: str,
) -> float:
    """Compute gradient t matching terminaltexteffects' build_coordinate_color_mapping.

    VERTICAL   : same color per row, ramp top→bottom
    HORIZONTAL : same color per col, ramp left→right
    DIAGONAL   : TTE formula (2*adj_row + adj_col) / (2*max_row + max_col)
    RADIAL     : TTE formula — aspect-ratio-corrected distance from center (row×2)
    """
    row_range = max(row_bot - row_top, 1)
    col_range = max(col_max - col_min, 1)

    if direction == "VERTICAL":
        return max(0.0, min(1.0, (row - row_top) / row_range))
    if direction == "HORIZONTAL":
        return max(0.0, min(1.0, (col - col_min) / col_range))
    if direction == "DIAGONAL":
        adj_row = row - row_top
        adj_col = col - col_min
        denom = 2 * row_range + col_range
        return max(0.0, min(1.0, (2 * adj_row + adj_col) / denom)) if denom else 0.0
    # RADIAL: aspect-ratio-corrected distance from center (TTE uses row*2 weight)
    center_row = row_top + row_range / 2
    center_col = col_min + col_range / 2
    max_dist = ((col_range / 2) ** 2 + (row_range) ** 2) ** 0.5  # row already ×2 via *2 below
    dy = (row - center_row) * 2
    dx = col - center_col
    dist = (dx ** 2 + dy ** 2) ** 0.5
    return min(1.0, dist / max_dist) if max_dist > 0 else 0.0


def render_banner_hero_text(markup_hero: str) -> Text:
    """Render banner hero markup; unstyled lines get a per-char diagonal gradient
    using the skin's startup_tte final_gradient_stops, falling back to a 3-stop
    top→bottom fade across banner_accent → banner_text → banner_dim.

    The gradient is mapped across the *painted* shape — visible cells per row
    and rows that contain visible cells — so the ramp lands on the actual
    sigil instead of being stretched across surrounding empty cells.
    """
    try:
        hero_text = Text.from_markup(markup_hero)
    except Exception:
        hero_text = Text(markup_hero)
    accent = _skin_color("banner_accent", "#FFBF00")
    text_c = _skin_color("banner_text", "#FFF8DC")
    dim = _skin_color("banner_dim", "#B8860B")
    stops = _hero_gradient_stops()
    lines = hero_text.split("\n", allow_blank=True)
    n = len(lines)

    # Compute visible-row range and per-row visible-col span so the gradient
    # maps across the painted shape, not the bounding box.
    row_has_paint = [
        any(not _is_blank_glyph(c) for c in ln.plain) for ln in lines
    ]
    paint_rows = [i for i, h in enumerate(row_has_paint) if h]
    row_top = paint_rows[0] if paint_rows else 0
    row_bot = paint_rows[-1] if paint_rows else max(n - 1, 0)
    row_span = max(row_bot - row_top, 1)
    row_extents: list[tuple[int, int]] = []
    for ln in lines:
        cols = [j for j, c in enumerate(ln.plain) if not _is_blank_glyph(c)]
        if cols:
            row_extents.append((cols[0], cols[-1]))
        else:
            row_extents.append((0, 0))

    # Global col bounds across all painted rows — needed for 2D gradient formulas.
    global_col_min = min((row_extents[i][0] for i in paint_rows), default=0)
    global_col_max = max((row_extents[i][1] for i in paint_rows), default=0)
    direction = _hero_gradient_direction() if stops is not None else "RADIAL"

    out = Text()
    for i, line in enumerate(lines):
        if line.style or line.spans:
            out.append_text(line)
        elif stops is not None:
            plain = line.plain
            for j, ch in enumerate(plain):
                if _is_blank_glyph(ch):
                    out.append(ch)
                    continue
                t = _tte_gradient_t(i, j, row_top, row_bot, global_col_min, global_col_max, direction)
                out.append(ch, style=_interp_stops(stops, t))
        else:
            if n <= 1:
                color = accent
            else:
                t = i / (n - 1)
                if t <= 0.5:
                    color = lerp_color(accent, text_c, t * 2.0)
                else:
                    color = lerp_color(text_c, dim, (t - 0.5) * 2.0)
            out.append_text(Text(line.plain, style=color))
        if i < n - 1:
            out.append("\n")
    return out


def _count_visual_rows(renderables: list) -> int:
    """Count visual rows: Text counts \\n+1; other renderables count 1."""
    n = 0
    for r in renderables:
        if isinstance(r, Text):
            n += r.plain.count("\n") + 1
        else:
            n += 1
    return n


def render_banner_logo_text(markup_logo: str) -> Text:
    """Render banner logo with a per-character diagonal gradient.

    When the active skin exposes `startup_tte.params.final_gradient_stops`,
    the logo's plain text is rendered with the same per-cell diagonal ramp
    as the hero — overriding any per-row hex markup that would otherwise
    paint the logo as horizontal stripes. Falls back to a row-wise
    accent→dim lerp when no stops are configured.
    """
    try:
        logo_text = Text.from_markup(markup_logo)
    except Exception:
        logo_text = Text(markup_logo)

    stops = _hero_gradient_stops()
    plain = logo_text.plain
    lines = plain.split("\n") if plain else [""]
    n = len(lines)
    width = max((len(l) for l in lines), default=1) or 1

    if stops is not None:
        direction = _hero_gradient_direction()
        # Compute painted bounding box for TTE-matching spatial gradient.
        paint_cols_logo = [[j for j, ch in enumerate(ln) if ch not in (" ", "⠀")] for ln in lines]
        paint_rows_logo = [i for i, cols in enumerate(paint_cols_logo) if cols]
        row_top_l = paint_rows_logo[0] if paint_rows_logo else 0
        row_bot_l = paint_rows_logo[-1] if paint_rows_logo else max(n - 1, 0)
        all_cols_l = [c for cols in paint_cols_logo for c in cols]
        col_min_l = min(all_cols_l) if all_cols_l else 0
        col_max_l = max(all_cols_l) if all_cols_l else max(width - 1, 0)
        out = Text()
        for i, line in enumerate(lines):
            for j, ch in enumerate(line):
                if ch == " " or ch == "⠀":
                    out.append(ch)
                    continue
                t = _tte_gradient_t(i, j, row_top_l, row_bot_l, col_min_l, col_max_l, direction)
                out.append(ch, style=f"bold {_interp_stops(stops, t)}")
            if i < n - 1:
                out.append("\n")
        return out

    if logo_text.style or logo_text.spans:
        return logo_text

    accent = _skin_color("banner_accent", "#FFBF00")
    dim = _skin_color("banner_dim", "#B8860B")
    out = Text()
    for idx, line in enumerate(lines):
        t = 0.0 if n <= 1 else idx / (n - 1)
        out.append(line, style=lerp_color(accent, dim, t))
        if idx != n - 1:
            out.append("\n")
    return out


def _recover_multiline_user_skin_art(skin_name: str, key: str, value: str) -> str:
    """Recover multiline user-skin ASCII art when YAML folded it into one line."""
    if not isinstance(value, str) or "\n" in value:
        return value

    try:
        from hermes_cli.skin_engine import _skins_dir

        skin_file = _skins_dir() / f"{skin_name}.yaml"
        if not skin_file.is_file():
            return value
        raw_lines = skin_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return value

    pattern = re.compile(rf"^{re.escape(key)}:(.*)$")
    for idx, line in enumerate(raw_lines):
        match = pattern.match(line)
        if not match:
            continue

        inline = match.group(1)
        if inline.lstrip().startswith(("|", ">")):
            return value

        recovered: list[str] = []
        if inline:
            recovered.append(inline[1:] if inline.startswith(" ") else inline)

        for next_line in raw_lines[idx + 1 :]:
            if next_line and not next_line.startswith((" ", "\t")):
                break
            if next_line == "":
                break
            recovered.append(next_line)

        if len(recovered) > 1:
            return "\n".join(recovered).rstrip()
        return value

    return value


try:
    from hermes_cli.skin_engine import register_skin_callback as _register_skin_callback
except Exception:
    # Banner rendering still works without callback registration; cache stays process-local.
    _register_skin_callback = None
else:
    _register_skin_callback(_invalidate_hero_cache)


# =========================================================================
# Skills scanning
# =========================================================================

def get_available_skills() -> Dict[str, List[str]]:
    """Return skills grouped by category, filtered by platform and disabled state.

    Delegates to ``_find_all_skills()`` from ``tools/skills_tool`` which already
    handles platform gating (``platforms:`` frontmatter) and respects the
    user's ``skills.disabled`` config list.
    """
    try:
        from tools.skills_tool import _find_all_skills
        all_skills = _find_all_skills()  # already filtered
    except Exception:
        return {}

    skills_by_category: Dict[str, List[str]] = {}
    for skill in all_skills:
        category = skill.get("category") or "general"
        skills_by_category.setdefault(category, []).append(skill["name"])
    return skills_by_category


# =========================================================================
# Update check
# =========================================================================

# Cache update check results for 6 hours to avoid repeated git fetches
_UPDATE_CHECK_CACHE_SECONDS = 6 * 3600


def check_for_updates() -> Optional[int]:
    """Check how many commits behind origin/main the local repo is.

    Does a ``git fetch`` at most once every 6 hours (cached to
    ``~/.hermes/.update_check``).  Returns the number of commits behind,
    or ``None`` if the check fails or isn't applicable.
    """
    hermes_home = get_hermes_home()
    repo_dir = hermes_home / "hermes-agent"
    cache_file = hermes_home / ".update_check"

    # Must be a git repo — fall back to project root for dev installs
    if not (repo_dir / ".git").exists():
        repo_dir = Path(__file__).parent.parent.resolve()
    if not (repo_dir / ".git").exists():
        return None

    # Read cache
    now = time.time()
    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            if now - cached.get("ts", 0) < _UPDATE_CHECK_CACHE_SECONDS:
                return cached.get("behind")
    except Exception:
        pass

    # Fetch latest refs (fast — only downloads ref metadata, no files)
    try:
        subprocess.run(
            ["git", "fetch", "origin", "--quiet"],
            capture_output=True, timeout=10,
            cwd=str(repo_dir),
        )
    except Exception:
        pass  # Offline or timeout — use stale refs, that's fine

    # Count commits behind
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True, text=True, timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            behind = int(result.stdout.strip())
        else:
            behind = None
    except Exception:
        behind = None

    # Write cache
    try:
        cache_file.write_text(json.dumps({"ts": now, "behind": behind}))
    except Exception:
        pass

    return behind


def _resolve_repo_dir() -> Optional[Path]:
    """Return the active Hermes git checkout, or None if this isn't a git install."""
    hermes_home = get_hermes_home()
    repo_dir = hermes_home / "hermes-agent"
    if not (repo_dir / ".git").exists():
        repo_dir = Path(__file__).parent.parent.resolve()
    return repo_dir if (repo_dir / ".git").exists() else None


def _git_short_hash(repo_dir: Path, rev: str) -> Optional[str]:
    """Resolve a git revision to an 8-character short hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", rev],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def get_git_banner_state(repo_dir: Optional[Path] = None) -> Optional[dict]:
    """Return upstream/local git hashes for the startup banner."""
    repo_dir = repo_dir or _resolve_repo_dir()
    if repo_dir is None:
        return None

    upstream = _git_short_hash(repo_dir, "origin/main")
    local = _git_short_hash(repo_dir, "HEAD")
    if not upstream or not local:
        return None

    ahead = 0
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            ahead = int((result.stdout or "0").strip() or "0")
    except Exception:
        ahead = 0

    return {"upstream": upstream, "local": local, "ahead": max(ahead, 0)}


def format_banner_version_label() -> str:
    """Return the version label shown in the startup banner title."""
    base = f"Hermes Agent v{VERSION} ({RELEASE_DATE})"
    state = get_git_banner_state()
    if not state:
        return base

    upstream = state["upstream"]
    local = state["local"]
    ahead = int(state.get("ahead") or 0)

    if ahead <= 0 or upstream == local:
        return f"{base} · upstream {upstream}"

    carried_word = "commit" if ahead == 1 else "commits"
    return f"{base} · upstream {upstream} · local {local} (+{ahead} carried {carried_word})"


# =========================================================================
# Non-blocking update check
# =========================================================================

_update_result: Optional[int] = None
_update_check_done = threading.Event()


def prefetch_update_check():
    """Kick off update check in a background daemon thread."""
    def _run():
        global _update_result
        _update_result = check_for_updates()
        _update_check_done.set()
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def get_update_result(timeout: float = 0.5) -> Optional[int]:
    """Get result of prefetched check. Returns None if not ready."""
    _update_check_done.wait(timeout=timeout)
    return _update_result


# =========================================================================
# Welcome banner
# =========================================================================

def _format_context_length(tokens: int) -> str:
    """Format a token count for display (e.g. 128000 → '128K', 1048576 → '1M')."""
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}M"
        return f"{val:.1f}M"
    elif tokens >= 1_000:
        val = tokens / 1_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}K"
        return f"{val:.1f}K"
    return str(tokens)


def _display_toolset_name(toolset_name: str) -> str:
    """Normalize internal/legacy toolset identifiers for banner display."""
    if not toolset_name:
        return "unknown"
    return (
        toolset_name[:-6]
        if toolset_name.endswith("_tools")
        else toolset_name
    )


_BANNER_ACK_DRIFT = 50   # re-show when behind grows by this many commits
_BANNER_ACK_TTL_S = 7 * 86400  # re-show after 7 days


def _should_show_update_banner(behind: int) -> bool:
    """Return True when the update warning should be displayed.

    Suppressed if the user previously acknowledged a behind count within 7 days
    and the drift since ack is < 50 commits.
    """
    ack_file = get_hermes_home() / "banner_ack.json"
    if not ack_file.exists():
        return True
    try:
        data = json.loads(ack_file.read_text())
        acked = int(data.get("acked_behind", 0))
        ts = float(data.get("ts", 0))
        age = time.time() - ts
        if age > _BANNER_ACK_TTL_S:
            return True
        if behind - acked >= _BANNER_ACK_DRIFT:
            return True
        return False
    except Exception:
        return True


def write_banner_ack(behind: int) -> None:
    """Write/overwrite the banner ack file with current behind count."""
    try:
        ack_file = get_hermes_home() / "banner_ack.json"
        ack_file.write_text(json.dumps({"acked_behind": behind, "ts": time.time()}))
    except Exception:
        logger.debug("banner_ack write failed", exc_info=True)


# Tracks the current session's behind value for the 'u' dismiss action.
_session_update_behind: int = 0


def _section_break(dim_color: str, width: int = 30) -> list[str]:
    """Two-element block: blank row + horizontal rule. Use between right-column sections."""
    return ["", f"[dim {dim_color}]{'─' * max(8, width)}[/]"]


def _format_skill_list(skills: list, width: int = 47) -> str:
    """Render skills joined by ', ' fitting in `width`, with '…+N more' overflow."""
    rendered: list[str] = []
    used = 0
    for i, s in enumerate(skills):
        sep_len = 2 if rendered else 0  # ', '
        if used + sep_len + len(s) > width:
            remaining = len(skills) - i
            return ", ".join(rendered) + f" …+{remaining} more"
        rendered.append(s)
        used += sep_len + len(s)
    return ", ".join(rendered)


def _format_session_id(sid: str, max_len: int) -> str:
    """Width-cap a session id, preserving the tail (the discriminator).

    Returns sid if short enough; otherwise emits "…<tail>" up to max_len chars.
    Empty input returns empty.
    """
    if not sid:
        return ""
    max_len = max(1, max_len)
    if len(sid) <= max_len:
        return sid
    if max_len == 1:
        return "…"
    tail_len = max_len - 1  # 1 char for the leading ellipsis
    return "…" + sid[-tail_len:]


def _format_cwd(cwd: str, max_len: int) -> str:
    """Compact cwd: ~ for home, drop middle segments, keep last 1-2."""
    if not cwd:
        return ""
    home = os.path.expanduser("~")
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        cwd = "~" + cwd[len(home):]
    # Strip trailing separator (preserve bare "/" for root).
    if len(cwd) > 1:
        cwd = cwd.rstrip("/")
    if len(cwd) <= max_len:
        return cwd
    parts = cwd.split("/")
    if len(parts) <= 3:
        return "…" + cwd[-(max(1, max_len) - 1):]
    head = parts[0] if parts[0] else "/"
    # Try last 2 segments
    tail2 = "/".join(parts[-2:])
    candidate = f"{head}/…/{tail2}" if head != "/" else f"/…/{tail2}"
    if len(candidate) <= max_len:
        return candidate
    # Fall back to last segment only
    candidate = f"{head}/…/{parts[-1]}" if head != "/" else f"/…/{parts[-1]}"
    if len(candidate) <= max_len:
        return candidate
    # Nothing fits the structured form; tail-truncate raw
    return "…" + cwd[-(max(1, max_len) - 1):]


def build_welcome_banner(console: Console, model: str, cwd: str,
                         tools: List[dict] = None,
                         enabled_toolsets: List[str] = None,
                         session_id: str = None,
                         get_toolset_for_tool=None,
                         context_length: int = None,
                         print_logo: bool = True,
                         print_hero: bool = True,
                         hero_text: str = "",
                         hero_renderable=None,
                         bg_color: str = "",
                         logo_placeholder: str = ""):
    """Build and print a welcome banner with caduceus on left and info on right.

    Args:
        console: Rich Console instance.
        model: Current model name.
        cwd: Current working directory.
        tools: List of tool definitions.
        enabled_toolsets: List of enabled toolset names.
        session_id: Session identifier.
        get_toolset_for_tool: Callable to map tool name -> toolset name.
        context_length: Model's context window size in tokens.
        print_logo: Whether to print the agent logo text art above the panel.
        print_hero: Whether to print the caduceus hero art in the panel left column.
                    Set False when startup_text_effect already rendered the hero.
        hero_text: If set, used as the hero content in the left column instead
                   of the default caduceus.
        hero_renderable: Optional Rich renderable for the hero slot. Used by
                         TUI startup animation so ANSI TTE frames aren't
                         inserted as plain strings.
    """
    from model_tools import check_tool_availability, TOOLSET_REQUIREMENTS
    if get_toolset_for_tool is None:
        from model_tools import get_toolset_for_tool

    tools = tools or []
    enabled_toolsets = enabled_toolsets or []

    # Load cached slow inputs (unavailable_toolsets, mcp_status, skills_by_category).
    # Cache hit: ~1 ms.  Cache miss (cold / stale / HERMES_NO_CACHE): live calls (~3 s).
    from hermes_cli.tui._banner_data_cache import load_banner_data as _load_banner_data
    _cached = _load_banner_data()

    _bw_t0 = time.monotonic()
    if _cached is not None:
        unavailable_toolsets = _cached.get("unavailable_toolsets") or []
        logger.info("BUILD-BANNER: check_tool_avail CACHE HIT n_unavail=%d", len(unavailable_toolsets))
    else:
        try:
            _, unavailable_toolsets = check_tool_availability(quiet=True)
        except Exception:
            logger.exception("check_tool_availability failed in live banner path")
            unavailable_toolsets = []
        logger.info("BUILD-BANNER: check_tool_avail +%.0fms n_unavail=%d",
                    (time.monotonic() - _bw_t0) * 1000, len(unavailable_toolsets))

    disabled_tools = set()
    # Tools whose toolset has a check_fn are lazy-initialized (e.g. honcho,
    # homeassistant) — they show as unavailable at banner time because the
    # check hasn't run yet, but they aren't misconfigured.
    lazy_tools = set()
    for item in unavailable_toolsets:
        toolset_name = item.get("name", "")
        ts_req = TOOLSET_REQUIREMENTS.get(toolset_name, {})
        tools_in_ts = item.get("tools", [])
        if ts_req.get("check_fn"):
            lazy_tools.update(tools_in_ts)
        else:
            disabled_tools.update(tools_in_ts)

    layout_table = Table.grid(padding=(0, 2))
    try:
        _, _hero_width = get_cached_hero_width()
    except Exception:
        _hero_width = 30
    layout_table.add_column("left", justify="left", width=_hero_width, no_wrap=True)
    layout_table.add_column("right", justify="left")

    # Resolve skin colors once for the entire banner
    accent = _skin_color("banner_accent", "#FFBF00")
    dim = _skin_color("banner_dim", "#B8860B")
    text = _skin_color("banner_text", "#FFF8DC")
    session_color = _skin_color("session_border", "#8B8682")

    # Build left column TOP (hero only); meta lines appended after right_lines is final
    left_top: list = []
    if hero_renderable is not None:
        left_top.extend([Text(""), hero_renderable, Text("")])
    elif hero_text:
        left_top.extend([Text(""), render_banner_hero_text(hero_text), Text("")])
    elif print_hero:
        try:
            from hermes_cli.skin_engine import get_active_skin
            _bskin = get_active_skin()
            _hero = _bskin.banner_hero if hasattr(_bskin, 'banner_hero') and _bskin.banner_hero else HERMES_CADUCEUS
        except Exception:
            logger.debug("hero resolution failed", exc_info=True)
            _hero = HERMES_CADUCEUS
        left_top.extend([Text(""), render_banner_hero_text(_hero), Text("")])
    model_short = model.split("/")[-1] if "/" in model else model
    if model_short.endswith(".gguf"):
        model_short = model_short[:-5]
    if len(model_short) > 28:
        model_short = model_short[:25] + "..."
    ctx_str = f" [dim {dim}]·[/] [dim {dim}]{_format_context_length(context_length)} context[/]" if context_length else ""
    left_meta: list = []
    left_meta.append(Text.from_markup(f"[{accent}]{model_short}[/]{ctx_str} [dim {dim}]·[/] [dim {dim}]Nous Research[/]"))
    cwd_display = _format_cwd(cwd, max_len=_hero_width)
    left_meta.append(Text.from_markup(f"[dim {dim}]{cwd_display}[/]"))
    if session_id:
        sid_budget = max(1, _hero_width - len("Session: "))
        sid_display = _format_session_id(session_id, max_len=sid_budget)
        left_meta.append(Text.from_markup(f"[dim {session_color}]Session: {sid_display}[/]"))

    # BL-3: hoist MCP and skills computation; build summary as the FIRST line
    _mcp_t0 = time.monotonic()
    if _cached is not None:
        mcp_status = _cached.get("mcp_status") or []
        logger.info("BUILD-BANNER: mcp_status CACHE HIT")
    else:
        try:
            from tools.mcp_tool import get_mcp_status
            mcp_status = get_mcp_status()
        except Exception:
            # EH-OK: MCP status is cosmetic; banner renders safely with mcp_status=[]
            logger.debug("get_mcp_status failed", exc_info=True)
            mcp_status = []
        logger.info("BUILD-BANNER: mcp_status +%.0fms", (time.monotonic() - _mcp_t0) * 1000)
    mcp_connected = sum(1 for s in mcp_status if s["connected"]) if mcp_status else 0

    _sk_t0 = time.monotonic()
    if _cached is not None:
        skills_by_category = _cached.get("skills_by_category") or {}
        logger.info("BUILD-BANNER: skills CACHE HIT")
    else:
        try:
            skills_by_category = get_available_skills()
        except Exception:
            logger.exception("get_available_skills failed in live banner path")
            skills_by_category = {}
        logger.info("BUILD-BANNER: skills +%.0fms n=%d",
                    (time.monotonic() - _sk_t0) * 1000,
                    sum(len(v) for v in skills_by_category.values()))
    total_skills = sum(len(s) for s in skills_by_category.values())

    summary_parts = [f"{len(tools)} tools", f"{total_skills} skills"]
    if mcp_connected:
        summary_parts.append(f"{mcp_connected} MCP servers")
    summary_parts.append("/help for commands")
    right_lines = [
        f"[dim {dim}]{' · '.join(summary_parts)}[/]",
        "",
        f"[bold {accent}]Available Tools[/]",
    ]
    toolsets_dict: Dict[str, list] = {}

    for tool in tools:
        tool_name = tool["function"]["name"]
        toolset = _display_toolset_name(get_toolset_for_tool(tool_name) or "other")
        toolsets_dict.setdefault(toolset, []).append(tool_name)

    for item in unavailable_toolsets:
        toolset_id = item.get("id", item.get("name", "unknown"))
        display_name = _display_toolset_name(toolset_id)
        if display_name not in toolsets_dict:
            toolsets_dict[display_name] = []
        for tool_name in item.get("tools", []):
            if tool_name not in toolsets_dict[display_name]:
                toolsets_dict[display_name].append(tool_name)

    sorted_toolsets = sorted(toolsets_dict.keys())
    display_toolsets = sorted_toolsets[:8]
    remaining_toolsets = len(sorted_toolsets) - 8

    for toolset in display_toolsets:
        tool_names = toolsets_dict[toolset]
        colored_names = []
        for name in sorted(tool_names):
            if name in disabled_tools:
                colored_names.append(f"[red]{name}[/]")
            elif name in lazy_tools:
                colored_names.append(f"[yellow]{name}[/]")
            else:
                colored_names.append(f"[{text}]{name}[/]")

        tools_str = ", ".join(colored_names)
        if len(", ".join(sorted(tool_names))) > 42:
            sorted_names = sorted(tool_names)
            short_names = []
            length = 0
            overflow_count = 0
            for i, name in enumerate(sorted_names):
                if length + len(name) + 2 > 42:
                    overflow_count = len(sorted_names) - i
                    break
                short_names.append(name)
                length += len(name) + 2
            colored_names = []
            for name in short_names:
                if name in disabled_tools:
                    colored_names.append(f"[red]{name}[/]")
                elif name in lazy_tools:
                    colored_names.append(f"[yellow]{name}[/]")
                else:
                    colored_names.append(f"[{text}]{name}[/]")
            if overflow_count > 0:
                colored_names.append(f"[dim {dim}]…+{overflow_count} more[/]")
            tools_str = ", ".join(colored_names)

        right_lines.append(f"[dim {dim}]{toolset}:[/] {tools_str}")

    if remaining_toolsets > 0:
        right_lines.append(f"[dim {dim}]…+{remaining_toolsets} more toolsets[/]")

    # MCP Servers section (only if configured) — uses pre-computed mcp_status
    if mcp_status:
        right_lines.extend(_section_break(dim))
        right_lines.append(f"[bold {accent}]MCP Servers[/]")
        for srv in mcp_status:
            if srv["connected"]:
                right_lines.append(
                    f"[dim {dim}]{srv['name']}[/] [{text}]({srv['transport']})[/] "
                    f"[dim {dim}]—[/] [{text}]{srv['tools']} tool(s)[/]"
                )
            else:
                right_lines.append(
                    f"[red]{srv['name']}[/] [dim]({srv['transport']})[/] "
                    f"[red]— failed[/]"
                )

    right_lines.extend(_section_break(dim))
    right_lines.append(f"[bold {accent}]Available Skills[/]")
    if skills_by_category:
        for category in sorted(skills_by_category.keys()):
            skill_names = sorted(skills_by_category[category])
            skills_str = _format_skill_list(skill_names)
            right_lines.append(f"[dim {dim}]{category}:[/] [{text}]{skills_str}[/]")
    else:
        right_lines.append(f"[dim {dim}]No skills installed[/]")

    # Show active profile name when not 'default'
    try:
        from hermes_cli.profiles import get_active_profile_name
        _profile_name = get_active_profile_name()
        if _profile_name and _profile_name != "default":
            right_lines.append(f"[bold {accent}]Profile:[/] [{text}]{_profile_name}[/]")
    except Exception:
        logger.debug("get_active_profile_name failed", exc_info=True)

    # Update check — use prefetched result if available
    try:
        behind = get_update_result(timeout=0.5)
        if behind and behind > 0 and _should_show_update_banner(behind):
            global _session_update_behind
            _session_update_behind = behind
            from hermes_cli.config import recommended_update_command
            commits_word = "commit" if behind == 1 else "commits"
            update_cmd = recommended_update_command()
            warn_color = _skin_color("banner_warning", "#FF8C00")
            warn_dim = _skin_color("banner_warning_dim", "#CD6500")
            key_color = _skin_color("banner_key", "#FFD700")
            right_lines.append(
                f"[bold {warn_color}]⚠ {behind} {commits_word} behind[/]"
                f"[{warn_dim}] — run [bold]{update_cmd}[/bold] to update[/]"
            )
            right_lines.append(
                f"[dim {dim}]run[/] [{text}]{update_cmd}[/] [dim {dim}]to install[/]"
            )
    except Exception:
        logger.debug("update check failed", exc_info=True)

    # BL-2: pad left column so meta lines pin to bottom of right column
    right_row_count = len(right_lines)
    left_row_count = _count_visual_rows(left_top) + len(left_meta)
    pad = max(0, right_row_count - left_row_count)
    left_renderables = left_top + [Text("")] * pad + left_meta
    left_content = Group(*left_renderables)

    right_content = "\n".join(right_lines)
    layout_table.add_row(left_content, right_content)

    # BL-1: hoisted up so wordmark/logo fallback can use these
    agent_name = _skin_branding("agent_name", "Hermes Agent")
    title_color = _skin_color("banner_title", "#FFD700")
    border_color = _skin_color("banner_border", "#CD7F32")
    panel_style = f"on {bg_color}" if bg_color else ""
    outer_panel = Panel(
        layout_table,
        title=f"[bold {title_color}]{format_banner_version_label()}[/]",
        border_style=border_color,
        style=panel_style,
        padding=(0, 2),
        expand=True,
    )

    console.print()
    term_size = shutil.get_terminal_size()
    term_width = term_size.columns
    term_rows = term_size.lines
    if print_logo and term_width >= 95:
        if term_rows >= 32:
            if logo_placeholder:
                from rich.text import Text as _Text
                logo_renderable = _Text(logo_placeholder)
                logo_renderable.no_wrap = True
                logo_renderable.overflow = "ignore"
                from rich.cells import cell_len as _cell_len
                _logo_lines = logo_renderable.split("\n", allow_blank=True)
                _content_w = max((_cell_len(ln.plain.rstrip()) for ln in _logo_lines), default=1)
                console.print(Align(logo_renderable, align="center", width=_content_w))
            else:
                markup_logo, _ = resolve_banner_logo_assets()
                logo_text = render_banner_logo_text(markup_logo)
                logo_text.no_wrap = True
                logo_text.overflow = "ignore"
                # Compute content width from the widest non-trailing-space line so that
                # all rows share the same centering anchor.  justify="center" strips
                # trailing spaces per-line before measuring, causing rows with trailing
                # padding (e.g. rows 2-5 of the block-letter logo) to get 1 extra left-
                # pad space compared to rows with no trailing spaces (rows 0-1).
                from rich.cells import cell_len as _cell_len
                _logo_lines = logo_text.split("\n", allow_blank=True)
                _content_w = max((_cell_len(ln.plain.rstrip()) for ln in _logo_lines), default=1)
                console.print(Align(logo_text, align="center", width=_content_w))
        else:
            wordmark = f"[bold {title_color}]{agent_name.upper()}[/]"
            console.print(Align.center(Text.from_markup(wordmark)))
        console.print()
    console.print(outer_panel)
