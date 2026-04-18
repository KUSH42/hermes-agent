# Tool Output Streamline — Implementation Spec

## §8.7 execute_streaming (Subprocess Reader Thread)

### 1. Overview

`execute_streaming()` enables incremental delivery of subprocess output to the
TUI while a foreground terminal command is running. Without it, `terminal_tool`
blocks until the subprocess exits, then emits all output at once. With it, each
line is delivered to an `on_line` callback as soon as the subprocess writes it,
allowing `StreamingToolBlock` to update in real time.

**Files changed:**

| File | Role |
|------|------|
| `tools/environments/base.py` | Adds `execute_streaming()` with blocking fallback |
| `tools/environments/local.py` | Overrides with Popen + reader thread |
| `tools/terminal_tool.py` | ContextVar callback API; foreground routing |
| `cli.py` | Sets/resets callback around each tool invocation |
| `tests/environments/test_execute_streaming.py` | Unit + timing tests |

---

### 2. Interface Contract

#### 2.1 `BaseEnvironment.execute_streaming()`

```python
def execute_streaming(
    self,
    command: str,
    cwd: str = "",
    *,
    timeout: int | None = None,
    on_line: "Callable[[str], None] | None" = None,
) -> dict:
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `command` | `str` | — | Shell command string (passed through `_prepare_command()` before execution) |
| `cwd` | `str` | `""` | Override working directory; falls back to `self.cwd` |
| `timeout` | `int \| None` | `None` | Max seconds; falls back to `self.timeout` |
| `on_line` | `Callable[[str], None] \| None` | `None` | Called once per output line (newline stripped). Optional — if omitted, output is still collected and returned normally |

**Return value:** `{"output": str, "returncode": int}` — identical shape to
`execute()`. `output` contains the full stdout+stderr text (with marker lines
stripped by `_update_cwd`). `returncode` is the subprocess exit code, or:

- `130` on interrupt (`is_interrupted()` returned True)
- `124` on timeout expiry

**Threading contract:** `on_line` is called from the reader thread (in
`LocalEnvironment`). The callback must be thread-safe. For TUI use, the
canonical pattern is:

```python
lambda line: app.call_from_thread(app.append_streaming_line, tool_call_id, line)
```

**Fallback behaviour (base class):** The default implementation on
`BaseEnvironment` calls `execute()` (blocking), then iterates the output with
`str.splitlines()` and calls `on_line(line)` for each line after the command
completes. This gives non-real-time streaming for SDK-backed environments
(Modal, Daytona, SSH) without requiring them to override the method.

```python
# base.py — fallback
def execute_streaming(self, command, cwd="", *, timeout=None, on_line=None):
    result = self.execute(command, cwd=cwd, timeout=timeout)
    if on_line:
        for line in result.get("output", "").splitlines():
            on_line(line)
    return result
```

---

#### 2.2 `LocalEnvironment.execute_streaming()` — Reader Thread Path

`LocalEnvironment` overrides `execute_streaming()` with a real-time reader
thread. The overall structure:

```
MainThread                          ReaderThread
───────────────────────────────     ───────────────────────────────
_before_execute()
_prepare_command(command)           (not started yet)
_wrap_command(exec_cmd, cwd)
_run_bash(wrapped, ...)  ──────────►  proc created (OS fork)
start reader thread  ──────────────► for raw_line in proc.stdout:
                                         output_chunks.append(raw_line)
poll loop (50ms tick):                   if on_line:
  is_interrupted()? → kill              on_line(raw_line.rstrip("\n"))
  deadline expired? → kill
  proc.poll() != None → break
