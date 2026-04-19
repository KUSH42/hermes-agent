"""
tests/tui/test_stream_effects.py — 28 tests for hermes_cli/stream_effects.py

Groups:
  A (5): Module API + factory
  B (5): FlashEffect TUI mode
  C (5): GradientTailEffect TUI mode
  D (5): GlowSettleEffect TUI mode
  E (4): DecryptEffect TUI mode
  F (2): on_line_complete / on_turn_end
  G (2): _stream_effect_cfg() config reader
"""
import sys
import types
from unittest.mock import patch

import pytest

from hermes_cli.stream_effects import (
    VALID_EFFECTS,
    FlashEffect,
    GlowSettleEffect,
    GradientTailEffect,
    DecryptEffect,
    NoneEffect,
    make_stream_effect,
    _lerp_color,
)


# ---------------------------------------------------------------------------
# Group A — Module API + factory (5 tests)
# ---------------------------------------------------------------------------

def test_a1_valid_effects_contains_all_seven():
    expected = {"none", "flash", "gradient_tail", "glow_settle", "decrypt", "shimmer", "breathe"}
    assert expected.issubset(set(VALID_EFFECTS))


def test_a2_make_none_effect():
    fx = make_stream_effect({"stream_effect": "none"})
    assert isinstance(fx, NoneEffect)
    assert fx.active is False


def test_a3_make_flash_effect():
    fx = make_stream_effect({"stream_effect": "flash"})
    assert isinstance(fx, FlashEffect)
    assert fx.active is True


def test_a4_unknown_effect_falls_back_to_none():
    fx = make_stream_effect({"stream_effect": "totally_unknown_xyz"})
    assert isinstance(fx, NoneEffect)
    assert fx.active is False


def test_a5_lerp_color_midpoint():
    result = _lerp_color("#000000", "#ffffff", 0.5)
    # round(127.5) = 128 in Python → #808080; accept 127 or 128 per rounding
    assert result.lower() in ("#7f7f7f", "#808080")


# ---------------------------------------------------------------------------
# Group B — FlashEffect TUI mode (5 tests)
# ---------------------------------------------------------------------------

def test_b1_flash_first_token_start_is_zero():
    fx = FlashEffect({})
    fx.register_token_tui("hello")
    assert fx._last_token_start == 0


def test_b2_flash_second_token_start():
    fx = FlashEffect({})
    fx.register_token_tui("hello")
    fx.register_token_tui(" world")
    assert fx._last_token_start == 5


def test_b3_flash_render_tui_last_span_accent():
    fx = FlashEffect({})
    fx._last_token_start = 6
    t = fx.render_tui("hello world", "#FFDD00", "#FFFFFF")
    # The second span (starting at 6) should carry the accent color
    spans = list(t._spans)
    assert any(s.start == 6 and "FFDD00" in str(s.style).upper() for s in spans)


def test_b4_flash_render_tui_prior_text_color():
    fx = FlashEffect({})
    fx._last_token_start = 6
    t = fx.render_tui("hello world", "#FFDD00", "#AABBCC")
    spans = list(t._spans)
    # First span (0..6) should carry the text color
    assert any(s.start == 0 and s.end == 6 and "AABBCC" in str(s.style).upper() for s in spans)


def test_b5_flash_clear_tui_resets():
    fx = FlashEffect({})
    fx.register_token_tui("hello")
    fx.register_token_tui(" world")
    fx.clear_tui()
    assert fx._last_token_start == 0
    assert fx._buf_len == 0


# ---------------------------------------------------------------------------
# Group C — GradientTailEffect TUI mode (5 tests)
# ---------------------------------------------------------------------------

def test_c1_gradient_short_buf_all_in_gradient():
    fx = GradientTailEffect({"stream_effect_length": 4})
    t = fx.render_tui("ab", "#FFDD00", "#FFFFFF")
    # buf shorter than length → all chars are in the gradient
    assert len(t._spans) == 2  # one per char


def test_c2_gradient_long_buf_head_is_text_color():
    fx = GradientTailEffect({"stream_effect_length": 4})
    buf = "x" * 20
    t = fx.render_tui(buf, "#FFDD00", "#FFFFFF")
    # First span covers chars 0..16 at text color — check plain text portion exists
    plain_parts = [s for s in t._spans if s.end <= 16]
    assert len(plain_parts) >= 1


def test_c3_gradient_last_char_has_accent_color():
    fx = GradientTailEffect({"stream_effect_length": 4})
    t = fx.render_tui("hello world!", "#FFDD00", "#AABBCC")
    spans = list(t._spans)
    # Last span (last char): frac = 1.0 → accent color
    last_span = max(spans, key=lambda s: s.start)
    assert "FF" in str(last_span.style).upper() or "FFDD00" in str(last_span.style).upper()


def test_c4_gradient_first_tail_char_between_text_and_accent():
    fx = GradientTailEffect({"stream_effect_length": 4})
    buf = "x" * 8
    t = fx.render_tui(buf, "#FFFFFF", "#000000")
    # The first char of the tail is at index 4; frac = 1/4 = 0.25 → between pure black and pure white
    gradient_spans = [s for s in t._spans if s.start >= 4]
    assert len(gradient_spans) > 0
    first_gradient = min(gradient_spans, key=lambda s: s.start)
    style_str = str(first_gradient.style).upper()
    assert style_str not in ("#FFFFFF", "#000000"), "First tail char should be between text and accent"


