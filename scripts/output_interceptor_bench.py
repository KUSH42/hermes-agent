#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import tempfile
import time
from html import escape
from pathlib import Path
from typing import Any

from agent.model_metadata import estimate_tokens_rough
from tools.output_interceptor import (
    CommandExecutionResult,
    InterceptorRequest,
    intercept_output,
    normalize_output,
    result_to_json_dict,
    serialization_mode,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "output_interceptor"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


def load_fixtures() -> list[dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixtures = []
    for item in manifest:
        text = (FIXTURE_DIR / item["output_file"]).read_text(encoding="utf-8")
        fixtures.append(
            {
                **item,
                "output": text,
                "verbosity": item.get("verbosity", "summary"),
                "exit_code": item.get("exit_code", 0),
                "env": item.get("env", {}),
            }
        )
    return fixtures


def baseline_output(text: str) -> str:
    return normalize_output(combined_output=text).combined_output


def raw_payload_dict(text: str, verbosity: str, *, truncated: bool) -> dict:
    return {
        "output": text,
        "summary": None,
        "structured": None,
        "verbosity": verbosity,
        "raw_available": bool(text),
        "derived_output": False,
        "interceptor_kind": None,
        "raw_output_path": None,
        "truncated": truncated,
        "confidence": "raw",
    }


@contextlib.contextmanager
def fixture_env(env: dict[str, str] | None):
    if not env:
        yield
        return
    old_values = {key: os.environ.get(key) for key in env}
    try:
        for key, value in env.items():
            os.environ[key] = value
        yield
    finally:
        for key, old in old_values.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def intercept_fixture(fixture: dict, tmp_home: str) -> dict:
    with fixture_env(fixture.get("env")):
        execution = CommandExecutionResult(
            command=fixture["command"],
            cwd="/bench",
            exit_code=fixture["exit_code"],
            stdout="",
            stderr="",
            combined_output=fixture["output"],
        )
        request = InterceptorRequest(execution=execution, verbosity=fixture["verbosity"], task_id="bench")
        result = intercept_output(request)
        raw_path_exists = bool(result.raw_output_path and Path(result.raw_output_path).exists())
        payload = result_to_json_dict(result, fixture["verbosity"])
    return {
        "output": result.output,
        "payload": payload,
        "payload_chars": len(json.dumps(payload, ensure_ascii=False)),
        "derived": result.derived,
        "raw_path_exists": raw_path_exists,
        "raw_output_path": result.raw_output_path,
        "confidence": result.confidence,
        "interceptor_kind": result.interceptor_kind,
        "fallback_reason": result.fallback_reason,
        "truncated": result.truncated,
    }


def time_call(fn, iterations: int = 200) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start
    return (elapsed / iterations) * 1000.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def run_benchmark() -> dict:
    fixtures = load_fixtures()
    rows = []
    reductions = []
    deltas = []
    raw_recovery = []

    with tempfile.TemporaryDirectory(prefix="hermes-output-interceptor-bench-") as tmp_home:
        import os

        old_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = tmp_home
        try:
            for fixture in fixtures:
                with fixture_env(fixture.get("env")):
                    raw = baseline_output(fixture["output"])
                    normalized = normalize_output(combined_output=fixture["output"])
                    intercept = intercept_fixture(fixture, tmp_home)
                raw_chars = len(
                    json.dumps(
                        raw_payload_dict(raw, fixture["verbosity"], truncated=normalized.truncated),
                        ensure_ascii=False,
                    )
                )
                intercepted_chars = intercept["payload_chars"]
                reduction = 0.0 if raw_chars == 0 else ((raw_chars - intercepted_chars) / raw_chars) * 100.0
                raw_tokens = estimate_tokens_rough(raw)
                intercepted_tokens = intercept["payload_chars"] // 4
                baseline_ms = time_call(lambda: baseline_output(fixture["output"]))
                intercept_ms = time_call(lambda: intercept_fixture(fixture, tmp_home))
                delta_ms = intercept_ms - baseline_ms
                expectation_matches = (
                    intercept["derived"] == fixture.get("expect_derived")
                    and intercept["confidence"] == fixture.get("expect_confidence")
                    and intercept["interceptor_kind"] == fixture.get("expect_kind")
                    and intercept["fallback_reason"] == fixture.get("expect_fallback_reason")
                    and intercept["raw_path_exists"] == fixture.get("expect_raw_path_exists", intercept["raw_path_exists"])
                    and intercept["truncated"] == fixture.get("expect_truncated", intercept["truncated"])
                )

                row = {
                    "id": fixture["id"],
                    "class": fixture["class"],
                    "command": fixture["command"],
                    "verbosity": fixture["verbosity"],
                    "exit_code": fixture["exit_code"],
                    "intercepted_expected": fixture["intercepted"],
                    "derived": intercept["derived"],
                    "raw_chars": raw_chars,
                    "intercepted_chars": intercepted_chars,
                    "reduction_pct": reduction,
                    "raw_tokens": raw_tokens,
                    "intercepted_tokens": intercepted_tokens,
                    "delta_ms": delta_ms,
                    "raw_path_exists": intercept["raw_path_exists"],
                    "truncated": intercept["truncated"],
                    "confidence": intercept["confidence"],
                    "interceptor_kind": intercept["interceptor_kind"],
                    "fallback_reason": intercept["fallback_reason"],
                    "serialization_mode": serialization_mode(),
                    "matches_expectation": expectation_matches,
                }
                rows.append(row)

                if row["derived"]:
                    reductions.append(reduction)
                    deltas.append(delta_ms)
                    raw_recovery.append(intercept["raw_path_exists"])
        finally:
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home

    by_class: dict[str, dict[str, float | int]] = {}
    by_verbosity: dict[str, dict[str, float | int]] = {}
    by_confidence: dict[str, dict[str, float | int]] = {}
    by_serialization_mode: dict[str, dict[str, int]] = {}
    for key_name, bucket in (("class", by_class), ("verbosity", by_verbosity)):
        for row in rows:
            key = row[key_name]
            entry = bucket.setdefault(
                key,
                {
                    "rows": 0,
                    "derived_rows": 0,
                    "fallback_rows": 0,
                    "median_reduction_pct": 0.0,
                },
            )
            entry["rows"] += 1
            if row["derived"]:
                entry["derived_rows"] += 1
            if row["confidence"] == "fallback":
                entry["fallback_rows"] += 1
        for key, entry in bucket.items():
            keyed_reductions = [row["reduction_pct"] for row in rows if row[key_name] == key and row["derived"]]
            entry["median_reduction_pct"] = statistics.median(keyed_reductions) if keyed_reductions else 0.0
    for row in rows:
        key = row["confidence"] or "none"
        entry = by_confidence.setdefault(
            key,
            {"rows": 0, "derived_rows": 0, "truncated_rows": 0},
        )
        entry["rows"] += 1
        if row["derived"]:
            entry["derived_rows"] += 1
        if row["truncated"]:
            entry["truncated_rows"] += 1
        serialization_entry = by_serialization_mode.setdefault(
            row["serialization_mode"],
            {"rows": 0, "derived_rows": 0, "fallback_rows": 0},
        )
        serialization_entry["rows"] += 1
        if row["derived"]:
            serialization_entry["derived_rows"] += 1
        if row["confidence"] == "fallback":
            serialization_entry["fallback_rows"] += 1

    return {
        "rows": rows,
        "aggregate": {
            "fixture_count": len(rows),
            "expectation_match_rate_pct": (sum(1 for row in rows if row["matches_expectation"]) / len(rows) * 100.0) if rows else 0.0,
            "derived_row_count": sum(1 for row in rows if row["derived"]),
            "raw_row_count": sum(1 for row in rows if row["confidence"] == "raw"),
            "fallback_row_count": sum(1 for row in rows if row["confidence"] == "fallback"),
            "truncated_row_count": sum(1 for row in rows if row["truncated"]),
            "median_reduction_pct": statistics.median(reductions) if reductions else 0.0,
            "p95_reduction_pct": percentile(reductions, 95),
            "median_delta_ms": statistics.median(deltas) if deltas else 0.0,
            "p95_delta_ms": percentile(deltas, 95),
            "raw_recovery_rate_pct": (sum(1 for ok in raw_recovery if ok) / len(raw_recovery) * 100.0) if raw_recovery else 0.0,
            "serialization_mode": serialization_mode(),
        },
        "by_class": by_class,
        "by_confidence": by_confidence,
        "by_verbosity": by_verbosity,
        "by_serialization_mode": by_serialization_mode,
    }


def print_markdown_table(results: dict) -> None:
    print("| Command class | Raw chars | Intercepted chars | Reduction | Raw est. tokens | Intercepted est. tokens | Delta latency |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in results["rows"]:
        print(
            f"| `{row['id']}` | {row['raw_chars']} | {row['intercepted_chars']} | "
            f"{row['reduction_pct']:.1f}% | {row['raw_tokens']} | {row['intercepted_tokens']} | "
            f"{row['delta_ms']:.3f} ms |"
        )
    aggregate = results["aggregate"]
    print(
        f"| `aggregate-median` | - | - | {aggregate['median_reduction_pct']:.1f}% | - | - | {aggregate['median_delta_ms']:.3f} ms |"
    )
    print(
        f"| `aggregate-p95` | - | - | {aggregate['p95_reduction_pct']:.1f}% | - | - | {aggregate['p95_delta_ms']:.3f} ms |"
    )
    print(f"\nRaw recovery rate: {aggregate['raw_recovery_rate_pct']:.1f}%")


def _svg_write(path: Path, width: int, height: int, body: str) -> None:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#faf7f2"/>'
        f"{body}</svg>"
    )
    path.write_text(svg, encoding="utf-8")


def _nice_color(row: dict[str, Any]) -> str:
    if row["confidence"] == "fallback":
        return "#c4493d"
    if row["derived"]:
        return "#2e8b57"
    return "#7a6f63"


def _write_reduction_chart(rows: list[dict[str, Any]], path: Path) -> None:
    ordered = sorted(rows, key=lambda row: (row["class"], row["verbosity"], row["id"]))
    width = max(1100, 90 + len(ordered) * 42)
    height = 500
    left = 70
    right = 24
    top = 40
    bottom = 160
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [row["reduction_pct"] for row in ordered]
    ymin = min(-25.0, min(values) - 5.0)
    ymax = max(85.0, max(values) + 5.0)

    def y_scale(value: float) -> float:
        return top + plot_h - ((value - ymin) / (ymax - ymin) * plot_h)

    zero_y = y_scale(0.0)
    bar_w = max(12, plot_w / max(1, len(ordered)) * 0.66)
    gap = plot_w / max(1, len(ordered))
    parts = [
        '<text x="24" y="26" font-size="18" font-weight="700" fill="#2a241f">Per-Fixture Payload Reduction</text>',
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="#3a322b" stroke-width="1.2"/>',
    ]
    for tick in (-20, 0, 20, 40, 60, 80):
        y = y_scale(tick)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#d9cfc1" stroke-dasharray="4 4"/>')
        parts.append(f'<text x="18" y="{y+4:.1f}" font-size="10" fill="#3a322b">{tick:.0f}%</text>')
    for idx, row in enumerate(ordered):
        x = left + idx * gap + (gap - bar_w) / 2
        y = y_scale(max(0.0, row["reduction_pct"]))
        if row["reduction_pct"] >= 0:
            rect_y = y
            rect_h = zero_y - y
        else:
            rect_y = zero_y
            rect_h = y_scale(row["reduction_pct"]) - zero_y
        parts.append(
            f'<rect x="{x:.1f}" y="{rect_y:.1f}" width="{bar_w:.1f}" height="{max(1.2, rect_h):.1f}" '
            f'fill="{_nice_color(row)}"><title>{escape(row["id"])}: {row["reduction_pct"]:.2f}%</title></rect>'
        )
        label_x = x + bar_w / 2
        label_y = height - bottom + 12
        parts.append(
            f'<g transform="translate({label_x:.1f},{label_y:.1f}) rotate(60)">'
            f'<text font-size="10" fill="#3a322b">{escape(row["id"])}</text></g>'
        )
    _svg_write(path, width, height, "".join(parts))


def _write_latency_scatter(rows: list[dict[str, Any]], path: Path) -> None:
    width = 820
    height = 520
    left = 70
    right = 28
    top = 44
    bottom = 58
    plot_w = width - left - right
    plot_h = height - top - bottom
    xs = [row["delta_ms"] for row in rows]
    ys = [row["reduction_pct"] for row in rows]
    xmin = min(0.0, min(xs) - 0.01)
    xmax = max(xs) + 0.02
    ymin = min(-25.0, min(ys) - 5.0)
    ymax = max(85.0, max(ys) + 5.0)

    def x_scale(value: float) -> float:
        return left + ((value - xmin) / (xmax - xmin or 1.0) * plot_w)

    def y_scale(value: float) -> float:
        return top + plot_h - ((value - ymin) / (ymax - ymin or 1.0) * plot_h)

    parts = [
        '<text x="24" y="28" font-size="18" font-weight="700" fill="#2a241f">Latency Cost vs Payload Reduction</text>',
    ]
    for tick in (0, 20, 40, 60, 80):
        y = y_scale(tick)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#d9cfc1" stroke-dasharray="4 4"/>')
        parts.append(f'<text x="18" y="{y+4:.1f}" font-size="10" fill="#3a322b">{tick:.0f}%</text>')
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = xmin + (xmax - xmin) * fraction
        x = x_scale(value)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#ece4d9"/>')
        parts.append(f'<text x="{x-8:.1f}" y="{height-bottom+18}" font-size="10" fill="#3a322b">{value:.2f}</text>')
    for row in rows:
        x = x_scale(row["delta_ms"])
        y = y_scale(row["reduction_pct"])
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{_nice_color(row)}" stroke="#2a241f" stroke-width="0.6">'
            f'<title>{escape(row["id"])}: {row["delta_ms"]:.3f}ms, {row["reduction_pct"]:.2f}%</title></circle>'
        )
        if row["id"] in {"git_diff_large", "pytest_noisy", "unknown_large_persisted"}:
            parts.append(f'<text x="{x+8:.1f}" y="{y-8:.1f}" font-size="10" fill="#2a241f">{escape(row["id"])}</text>')
    _svg_write(path, width, height, "".join(parts))


def _write_breakdown_chart(results: dict[str, Any], path: Path) -> None:
    width = 1080
    height = 460
    parts = ['<text x="24" y="28" font-size="18" font-weight="700" fill="#2a241f">Benchmark Breakdowns</text>']

    class_items = sorted(results["by_class"].items())
    left = 60
    top = 70
    plot_w = 430
    plot_h = 280
    gap = plot_w / max(1, len(class_items))
    bar_w = gap * 0.55
    max_total = max(item[1]["rows"] for item in class_items)
    parts.append(f'<text x="{left}" y="{top-16}" font-size="13" font-weight="600">Outcome mix by class</text>')
    for idx, (label, data) in enumerate(class_items):
        display_label = "unclassified" if label == "unknown" else label
        x = left + idx * gap + (gap - bar_w) / 2
        derived_h = (data["derived_rows"] / max_total) * plot_h
        fallback_h = (data["fallback_rows"] / max_total) * plot_h
        raw_h = ((data["rows"] - data["derived_rows"] - data["fallback_rows"]) / max_total) * plot_h
        base = top + plot_h
        parts.append(f'<rect x="{x:.1f}" y="{base-derived_h:.1f}" width="{bar_w:.1f}" height="{derived_h:.1f}" fill="#2e8b57"/>')
        parts.append(f'<rect x="{x:.1f}" y="{base-derived_h-raw_h:.1f}" width="{bar_w:.1f}" height="{raw_h:.1f}" fill="#7a6f63"/>')
        parts.append(f'<rect x="{x:.1f}" y="{base-derived_h-raw_h-fallback_h:.1f}" width="{bar_w:.1f}" height="{fallback_h:.1f}" fill="#c4493d"/>')
        parts.append(f'<text x="{x+bar_w/2-24:.1f}" y="{base+18:.1f}" font-size="10" fill="#3a322b">{escape(display_label)}</text>')

    legend_x = left
    legend_y = top + plot_h + 42
    for idx, (name, color) in enumerate((("derived", "#2e8b57"), ("raw", "#7a6f63"), ("fallback", "#c4493d"))):
        x = legend_x + idx * 96
        parts.append(f'<rect x="{x}" y="{legend_y}" width="14" height="14" fill="{color}"/>')
        parts.append(f'<text x="{x+20}" y="{legend_y+11}" font-size="11" fill="#3a322b">{name}</text>')

    verbosity_items = [
        (label, data)
        for label, data in sorted(results["by_verbosity"].items())
        if data["derived_rows"] > 0
    ]
    left2 = 590
    plot_w2 = 400
    plot_h2 = 280
    gap2 = plot_w2 / max(1, len(verbosity_items))
    bar_w2 = gap2 * 0.55
    max_median = max(1.0, max(item[1]["median_reduction_pct"] for item in verbosity_items))
    parts.append(f'<text x="{left2}" y="{top-16}" font-size="13" font-weight="600">Median reduction by verbosity</text>')
    for idx, (label, data) in enumerate(verbosity_items):
        x = left2 + idx * gap2 + (gap2 - bar_w2) / 2
        h = (data["median_reduction_pct"] / max_median) * plot_h2
        color = {"summary": "#d6a04c", "medium": "#2e8b57", "full": "#7a6f63"}.get(label, "#4d6c8a")
        y = top + plot_h2 - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w2:.1f}" height="{h:.1f}" fill="{color}"/>')
        parts.append(f'<text x="{x+bar_w2/2-12:.1f}" y="{top+plot_h2+18:.1f}" font-size="10" fill="#3a322b">{escape(label)}</text>')
        parts.append(f'<text x="{x+bar_w2/2-14:.1f}" y="{y-8:.1f}" font-size="10" fill="#3a322b">{data["median_reduction_pct"]:.1f}%</text>')

    _svg_write(path, width, height, "".join(parts))


