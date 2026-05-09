"""Tests for MPC-H1/MPC-M1/MPC-M2/MPC-L1: background model catalog cache.

MPC-H1  _populate_model_list reads from cache; fires background worker on miss
MPC-M2  _populate_provider_list reads from _provider_list_cache
MPC-M1  dismiss_overlay resets _model_prefetch_done flag
MPC-L1  Worker name dedup guards prevent duplicate fetches
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.overlays.config import ConfigOverlay


# ─── shared helpers ──────────────────────────────────────────────────────────


class _CfgApp(App):
    def compose(self) -> ComposeResult:
        yield ConfigOverlay(id="cfg")


def _make_app() -> _CfgApp:
    return _CfgApp()


def _fake_cfg(provider: str = "openrouter", model: str = "gpt-4o") -> dict:
    return {
        "model": {"provider": provider, "default": model},
        "models": {},
        "display": {
            "tool_progress": "all",
            "skin": "hermes",
            "show_reasoning": False,
            "rich_reasoning": True,
            "skin_overrides": {"vars": {}},
        },
        "approvals": {"mode": "manual"},
    }


def _fake_provider(slug: str) -> dict:
    return {"id": slug, "label": slug, "authenticated": True}


def _overlay_standalone() -> ConfigOverlay:
    """Return a ConfigOverlay with no app — for unit tests that don't mount."""
    ov = ConfigOverlay.__new__(ConfigOverlay)
    ConfigOverlay.__init__(ov)
    # Minimal stubs so workers/DOM calls don't crash
    ov.workers = SimpleNamespace(
        __iter__=lambda s: iter([]),
        __contains__=lambda s, x: False,
    )
    return ov


# ─── MPC-H1: _populate_model_list uses cache ─────────────────────────────────


