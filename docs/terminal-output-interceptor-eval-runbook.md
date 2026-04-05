# Terminal output interceptor eval runbook

This runbook explains how to run the current terminal output interceptor
benchmark and local-model eval, and which artifacts to share back when you are
testing the feature from a fork.

> **Note:** This is a preview workflow currently under active development.

## What this covers

Use this runbook if you want to do one or both of these tasks:

- measure payload reduction and capture-policy behavior on the committed
  fixture corpus
- compare task quality across `off`, `summary`, and `full` on the workspace
  eval corpus

The current benchmark and eval surface focuses on:

- `git status`
- `git diff`
- `pytest`

## Prerequisites

Before you run the benchmark or eval, make sure your environment is ready.

1. Activate the project virtual environment.

```bash
source venv/bin/activate
```

2. If you want to run the local-model eval, make sure you have an
   OpenAI-compatible endpoint running and reachable.

The current defaults are:

- base URL: `http://127.0.0.1:8080/v1`
- API key: `local`

3. Make sure your branch includes the current interceptor benchmark and eval
   tooling:

- `scripts/output_interceptor_bench.py`
- `scripts/output_interceptor_llm_eval.py`

## Run the benchmark

Use the fixture benchmark to measure payload compression, fallback behavior,
capture policy, and chart generation.

Run the benchmark as JSON:

```bash
source venv/bin/activate
python scripts/output_interceptor_bench.py --json
```

If you want a chart bundle and HTML report, run:

```bash
source venv/bin/activate
python scripts/output_interceptor_bench.py \
  --chart-dir /tmp/output-interceptor-bench-report
```

This writes:

- `benchmark_report.html`
- `benchmark_summary.md` if you also pass `--eval-json`
- `reduction_by_fixture.png`
- `latency_vs_reduction.png`
- `breakdowns.png`
- `capture_policy.png`
- `charts_manifest.json`

## Run the workspace eval

Use the workspace eval to compare task quality across raw-like and summarized
paths on the current synthetic workspace corpus.

Run the workspace eval as JSON:

```bash
source venv/bin/activate
python scripts/output_interceptor_llm_eval.py \
  --suite workspace \
  --modes off,summary,full \
  --temperature 0.0 \
  --seed 7 \
  --json
```

If you want to save the JSON to a file:

```bash
source venv/bin/activate
python scripts/output_interceptor_llm_eval.py \
  --suite workspace \
  --modes off,summary,full \
  --temperature 0.0 \
  --seed 7 \
  --json \
  > /tmp/output-interceptor-llm-eval-workspace.json
```

If you want to time the whole run:

```bash
source venv/bin/activate
/usr/bin/time -p \
  python scripts/output_interceptor_llm_eval.py \
    --suite workspace \
    --modes off,summary,full \
    --temperature 0.0 \
    --seed 7 \
    --json \
    > /tmp/output-interceptor-llm-eval-workspace.json
```

The current workspace eval compares:

- `off`: interceptor disabled
- `summary`: default summarized derived path
- `full`: raw-output comparison/debug baseline with the interceptor enabled

## Run the fixture-backed eval

Use the fixture-backed eval if you want tighter output control than the
workspace cases provide.

Run:

```bash
source venv/bin/activate
python scripts/output_interceptor_llm_eval.py \
  --suite fixtures \
  --modes manifest \
  --temperature 0.0 \
  --seed 7 \
  --json \
  > /tmp/output-interceptor-llm-eval-fixtures.json
```

`manifest` mode uses the fixture-defined verbosity for each replayed case.

## Generate a combined benchmark and eval report

If you already have a saved eval JSON file, you can merge it into the benchmark
report so the HTML and markdown summary include the current task-quality
assessment.

Example:

```bash
source venv/bin/activate
python scripts/output_interceptor_bench.py \
  --chart-dir /tmp/output-interceptor-final-report \
  --eval-json /tmp/output-interceptor-llm-eval-workspace.json
```

This produces a combined report bundle in the output directory, including:

- `benchmark_report.html`
- `benchmark_summary.md`
- chart bundle files

If the eval data supports it, the generated report and summary will say:

- `Task-quality parity achieved on this eval run.`

That wording is generated from the supplied eval JSON. It is not hardcoded.

## What to share back

If you are helping evaluate the feature from a fork, share enough information
to make your run reproducible.

Include:

- commit SHA
- model name
- base URL type or backend used for the model endpoint
- exact command lines you ran
- whether you ran workspace eval, fixture eval, or both
- total wall-clock time if you measured it

Attach or link these artifacts when possible:

- benchmark JSON output
- eval JSON output
- `benchmark_report.html`
- `benchmark_summary.md`
- at least the payload-reduction chart and capture-policy chart
