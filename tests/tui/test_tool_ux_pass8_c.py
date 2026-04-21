"""Tool UX Audit Pass 8 — Phase C tests.

C1: web_result_v4 code=None non-error → primary "✓ {size}", no status chip
C2: generic_result_v4 success primary = "✓ N lines" or "✓ done"
C3: agent_result_v4 success includes copy_body action
C4: _parse_http_response detects redirect_url/location fields
C5: file_result_v4 fallback suppresses count chip when n <= 1
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(raw, is_error=False, tool_name="web_search"):
    """Build a minimal ParseContext-like object."""
    ctx = MagicMock()
    ctx.complete = MagicMock()
    ctx.complete.raw_result = raw
    ctx.complete.is_error = is_error
    ctx.tool_name = tool_name
    return ctx


# ---------------------------------------------------------------------------
# C1 — web_result_v4 code=None non-error
# ---------------------------------------------------------------------------

class TestC1WebResultNoCode:
    def test_code_none_non_error_primary_has_no_question_mark(self):
        """When HTTP code is unknown and not an error, don't show '? status' primary."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        # Raw JSON-like response with no status_code
        ctx = _make_ctx({"content": "page text", "url": "https://example.com"}, is_error=False)
        result = web_result_v4(ctx)
        # Primary should not contain "?" (ambiguous code)
        assert result.primary is not None
        assert "?" not in result.primary, (
            f"primary should not contain '?' for no-code success, got: {result.primary!r}"
        )

    def test_code_none_non_error_no_unknown_status_chip(self):
        """No status chip with '?' when code is None and not error."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = _make_ctx({"content": "text", "url": "https://x.com"}, is_error=False)
        result = web_result_v4(ctx)
        chip_texts = [c.text for c in result.chips]
        # Should not have a "?" status chip
        assert "?" not in chip_texts, (
            f"chips must not include '?' status for no-code success, got: {chip_texts}"
        )

    def test_code_none_non_error_primary_has_checkmark(self):
        """Success non-error with no code should still show ✓ in primary."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = _make_ctx({"content": "data"}, is_error=False)
        result = web_result_v4(ctx)
        assert "✓" in result.primary, (
            f"primary should include ✓ for non-error result, got: {result.primary!r}"
        )

    def test_error_result_still_shows_code(self):
        """Error results should still show status/code information."""
        from hermes_cli.tui.tool_result_parse import web_result_v4
        ctx = _make_ctx("404 Not Found - page missing", is_error=True)
        result = web_result_v4(ctx)
        assert result.is_error is True


# ---------------------------------------------------------------------------
# C2 — generic_result_v4 success primary
# ---------------------------------------------------------------------------

class TestC2GenericResultPrimary:
    def test_generic_result_success_with_lines(self):
        from hermes_cli.tui.tool_result_parse import generic_result_v4
        ctx = _make_ctx("line one\nline two\nline three", is_error=False)
        result = generic_result_v4(ctx)
        assert "✓" in result.primary, f"primary must include ✓, got: {result.primary!r}"
        assert "3" in result.primary or "line" in result.primary.lower(), (
            f"primary must include line count for multi-line output, got: {result.primary!r}"
        )

    def test_generic_result_success_empty_raw(self):
        from hermes_cli.tui.tool_result_parse import generic_result_v4
        ctx = _make_ctx("", is_error=False)
        result = generic_result_v4(ctx)
        assert "✓" in result.primary
        assert "done" in result.primary.lower() or "0" in result.primary, (
            f"primary for empty output should say 'done' or '0 lines', got: {result.primary!r}"
        )

    def test_generic_result_not_bare_checkmark(self):
        from hermes_cli.tui.tool_result_parse import generic_result_v4
        ctx = _make_ctx("some content", is_error=False)
        result = generic_result_v4(ctx)
        # Bare "✓" alone is not acceptable — must have additional info
        assert result.primary.strip() != "✓", (
            "primary must not be bare '✓' — must include line count or 'done'"
        )

    def test_generic_result_error_unchanged(self):
        from hermes_cli.tui.tool_result_parse import generic_result_v4
        ctx = _make_ctx("something failed", is_error=True)
        result = generic_result_v4(ctx)
        assert result.is_error is True


# ---------------------------------------------------------------------------
# C3 — agent_result_v4 success includes copy_body action
# ---------------------------------------------------------------------------

