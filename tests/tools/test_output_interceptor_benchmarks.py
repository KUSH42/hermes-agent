import json
from pathlib import Path

from scripts.output_interceptor_bench import (
    run_benchmark,
    summarize_eval_parity,
    write_chart_bundle,
    write_detailed_report,
    write_markdown_summary,
)


def _rows_by_id(results):
    return {row["id"]: row for row in results["rows"]}


def test_output_interceptor_benchmark_acceptance_targets():
    results = run_benchmark()
    rows = _rows_by_id(results)
    aggregate = results["aggregate"]
    by_class = results["by_class"]
    by_confidence = results["by_confidence"]
    by_verbosity = results["by_verbosity"]
    by_serialization_mode = results["by_serialization_mode"]

    assert aggregate["fixture_count"] >= 23
    assert aggregate["expectation_match_rate_pct"] == 100.0
    assert aggregate["derived_row_count"] >= 12
    assert aggregate["captured_derived_row_count"] >= 7
    assert aggregate["uncaptured_derived_row_count"] >= 1
    assert aggregate["raw_row_count"] >= 7
    assert aggregate["fallback_row_count"] >= 4
    assert aggregate["truncated_row_count"] >= 1
    assert aggregate["median_reduction_pct"] >= 40.0
    assert aggregate["median_delta_ms"] <= 10.0
    assert aggregate["captured_derived_rate_pct"] < 100.0
    assert aggregate["serialization_mode"] == "production"

    assert rows["git_diff_small"]["reduction_pct"] > 0.0
    assert rows["git_diff_small"]["capture_mode"] == "derived_optional_skipped"
    assert rows["git_diff_small"]["captured_derived"] is False
    assert rows["git_diff_medium"]["reduction_pct"] >= 45.0
    assert rows["git_diff_medium"]["captured_derived"] is True
    assert rows["git_diff_large"]["reduction_pct"] >= 75.0
    assert rows["pytest_noisy"]["reduction_pct"] >= 70.0
    assert rows["pytest_noisy"]["capture_mode"] == "derived_required_recovery"

    assert rows["unknown_simple"]["derived"] is False
    assert rows["unknown_complex"]["derived"] is False
    assert rows["unknown_simple"]["intercepted_chars"] == rows["unknown_simple"]["raw_chars"]
    assert rows["unknown_complex"]["intercepted_chars"] == rows["unknown_complex"]["raw_chars"]
    assert rows["git_status_clean"]["derived"] is False
    assert rows["git_status_dirty"]["derived"] is False
    assert rows["git_status_large_dirty"]["derived"] is True
    assert rows["git_status_large_dirty"]["interceptor_kind"] == "git_status"
    assert rows["git_status_ambiguous"]["confidence"] == "fallback"
    assert rows["git_diff_ambiguous"]["fallback_reason"] == "ambiguous_git_diff_output"
    assert rows["pytest_ambiguous"]["fallback_reason"] == "ambiguous_pytest_output"
    assert rows["git_diff_large_full"]["derived"] is False
    assert rows["git_diff_medium_medium"]["derived"] is True
    assert rows["git_diff_large_medium"]["derived"] is True
    assert rows["pytest_noisy_full"]["derived"] is False
    assert rows["pytest_fail_medium"]["derived"] is True
    assert rows["pytest_pass_medium"]["derived"] is True
    assert rows["unknown_large_persisted"]["raw_path_exists"] is True
    assert rows["unknown_large_persisted"]["truncated"] is True
    assert rows["git_status_clean"]["fallback_reason"] is None

    assert by_class["git_status"]["derived_rows"] >= 1
    assert by_class["git_diff"]["captured_derived_rows"] >= 3
    assert by_class["git_diff"]["derived_rows"] >= 5
    assert by_class["pytest"]["fallback_rows"] >= 1
    assert by_confidence["high"]["derived_rows"] >= 12
    assert by_confidence["high"]["captured_derived_rows"] >= 7
    assert by_confidence["raw"]["truncated_rows"] >= 1
    assert by_confidence["fallback"]["rows"] >= 4
    assert by_verbosity["full"]["derived_rows"] == 0
    assert by_verbosity["summary"]["rows"] >= 16
    assert by_verbosity["medium"]["rows"] >= 5
    assert by_verbosity["medium"]["derived_rows"] >= 5
    assert by_serialization_mode["production"]["captured_derived_rows"] >= 7
    assert by_serialization_mode["production"]["rows"] >= 23


def test_output_interceptor_benchmark_writes_chart_bundle(tmp_path):
    results = run_benchmark()
    charts = write_chart_bundle(results, tmp_path)
    eval_report = {
        "model": "demo-model",
        "suite": "workspace",
        "aggregate": {
            "off": {"success_rate": 0.75},
            "summary": {"success_rate": 0.75},
            "full": {"success_rate": 0.75},
        },
    }
    report_path = write_detailed_report(results, tmp_path, charts, eval_report=eval_report)
    summary_path = write_markdown_summary(results, tmp_path, eval_report=eval_report)

    assert Path(charts["reduction_by_fixture"]).exists()
    assert Path(charts["latency_vs_reduction"]).exists()
    assert Path(charts["breakdowns"]).exists()
    assert Path(charts["capture_policy"]).exists()
    assert Path(report_path).exists()
    assert Path(summary_path).exists()
    report_html = Path(report_path).read_text(encoding="utf-8")
    assert "Output Interceptor Benchmark Report" in report_html
    assert Path(charts["reduction_by_fixture"]).name in report_html
    assert Path(charts["capture_policy"]).name in report_html
    assert "Capture policy" in report_html
    assert "By Serialization Mode" in report_html
    assert "Task-quality parity achieved on this eval run." in report_html
    summary_md = Path(summary_path).read_text(encoding="utf-8")
    assert "Task-quality parity achieved on this eval run." in summary_md
    manifest = json.loads(Path(charts["manifest"]).read_text(encoding="utf-8"))
    assert "aggregate" in manifest
    assert manifest["backend"] in {"matplotlib", "svg"}
    assert "charts" in manifest


def test_summarize_eval_parity_detects_equal_success_rates():
    summary = summarize_eval_parity(
        {
            "model": "demo-model",
            "suite": "workspace",
            "aggregate": {
                "off": {"success_rate": 0.8333333333},
                "summary": {"success_rate": 0.8333333333},
                "full": {"success_rate": 0.8333333333},
            },
        }
    )

    assert summary["parity_achieved"] is True
    assert summary["headline"] == "Task-quality parity achieved on this eval run."
