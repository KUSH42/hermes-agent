"""Streaming code block right-edge clip — wrap at log content width.

Spec: /home/xush/.hermes/2026-05-09-stream-code-rightedge-clip-spec.md (R-C1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel, StreamingCodeBlock
from hermes_cli.tui.widgets.utils import _strip_ansi


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    return HermesApp(cli=cli)


async def _mount_block(pilot, lang: str = "python") -> StreamingCodeBlock:
    output = pilot.app.query_one(OutputPanel)
    block = StreamingCodeBlock(lang=lang)
    await output.mount(block)
    await pilot.pause()
    # Layout settled — ensure log has a real region width.
    assert block._content_width() > 0, "test setup: log not laid out"
    return block


@pytest.mark.asyncio
async def test_short_line_unchanged():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        w = block._content_width()
        line = "x" * (w // 2)
        block.append_line(line)
        await pilot.pause()
        plain = block._log._plain_lines
        assert len(plain) == 1
        assert plain[0] == line
        assert not plain[0].startswith(" ")


@pytest.mark.asyncio
async def test_long_line_wraps_at_last_space():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        w = block._content_width()
        # Indent of 2 spaces — continuation rows should match.
        words = " ".join(["word"] * (w + 5))
        line = f"  x = {words}"
        block.append_line(line)
        await pilot.pause()
        plain = block._log._plain_lines
        assert len(plain) >= 2
        for entry in plain:
            assert len(entry) <= w, f"entry exceeds width {w}: {len(entry)} {entry!r}"
        for cont in plain[1:]:
            assert cont.startswith("  "), f"continuation missing source indent: {cont!r}"


@pytest.mark.asyncio
async def test_unbreakable_token_force_breaks():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        w = block._content_width()
        url = "h" + "t" * 298 + "p"  # 300 chars, no spaces
        block.append_line(url)
        await pilot.pause()
        plain = block._log._plain_lines
        assert len(plain) >= 2
        for entry in plain:
            assert len(entry) <= w
        # No data loss — concatenating entries minus continuation indent equals original.
        joined = plain[0] + "".join(e.lstrip(" ") for e in plain[1:])
        assert joined == url


@pytest.mark.asyncio
async def test_pre_layout_writes_deferred_then_rendered():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        # Force pre-layout state by patching content width to 0.
        block._content_width = lambda: 0  # type: ignore[method-assign]
        # Reset state so any prior renders are cleared.
        block._log.clear()
        block._log._source_ops.clear()
        block._log._rendered_max_width = 0
        block._rendered_count = 0
        block._pending_render = False

        block.append_line("x" * 200)
        assert block._log._plain_lines == []
        assert block._pending_render is True

        # Restore real bound method so _render_all_buffered sees real width.
        del block._content_width
        block._render_all_buffered()
        assert block._pending_render is False
        plain = block._log._plain_lines
        assert len(plain) >= 1
        w = block._content_width()
        for entry in plain:
            assert len(entry) <= w


@pytest.mark.asyncio
async def test_resize_during_streaming_rewraps_all_lines():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        for i in range(5):
            block.append_line(f"line_{i} = " + " ".join(["alpha"] * 30))
        await pilot.pause()
        original = list(block._code_lines)

        await pilot.resize_terminal(60, 40)
        # Drain parent + child resize cascade and any deferred re-renders.
        for _ in range(10):
            await pilot.pause()
            if not block._pending_render:
                break

        w = block._content_width()
        plain = block._log._plain_lines
        assert plain, "expected re-rendered content after resize"
        for entry in plain:
            assert len(entry) <= w, f"entry exceeds width {w}: {len(entry)} {entry!r}"
        # Reconstruct: strip continuation indent (>= source line indent or 4-space fallback)
        # and verify joined content matches the original lines concatenated.
        joined_orig = "".join(original)
        joined_render = ""
        for entry in plain:
            joined_render += entry
        # Normalise: collapse all whitespace runs, since wrap may insert breaks at spaces
        # and continuation indent is whitespace.
        assert "".join(joined_render.split()) == "".join(joined_orig.split())


@pytest.mark.asyncio
async def test_complete_during_pending_render_is_safe():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _mount_block(pilot)
        # Seed source so complete() has content to finalise.
        block.append_line("x = 1")
        block.append_line("y = 2")
        await pilot.pause()

        # Force a pending render to be queued.
        block._pending_render = True

        skin_vars = app.get_css_variables()
        block.complete(skin_vars)
        # Drain finalize_syntax callback.
        for _ in range(5):
            await pilot.pause()

        assert block._state == "COMPLETE"
        assert block._pending_render is False
        assert block._log._streaming_active is False