def _write_matplotlib_chart_bundle(results: dict[str, Any], output_dir: Path) -> dict[str, str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = results["rows"]
    charts: dict[str, str] = {}

    derived_rows = [row for row in rows if row["derived"]]
    ordered = sorted(rows, key=lambda row: (row["class"], row["verbosity"], row["id"]))

    fig, ax = plt.subplots(figsize=(max(10, len(ordered) * 0.45), 5.5))
    labels = [row["id"] for row in ordered]
    reductions = [row["reduction_pct"] for row in ordered]
    colors = [_nice_color(row) for row in ordered]
    ax.bar(labels, reductions, color=colors)
    ax.axhline(0, color="#3a322b", linewidth=1)
    ax.set_title("Per-Fixture Payload Reduction")
    ax.set_ylabel("Reduction vs raw payload (%)")
    ax.set_xlabel("Fixture")
    ax.tick_params(axis="x", rotation=70)
    ax.grid(axis="y", linestyle="--", alpha=0.55)
    fig.tight_layout()
    reduction_path = output_dir / "reduction_by_fixture.png"
    fig.savefig(reduction_path, dpi=180)
    plt.close(fig)
    charts["reduction_by_fixture"] = str(reduction_path)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = [row["delta_ms"] for row in rows]
    y = [row["reduction_pct"] for row in rows]
    scatter_colors = [_nice_color(row) for row in rows]
    ax.scatter(x, y, c=scatter_colors, alpha=0.9, s=48, edgecolors="#2a241f", linewidths=0.4)
    for row in rows:
        if row["id"] in {"git_diff_large", "pytest_noisy", "unknown_large_persisted"}:
            ax.annotate(row["id"], (row["delta_ms"], row["reduction_pct"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.set_title("Latency Cost vs Payload Reduction")
    ax.set_xlabel("Added latency (ms)")
    ax.set_ylabel("Reduction vs raw payload (%)")
    ax.grid(True, linestyle="--", alpha=0.55)
    fig.tight_layout()
    tradeoff_path = output_dir / "latency_vs_reduction.png"
    fig.savefig(tradeoff_path, dpi=180)
    plt.close(fig)
    charts["latency_vs_reduction"] = str(tradeoff_path)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    class_items = sorted(results["by_class"].items())
    class_labels = ["unclassified" if label == "unknown" else label for label, _ in class_items]
    class_derived = [data["derived_rows"] for _, data in class_items]
    class_total = [data["rows"] for _, data in class_items]
    class_fallback = [data["fallback_rows"] for _, data in class_items]
    class_raw_only = [total - derived - fallback for total, derived, fallback in zip(class_total, class_derived, class_fallback)]
    axes[0].bar(class_labels, class_derived, label="derived", color="#2e8b57")
    axes[0].bar(class_labels, class_raw_only, bottom=class_derived, label="raw", color="#7a6f63")
    axes[0].bar(class_labels, class_fallback, bottom=[d + r for d, r in zip(class_derived, class_raw_only)], label="fallback", color="#c4493d")
    axes[0].set_title("Outcome Mix by Command Class")
    axes[0].set_ylabel("Fixture count")
    axes[0].grid(axis="y", linestyle="--", alpha=0.55)
    axes[0].legend(frameon=False)

    verbosity_items = [
        (label, data)
        for label, data in sorted(results["by_verbosity"].items())
        if data["derived_rows"] > 0
    ]
    verbosity_labels = [label for label, _ in verbosity_items]
    verbosity_medians = [data["median_reduction_pct"] for _, data in verbosity_items]
    verbosity_colors = [{"summary": "#d6a04c", "medium": "#2e8b57", "full": "#7a6f63"}.get(label, "#4d6c8a") for label in verbosity_labels]
    axes[1].bar(verbosity_labels, verbosity_medians, color=verbosity_colors)
    axes[1].set_title("Median Reduction by Verbosity")
    axes[1].set_ylabel("Median reduction on derived rows (%)")
    axes[1].grid(axis="y", linestyle="--", alpha=0.55)
    fig.tight_layout()
    breakdown_path = output_dir / "breakdowns.png"
    fig.savefig(breakdown_path, dpi=180)
    plt.close(fig)
    charts["breakdowns"] = str(breakdown_path)
    return charts


def write_chart_bundle(results: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate = results["aggregate"]
    try:
        charts = _write_matplotlib_chart_bundle(results, output_dir)
        backend = "matplotlib"
    except Exception:
        charts = {}
        reduction_path = output_dir / "reduction_by_fixture.svg"
        tradeoff_path = output_dir / "latency_vs_reduction.svg"
        breakdown_path = output_dir / "breakdowns.svg"
        _write_reduction_chart(results["rows"], reduction_path)
        _write_latency_scatter(results["rows"], tradeoff_path)
        _write_breakdown_chart(results, breakdown_path)
        charts["reduction_by_fixture"] = str(reduction_path)
        charts["latency_vs_reduction"] = str(tradeoff_path)
        charts["breakdowns"] = str(breakdown_path)
        backend = "svg"

    manifest = {
        "aggregate": aggregate,
        "backend": backend,
        "charts": charts,
    }
    manifest_path = output_dir / "charts_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    charts["manifest"] = str(manifest_path)
    return charts


def _fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def _fmt_ms(value: float) -> str:
    return f"{value:.3f} ms"


def _report_table(headers: list[str], rows: list[list[str]]) -> str:
    thead = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_detailed_report(results: dict[str, Any], output_dir: Path, charts: dict[str, str]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate = results["aggregate"]
    rows = results["rows"]

    def rel(name: str) -> str:
        return Path(charts[name]).name

    aggregate_rows = [
        ["Fixture count", str(aggregate["fixture_count"])],
        ["Expectation match rate", _fmt_pct(aggregate["expectation_match_rate_pct"])],
        ["Derived rows", str(aggregate["derived_row_count"])],
        ["Raw rows", str(aggregate["raw_row_count"])],
        ["Fallback rows", str(aggregate["fallback_row_count"])],
        ["Truncated rows", str(aggregate["truncated_row_count"])],
        ["Median reduction", _fmt_pct(aggregate["median_reduction_pct"])],
        ["P95 reduction", _fmt_pct(aggregate["p95_reduction_pct"])],
        ["Median added latency", _fmt_ms(aggregate["median_delta_ms"])],
        ["P95 added latency", _fmt_ms(aggregate["p95_delta_ms"])],
        ["Raw recovery rate", _fmt_pct(aggregate["raw_recovery_rate_pct"])],
        ["Serialization mode", escape(str(aggregate["serialization_mode"]))],
    ]

    class_rows = [
        [
            escape("unclassified" if label == "unknown" else label),
            str(data["rows"]),
            str(data["derived_rows"]),
            str(data["fallback_rows"]),
            _fmt_pct(float(data["median_reduction_pct"])),
        ]
        for label, data in sorted(results["by_class"].items())
    ]
    verbosity_rows = [
        [
            escape(label),
            str(data["rows"]),
            str(data["derived_rows"]),
            str(data["fallback_rows"]),
            _fmt_pct(float(data["median_reduction_pct"])),
        ]
        for label, data in sorted(results["by_verbosity"].items())
    ]
    confidence_rows = [
        [
            escape(label),
            str(data["rows"]),
            str(data["derived_rows"]),
            str(data["truncated_rows"]),
        ]
        for label, data in sorted(results["by_confidence"].items())
    ]
    serialization_rows = [
        [
            escape(label),
            str(data["rows"]),
            str(data["derived_rows"]),
            str(data["fallback_rows"]),
        ]
        for label, data in sorted(results["by_serialization_mode"].items())
    ]
    fixture_rows = [
        [
            f"<code>{escape(row['id'])}</code>",
            escape("unclassified" if row["class"] == "unknown" else row["class"]),
            escape(row["verbosity"]),
            "yes" if row["derived"] else "no",
            escape(str(row["confidence"])),
            _fmt_pct(float(row["reduction_pct"])),
            _fmt_ms(float(row["delta_ms"])),
            "yes" if row["raw_path_exists"] else "no",
            "yes" if row["truncated"] else "no",
        ]
        for row in rows
    ]

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Output Interceptor Benchmark Report</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      background: #f6f2eb;
      color: #2a241f;
      font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1200px; margin: 0 auto; }}
    h1, h2 {{ margin: 0 0 12px; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 22px; margin-top: 28px; }}
    p {{ margin: 0 0 14px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: #fffdf9;
      border: 1px solid #ddd1c3;
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 2px 10px rgba(44, 33, 21, 0.05);
    }}
    .chart-card img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 10px;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fffdf9;
      border: 1px solid #ddd1c3;
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid #ece1d5;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #efe5d7;
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: none; }}
    code {{
      font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .muted {{ color: #665b50; }}
  </style>
</head>
<body>
  <main>
    <h1>Output Interceptor Benchmark Report</h1>
    <p class="muted">
      Detailed benchmark report for the terminal output interceptor. This report includes aggregate metrics,
      per-fixture results, safety buckets, and generated charts.
    </p>

    <h2>Overview</h2>
    {_report_table(["Metric", "Value"], aggregate_rows)}

    <h2>Charts</h2>
    <div class="grid">
      <section class="card chart-card">
        <h3>Per-Fixture Reduction</h3>
        <img src="{escape(rel('reduction_by_fixture'))}" alt="Per-fixture reduction chart">
      </section>
      <section class="card chart-card">
        <h3>Latency vs Reduction</h3>
        <img src="{escape(rel('latency_vs_reduction'))}" alt="Latency versus reduction chart">
      </section>
      <section class="card chart-card">
        <h3>Breakdowns</h3>
        <img src="{escape(rel('breakdowns'))}" alt="Breakdown charts">
      </section>
    </div>

    <h2>By Class</h2>
    {_report_table(["Class", "Rows", "Derived", "Fallback", "Median Reduction"], class_rows)}

    <h2>By Verbosity</h2>
    {_report_table(["Verbosity", "Rows", "Derived", "Fallback", "Median Reduction"], verbosity_rows)}

    <h2>By Confidence</h2>
    {_report_table(["Confidence", "Rows", "Derived", "Truncated"], confidence_rows)}

    <h2>By Serialization Mode</h2>
    {_report_table(["Mode", "Rows", "Derived", "Fallback"], serialization_rows)}

    <h2>Fixture Detail</h2>
    {_report_table(["Fixture", "Class", "Verbosity", "Derived", "Confidence", "Reduction", "Delta", "Raw Path", "Truncated"], fixture_rows)}
  </main>
</body>
</html>
"""
    report_path = output_dir / "benchmark_report.html"
    report_path.write_text(html, encoding="utf-8")
    return str(report_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark output interceptor fixtures.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    parser.add_argument("--chart-dir", default="", help="Optional directory to write benchmark charts as PNG files.")
    args = parser.parse_args()

    results = run_benchmark()
    if args.chart_dir:
        charts = write_chart_bundle(results, Path(args.chart_dir))
        report_path = write_detailed_report(results, Path(args.chart_dir), charts)
        results = {**results, "charts": charts, "report": report_path}
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_markdown_table(results)
        if args.chart_dir:
            print(f"\nCharts written to {args.chart_dir}")
            print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
