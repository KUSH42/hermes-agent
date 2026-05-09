"""DEDUP-2: Lock the _dup_trace site catalogue.

Spec: 2026-05-09-stream-dedup-emoji-suffix-spec.md

Any new _commit_to_log call site must be added both to _DUP_TRACE_SITES in
response_flow.py AND to the expected set in this test.
"""
from __future__ import annotations

from hermes_cli.tui.response_flow import _DUP_TRACE_SITES


class TestDupTraceCatalogue:

    def test_known_dup_trace_sites_catalogue(self) -> None:
        """_DUP_TRACE_SITES must exactly match the known set of commit sites."""
        expected = {
            "prose_main",
            "prose_separator",
            "footnote_ref",
            "math_sync_unicode",
            "math_unicode_late",
            "ansi_block_fallback",
            "ansi_block_single",
            "hr",
        }
        assert set(_DUP_TRACE_SITES) == expected, (
            f"Site catalogue mismatch.\n"
            f"  Expected: {sorted(expected)}\n"
            f"  Got:      {sorted(_DUP_TRACE_SITES)}\n"
            "Add new _commit_to_log sites to _DUP_TRACE_SITES and this test."
        )