def test_c5_gradient_length_zero_all_text_color():
    fx = GradientTailEffect({"stream_effect_length": 0})
    t = fx.render_tui("hello", "#FFDD00", "#AABBCC")
    # length=0 → tail_start = len(buf) → no gradient chars; only the text-color plain portion
    # rendered as plain Text(buf, style=text_hex) or single span
    text = t.plain
    assert text == "hello"


# ---------------------------------------------------------------------------
# Group D — GlowSettleEffect TUI mode (5 tests)
# ---------------------------------------------------------------------------

def test_d1_glow_fresh_token_at_accent():
    fx = GlowSettleEffect({"stream_effect_settle_frames": 6})
    fx.register_token_tui("hi")
    t = fx.render_tui("hi", "#FFDD00", "#AABBCC")
    spans = list(t._spans)
    # age=0 → brightness=1.0 → accent color
    assert any("FFDD00" in str(s.style).upper() for s in spans)


def test_d2_glow_settled_token_at_text_color():
    fx = GlowSettleEffect({"stream_effect_settle_frames": 6})
    fx.register_token_tui("hi")
    # Age the token to settle_frames
    fx._tokens[0] = (fx._tokens[0][0], fx._tokens[0][1], 6)
    t = fx.render_tui("hi", "#FFDD00", "#AABBCC")
    spans = list(t._spans)
    # age == settle_frames → brightness=0.0 → text color
    assert any("AABBCC" in str(s.style).upper() for s in spans)


def test_d3_glow_tick_increments_age():
    fx = GlowSettleEffect({"stream_effect_settle_frames": 6})
    fx.register_token_tui("word")
    changed = fx.tick_tui()
    assert changed is True
    assert fx._tokens[0][2] == 1


def test_d4_glow_tick_returns_false_when_settled():
    fx = GlowSettleEffect({"stream_effect_settle_frames": 2})
    fx.register_token_tui("a")
    fx.tick_tui()
    fx.tick_tui()
    # Now age == settle_frames; next tick should return False
    changed = fx.tick_tui()
    assert changed is False


def test_d5_glow_clear_tui_removes_tokens():
    fx = GlowSettleEffect({})
    fx.register_token_tui("hello")
    fx.register_token_tui(" world")
    fx.clear_tui()
    assert fx._tokens == []
    assert fx._buf_len == 0


# ---------------------------------------------------------------------------
# Group E — DecryptEffect TUI mode (4 tests)
# ---------------------------------------------------------------------------

def test_e1_decrypt_age_zero_fully_scrambled():
    fx = DecryptEffect({"stream_effect_scramble_frames": 14})
    # Force a word with age=0 directly
    fx._words = [("hello ", 0)]
    t = fx.render_tui("hello ", "#FFDD00", "#FFFFFF")
    # age=0 → frac=0 → resolved_n=0 → all chars scrambled
    rendered = t.plain
    # Length should match; all chars are scramble chars (not original "hello ")
    assert len(rendered) == 6
    assert rendered != "hello "


def test_e2_decrypt_settled_word_shows_original():
    fx = DecryptEffect({"stream_effect_scramble_frames": 14})
    fx._words = [("hello ", 14)]
    t = fx.render_tui("hello ", "#FFDD00", "#FFFFFF")
    assert t.plain == "hello "


def test_e3_decrypt_tick_increments_ages():
    fx = DecryptEffect({"stream_effect_scramble_frames": 14})
    fx._words = [("hello ", 0), ("world ", 3)]
    changed = fx.tick_tui()
    assert changed is True
    assert fx._words[0][1] == 1
    assert fx._words[1][1] == 4


def test_e4_decrypt_clear_tui_empties_words():
    fx = DecryptEffect({})
    fx._words = [("hello ", 5)]
    fx._current_partial = "wor"
    fx.clear_tui()
    assert fx._words == []
    assert fx._current_partial == ""


# ---------------------------------------------------------------------------
# Group F — on_line_complete / on_turn_end (2 tests)
# ---------------------------------------------------------------------------

def test_f1_flash_on_line_complete_resets():
    fx = FlashEffect({})
    fx.register_token_tui("hello")
    fx.register_token_tui(" world")
    assert fx._last_token_start != 0
    fx.on_line_complete()
    assert fx._last_token_start == 0
    assert fx._buf_len == 0


def test_f2_glow_on_turn_end_clears_state():
    fx = GlowSettleEffect({})
    fx.register_token_tui("hello")
    fx.register_token_tui(" world")
    assert len(fx._tokens) == 2
    fx.on_turn_end()
    assert fx._tokens == []
    assert fx._buf_len == 0


# ---------------------------------------------------------------------------
# Group G — _stream_effect_cfg() config reader (2 tests)
# ---------------------------------------------------------------------------

def test_g1_stream_effect_cfg_defaults():
    from hermes_cli.tui.widgets import _stream_effect_cfg
    with patch("hermes_cli.config.read_raw_config", return_value={}):
        cfg = _stream_effect_cfg()
    assert cfg["stream_effect"] == "none"
    assert cfg["stream_effect_length"] == 16
    assert cfg["stream_effect_settle_frames"] == 6
    assert cfg["stream_effect_scramble_frames"] == 14


def test_g2_stream_effect_cfg_custom_length():
    from hermes_cli.tui.widgets import _stream_effect_cfg
    raw = {"terminal": {"stream_effect": {"enabled": "flash", "length": 32}}}
    with patch("hermes_cli.config.read_raw_config", return_value=raw):
        cfg = _stream_effect_cfg()
    assert cfg["stream_effect"] == "flash"
    assert cfg["stream_effect_length"] == 32
