"""Mech sweep B — dead-code removal verification.

Per spec /home/xush/.hermes/2026-04-25-mech-sweep-B-dead-code-spec.md:
DC-1 deletes ``perf.measure_perf()``,
DC-2 deletes ``tool_result_parse._ARTIFACT_CAP``,
DC-3 deletes ``resize_utils.THRESHOLD_BAR_HIDE``,
DC-4 updates ``skills/tui-development/references/module-map.md``.

These tests are pure attribute/string checks — no DOM, no app.
"""

from __future__ import annotations

from pathlib import Path


class TestDC1MeasurePerfRemoved:
    def test_measure_perf_removed(self) -> None:
        from hermes_cli.tui import perf as perf_module

        assert not hasattr(perf_module, "measure_perf")

    def test_perf_imports_clean(self) -> None:
        # Re-import succeeds without ImportError, and ``measure`` still works.
        from hermes_cli.tui import perf as perf_module

        assert hasattr(perf_module, "measure")
        with perf_module.measure("dc1-smoke", silent=True) as result:
            pass
        assert result.label == "dc1-smoke"
        assert result.elapsed_ms >= 0.0


class TestDC2ArtifactCapRemoved:
    def test_artifact_cap_removed(self) -> None:
        from hermes_cli.tui import tool_result_parse

        assert not hasattr(tool_result_parse, "_ARTIFACT_CAP")


class TestDC3BarHideRemoved:
    def test_threshold_bar_hide_removed(self) -> None:
        from hermes_cli.tui import resize_utils

        assert not hasattr(resize_utils, "THRESHOLD_BAR_HIDE")


class TestDC4ModuleMapClean:
    def test_module_map_no_dead_refs(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        module_map = (
            repo_root
            / "skills"
            / "tui-development"
            / "references"
            / "module-map.md"
        )
        text = module_map.read_text(encoding="utf-8")
        assert "measure_perf" not in text
        assert "THRESHOLD_BAR_HIDE" not in text