class TestPopulateUsesCache:
    """MPC-H1: cache-read path and cache-miss placeholder + worker kick-off."""

    @pytest.mark.asyncio
    async def test_populate_uses_cache_when_warm(self):
        """Cache pre-populated → provider_model_ids never called."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache["openrouter"] = ["model-a", "model-b"]
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch("hermes_cli.models.provider_model_ids") as mock_ids:
                ov._populate_model_list("openrouter", "model-a")
                mock_ids.assert_not_called()
            from textual.widgets import OptionList
            ol = ov.query_one("#co-model-list", OptionList)
            opts = [ol.get_option_at_index(i).id for i in range(ol.option_count)]
            assert "co-model-opt-model-a" in opts
            assert "co-model-opt-model-b" in opts

    @pytest.mark.asyncio
    async def test_populate_shows_placeholder_on_miss(self):
        """Cache empty → OptionList contains the loading placeholder."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache.clear()
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch.object(ov, "run_worker"):
                ov._populate_model_list("openrouter", "gpt-4o")
                await pilot.pause()
            from textual.widgets import OptionList
            ol = ov.query_one("#co-model-list", OptionList)
            labels = [ol.get_option_at_index(i).prompt for i in range(ol.option_count)]
            assert any("loading" in str(lbl) for lbl in labels)

    @pytest.mark.asyncio
    async def test_populate_kicks_off_fetch_on_miss(self):
        """Cache empty → run_worker called with a callable and correct worker name."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache.clear()
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch.object(ov, "run_worker") as mock_rw:
                ov._populate_model_list("openrouter", "gpt-4o")
            assert mock_rw.called
            kwargs = mock_rw.call_args[1]
            assert kwargs.get("name") == "model-catalog-fetch-openrouter"
            assert callable(mock_rw.call_args[0][0])

    @pytest.mark.asyncio
    async def test_fetch_worker_stores_in_cache(self):
        """_fetch_provider_models stores IDs in _model_cache on success."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache.clear()
            fake_ids = ["m1", "m2", "m3"]
            with patch(
                "hermes_cli.models.provider_model_ids", return_value=iter(fake_ids)
            ), patch.object(pilot.app, "call_from_thread"):
                ov._fetch_provider_models("openrouter", "m1")
            assert ov._model_cache["openrouter"] == fake_ids

    @pytest.mark.asyncio
    async def test_fetch_worker_repopulates_if_still_browsed(self):
        """_fetch_provider_models calls app.call_from_thread when provider unchanged."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._browsed_provider = "openrouter"
            with patch(
                "hermes_cli.models.provider_model_ids", return_value=iter(["m1"])
            ), patch.object(pilot.app, "call_from_thread") as mock_cft:
                ov._fetch_provider_models("openrouter", "m1")
            assert mock_cft.called
            # Bound methods aren't identity-equal across accesses; compare __func__
            assert mock_cft.call_args[0][0].__func__ is ConfigOverlay._populate_model_list

    @pytest.mark.asyncio
    async def test_fetch_worker_skips_repopulate_if_provider_changed(self):
        """_fetch_provider_models skips call_from_thread when browsed provider moved."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._browsed_provider = "anthropic"  # user already moved to different provider
            with patch(
                "hermes_cli.models.provider_model_ids", return_value=iter(["m1"])
            ), patch.object(pilot.app, "call_from_thread") as mock_cft:
                ov._fetch_provider_models("openrouter", "m1")
            mock_cft.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefetch_worker_fills_all_providers(self):
        """_prefetch_all_providers populates _model_cache for all providers."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache.clear()
            providers = [
                _fake_provider("openrouter"),
                _fake_provider("anthropic"),
                _fake_provider("openai"),
            ]
            model_map = {
                "openrouter": ["or-m1", "or-m2"],
                "anthropic": ["claude-3"],
                "openai": ["gpt-4o"],
            }

            def _ids(slug, force_refresh=False):
                return iter(model_map.get(slug, []))

            with patch(
                "hermes_cli.models.list_available_providers", return_value=providers
            ), patch("hermes_cli.models.provider_model_ids", side_effect=_ids):
                ov._prefetch_all_providers.__wrapped__(ov)  # call underlying fn directly
            assert ov._model_cache["openrouter"] == ["or-m1", "or-m2"]
            assert ov._model_cache["anthropic"] == ["claude-3"]
            assert ov._model_cache["openai"] == ["gpt-4o"]
            assert ov._model_prefetch_done is True


# ─── MPC-M2: _populate_provider_list uses _provider_list_cache ───────────────


class TestProviderListCache:
    """MPC-M2: provider list read from cache avoids main-thread network call."""

    @pytest.mark.asyncio
    async def test_provider_list_from_cache(self):
        """_provider_list_cache populated → list_available_providers not called."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._provider_list_cache = [_fake_provider("openrouter")]
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch("hermes_cli.models.list_available_providers") as mock_lap:
                ov._populate_provider_list("openrouter")
            mock_lap.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_list_fallback_when_cache_empty(self):
        """_provider_list_cache is None → falls back to live call."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._provider_list_cache = None
            fake_providers = [_fake_provider("openrouter")]
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", return_value=fake_providers
            ) as mock_lap, patch(
                "hermes_cli.models.normalize_provider", side_effect=lambda s: s
            ):
                ov._populate_provider_list("openrouter")
            mock_lap.assert_called_once()

    @pytest.mark.asyncio
    async def test_prefetch_stores_provider_list(self):
        """Prefetch worker stores providers in _provider_list_cache."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._provider_list_cache = None
            providers = [_fake_provider("openrouter"), _fake_provider("anthropic")]
            with patch(
                "hermes_cli.models.list_available_providers", return_value=providers
            ), patch("hermes_cli.models.provider_model_ids", return_value=iter([])):
                ov._prefetch_all_providers.__wrapped__(ov)
            assert ov._provider_list_cache is providers

    @pytest.mark.asyncio
    async def test_provider_list_fallback_logs_warning(self):
        """Live call raises → _log.warning called and empty list used (no crash)."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._provider_list_cache = None
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", side_effect=RuntimeError("net fail")
            ), patch(
                "hermes_cli.models.normalize_provider", side_effect=lambda s: s
            ), patch(
                "hermes_cli.tui.overlays.config._log"
            ) as mock_log:
                ov._populate_provider_list("openrouter")
            mock_log.warning.assert_called()


# ─── MPC-M1: dismiss resets prefetch flag ────────────────────────────────────


class TestDismissReset:
    """MPC-M1: dismiss_overlay resets _model_prefetch_done."""

    @pytest.mark.asyncio
    async def test_dismiss_resets_prefetch_flag(self):
        """dismiss_overlay sets _model_prefetch_done to False."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_prefetch_done = True
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.dismiss_overlay()
            assert ov._model_prefetch_done is False

    @pytest.mark.asyncio
    async def test_reopen_starts_prefetch_again(self):
        """open → dismiss → reopen: prefetch worker started twice."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            call_count = 0

            def _fake_prefetch():
                nonlocal call_count
                call_count += 1

            with patch.object(ov, "_prefetch_all_providers", _fake_prefetch), patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", return_value=[]
            ), patch(
                "hermes_cli.models.provider_model_ids", return_value=iter([])
            ):
                ov.show_overlay(tab="model")
                ov.dismiss_overlay()
                ov.show_overlay(tab="model")
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_cache_retained_across_reopen(self):
        """Cached entries stay after dismiss; not re-fetched on second open."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache["openrouter"] = ["cached-model"]
            fetch_slugs: list[str] = []

            def _fake_ids(slug, force_refresh=False):
                fetch_slugs.append(slug)
                return iter([])

            providers = [_fake_provider("openrouter")]
            with patch(
                "hermes_cli.models.list_available_providers", return_value=providers
            ), patch("hermes_cli.models.provider_model_ids", side_effect=_fake_ids):
                ov.dismiss_overlay()
                ov._prefetch_all_providers.__wrapped__(ov)
            # openrouter already cached → should not be re-fetched
            assert "openrouter" not in fetch_slugs
            assert ov._model_cache["openrouter"] == ["cached-model"]


