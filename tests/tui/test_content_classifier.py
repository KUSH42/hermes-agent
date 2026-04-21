"""Tests for full Phase C content_classifier heuristics (24 tests)."""
from __future__ import annotations

import pytest

from hermes_cli.tui.content_classifier import classify_content, _cached_classify
from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


def _payload(output_raw: str, tool_name: str = "", args: dict | None = None) -> ToolPayload:
    return ToolPayload(
        tool_name=tool_name,
        category=ToolCategory.UNKNOWN,
        args=args or {},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


@pytest.fixture(autouse=True)
def clear_cache():
    _cached_classify.cache_clear()
    yield
    _cached_classify.cache_clear()


# ----------------------------
# EMPTY
# ----------------------------

def test_empty_string_is_empty_kind():
    result = classify_content(_payload(""))
    assert result.kind == ResultKind.EMPTY
    assert result.confidence == 1.0


def test_whitespace_only_is_empty_kind():
    result = classify_content(_payload("   \n\t  \n"))
    assert result.kind == ResultKind.EMPTY


# ----------------------------
# BINARY
# ----------------------------

def test_binary_content_detected():
    # Craft bytes with many non-printable control chars (> 5%)
    binary_str = "".join(chr(i) for i in range(0, 20) if i not in (9, 10, 13, 27)) * 10
    result = classify_content(_payload(binary_str))
    assert result.kind == ResultKind.BINARY


def test_binary_threshold_exact():
    # 4.9% → TEXT; 5.1% → BINARY
    # 4096 sample; 4.9% = ~200 non-print chars, 5.1% = ~208
    sample_len = 4096
    # Build a string where non-printable ratio is exactly below threshold
    nonprint_count_low = int(sample_len * 0.049)
    nonprint_count_high = int(sample_len * 0.051) + 1
    safe_chars = "a" * sample_len

    # Low: should NOT be binary
    low_str = chr(1) * nonprint_count_low + "a" * (sample_len - nonprint_count_low)
    result_low = classify_content(_payload(low_str))
    assert result_low.kind != ResultKind.BINARY

    # High: should be binary
    _cached_classify.cache_clear()
    high_str = chr(1) * nonprint_count_high + "a" * max(0, sample_len - nonprint_count_high)
    result_high = classify_content(_payload(high_str))
    assert result_high.kind == ResultKind.BINARY


# ----------------------------
# DIFF
# ----------------------------

def test_unified_diff_detected():
    diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def foo():
-    pass
+    return 1
"""
    result = classify_content(_payload(diff_text))
    assert result.kind == ResultKind.DIFF
    assert result.confidence >= 0.8


def test_diff_without_markers_is_not_diff():
    plain = "line one\nline two\nline three\n"
    result = classify_content(_payload(plain))
    assert result.kind != ResultKind.DIFF


# ----------------------------
# SEARCH
# ----------------------------

def test_search_three_hits_detected():
    search_text = "src/foo.py\n  1: def foo():\n  2: return 1\n  3: pass\n"
    result = classify_content(_payload(search_text))
    assert result.kind == ResultKind.SEARCH
    assert result.confidence >= 0.8


def test_search_two_hits_not_search():
    search_text = "src/foo.py\n  1: def foo():\n  2: return 1\n"
    result = classify_content(_payload(search_text))
    assert result.kind != ResultKind.SEARCH


def test_search_query_extracted_from_args():
    search_text = "src/foo.py\n  1: def foo():\n  2: return 1\n  3: pass\n"
    result = classify_content(_payload(search_text, args={"query": "def foo"}))
    assert result.kind == ResultKind.SEARCH
    assert result.metadata.get("query") == "def foo"


# ----------------------------
# JSON
# ----------------------------

def test_json_object_detected():
    json_text = '{"key": "value", "num": 42, "nested": {"a": 1}}'
    result = classify_content(_payload(json_text))
    assert result.kind == ResultKind.JSON
    assert result.confidence >= 0.9


def test_json_array_detected():
    json_text = '[1, 2, 3, "four", {"five": 5}]'
    result = classify_content(_payload(json_text))
    assert result.kind == ResultKind.JSON


def test_json_too_short_not_json():
    # < 20 chars, no newline — should not be JSON
    short = '{"a":1}'  # 7 chars
    result = classify_content(_payload(short))
    assert result.kind != ResultKind.JSON


def test_json_invalid_not_json():
    invalid = '{"key": "value" INVALID'
    result = classify_content(_payload(invalid + " " * 20))
    assert result.kind != ResultKind.JSON


# ----------------------------
# TABLE
# ----------------------------

def test_table_pipe_delimited():
    # Use a separator that doesn't start with "---" (which triggers diff detection)
    table_text = "Name | Age | City\nAlice | 30 | NYC\nBob | 25 | LA\nCarol | 28 | SF\n"
    result = classify_content(_payload(table_text))
    assert result.kind == ResultKind.TABLE


def test_table_tab_delimited():
    table_text = "Name\tAge\tCity\nAlice\t30\tNYC\nBob\t25\tLA\nCarol\t28\tSF\n"
    result = classify_content(_payload(table_text))
    assert result.kind == ResultKind.TABLE


def test_table_inconsistent_not_table():
    # Columns vary wildly → not table
    messy = "a | b\nc | d | e | f\ng\nh | i\n"
    result = classify_content(_payload(messy))
    assert result.kind != ResultKind.TABLE


# ----------------------------
# LOG
# ----------------------------

def test_log_timestamps_detected():
    log_text = (
        "2024-01-01 10:00:00 Starting server\n"
        "2024-01-01 10:00:01 Listening on port 8080\n"
        "2024-01-01 10:00:02 Ready\n"
    )
    result = classify_content(_payload(log_text))
    assert result.kind == ResultKind.LOG


def test_log_level_tokens_detected():
    log_text = (
        "INFO Starting server\n"
        "ERROR Failed to connect\n"
        "WARN Retry attempt 1\n"
    )
    result = classify_content(_payload(log_text))
    assert result.kind == ResultKind.LOG


def test_log_one_hit_not_log():
    # Only 1 log-like line — should not be LOG (need >= 2)
    one_hit = "INFO Starting server\nsome other text\nmore plain text\n"
    result = classify_content(_payload(one_hit))
    assert result.kind != ResultKind.LOG


# ----------------------------
# CODE
# ----------------------------

def test_code_fenced_triple_backtick():
    code_text = "```python\ndef hello():\n    print('hi')\n```\n"
    result = classify_content(_payload(code_text))
    assert result.kind == ResultKind.CODE


def test_code_path_extension():
    # tool_name set + path arg ending in .py → CODE
    code_text = "def foo():\n    return 1\n"
    result = classify_content(_payload(code_text, tool_name="read_file", args={"path": "src/main.py"}))
    assert result.kind == ResultKind.CODE


# ----------------------------
# TEXT fallback
# ----------------------------

def test_plain_text_falls_through():
    plain = "This is just some plain text output without any special markers.\n"
    result = classify_content(_payload(plain))
    assert result.kind == ResultKind.TEXT
    assert result.confidence == 1.0


# ----------------------------
# Cache
# ----------------------------

def test_lru_cache_hit():
    text = "Hello, this is plain text output\n"
    r1 = classify_content(_payload(text))
    r2 = classify_content(_payload(text))
    assert r1 is r2  # same cached object


def test_cache_clear_works():
    text = "Hello, this is plain text output\n"
    r1 = classify_content(_payload(text))
    classify_content.cache_clear()
    r2 = classify_content(_payload(text))
    # After cache clear, a new result is computed (different object)
    # Both should still have same kind/confidence
    assert r1.kind == r2.kind
    assert r1.confidence == r2.confidence
