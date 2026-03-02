# Prompt Machine-Readable Terminal Result Contract (v1)

## Purpose
Define a stable, machine-readable terminal contract for `cpp-code-agent prompt` so an external evaluator can parse one authoritative final outcome without scraping human text.

## Scope
- Applies to `cpp-code-agent prompt ...`.
- Backward compatible: human output remains default behavior.
- Enabled only when machine output is requested.

## CLI Additions
- `--machine-output jsonl`
  - Enables JSONL event stream on `stderr`.
- `--result-json-path <path>`
  - Writes final terminal object as JSON file.
  - Parent directories are created.
- `--no-human-output` (optional)
  - Suppresses human-oriented report text on `stdout`.

## Required JSONL Events
When `--machine-output jsonl` is set, emit exactly:
1. `prompt.run.started` (once, after request envelope creation and before dispatch)
2. `prompt.run.finished` (once, immediately before process exit)

All events are single-line JSON objects.

### `prompt.run.started`
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.started",
  "ts": "2026-02-28T12:34:56Z",
  "pid": 12345,
  "request_id": "REQ-20260228T123456Z-ab12cd",
  "experiment": {
    "test_case_id": "fmtlib__fmt-2310",
    "variant_id": "run-001",
    "campaign_id": "swebench-cpp-12"
  },
  "repo_root": "/abs/path/repo",
  "build_dir": "/abs/path/build",
  "run_dir": "/abs/path/run_dir_or_empty"
}
```

### `prompt.run.finished`
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.finished",
  "ts": "2026-02-28T12:45:00Z",
  "pid": 12345,
  "request_id": "REQ-20260228T123456Z-ab12cd",
  "ok": false,
  "terminal_status": "verification_failed",
  "terminal_retryable": false,
  "exit_code": 34,
  "session_status_code": 1,
  "error_message": "targeted tests failed",
  "verification": {
    "ran": true,
    "ok": false,
    "targeted_tests_attempted": true,
    "full_suite_attempted": false
  },
  "patch": {
    "has_diff": true,
    "changed_files_count": 2
  },
  "artifacts": {
    "event_summary": "/abs/.../event_summary.json",
    "event_trajectory": "/abs/.../event_trajectory.jsonl",
    "llm_details": "/abs/.../llm_details.jsonl"
  },
  "duration_ms": 603210
}
```

## Determinism Rules
- Exactly one `started` and one `finished` event per process.
- `request_id` must match across both events.
- `finished` event must be emitted even on failures (except hard crash before process control).

## Error Handling
- If JSONL emission fails, process still exits using normal prompt exit code.
- `prompt.run.finished` should include `"output_warning": "machine_output_write_failed"` when partial writes occur.

## Acceptance Criteria
- Evaluator can parse `request_id`, `terminal_status`, `exit_code`, and artifact paths from one JSON object.
- No dependence on natural-language report text.

