# Skin/CSS-Var Diagnostic Logging + Lint Gate (SPEC-CSS)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** SKIN-H1, SVC-H1 (populate_slash_commands swallow), SVC-H2 (play_effects_blocking), STAT-M2, OVERLAY-CTOR-WATCH-SWALLOW, THEME-REFRESH-EXCEPT-TUPLE, SKIN-L1
**Test file:** `tests/tui/test_skin_var_diagnostics.py` + extension to `tests/tui/test_invariants.py`
**Estimated tests:** 14

---

## Summary

`get_css_variables()` is the documented-fragile DESIGN.md SkinPayload contract surface, called from at least 4 lifecycle-critical sites (AssistantNameplate, HintBar, StatusBar, ThemeService). Three of those sites currently `except Exception: pass` with no log. Skin hot-swap can fail silently and leave widgets stuck on stale colors — exactly the failure class IL-1..IL-8 was designed to prevent for tools, but the skin contract has no equivalent gate. This spec adds `_log.warning(..., exc_info=True)` at every swallow site and an `IL-S1` invariant test that lints `get_css_variables()` callsites for the log pattern.

---

## CSS-1 — AssistantNameplate × 4 sites swallow `get_css_variables()` failures

### Problem

`hermes_cli/tui/widgets/__init__.py:1029-1030, 1037-1040, 1067-1069, 1075-1077` — four bare-fallback sites:

```python
try:
    vars_ = self.app.get_css_variables()
    self._tier_color = vars_.get(...)
except Exception:
    pass  # falls through to default hex; no log
```

A skin hot-swap that breaks `get_css_variables()` (component var key collision, theme corruption) silently keeps stale colors. The user sees "the new skin didn't apply" with nothing to grep.

### Fix

At each site:

```python
except Exception:
    _log.warning("AssistantNameplate.<method>: skin var resolve failed", exc_info=True)
    # Fall through to _DEFAULT_TIER_HEX
```

Add `import logging; _log = logging.getLogger(__name__)` at module top if not already present.

### Tests (3)

- `test_nameplate_logs_warning_on_get_css_variables_exception` — patch `app.get_css_variables` to raise; mount Nameplate; assert `_log.warning` called once with `exc_info` truthy.
- `test_nameplate_falls_back_to_default_hex_after_log` — color attribute equals `_DEFAULT_TIER_HEX` after failure.
- `test_nameplate_set_tier_logs_on_failure` — same pattern via `set_tier()` path.

---

## CSS-2 — `populate_slash_commands` swallows all errors silently (SVC-H1)

### Problem

`hermes_cli/tui/services/theme.py:259-260`. Outer `except Exception: pass` with no log. If `COMMAND_REGISTRY` iteration or `HermesInput.set_slash_*` raises, slash-command autocomplete is empty for the whole session.

### Fix

```python
except Exception:
    _log.warning("populate_slash_commands failed; slash autocomplete may be empty", exc_info=True)
```

### Tests (1)

- `test_populate_slash_commands_logs_on_failure` — patch registry to raise on iter; assert log called.

---

## CSS-3 — `play_effects_blocking` returns False without log (SVC-H2)

### Problem

`hermes_cli/tui/services/io.py:240-243`:

```python
try:
    return future.result(timeout=...)
except Exception:
    return False  # silent
```

User-blocking call with no diagnostic.

### Fix

```python
except concurrent.futures.TimeoutError:
    _log.warning("play_effects_blocking: timed out waiting for effects future")
    return False
except Exception:
    _log.warning("play_effects_blocking: future failed", exc_info=True)
    return False
```

### Tests (2)

- `test_play_effects_blocking_logs_timeout`
- `test_play_effects_blocking_logs_other_exception`

---

## CSS-4 — `HintBar._get_key_color` swallows `get_css_variables` (STAT-M2)

### Problem

`hermes_cli/tui/widgets/status_bar.py:283-288`:

```python
try:
    vars_ = self.app.get_css_variables()
    return vars_.get(key, fallback)
except Exception:
    return fallback  # no log
```

### Fix

```python
except Exception:
    _log.debug("HintBar._get_key_color: css var lookup failed for %r", key, exc_info=True)
    return fallback
```

DEBUG (not WARNING) because HintBar reads keys on every render — flooding WARNING would be noise.

### Tests (1)

- `test_hintbar_get_key_color_logs_at_debug_on_failure`

---

## CSS-5 — DrawbrailleOverlay `watch_color/_b/_multi` × 3 sites silently swallow (OVERLAY-CTOR-WATCH-SWALLOW)

