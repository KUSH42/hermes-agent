"""TUI test suite conftest — shared fixtures for tests/tui/.

Disables the TTE disk cache for all TUI tests by default so tests that
patch iter_frames to yield nothing still observe the cache-miss path.

Integration tests that need to exercise the cache explicitly override this
by using their own load_tte_frames mock rather than relying on the real
module.  The autouse fixture patches the real cache functions inside
hermes_cli.tui._tte_cache so any import path reaches the mock.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _inject_missing_css_var_defaults():
    """Inject CSS variable fallbacks that skins provide but COMPONENT_VAR_DEFAULTS omits.

    ``$user-accent`` is defined in every bundled skin's DESIGN.md but is not
    listed in COMPONENT_VAR_DEFAULTS, so test runs that never load a skin leave
    it unresolved.  Textual raises UnresolvedVariableError when a DEFAULT_CSS
    string references an undefined ``$`` variable, crashing any test that
    mounts ``UserMessagePanel`` (which uses ``border-left: vkey $user-accent``).

    This fixture patches the dict in-place before each test so the fallback is
    visible to ``_defaults_as_strs()`` → ``HermesApp.get_css_variables()``.
    """
    try:
        import hermes_cli.tui.theme_manager as _tm
        _orig = _tm.COMPONENT_VAR_DEFAULTS
        if "user-accent" not in _orig:
            _tm.COMPONENT_VAR_DEFAULTS = {**_orig, "user-accent": "#888888"}
        yield
        _tm.COMPONENT_VAR_DEFAULTS = _orig
    except Exception:
        # Module not importable in this environment; no-op.
        yield


@pytest.fixture(autouse=True)
def _disable_tte_cache_for_tui_tests():
    """Disable TTE disk cache reads for all TUI tests.

    Without this, tests that patch iter_frames to return nothing still get a
    cache hit from a prior successful run, causing unexpected cache-hit paths.
    This fixture patches load_tte_frames to always return None (cache miss)
    and save_tte_frames / gc_tte_cache to no-ops, so test assertions match the
    expected flow without stale on-disk state influencing results.

    Tests that exercise the cache explicitly (TestIntegration in test_tte_cache.py)
    use their own fine-grained mocks which override these patches per test.
    """
    try:
        with patch("hermes_cli.tui._tte_cache.load_tte_frames", return_value=None), \
             patch("hermes_cli.tui._tte_cache.save_tte_frames"), \
             patch("hermes_cli.tui._tte_cache.gc_tte_cache"):
            yield
    except Exception:
        # Module may not be importable in all test environments; yield anyway.
        yield
