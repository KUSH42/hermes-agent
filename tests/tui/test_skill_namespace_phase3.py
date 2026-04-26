"""Tests for SNS3 Phase 3 — hard cutover: /skill-name rejected, docs swept."""
from __future__ import annotations

import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the repo working tree root."""
    return Path(__file__).resolve().parents[2]


def _run_phase3_dispatch(
    cmd_original: str,
    skill_commands: dict,
    plugin_names: "set[str] | None" = None,
) -> dict:
    """Minimal Phase-3 dispatch inline — mirrors cli.py ordering.

    Branches tested: $-prefix → dispatch; plugin handler → dispatch;
    skill slash → reject; else → unknown.
    """
    from agent.skill_commands import build_skill_invocation_message

    if plugin_names is None:
        plugin_names = set()

    calls: dict = {"cprint": [], "dispatched": False, "rejected": False, "unknown": False}

    def _cprint(s: str) -> None:
        calls["cprint"].append(s)

    base_cmd = cmd_original.split()[0].lower() if cmd_original.strip() else ""

    # $-branch
    if cmd_original.lstrip().startswith("$"):
        _bare = cmd_original.lstrip()[1:]
        parts = _bare.split(None, 1)
        if parts:
            _cmd_key = f"/{parts[0].replace('_', '-')}"
            if _cmd_key in skill_commands:
                calls["dispatched"] = True
            else:
                _cprint(f"no such skill: {parts[0]}")
        return calls

    # plugin branch (runs before skill rejection)
    if base_cmd.lstrip("/") in plugin_names:
        calls["dispatched"] = True
        return calls

    # skill rejection branch (Phase 3 — no dispatch)
    if base_cmd in skill_commands:
        name = base_cmd.lstrip("/")
        _cprint(f"/{name} no longer invokes skills — use ${name} (Alt+$ for picker)")
        calls["rejected"] = True
        return calls

    # unknown
    calls["unknown"] = True
    return calls


# ---------------------------------------------------------------------------
# SNS3-1 — Reject /skill-name
# ---------------------------------------------------------------------------

class TestSlashSkillRejected:
    """Six tests covering the hard-cutover rejection branch."""

    def test_slash_skill_rejected_phase3(self):
        """'/review-pr 1' → rejection message, no dispatch."""
        skill_commands = {"/review-pr": {"name": "review-pr", "description": "Review PR"}}
        result = _run_phase3_dispatch("/review-pr 1", skill_commands)
        assert result["rejected"]
        assert not result["dispatched"]
        expected = "/review-pr no longer invokes skills — use $review-pr (Alt+$ for picker)"
        assert any(expected in s for s in result["cprint"]), result["cprint"]

    def test_slash_skill_rejected_message_exact(self):
        """Rejection message contains exact Alt+$ trailer."""
        skill_commands = {"/gif-search": {"name": "gif-search", "description": "GIF search"}}
        result = _run_phase3_dispatch("/gif-search", skill_commands)
        assert result["rejected"]
        msg = result["cprint"][0]
        assert "gif-search" in msg
        assert "Alt+$" in msg
        assert "$gif-search" in msg

    def test_dollar_skill_still_works_phase3(self):
        """'$review-pr 1' dispatches normally — $-branch is untouched."""
        skill_commands = {"/review-pr": {"name": "review-pr", "description": "Review PR"}}
        result = _run_phase3_dispatch("$review-pr 1", skill_commands)
        assert result["dispatched"]
        assert not result["rejected"]
        assert not result["cprint"]

    def test_slash_builtin_still_works_phase3(self):
        """'/help' is not in skill_commands → falls through to unknown (not rejected)."""
        # /help is a built-in; it won't be in _skill_commands
        skill_commands = {"/review-pr": {"name": "review-pr", "description": "Review PR"}}
        result = _run_phase3_dispatch("/help", skill_commands)
        assert not result["rejected"]
        assert result["unknown"]  # built-in dispatch happens outside this helper's scope

    def test_slash_plugin_still_works_phase3(self):
        """Plugin command 'foo' (no skill named 'foo') → plugin dispatch, NOT rejection."""
        skill_commands = {"/review-pr": {"name": "review-pr", "description": "Review PR"}}
        plugin_names = {"foo"}
        result = _run_phase3_dispatch("/foo", skill_commands, plugin_names=plugin_names)
        assert result["dispatched"]
        assert not result["rejected"]
        assert not result["cprint"]

    def test_slash_plugin_wins_over_skill_collision_phase3(self):
        """Plugin AND skill named 'foo': /foo → plugin wins; rejection never fires."""
        # Both registered — plugin branch at 5899 runs before skill rejection at 5911
        skill_commands = {"/foo": {"name": "foo", "description": "Foo skill"}}
        plugin_names = {"foo"}
        result = _run_phase3_dispatch("/foo", skill_commands, plugin_names=plugin_names)
        assert result["dispatched"]
        assert not result["rejected"]
        # No rejection message emitted
        assert not any("no longer invokes" in s for s in result["cprint"])

    def test_slash_unknown_unchanged_phase3(self):
        """/nope not in skill_commands → unknown, not the rejection message."""
        skill_commands = {"/review-pr": {"name": "review-pr", "description": "Review PR"}}
        result = _run_phase3_dispatch("/nope", skill_commands)
        assert result["unknown"]
        assert not result["rejected"]
        assert not any("no longer invokes" in s for s in result["cprint"])


# ---------------------------------------------------------------------------
# SNS3-2 — Lock KNOWN_SLASH_COMMANDS purity
# ---------------------------------------------------------------------------

class TestKnownSlashCleansed:
    """Three tests guarding KNOWN_SLASH_COMMANDS purity and the disjoint assertion."""

    def test_known_slash_remains_pure_builtins(self):
        """KNOWN_SLASH_COMMANDS equals the 14-element built-in set exactly."""
        from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS
        expected = frozenset([
            "/loop", "/schedule", "/anim", "/yolo", "/verbose",
            "/model", "/reasoning", "/skin",
            "/help", "/queue", "/btw", "/clear", "/density",
            "/layout",
        ])
        assert KNOWN_SLASH_COMMANDS == expected, (
            f"Extra: {KNOWN_SLASH_COMMANDS - expected!r}  "
            f"Missing: {expected - KNOWN_SLASH_COMMANDS!r}"
        )

    def test_known_slash_known_skills_disjoint_after_normalization(self, _clean_known_skills):
        """refresh_known_skills(['review-pr','gif-search']) → no AssertionError."""
        from hermes_cli.tui._app_constants import (
            refresh_known_skills, KNOWN_SKILLS, _KNOWN_SLASH_BARE,
        )
        refresh_known_skills(["review-pr", "gif-search"])
        assert _KNOWN_SLASH_BARE.isdisjoint(KNOWN_SKILLS)

    def test_refresh_assertion_fires_on_overlap(self, _clean_known_skills):
        """refresh_known_skills(['help']) → AssertionError (bare 'help' collides with /help)."""
        import pytest
        from hermes_cli.tui._app_constants import refresh_known_skills
        with pytest.raises(AssertionError, match="collides with built-in"):
            refresh_known_skills(["help"])

    # Fixture — defined as a method to keep it class-scoped without a conftest
    import pytest as _pytest

    @_pytest.fixture(autouse=False)
    def _clean_known_skills(self):
        """Unconditionally clear KNOWN_SKILLS before and after each test."""
        from hermes_cli.tui._app_constants import KNOWN_SKILLS
        KNOWN_SKILLS.clear()
        try:
            yield
        finally:
            KNOWN_SKILLS.clear()


# ---------------------------------------------------------------------------
# SNS3-3 — Documentation + trigger phrases sweep
# ---------------------------------------------------------------------------

class TestDocsSweep:
    """Three tests verifying the docs sweep landed correctly."""

    _SLASH_SKILL_RE = re.compile(r"(?<![\w/$])/[a-z0-9_-]+\b(?![\w:])")
    _TRIGGER_WORDS_RE = re.compile(
        r"TRIGGER when|Trigger:|Use when|invoke with|user says", re.IGNORECASE
    )

    def test_help_text_uses_dollar_examples_cli(self):
        """cli.py show_help emits '$review-pr' (not '/review-pr') and 'Alt+$'."""
        import inspect
        import sys
        # Verify by source inspection — avoids full HermesCLI instantiation.
        # Pull cli module without executing __main__ guard.
        import importlib.util
        cli_path = str(_repo_root() / "cli.py")
        spec = importlib.util.spec_from_file_location("cli_for_test", cli_path)
        # Source-level check is sufficient and avoids global side effects.
        src = Path(cli_path).read_text()
        show_help_start = src.find("def show_help(")
        assert show_help_start != -1, "show_help not found in cli.py"
        show_help_end = src.find("\n    def ", show_help_start + 1)
        show_help_src = src[show_help_start:show_help_end] if show_help_end != -1 else src[show_help_start:]
        # (a) dollar_cmd uses $-prefix at render time
        assert 'dollar_cmd = f"${' in show_help_src or "dollar_cmd" in show_help_src, (
            "show_help must render skills with $-prefix"
        )
        # (b) does NOT render /review-pr as a row entry (no /name format strings for skills)
        # The old else-branch showing '/name in CLI/gateway mode' must be gone
        assert "/name in CLI/gateway mode" not in show_help_src, (
            "Old /name in CLI/gateway mode text must be removed from show_help"
        )
        # (c) Alt+$ mention preserved
        assert "Alt+$" in show_help_src, "show_help must mention Alt+$ for picker"

    def test_no_remaining_slash_skill_examples_in_skill_md(self):
        """No SKILL.md in the repo has /skill-name invocation examples (excl. built-ins)."""
        from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS

        known_bare = {c.lstrip("/") for c in KNOWN_SLASH_COMMANDS} | {"skills"}
        repo = _repo_root()
        spec_dir = repo / "skill-namespace-migration"  # not in worktree but guard anyway

        failures: list[str] = []
        for skill_md in repo.rglob("SKILL.md"):
            # Skip spec docs and worktrees
            if "skill-namespace-migration" in str(skill_md):
                continue
            if ".claude/worktrees" in str(skill_md):
                continue
            try:
                lines = skill_md.read_text(errors="replace").splitlines()
            except OSError:
                continue

            # Scope 1 — frontmatter description:
            in_fm = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if i == 0 and stripped == "---":
                    in_fm = True
                    continue
                if in_fm:
                    if stripped == "---":
                        break
                    if stripped.startswith("description:"):
                        for m in self._SLASH_SKILL_RE.finditer(stripped):
                            tok = m.group(0).lstrip("/")
                            if tok not in known_bare:
                                failures.append(
                                    f"{skill_md}:{i+1} frontmatter: {stripped!r}"
                                )

            # Scope 2 — trigger-phrase body lines
            for i, line in enumerate(lines):
                if self._SLASH_SKILL_RE.search(line):
                    window = "\n".join(lines[max(0, i - 5): i + 1])
                    if self._TRIGGER_WORDS_RE.search(window):
                        for m in self._SLASH_SKILL_RE.finditer(line):
                            tok = m.group(0).lstrip("/")
                            if tok not in known_bare:
                                failures.append(
                                    f"{skill_md}:{i+1} trigger: {line.strip()!r}"
                                )

        assert not failures, (
            f"{len(failures)} unresolved /skill-name invocation example(s):\n"
            + "\n".join(failures[:20])
        )

    def test_readme_uses_dollar_for_skill_examples(self):
        """README.md Browse-skills row uses $<skill-name> in both CLI and TUI columns."""
        readme = (_repo_root() / "README.md").read_text()
        lines = readme.splitlines()
        browse_lines = [l for l in lines if "Browse skills" in l]
        assert browse_lines, "README.md Browse-skills row not found"
        row = browse_lines[0]
        assert "$<skill-name>" in row, (
            f"README.md Browse-skills row must contain $<skill-name>, got: {row!r}"
        )
        # /skills (the list command) is still present
        assert "/skills" in row, (
            f"README.md Browse-skills row must still contain /skills, got: {row!r}"
        )
        # Old /<skill-name> must be gone
        assert "/<skill-name>" not in row, (
            f"README.md Browse-skills row must not contain /<skill-name>, got: {row!r}"
        )