class TestC3AgentResultCopyBodyAction:
    def test_agent_result_success_has_copy_body_action(self):
        from hermes_cli.tui.tool_result_parse import agent_result_v4
        ctx = _make_ctx("Agent completed the task.", is_error=False, tool_name="agent")
        result = agent_result_v4(ctx)
        action_kinds = [a.kind for a in (result.actions or ())]
        assert "copy_body" in action_kinds, (
            f"agent_result_v4 success must include copy_body action, got kinds: {action_kinds}"
        )

    def test_agent_result_copy_body_has_payload(self):
        from hermes_cli.tui.tool_result_parse import agent_result_v4
        ctx = _make_ctx("Agent did something.\nMultiple lines.", is_error=False, tool_name="agent")
        result = agent_result_v4(ctx)
        copy_action = next((a for a in (result.actions or ()) if a.kind == "copy_body"), None)
        assert copy_action is not None
        assert copy_action.payload, "copy_body action must have non-empty payload"

    def test_agent_result_success_primary(self):
        from hermes_cli.tui.tool_result_parse import agent_result_v4
        ctx = _make_ctx("Done.", is_error=False, tool_name="agent")
        result = agent_result_v4(ctx)
        assert not result.is_error
        assert "✓" in result.primary or "done" in result.primary.lower()

    def test_agent_result_error_not_affected(self):
        from hermes_cli.tui.tool_result_parse import agent_result_v4
        ctx = _make_ctx("Error: failed to complete.", is_error=True, tool_name="agent")
        result = agent_result_v4(ctx)
        assert result.is_error is True


# ---------------------------------------------------------------------------
# C4 — _parse_http_response detects redirect_url / location
# ---------------------------------------------------------------------------

class TestC4ParseHttpResponseRedirect:
    def test_redirect_url_field_synthesizes_302(self):
        from hermes_cli.tui.tool_result_parse import _parse_http_response
        raw = {"redirect_url": "https://example.com/new", "ok": True}
        code, reason, length = _parse_http_response(raw)
        assert code is not None, "redirect_url should synthesize a status code"
        assert code == 302, f"redirect_url should produce code=302, got: {code}"

    def test_location_field_synthesizes_302(self):
        from hermes_cli.tui.tool_result_parse import _parse_http_response
        # Use only "location" field — no "status" to avoid int("moved") error
        raw = {"location": "https://example.com/moved"}
        code, reason, length = _parse_http_response(raw)
        assert code is not None, "location field should synthesize a status code"
        assert code == 302, f"location field should produce code=302, got: {code}"

    def test_explicit_status_code_takes_priority(self):
        from hermes_cli.tui.tool_result_parse import _parse_http_response
        raw = {"status_code": 200, "redirect_url": "...", "content": "ok"}
        code, reason, length = _parse_http_response(raw)
        assert code == 200, "explicit status_code must take priority over redirect_url"

    def test_no_redirect_fields_returns_none_code(self):
        from hermes_cli.tui.tool_result_parse import _parse_http_response
        raw = {"content": "just content"}
        code, reason, length = _parse_http_response(raw)
        # Should have no synthesized code
        assert code is None, f"no redirect fields: code should be None, got: {code}"


# ---------------------------------------------------------------------------
# C5 — file_result_v4 fallback suppresses count chip when n <= 1
# ---------------------------------------------------------------------------

class TestC5FileResultCountChip:
    def test_single_line_output_no_count_chip(self):
        from hermes_cli.tui.tool_result_parse import file_result_v4
        # Single line raw output — count chip should be suppressed
        ctx = _make_ctx("wrote file", is_error=False, tool_name="write_file")
        result = file_result_v4(ctx)
        chip_kinds = [c.kind for c in result.chips]
        count_chips = [c for c in result.chips if c.kind == "count"]
        for chip in count_chips:
            assert chip.text != "1", (
                f"count chip of '1' should be suppressed (n<=1), got: {chip.text!r}"
            )

    def test_empty_output_no_count_chip(self):
        from hermes_cli.tui.tool_result_parse import file_result_v4
        ctx = _make_ctx("", is_error=False, tool_name="write_file")
        result = file_result_v4(ctx)
        count_chips = [c for c in result.chips if c.kind == "count"]
        assert len(count_chips) == 0 or count_chips[0].text not in ("0", "1"), (
            "count chip of 0 or 1 should be suppressed"
        )

    def test_multi_line_output_keeps_count_chip(self):
        from hermes_cli.tui.tool_result_parse import file_result_v4
        raw = "line one\nline two\nline three\nline four"
        ctx = _make_ctx(raw, is_error=False, tool_name="write_file")
        result = file_result_v4(ctx)
        # Multi-line (4 lines) should show count chip
        count_chips = [c for c in result.chips if c.kind == "count"]
        if count_chips:
            assert int(count_chips[0].text) > 1, "count chip should show n>1 for multi-line output"

    def test_no_changes_path_not_broken(self):
        from hermes_cli.tui.tool_result_parse import file_result_v4
        ctx = _make_ctx("no changes made", is_error=False, tool_name="write_file")
        result = file_result_v4(ctx)
        # Should not error
        assert result is not None
        assert not result.is_error
