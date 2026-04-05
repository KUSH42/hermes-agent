from scripts.output_interceptor_llm_eval import (
    _fixture_expected_substrings,
    _primary_executable,
    load_fixture_eval_cases,
    summarize,
    EvalRunResult,
)


def test_primary_executable_handles_python_module_pytest():
    assert _primary_executable("python -m pytest tests/test_demo.py -q") == "python"
    assert _primary_executable("FOO=bar git diff --cached") == "git"


def test_fixture_eval_cases_cover_manifest_rows():
    cases = load_fixture_eval_cases()
    by_id = {case.id: case for case in cases}

    assert len(cases) >= 23
    assert "fixture_git_diff_large" in by_id
    assert "fixture_git_status_large_dirty" in by_id
    assert "fixture_unknown_large_persisted" in by_id
    assert "__fixture_id__" in by_id["fixture_git_diff_large"].env_overrides
    assert by_id["fixture_git_diff_large"].suite == "fixture"


def test_fixture_expected_substrings_include_manifest_metadata():
    substrings = _fixture_expected_substrings(
        {
            "expect_derived": True,
            "expect_confidence": "high",
            "expect_kind": "git_diff",
            "expect_fallback_reason": None,
            "expect_raw_path_exists": True,
            "expect_truncated": False,
        }
    )

    assert "derived=true" in substrings
    assert "confidence=high" in substrings
    assert "kind=git_diff" in substrings
    assert "fallback_reason=none" in substrings
    assert "raw_output_path=yes" in substrings
    assert "truncated=false" in substrings


def test_summarize_reports_serialization_modes():
    summary = summarize(
        [
            EvalRunResult(
                case_id="fixture_git_diff_large",
                mode="summary",
                repeat_index=1,
                success=True,
                duration_seconds=1.0,
                answer="ok",
                matched_substrings=["x"],
                missing_substrings=[],
                total_tool_json_chars=100,
                total_terminal_output_chars=50,
                terminal_call_count=1,
                serialization_mode="production",
            )
        ]
    )

    assert summary["summary"]["serialization_modes"] == ["production"]
