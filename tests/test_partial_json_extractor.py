"""Tests for PartialJSONCodeExtractor (§13.1 of ExecuteCodeBlock spec)."""
import pytest
from hermes_cli.tui.partial_json import PartialJSONCodeExtractor


def _feed_all(chunks: list[str]) -> str:
    e = PartialJSONCodeExtractor()
    return "".join(e.feed(c) for c in chunks)


def test_seek_then_extract():
    result = _feed_all(['{"code":"abc"}'])
    assert result == "abc"


def test_chunked_body():
    result = _feed_all(['{"code":"', 'imp', 'ort"}'])
    assert result == "import"


def test_escapes_nl_tab():
    result = _feed_all(['{"code":"line1\\nline2\\tend"}'])
    assert result == "line1\nline2\tend"


def test_escape_quote_backslash():
    e = PartialJSONCodeExtractor()
    result = e.feed('{"code":"\\"hello\\"\\\\end"}')
    assert result == '"hello"\\end'


def test_unicode_escape():
    e = PartialJSONCodeExtractor()
    result = e.feed('{"code":"caf\\u00e9"}')
    assert result == "café"


def test_unicode_escape_cross_chunk():
    e = PartialJSONCodeExtractor()
    r1 = e.feed('{"code":"\\u00')
    r2 = e.feed('e9"}')
    assert r1 + r2 == "é"


def test_mid_escape_split():
    e = PartialJSONCodeExtractor()
    r1 = e.feed('{"code":"hello\\')
    r2 = e.feed('nworld"}')
    assert r1 + r2 == "hello\nworld"


def test_ignores_other_fields():
    result = _feed_all(['{"foo":"x","code":"y"}'])
    assert result == "y"


def test_closing_quote_terminates():
    e = PartialJSONCodeExtractor()
    r1 = e.feed('{"code":"abc"}')
    r2 = e.feed('ignored')
    assert r1 == "abc"
    assert r2 == ""
