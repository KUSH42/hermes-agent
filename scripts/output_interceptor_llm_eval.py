#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI

from run_agent import AIAgent
from tools.output_interceptor import serialization_mode


DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_API_KEY = "local"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "output_interceptor"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


@dataclass
class EvalCase:
    id: str
    description: str
    prompt: str
    expected_substrings: list[str]
    suite: Literal["workspace", "fixture"] = "workspace"
    setup_fn: Callable[[Path], None] | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolTrace:
    name: str
    args: dict
    raw_json_chars: int
    output_chars: int
    result: dict | None


@dataclass
class EvalRunResult:
    case_id: str
    mode: str
    repeat_index: int
    success: bool
    duration_seconds: float
    answer: str
    matched_substrings: list[str]
    missing_substrings: list[str]
    total_tool_json_chars: int
    total_terminal_output_chars: int
    terminal_call_count: int
    serialization_mode: str
    tool_traces: list[ToolTrace] = field(default_factory=list)
    error: str | None = None


class EvalAgent(AIAgent):
    def __init__(self, *args, eval_temperature: float | None = None, eval_seed: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._eval_temperature = eval_temperature
        self._eval_seed = eval_seed

    def _build_api_kwargs(self, api_messages: list) -> dict:
        kwargs = super()._build_api_kwargs(api_messages)
        if self.api_mode == "chat_completions":
            if self._eval_temperature is not None:
                kwargs["temperature"] = self._eval_temperature
            if self._eval_seed is not None:
                extra_body = dict(kwargs.get("extra_body") or {})
                extra_body["seed"] = self._eval_seed
                kwargs["extra_body"] = extra_body
        return kwargs


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_executable(path: Path, content: str) -> None:
    _write(path, content)
    path.chmod(0o755)


def setup_git_status_case(root: Path) -> None:
    _run(["git", "init", "-b", "main"], root)
    _run(["git", "config", "user.name", "Hermes Eval"], root)
    _run(["git", "config", "user.email", "hermes-eval@example.com"], root)
    _write(root / "tracked.txt", "base\n")
    _write(root / "notes.md", "# Notes\n")
    _run(["git", "add", "tracked.txt", "notes.md"], root)
    _run(["git", "commit", "-m", "initial"], root)
    _write(root / "tracked.txt", "base\nchanged\n")
    _write(root / "untracked.txt", "new file\n")


def setup_git_diff_case(root: Path) -> None:
    _run(["git", "init", "-b", "main"], root)
    _run(["git", "config", "user.name", "Hermes Eval"], root)
    _run(["git", "config", "user.email", "hermes-eval@example.com"], root)
    _write(root / "alpha.py", "def alpha():\n    return 1\n")
    _write(root / "beta.py", "def beta():\n    return 'beta'\n")
    _run(["git", "add", "alpha.py", "beta.py"], root)
    _run(["git", "commit", "-m", "initial"], root)
    _write(root / "alpha.py", "def alpha():\n    value = 1\n    value += 2\n    return value\n")
    _write(root / "beta.py", "def beta():\n    return 'beta-v2'\n")


def setup_git_diff_large_case(root: Path) -> None:
    _run(["git", "init", "-b", "main"], root)
    _run(["git", "config", "user.name", "Hermes Eval"], root)
    _run(["git", "config", "user.email", "hermes-eval@example.com"], root)
    base_lines = "\n".join(f"line_{i} = {i}" for i in range(1, 121)) + "\n"
    _write(root / "big.py", base_lines)
    _run(["git", "add", "big.py"], root)
    _run(["git", "commit", "-m", "initial"], root)
    updated_lines = "\n".join(f"line_{i} = {i * 2}" for i in range(1, 121)) + "\n"
    _write(root / "big.py", updated_lines)


def setup_pytest_case(root: Path) -> None:
    _write(root / "app.py", "def add(a, b):\n    return a - b\n\ndef greet(name):\n    return 'hi'\n")
    _write(
        root / "tests" / "test_app.py",
        textwrap.dedent(
            """\
            from app import add, greet


            def test_add():
                assert add(2, 3) == 5


            def test_greet():
                assert greet("x") == "hi x"
            """
        ),
    )


def setup_pytest_noisy_case(root: Path) -> None:
    _write(
        root / "app.py",
        textwrap.dedent(
            """\
            def build_payload():
                return {
                    "name": "example",
                    "items": [f"item-{i}" for i in range(40)],
                    "flags": {"enabled": False, "debug": True},
                }
            """
        ),
    )
    _write(
        root / "tests" / "test_payload.py",
        textwrap.dedent(
            """\
            from app import build_payload


            def test_payload_flags():
                payload = build_payload()
                assert payload["flags"]["enabled"] is True


            def test_payload_items():
                payload = build_payload()
                expected = [f"wrong-{i}" for i in range(40)]
                assert payload["items"] == expected
            """
        ),
    )


WORKSPACE_CASES = [
    EvalCase(
        id="git_status_dirty",
        description="Dirty repo with one modified tracked file and one untracked file.",
        prompt=(
            "Use the terminal tool. Run `git status --porcelain=v1 --branch` in the current working directory. "
            "Then answer in one line with exactly this shape: "
            "`branch=<branch>; modified=<comma-separated modified files>; untracked=<comma-separated untracked files>`."
        ),
        suite="workspace",
        setup_fn=setup_git_status_case,
        expected_substrings=["branch=main", "modified=tracked.txt", "untracked=untracked.txt"],
    ),
    EvalCase(
        id="git_diff_two_files",
        description="Two-file working tree diff with deterministic file names.",
        prompt=(
            "Use the terminal tool. Run `git diff --stat` in the current working directory. "
            "Then answer in one line with exactly this shape: "
            "`files=<comma-separated changed files>; summary=<copy the insertions/deletions totals>`."
        ),
        suite="workspace",
        setup_fn=setup_git_diff_case,
        expected_substrings=["files=alpha.py,beta.py", "insertions", "deletions"],
    ),
    EvalCase(
        id="pytest_failures",
        description="Minimal project with two failing pytest tests.",
        prompt=(
            "Use the terminal tool. Run `python -m pytest -q` in the current working directory. "
            "Then answer in one line with exactly this shape: "
            "`failing=<comma-separated failing tests>`."
        ),
        suite="workspace",
        setup_fn=setup_pytest_case,
        expected_substrings=[
            "failing=tests/test_app.py::test_add,tests/test_app.py::test_greet",
        ],
    ),
    EvalCase(
        id="git_diff_large",
        description="Large one-file diff where summary mode should save tokens.",
        prompt=(
            "Use the terminal tool. Run `git diff` in the current working directory. "
            "Then answer in one line with exactly this shape: "
            "`files=<comma-separated changed files>; summary=<copy the insertions/deletions totals>`."
        ),
        suite="workspace",
        setup_fn=setup_git_diff_large_case,
        expected_substrings=["files=big.py", "insertions", "deletions"],
    ),
    EvalCase(
        id="pytest_noisy",
        description="Noisy failing pytest output with large assertion diffs.",
        prompt=(
            "Use the terminal tool. Run `python -m pytest -q` in the current working directory. "
            "Then answer in one line with exactly this shape: "
            "`failing=<comma-separated failing tests>`."
        ),
        suite="workspace",
        setup_fn=setup_pytest_noisy_case,
        expected_substrings=[
            "failing=tests/test_payload.py::test_payload_flags,tests/test_payload.py::test_payload_items",
        ],
    ),
]


def _split_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    idx = 0
    while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith(("-", "/", ".")):
        if tokens[idx].split("=", 1)[0].replace("_", "").isalnum():
            idx += 1
            continue
        break
    return tokens[idx:]


def _primary_executable(command: str) -> str | None:
    tokens = _split_command(command)
    if not tokens:
        return None
    return Path(tokens[0]).name


def _fixture_expected_substrings(item: dict) -> list[str]:
    expect_derived = str(bool(item.get("expect_derived"))).lower()
    expect_confidence = str(item.get("expect_confidence") or "none")
    expect_kind = str(item.get("expect_kind") or "none")
    expect_fallback = str(item.get("expect_fallback_reason") or "none")
    expect_raw_path = "yes" if item.get("expect_raw_path_exists", bool(item.get("expect_derived"))) else "no"
    expect_truncated = str(bool(item.get("expect_truncated", False))).lower()
    return [
        f"derived={expect_derived}",
        f"confidence={expect_confidence}",
        f"kind={expect_kind}",
        f"fallback_reason={expect_fallback}",
        f"raw_output_path={expect_raw_path}",
        f"truncated={expect_truncated}",
    ]


def _fixture_prompt(item: dict) -> str:
    return (
        "Use the terminal tool exactly once. "
        f"Run `{item['command']}` in the current working directory. "
        "Read the terminal tool JSON carefully. "
        "Then answer in one line exactly with this shape, using the tool field names literally: "
        "`derived=<true|false>; confidence=<value>; kind=<value-or-none>; "
        "fallback_reason=<value-or-none>; raw_output_path=<yes|no>; truncated=<true|false>`. "
        "For `raw_output_path`, answer `yes` if the field is non-null, otherwise `no`."
    )


def _load_fixture_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _setup_fixture_shim(root: Path, item: dict) -> dict[str, str]:
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    output_path = root / "fixture-output.txt"
    output_path.write_text((FIXTURE_DIR / item["output_file"]).read_text(encoding="utf-8"), encoding="utf-8")
    executable = _primary_executable(item["command"])
    if executable and executable not in {"echo"}:
        shim_path = bin_dir / executable
        _write_executable(
            shim_path,
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                cat {shlex.quote(str(output_path))}
                exit {int(item.get("exit_code", 0))}
                """
            ),
        )
    path_parts = [str(bin_dir)]
    existing_path = os.environ.get("PATH")
    if existing_path:
        path_parts.append(existing_path)
    env = {
        "PATH": ":".join(path_parts),
        "HERMES_HOME": str(root / ".hermes"),
    }
    env.update({str(k): str(v) for k, v in (item.get("env") or {}).items()})
    return env


def load_fixture_eval_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for item in _load_fixture_manifest():
        cases.append(
            EvalCase(
                id=f"fixture_{item['id']}",
                description=f"Fixture-backed terminal replay for `{item['id']}`.",
                prompt=_fixture_prompt(item),
                suite="fixture",
                expected_substrings=_fixture_expected_substrings(item),
                env_overrides={
                    "__fixture_id__": str(item["id"]),
                    "__fixture_verbosity__": str(item.get("verbosity", "summary")),
                },
            )
        )
    return cases


def detect_model(base_url: str, api_key: str) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key)
    models = client.models.list()
    data = list(getattr(models, "data", []) or [])
    if not data:
        raise RuntimeError("No models returned by local endpoint")
    return str(data[0].id)


def make_tool_collector() -> tuple[list[ToolTrace], Callable]:
    traces: list[ToolTrace] = []

    def _on_complete(_tool_id, name, args, function_result):
        parsed = None
        output_chars = 0
        try:
            parsed = json.loads(function_result)
            output_field = parsed.get("output")
            if isinstance(output_field, str):
                output_chars = len(output_field)
        except Exception:
            pass
        traces.append(
            ToolTrace(
                name=name,
                args=dict(args or {}),
                raw_json_chars=len(function_result or ""),
                output_chars=output_chars,
                result=parsed,
            )
        )

    return traces, _on_complete


def _set_terminal_mode(mode: str, workdir: Path, *, extra_env: dict[str, str] | None = None, default_verbosity: str | None = None) -> dict[str, str | None]:
    env_keys = {
        "TERMINAL_ENV": os.environ.get("TERMINAL_ENV"),
        "TERMINAL_CWD": os.environ.get("TERMINAL_CWD"),
        "TERMINAL_OUTPUT_INTERCEPTOR_ENABLED": os.environ.get("TERMINAL_OUTPUT_INTERCEPTOR_ENABLED"),
        "TERMINAL_OUTPUT_DEFAULT_VERBOSITY": os.environ.get("TERMINAL_OUTPUT_DEFAULT_VERBOSITY"),
        "PATH": os.environ.get("PATH"),
        "HERMES_HOME": os.environ.get("HERMES_HOME"),
    }
    for key in extra_env or {}:
        env_keys.setdefault(key, os.environ.get(key))
    os.environ["TERMINAL_ENV"] = "local"
    os.environ["TERMINAL_CWD"] = str(workdir)
    if mode == "off":
        os.environ["TERMINAL_OUTPUT_INTERCEPTOR_ENABLED"] = "false"
        os.environ.pop("TERMINAL_OUTPUT_DEFAULT_VERBOSITY", None)
    else:
        os.environ["TERMINAL_OUTPUT_INTERCEPTOR_ENABLED"] = "true"
        os.environ["TERMINAL_OUTPUT_DEFAULT_VERBOSITY"] = default_verbosity or ("summary" if mode == "manifest" else mode)
    for key, value in (extra_env or {}).items():
        os.environ[key] = value
    return env_keys


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_case(
    case: EvalCase,
    mode: str,
    repeat_index: int,
    base_url: str,
    api_key: str,
    model: str,
    seed: int | None,
    temperature: float | None,
    max_iterations: int,
) -> EvalRunResult:
    with tempfile.TemporaryDirectory(prefix=f"hermes-interceptor-eval-{case.id}-") as tmpdir:
        root = Path(tmpdir)
        extra_env: dict[str, str] = dict(case.env_overrides)
        if case.suite == "workspace":
            if case.setup_fn is None:
                raise RuntimeError(f"Workspace case `{case.id}` is missing setup_fn")
            case.setup_fn(root)
            default_verbosity = None
        else:
            fixture_id = extra_env.pop("__fixture_id__", "")
            fixture_verbosity = extra_env.pop("__fixture_verbosity__", "summary")
            manifest_item = next((item for item in _load_fixture_manifest() if item["id"] == fixture_id), None)
            if manifest_item is None:
                raise RuntimeError(f"Missing manifest fixture `{fixture_id}`")
            extra_env.update(_setup_fixture_shim(root, manifest_item))
            default_verbosity = fixture_verbosity
        traces, callback = make_tool_collector()
        env_snapshot = _set_terminal_mode(mode, root, extra_env=extra_env, default_verbosity=default_verbosity)
        session_id = f"eval_{case.id}_{mode}_r{repeat_index}_{uuid.uuid4().hex[:8]}"
        started = time.perf_counter()
        try:
            agent = EvalAgent(
                base_url=base_url,
                api_key=api_key,
                provider="custom",
                api_mode="chat_completions",
                model=model,
                max_iterations=max_iterations,
                enabled_toolsets=["terminal"],
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
                save_trajectories=False,
                reasoning_config={"enabled": False},
                tool_complete_callback=callback,
                session_id=session_id,
                eval_seed=seed,
                eval_temperature=temperature,
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = agent.run_conversation(case.prompt, task_id=session_id)
            answer = str(result.get("final_response") or "").strip()
            lowered = _normalize_answer(answer)
            matched = [s for s in case.expected_substrings if _normalize_answer(s) in lowered]
            missing = [s for s in case.expected_substrings if _normalize_answer(s) not in lowered]
            duration = time.perf_counter() - started
            return EvalRunResult(
                case_id=case.id,
                mode=mode,
                repeat_index=repeat_index,
                success=not missing,
                duration_seconds=duration,
                answer=answer,
                matched_substrings=matched,
                missing_substrings=missing,
                total_tool_json_chars=sum(t.raw_json_chars for t in traces),
                total_terminal_output_chars=sum(t.output_chars for t in traces if t.name == "terminal"),
                terminal_call_count=sum(1 for t in traces if t.name == "terminal"),
                serialization_mode=serialization_mode(),
                tool_traces=traces,
            )
        except Exception as exc:
            duration = time.perf_counter() - started
            return EvalRunResult(
                case_id=case.id,
                mode=mode,
                repeat_index=repeat_index,
                success=False,
                duration_seconds=duration,
                answer="",
                matched_substrings=[],
                missing_substrings=list(case.expected_substrings),
                total_tool_json_chars=sum(t.raw_json_chars for t in traces),
                total_terminal_output_chars=sum(t.output_chars for t in traces if t.name == "terminal"),
                terminal_call_count=sum(1 for t in traces if t.name == "terminal"),
                serialization_mode=serialization_mode(),
                tool_traces=traces,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            _restore_env(env_snapshot)


def summarize(results: list[EvalRunResult]) -> dict:
    by_mode: dict[str, list[EvalRunResult]] = {}
    for result in results:
        by_mode.setdefault(result.mode, []).append(result)

    summary = {}
    for mode, rows in by_mode.items():
        durations = [r.duration_seconds for r in rows]
        tool_json = [r.total_tool_json_chars for r in rows]
        terminal_chars = [r.total_terminal_output_chars for r in rows]
        summary[mode] = {
            "success_rate": sum(1 for r in rows if r.success) / len(rows) if rows else 0.0,
            "avg_duration_seconds": statistics.mean(durations) if rows else 0.0,
            "stdev_duration_seconds": statistics.pstdev(durations) if len(durations) > 1 else 0.0,
            "avg_tool_json_chars": statistics.mean(tool_json) if rows else 0.0,
            "stdev_tool_json_chars": statistics.pstdev(tool_json) if len(tool_json) > 1 else 0.0,
            "avg_terminal_output_chars": statistics.mean(terminal_chars) if rows else 0.0,
            "stdev_terminal_output_chars": statistics.pstdev(terminal_chars) if len(terminal_chars) > 1 else 0.0,
            "avg_terminal_calls": statistics.mean(r.terminal_call_count for r in rows) if rows else 0.0,
            "serialization_modes": sorted({r.serialization_mode for r in rows}),
        }
    return summary


def _normalize_answer(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("=null", "=none")
    normalized = normalized.replace("fallback_reason=;", "fallback_reason=none;")
    normalized = normalized.replace("fallback_reason= ", "fallback_reason=none ")
    if normalized.endswith("fallback_reason="):
        normalized = normalized[:-len("fallback_reason=")] + "fallback_reason=none"
    normalized = normalized.replace(": null", ": none")
    normalized = normalized.replace(", ", ",")
    normalized = " ".join(normalized.split())
    return normalized


def print_report(results: list[EvalRunResult]) -> None:
    print("| Case | Mode | Serialization | Success | Tool JSON chars | Terminal output chars | Terminal calls | Duration |")
    print("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
    for row in results:
        print(
            f"| `{row.case_id}` | `{row.mode}` | `{row.serialization_mode}` | {'yes' if row.success else 'no'} | "
            f"{row.total_tool_json_chars} | {row.total_terminal_output_chars} | "
            f"{row.terminal_call_count} | {row.duration_seconds:.2f}s |"
        )

    print("\nPer-run details:")
    for row in results:
        print(f"- `{row.case_id}` / `{row.mode}` / repeat `{row.repeat_index}`")
        if row.error:
            print(f"  error: {row.error}")
        print(f"  serialization_mode: {row.serialization_mode}")
        print(f"  answer: {row.answer or '(empty)'}")
        if row.missing_substrings:
            print(f"  missing: {', '.join(row.missing_substrings)}")

    aggregate = summarize(results)
    print("\nAggregate:")
    for mode, metrics in aggregate.items():
        print(
            f"- `{mode}`: success_rate={metrics['success_rate']:.2f}, "
            f"avg_tool_json_chars={metrics['avg_tool_json_chars']:.1f}±{metrics['stdev_tool_json_chars']:.1f}, "
            f"avg_terminal_output_chars={metrics['avg_terminal_output_chars']:.1f}±{metrics['stdev_terminal_output_chars']:.1f}, "
            f"avg_duration={metrics['avg_duration_seconds']:.2f}s±{metrics['stdev_duration_seconds']:.2f}s"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local llama.cpp evals for the terminal output interceptor.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--model", default="", help="Model ID exposed by the OpenAI-compatible endpoint. Auto-detected if omitted.")
    parser.add_argument("--suite", default="workspace", help="Case suite to run: workspace, fixtures, or all")
    parser.add_argument("--modes", default="off,summary,full,manifest", help="Comma-separated modes to run: off, summary, medium, full, manifest")
    parser.add_argument("--cases", default="all", help="Comma-separated case IDs or 'all'")
    parser.add_argument("--seed", type=int, default=7, help="Fixed request seed for deterministic runs when supported by the endpoint.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature for deterministic comparisons.")
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--repeats", type=int, default=1, help="Number of repeated runs per case/mode.")
    parser.add_argument("--report-file", default="", help="Optional path to write the JSON report.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = args.model or detect_model(args.base_url, args.api_key)
    selected_modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    selected_cases = {c.strip() for c in args.cases.split(",") if c.strip()} if args.cases != "all" else None

    all_cases: list[EvalCase] = []
    if args.suite in {"workspace", "all"}:
        all_cases.extend(WORKSPACE_CASES)
    if args.suite in {"fixtures", "all"}:
        all_cases.extend(load_fixture_eval_cases())

    cases = [case for case in all_cases if selected_cases is None or case.id in selected_cases]
    if not cases:
        raise SystemExit("No matching cases selected")

    results: list[EvalRunResult] = []
    for case in cases:
        modes_for_case = [
            mode for mode in selected_modes
            if (case.suite == "workspace" and mode != "manifest")
            or (case.suite == "fixture" and mode == "manifest")
        ]
        if not modes_for_case:
            continue
        for mode in modes_for_case:
            for repeat_index in range(1, args.repeats + 1):
                repeat_seed = None if args.seed is None else args.seed + (repeat_index - 1)
                results.append(
                    run_case(
                        case=case,
                        mode=mode,
                        repeat_index=repeat_index,
                        base_url=args.base_url,
                        api_key=args.api_key,
                        model=model,
                        seed=repeat_seed,
                        temperature=args.temperature,
                        max_iterations=args.max_iterations,
                        )
                )
    if not results:
        raise SystemExit("No compatible case/mode combinations selected")

    payload = {
        "model": model,
        "suite": args.suite,
        "seed": args.seed,
        "temperature": args.temperature,
        "repeats": args.repeats,
        "results": [
            {
                "case_id": r.case_id,
                "mode": r.mode,
                "repeat_index": r.repeat_index,
                "success": r.success,
                "duration_seconds": r.duration_seconds,
                "answer": r.answer,
                "matched_substrings": r.matched_substrings,
                "missing_substrings": r.missing_substrings,
                "total_tool_json_chars": r.total_tool_json_chars,
                "total_terminal_output_chars": r.total_terminal_output_chars,
                "terminal_call_count": r.terminal_call_count,
                "serialization_mode": r.serialization_mode,
                "error": r.error,
            }
            for r in results
        ],
        "aggregate": summarize(results),
    }
    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Model: {model}")
        print(f"Seed: {args.seed}")
        print(f"Temperature: {args.temperature}")
        print(f"Repeats: {args.repeats}")
        if args.report_file:
            print(f"Report file: {args.report_file}")
        print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