### Problem

`hermes_cli/tui/drawbraille_overlay.py:612-631`. Three reactive watchers `try: ... except Exception: pass` with comment-only justification ("renderer not ready"). A real `_resolve_color` failure on bad input → stale color forever, no log.

### Fix

```python
except Exception:
    _log.debug("watch_color: resolve failed for %r", value, exc_info=True)
```

DEBUG severity — these fire on every reactive change, so WARNING would spam.

Also fix `_has_nameplate` at `drawbraille_overlay.py:899-902`:

```python
except NoMatches:
    return False
except Exception:
    _log.debug("_has_nameplate: unexpected DOM error", exc_info=True)
    return False
```

And `drawbraille_overlay.py:901` (the bare `except Exception: pass` from L2 in the audit) — same treatment.

### Tests (2)

- `test_watch_color_logs_on_resolve_failure` — inject bad value; assert `_log.debug` called.
- `test_has_nameplate_narrow_swallow_for_nomatches` — NoMatches returns False without logging; other Exception logs.

---

## CSS-6 — `services/theme.py` `except (NoMatches, Exception): pass` (THEME-REFRESH-EXCEPT-TUPLE)

### Problem

`hermes_cli/tui/services/theme.py:204-205`:

```python
except (NoMatches, Exception):
    pass
```

`Exception` makes `NoMatches` redundant AND swallows everything. Project rule: every except must log/re-raise/comment.

### Fix

Split:

```python
except NoMatches:
    pass  # overlay not mounted yet — expected during early startup
except Exception:
    _log.exception("services.theme: refresh failed unexpectedly")
```

### Tests (1)

- `test_theme_refresh_logs_on_unexpected_exception` — non-NoMatches exception logged.

---

## CSS-7 — `_builtin_skin_to_css` silently drops keys when `_hex` returns None (SKIN-L1)

### Problem

`hermes_cli/tui/theme_manager.py:391-470`. `_cv` helper skips falsy values. Skins lacking `ui_accent` silently fall through to defaults with no warning that built-in derivation found nothing.

### Fix

At end of function:

```python
if all(v is None for v in (resolved_accent, resolved_dim, resolved_warn, resolved_error,
                           resolved_chrome, resolved_panel)):
    _log.debug("_builtin_skin_to_css: skin %r had no usable color keys; using defaults",
               skin.name)
```

### Tests (1)

- `test_builtin_skin_logs_when_all_keys_missing`

---

## IL-S1 — Invariant gate: `get_css_variables()` calls must log on exception

### Problem

The contract surface has no enforcement gate; future code can re-introduce bare swallows.

### Fix

Add `tests/tui/test_invariants.py::TestSkinDiagnostics::test_il_s1_get_css_variables_calls_log_on_failure`. AST-walk `hermes_cli/tui/` for `Call` nodes whose `func` resolves to attribute access ending in `get_css_variables`. For each, walk up to the enclosing `Try` node; assert at least one of its `handlers` includes a `Call` whose function attribute is one of `_log.warning`, `_log.exception`, `_log.error`, `_log.debug` AND that call has `exc_info=True` OR is `_log.exception` (which is implicitly exc_info).

Bare `pass` handlers fail unless preceded by `# il-s1: <reason>` exemption.

### Tests (3)

- `test_il_s1_passes_on_compliant_call`
- `test_il_s1_rejects_bare_swallow`
- `test_il_s1_honors_exemption_comment`

---

## Implementation order

1. **CSS-1** first — Nameplate is the highest-visibility surface and the first thing users see.
2. **CSS-2 + CSS-3** — short app-level patches.
3. **CSS-4 + CSS-5 + CSS-6 + CSS-7** — pattern-aligned cleanup; small and safe.
4. **IL-S1** last — gate lands once all known violators are clean.

---

## Test file layout

```python
# tests/tui/test_skin_var_diagnostics.py

class TestNameplateSkinDiagnostics: ...   # 3
class TestSlashCommandLogging: ...         # 1
class TestPlayEffectsLogging: ...          # 2
class TestHintBarKeyColor: ...             # 1
class TestDrawbrailleWatchers: ...         # 2
class TestThemeRefreshSplit: ...           # 1
class TestBuiltinSkinFallback: ...         # 1
# Total: 11

# tests/tui/test_invariants.py (extension)
class TestSkinDiagnostics: ...             # 3
# Total: 3

# Grand total: 14
```

Tests use `caplog` (pytest builtin) for log assertions; widget tests mount only the affected widget via `Pilot`.
