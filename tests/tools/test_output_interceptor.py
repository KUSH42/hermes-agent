import json
import os
from pathlib import Path
from unittest.mock import patch

from tools.output_interceptor import (
    CommandExecutionResult,
    InterceptorRequest,
    classify_command,
    intercept_output,
    result_to_json_dict,
)
from tools.terminal_tool import terminal_tool


class TestOutputInterceptor:
    def test_classify_supported_commands(self):
        assert classify_command("git status") == "git_status"
        assert classify_command("git diff HEAD~1") == "git_diff"
        assert classify_command("pytest -q") == "pytest"
        assert classify_command("python -m pytest tests/") == "python_pytest"

    def test_git_diff_summary_persists_raw_capture(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("TERMINAL_INTERCEPTOR_MIN_SAVINGS_CHARS", "0")
        monkeypatch.setenv("TERMINAL_INTERCEPTOR_MIN_SAVINGS_RATIO", "0.0")
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,4 +1,12 @@\n"
            "-old\n"
            "+new\n"
            "+line 1\n"
            "+line 2\n"
            "+line 3\n"
            "+line 4\n"
            "+line 5\n"
            "+line 6\n"
            "diff --git a/bar.py b/bar.py\n"
            "--- a/bar.py\n"
            "+++ b/bar.py\n"
            "@@ -10,3 +10,6 @@\n"
            "-x\n"
            "+y\n"
            "+z\n"
            "+w\n"
        )
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="git diff",
                    cwd="/repo",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    combined_output=diff,
                ),
                verbosity="summary",
                task_id="task123",
            )
        )

        assert result.interceptor_kind == "git_diff"
        assert result.derived is True
        assert "2 files changed" in result.summary
        assert result.raw_output_path is not None
        assert Path(result.raw_output_path).exists()

    def test_git_diff_medium_returns_compact_file_list(self):
        with patch.dict(os.environ, {"TERMINAL_INTERCEPTOR_CAPTURE_SUMMARIZED_RAW": "false"}):
            diff = (
                "diff --git a/foo.py b/foo.py\n"
                "--- a/foo.py\n"
                "+++ b/foo.py\n"
                "@@ -1,4 +1,12 @@\n"
                "-old\n"
                "+new\n"
                "+line 1\n"
                "+line 2\n"
                "+line 3\n"
                "+line 4\n"
                "+line 5\n"
                "+line 6\n"
                "diff --git a/bar.py b/bar.py\n"
                "--- a/bar.py\n"
                "+++ b/bar.py\n"
                "@@ -10,3 +10,6 @@\n"
                "-x\n"
                "+y\n"
                "+z\n"
                "+w\n"
            )
            result = intercept_output(
                InterceptorRequest(
                    execution=CommandExecutionResult(
                        command="git diff",
                        cwd="/repo",
                        exit_code=1,
                        stdout="",
                        stderr="",
                        combined_output=diff,
                    ),
                    verbosity="medium",
                )
            )

        assert result.derived is True
        assert result.interceptor_kind == "git_diff"
        assert result.confidence == "high"
        assert "2 files changed" in result.output
        assert "Files: foo.py, bar.py" in result.output
        assert "@@ -1,4 +1,12 @@" not in result.output

    def test_small_summary_can_fall_back_to_raw_when_not_smaller(self):
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="git status --porcelain=v1 --branch",
                    cwd="/repo",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    combined_output="## main...origin/main\n",
                ),
                verbosity="summary",
            )
        )

        assert result.derived is False
        assert result.confidence == "raw"
        assert result.output == "## main...origin/main"

    def test_git_status_summary_uses_compact_structured_payload(self):
        combined_output = (
            "## feat/demo...origin/feat/demo [ahead 2]\n"
            + "".join(f" M tracked_{i:02d}.py\n" for i in range(1, 11))
            + "".join(f"?? scratch_{i:02d}.txt\n" for i in range(1, 9))
        )
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="git status --porcelain=v1 --branch",
                    cwd="/repo",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    combined_output=combined_output,
                ),
                verbosity="summary",
            )
        )

        assert result.derived is True
        assert result.structured == {
            "branch": "feat/demo",
            "ahead": 2,
            "counts": {"modified": 10, "untracked": 8},
        }

    def test_pytest_summary_extracts_failures_for_noisy_output(self):
        with patch.dict(os.environ, {"TERMINAL_INTERCEPTOR_CAPTURE_SUMMARIZED_RAW": "false"}):
            text = (
                "============================= test session starts ==============================\n"
                "platform linux -- Python 3.12.1, pytest-8.3.1\n"
                "collected 5 items\n\n"
                "FAILED tests/test_demo.py::test_a - AssertionError: no\n"
                "FAILED tests/test_demo.py::test_b - ValueError: bad\n"
                "tests/test_demo.py ...F.F\n\n"
                "=================================== FAILURES ===================================\n"
                "_______________________________ test_a _______________________________\n"
                "E AssertionError: no\n"
                "_______________________________ test_b _______________________________\n"
                "E ValueError: bad\n"
                "========== 2 failed, 3 passed in 0.12s ==========\n"
            )
            result = intercept_output(
                InterceptorRequest(
                    execution=CommandExecutionResult(
                        command="pytest -q",
                        cwd="/repo",
                        exit_code=1,
                        stdout="",
                        stderr="",
                        combined_output=text,
                    ),
                    verbosity="summary",
                )
            )

        assert result.interceptor_kind == "pytest"
        assert "3 passed" in result.summary
        assert "2 failed" in result.summary
        assert "tests/test_demo.py::test_a" in result.summary
        assert result.structured == {
            "passed": 3,
            "failed": 2,
            "failing_tests": [
                "tests/test_demo.py::test_a",
                "tests/test_demo.py::test_b",
            ],
        }

    def test_full_verbosity_returns_raw_output(self):
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="echo hello",
                    cwd="/repo",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    combined_output="hello\n",
                ),
                verbosity="full",
            )
        )

        assert result.derived is False
        assert result.output == "hello"
        assert result.confidence == "raw"

    def test_ambiguous_git_status_falls_back_to_raw(self):
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="git status",
                    cwd="/repo",
                    exit_code=0,
                    stdout="",
                    stderr="",
                    combined_output="fatal: not a git repository\n",
                ),
                verbosity="summary",
            )
        )

        assert result.derived is False
        assert result.interceptor_kind is None
        assert result.fallback_reason == "ambiguous_git_status_output"
        assert result.confidence == "fallback"
        assert "fatal: not a git repository" in result.output

    def test_ambiguous_pytest_falls_back_to_raw(self):
        result = intercept_output(
            InterceptorRequest(
                execution=CommandExecutionResult(
                    command="pytest -q",
                    cwd="/repo",
                    exit_code=1,
                    stdout="",
                    stderr="",
                    combined_output="python: can't open file '/tmp/pytest': [Errno 2] No such file or directory\n",
                ),
                verbosity="summary",
            )
        )

        assert result.derived is False
        assert result.fallback_reason == "ambiguous_pytest_output"
        assert result.confidence == "fallback"
        assert "can't open file" in result.output

    def test_result_json_can_hide_fallback_reason_while_preserving_confidence(self):
        with patch.dict(os.environ, {"TERMINAL_INTERCEPTOR_INCLUDE_FALLBACK_REASON": "false"}):
            result = intercept_output(
                InterceptorRequest(
                    execution=CommandExecutionResult(
                        command="git status",
                        cwd="/repo",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        combined_output="fatal: not a git repository\n",
                    ),
                    verbosity="summary",
                )
            )
            payload = result_to_json_dict(result, "summary")

        assert result.confidence == "fallback"
        assert result.fallback_reason == "ambiguous_git_status_output"
        assert payload["confidence"] == "fallback"
        assert "fallback_reason" not in payload


