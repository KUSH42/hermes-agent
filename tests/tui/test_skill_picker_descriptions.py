"""Tests for SP-1/SP-2: empty-description fallback in SkillPickerOverlay."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
from hermes_cli.tui.types.skill_candidate import SkillCandidate


def _make_candidate(name="my-skill", description="", enabled=True):
    return SkillCandidate(
        name=name,
        description=description,
        trigger_phrases=[],
        do_not_trigger=[],
        source="user",
        enabled=enabled,
    )


class _PickerApp(App):
    """Minimal App host; avoids HermesApp VarSpec crash."""

    def __init__(self, picker: SkillPickerOverlay):
        super().__init__()
        self._picker = picker

    def compose(self) -> ComposeResult:
        yield self._picker


class TestListRowDescriptions:
    """SP-1: list row rendering of descriptions."""

    @pytest.mark.asyncio
    async def test_list_row_with_description(self):
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [_make_candidate(name="my-skill", description="Scrape URLs")]
            picker._rebuild_list()
            await pilot.pause()
            option_list = picker.query_one("#picker-list", OptionList)
            label = str(option_list.get_option("my-skill").prompt)
            assert "[dim]Scrape URLs[/dim]" in label

    @pytest.mark.asyncio
    async def test_list_row_empty_description(self):
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [_make_candidate(name="my-skill", description="")]
            picker._rebuild_list()
            await pilot.pause()
            option_list = picker.query_one("#picker-list", OptionList)
            label = str(option_list.get_option("my-skill").prompt)
            assert "[dim]—[/dim]" in label

    @pytest.mark.asyncio
    async def test_list_row_long_description_truncated(self):
        long_desc = "A" * 50
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [_make_candidate(name="my-skill", description=long_desc)]
            picker._rebuild_list()
            await pilot.pause()
            option_list = picker.query_one("#picker-list", OptionList)
            label = str(option_list.get_option("my-skill").prompt)
            assert "A" * 40 in label
            assert "A" * 41 not in label


class TestDetailPaneDescriptions:
    """SP-2: detail pane rendering of descriptions."""

    @pytest.mark.asyncio
    async def test_detail_pane_description_shown(self):
        candidate = _make_candidate(name="my-skill", description="Scrape URLs and return markdown")
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [candidate]
            picker._selected_candidate = lambda: candidate
            picker._refresh_detail()
            await pilot.pause()
            detail_statics = list(picker.query("#picker-right Static").results(Static))
            contents = [str(s.content) for s in detail_statics]
            assert any("Scrape URLs and return markdown" in c for c in contents)

    @pytest.mark.asyncio
    async def test_detail_pane_empty_description_fallback(self):
        candidate = _make_candidate(name="my-skill", description="")
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [candidate]
            picker._selected_candidate = lambda: candidate
            picker._refresh_detail()
            await pilot.pause()
            detail_statics = list(picker.query("#picker-right Static").results(Static))
            contents = [str(s.content) for s in detail_statics]
            assert any("(no description)" in c for c in contents)

    @pytest.mark.asyncio
    async def test_detail_pane_disabled_skill_still_shows_fallback(self):
        candidate = _make_candidate(name="my-skill", description="", enabled=False)
        picker = SkillPickerOverlay()
        async with _PickerApp(picker).run_test() as pilot:
            picker._candidates = [candidate]
            picker._selected_candidate = lambda: candidate
            picker._refresh_detail()
            await pilot.pause()
            detail_statics = list(picker.query("#picker-right Static").results(Static))
            contents = [str(s.content) for s in detail_statics]
            assert any("(no description)" in c for c in contents)
            assert any("Skill is disabled" in c for c in contents)