# ─── MPC-L1: worker dedup guards ─────────────────────────────────────────────


class TestWorkerDedup:
    """MPC-L1: worker name guards prevent duplicate fetches."""

    @pytest.mark.asyncio
    async def test_no_duplicate_prefetch_worker(self):
        """show_overlay while prefetch still running → worker not launched again."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_prefetch_done = False
            ov._model_cache["openrouter"] = ["cached-m"]  # avoid targeted-fetch run_worker

            # Simulate a running worker named "model-catalog-prefetch"
            running_worker = MagicMock()
            running_worker.name = "model-catalog-prefetch"
            running_worker.state = MagicMock()  # not in _WORKER_DONE set

            with patch.object(ov, "_prefetch_all_providers") as mock_prefetch, patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", return_value=[]
            ), patch(
                "hermes_cli.models.provider_model_ids", return_value=iter([])
            ), patch.object(
                type(ov), "workers", new_callable=PropertyMock, return_value=[running_worker]
            ):
                ov.show_overlay(tab="model")

            mock_prefetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_open_after_done_skips_worker(self):
        """_model_prefetch_done=True → no prefetch worker started on show_overlay."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_prefetch_done = True

            with patch.object(ov, "_prefetch_all_providers") as mock_prefetch, patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", return_value=[]
            ), patch(
                "hermes_cli.models.provider_model_ids", return_value=iter([])
            ):
                ov.show_overlay(tab="model")

            mock_prefetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_open_after_reset_starts_worker(self):
        """After dismiss (reset), show_overlay starts prefetch worker."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_prefetch_done = False  # as if dismiss was called

            with patch.object(ov, "_prefetch_all_providers") as mock_prefetch, patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), patch(
                "hermes_cli.models.list_available_providers", return_value=[]
            ), patch(
                "hermes_cli.models.provider_model_ids", return_value=iter([])
            ):
                ov.show_overlay(tab="model")

            mock_prefetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_targeted_fetch_no_duplicate(self):
        """_populate_model_list called twice for same provider → run_worker once."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov._model_cache.clear()

            worker_name = "model-catalog-fetch-openrouter"
            running_worker = MagicMock()
            running_worker.name = worker_name
            running_worker.state = MagicMock()  # not in _WORKER_DONE set

            run_worker_calls = 0

            def _fake_run_worker(fn, *args, thread=False, name=""):
                nonlocal run_worker_calls
                run_worker_calls += 1

            with patch.object(ov, "run_worker", side_effect=_fake_run_worker):
                # First call — no worker running, run_worker fires
                ov._populate_model_list("openrouter", "gpt-4o")
                # Second call — simulate worker as now running; dedup guard fires
                with patch.object(
                    type(ov), "workers", new_callable=PropertyMock, return_value=[running_worker]
                ):
                    ov._populate_model_list("openrouter", "gpt-4o")

            assert run_worker_calls == 1