reader.join(timeout=5)
proc.stdout.close()
_update_cwd(result)
return {"output": ..., "returncode": ...}
```

**Step-by-step:**

1. **`_before_execute()`** — increments call counter, initialises snapshot if
   this is the first call.

2. **`_prepare_command(command)`** — transforms `sudo` invocations (adds `-S -p
   ''`); returns `(exec_command, sudo_stdin)`.

3. **Heredoc embedding** — if `sudo_stdin is not None and self._stdin_mode ==
   "heredoc"`, embed password as heredoc and set `sudo_stdin = None` (SSH/cloud
   backends; unnecessary for local but handled for subclass correctness).

4. **`_wrap_command(exec_command, effective_cwd)`** — wraps in a bash script
   that sources the snapshot env file, sets CWD, emits the CWD marker after
   completion. This is the script actually executed.

5. **`_run_bash(wrapped, login=login, timeout=..., stdin_data=sudo_stdin)`** —
   returns a `subprocess.Popen` with `stdout=PIPE`, `stderr=STDOUT`,
   `text=True`, `preexec_fn=os.setsid` (Unix).

6. **Reader thread** — started immediately after Popen. Iterates
   `proc.stdout` line by line (blocks on each `readline()`). Each line:
   - Appended to `output_chunks` (for `result["output"]`)
   - Passed to `on_line(raw_line.rstrip("\n"))` if `on_line` is not None

7. **Poll loop (main thread)** — sleeps 50 ms per tick:
   - `is_interrupted()` → `_kill_process(proc)`, `reader.join(timeout=2)`, return
     `{"output": partial + "\n[Command interrupted]", "returncode": 130}`
   - `time.monotonic() > deadline` → same kill sequence, return
     `{"output": partial + f"\n[Command timed out after {N}s]", "returncode": 124}`
   - `proc.poll() is not None` → break

8. **Drain** — `reader.join(timeout=5)` ensures all buffered stdout lines are
   consumed before we finalise.

9. **Result** — `{"output": "".join(output_chunks), "returncode": proc.wait()}`.
   `_update_cwd(result)` strips CWD marker and updates `self.cwd`.

**`_kill_process()` (Unix):**

```python
def _kill_process(self, proc):
    pgid = os.getpgid(proc.pid)
    os.killpg(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        os.killpg(pgid, signal.SIGKILL)
```

Process group kill ensures child processes spawned by the command (e.g. shell
pipelines) are also terminated.

---

### 3. Streaming Callback API in `terminal_tool.py`

The TUI cannot pass a callback directly into `terminal_tool()` (it is invoked
by the agent SDK, not called directly). Instead, `terminal_tool.py` exposes a
ContextVar-based API:

```python
# tools/terminal_tool.py

_streaming_line_callback: contextvars.ContextVar[
    "Callable[[str], None] | None"
] = contextvars.ContextVar("terminal_streaming_line_callback", default=None)

def set_streaming_callback(cb) -> contextvars.Token:
    return _streaming_line_callback.set(cb)

def reset_streaming_callback(token: contextvars.Token) -> None:
    _streaming_line_callback.reset(token)
```

`ContextVar` is used (not a module-level global) so that concurrent tool calls
on different threads get independent callbacks, which is critical for multi-
tool parallelism.

---

### 4. Foreground Routing in `terminal_tool()`

Inside the foreground execution block (i.e., `background=False`), the routing
decision:

```python
_on_line = _streaming_line_callback.get(None)
_use_streaming = (
    _on_line is not None
    and env_type == "local"
    and hasattr(env, "execute_streaming")
)

if _use_streaming:
    result = env.execute_streaming(command, **execute_kwargs, on_line=_on_line)
else:
    result = env.execute(command, **execute_kwargs)
```

**Guard conditions:**

| Condition | Reason |
|-----------|--------|
| `_on_line is not None` | No callback registered → fall through to blocking `execute()` |
| `env_type == "local"` | Only `LocalEnvironment` has real streaming; SDK envs use fallback which is non-real-time anyway |
| `hasattr(env, "execute_streaming")` | Forward-compat guard: safe if method absent on an older backend |

Background commands (`background=True`) bypass this path entirely and go
through `process_registry.spawn_*()`.

---

### 5. CLI Integration (`cli.py`)

`cli.py` sets the callback before a tool invocation and resets it after:

```python
from tools.terminal_tool import set_streaming_callback, reset_streaming_callback

# Before tool call (in _on_tool_start or equivalent):
token = set_streaming_callback(
    lambda line, _tid=tool_call_id: tui.call_from_thread(
        tui.append_streaming_line, _tid, line
    )
)
self._stream_callback_tokens[tool_call_id] = token

# After tool call completes (in _on_tool_complete):
token = self._stream_callback_tokens.pop(tool_call_id, None)
if token is not None:
    reset_streaming_callback(token)
```

The lambda captures `tool_call_id` to route lines to the correct
`StreamingToolBlock` in the TUI output pane. `call_from_thread` ensures the
DOM mutation happens on the Textual event loop, not the tool thread.

---

### 6. `ProcessHandle` Protocol

All backends must return an object satisfying:

```python
class ProcessHandle(Protocol):
    def poll(self) -> int | None: ...   # None = still running
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...

    @property
    def stdout(self) -> IO[str] | None: ...

    @property
    def returncode(self) -> int | None: ...
```

`subprocess.Popen` satisfies this natively. SDK backends (Modal, Daytona) use
`_ThreadedProcessHandle`, which wraps a blocking `exec_fn() -> (output_str,
exit_code)` in a daemon thread and exposes a pipe-based `stdout` so the same
reader-thread pattern works.

---

### 7. Test Requirements

**File:** `tests/environments/test_execute_streaming.py`

#### Group A — BaseEnvironment fallback

| ID | Name | What it asserts |
|----|------|-----------------|
| A1 | `test_fallback_calls_on_line_for_each_output_line` | `on_line` called once per `splitlines()` entry |
| A2 | `test_fallback_returns_execute_result` | Return value is the `execute()` dict unchanged |
| A3 | `test_fallback_no_on_line_noop` | `on_line=None` does not raise |

#### Group B — LocalEnvironment real streaming

| ID | Name | What it asserts |
|----|------|-----------------|
| B1 | `test_basic_echo` | Single-line echo delivers the line; `returncode == 0` |
| B2 | `test_multiline_output` | `printf 'a\nb\nc\n'` delivers all three lines |
| B3 | `test_incremental_timing` | `echo first; sleep 0.5; echo second` — "first" arrives at t < 0.3s before command end |
| B4 | `test_no_on_line_still_returns_output` | Without callback, `result["output"]` is still populated |
| B5 | `test_output_in_result_matches_on_line_calls` | `result["output"]` and aggregated `on_line` lines contain the same content |

#### Group C — ContextVar callback API

| ID | Name | What it asserts |
|----|------|-----------------|
| C1 | `test_set_and_get` | `set_streaming_callback` stores cb; `reset_streaming_callback` restores `None` |
| C2 | `test_reset_restores_previous` | Nested set/reset restores the outer callback |
| C3 | `test_independent_per_thread` | ContextVar does not leak across thread boundaries |

**Timing tolerance for B3:** The `echo first; sleep 0.5; echo second` pattern
is used rather than `sleep 1` to keep the test under 2 s in CI. The assertion
is `first_ts - t0 < total_elapsed - 0.2`, which passes as long as "first"
arrives at least 200 ms before the command exits. This is conservative; in
practice the gap is ≥ 450 ms.

**Skip guard:** All Group B tests call `_make_local_env()` which wraps
`LocalEnvironment()` in a `pytest.skip` if the constructor raises (e.g., no
bash in PATH, CI container without subprocess).

---

### 8. Edge Cases and Invariants

**Empty output:** `on_line` is never called; `result["output"]` is `""`;
`returncode` reflects the exit code normally.

**Output without trailing newline:** The final incomplete line is still flushed
when the process exits because `proc.stdout` exhausts when the FD closes.
`raw_line.rstrip("\n")` strips any partial newline.

**Non-zero exit code:** `on_line` receives all output lines regardless of exit
code. Callers must check `result["returncode"]`.

**Exception in `on_line`:** Currently propagates and kills the reader thread
silently (exception in daemon thread is logged but not re-raised). The main
poll loop will still join and return a result, but some lines may be lost. The
TUI `call_from_thread` wrapper does not raise on the reader thread.

**`on_line` called from reader thread:** Never call Textual DOM methods
directly from `on_line`. Always use `app.call_from_thread(...)`.

**SDK backends (Modal, Daytona, SSH):** These inherit the fallback from
`BaseEnvironment`. The `env_type == "local"` gate in `terminal_tool()` prevents
them from being routed to `execute_streaming()` even if they inherit it.
Post-hoc emission still gives some UX benefit (bulk flush at end rather than
a single large blob, since `StreamingToolBlock` can still show lines
progressively in the UI if the backend is fast).

**Interrupt during streaming:** `is_interrupted()` is checked every 50 ms.
When set, `_kill_process` sends SIGTERM to the entire process group, giving
child processes a chance to clean up before SIGKILL. The partial output
collected so far is returned with `returncode=130`.

**Timeout during streaming:** Same kill sequence. `returncode=124` (matching
`timeout(1)` POSIX convention). The timeout notice is appended to `output` so
it appears in the `StreamingToolBlock` body.

---

### 9. Non-Goals

- Streaming for background processes (use `process_registry` poll path).
- PTY allocation (separate `pty=True` flag in `terminal_tool()`).
- Streaming for SSH/Modal/Daytona environments (requires backend-specific
  async or chunked output APIs; deferred).
- Cancellation from within `on_line` (no cancel token; interrupt via
  `tools.interrupt.set_interrupted()`).