class TestTerminalToolInterceptor:
    def test_terminal_tool_returns_additive_interceptor_fields(self):
        class FakeEnv:
            def execute(self, command, **kwargs):
                return {
                    "output": (
                        "============================= test session starts ==============================\n"
                        "platform linux -- Python 3.12.1, pytest-8.3.1\n"
                        "collected 5 items\n\n"
                        "FAILED tests/test_demo.py::test_a - AssertionError: no\n"
                        "FAILED tests/test_demo.py::test_b - ValueError: bad\n"
                        "tests/test_demo.py ...F.F\n\n"
                        "=================================== FAILURES ===================================\n"
                        "_______________________________ test_a _______________________________\n"
                        "E AssertionError: no\n"
                        "_______________________________ test_b _______________________________\n"
                        "E ValueError: bad\n"
                        "========== 2 failed, 3 passed in 0.12s ==========\n"
                    ),
                    "returncode": 1,
                }

        with patch.dict(os.environ, {"TERMINAL_INTERCEPTOR_CAPTURE_SUMMARIZED_RAW": "false"}), patch("tools.terminal_tool._get_env_config", return_value={
            "env_type": "local",
            "cwd": "/repo",
            "timeout": 30,
            "docker_image": "",
            "singularity_image": "",
            "modal_image": "",
            "daytona_image": "",
            "local_persistent": False,
        }), patch("tools.terminal_tool._start_cleanup_thread"), patch(
            "tools.terminal_tool._create_environment", return_value=FakeEnv()
        ), patch("tools.terminal_tool._check_all_guards", return_value={"approved": True}), patch(
            "tools.terminal_tool._active_environments", {}
        ), patch("tools.terminal_tool._last_activity", {}):
            result = json.loads(terminal_tool("pytest -q", task_id="task_pytest"))

        assert result["exit_code"] == 1
        assert result["derived_output"] is True
        assert result["interceptor_kind"] == "pytest"
        assert result["verbosity"] == "summary"
        assert result["confidence"] == "high"
        assert "2 failed" in result["summary"]

    def test_terminal_tool_full_verbosity_returns_raw(self):
        class FakeEnv:
            def execute(self, command, **kwargs):
                return {
                    "output": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n-old\n+new\n",
                    "returncode": 1,
                }

        with patch("tools.terminal_tool._get_env_config", return_value={
            "env_type": "local",
            "cwd": "/repo",
            "timeout": 30,
            "docker_image": "",
            "singularity_image": "",
            "modal_image": "",
            "daytona_image": "",
            "local_persistent": False,
        }), patch("tools.terminal_tool._start_cleanup_thread"), patch(
            "tools.terminal_tool._create_environment", return_value=FakeEnv()
        ), patch("tools.terminal_tool._check_all_guards", return_value={"approved": True}), patch(
            "tools.terminal_tool._active_environments", {}
        ), patch("tools.terminal_tool._last_activity", {}):
            result = json.loads(terminal_tool("git diff", task_id="task_gitdiff", verbosity="full"))

        assert result["derived_output"] is False
        assert result["confidence"] == "raw"
        assert result["output"].startswith("diff --git")

    def test_terminal_tool_ambiguous_summary_falls_back_to_raw(self):
        class FakeEnv:
            def execute(self, command, **kwargs):
                return {
                    "output": "fatal: not a git repository (or any of the parent directories): .git\n",
                    "returncode": 128,
                }

        with patch("tools.terminal_tool._get_env_config", return_value={
            "env_type": "local",
            "cwd": "/repo",
            "timeout": 30,
            "docker_image": "",
            "singularity_image": "",
            "modal_image": "",
            "daytona_image": "",
            "local_persistent": False,
        }), patch("tools.terminal_tool._start_cleanup_thread"), patch(
            "tools.terminal_tool._create_environment", return_value=FakeEnv()
        ), patch("tools.terminal_tool._check_all_guards", return_value={"approved": True}), patch(
            "tools.terminal_tool._active_environments", {}
        ), patch("tools.terminal_tool._last_activity", {}):
            result = json.loads(terminal_tool("git status", task_id="task_ambiguous", verbosity="summary"))

        assert result["derived_output"] is False
        assert result["confidence"] == "fallback"
        assert "fallback_reason" not in result
        assert "fatal: not a git repository" in result["output"]
