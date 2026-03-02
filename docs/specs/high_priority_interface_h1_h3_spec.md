# High-Priority Interface Remediation Spec (H1-H3)

## Document Status
- Version: `v1`
- Scope: `cpp-code-agent prompt` interface used by external evaluators
- Audience: C++ agent maintainers and Python harness maintainers

## Why This Spec Exists
This specification defines contract-level fixes for the first three High issues from the latest interface review:
1. Machine-output handshake is not guaranteed for some early/preflight failures.
2. Process exit semantics can diverge from observer `terminal.exit_code`.
3. `FinalReportReadyMessage` terminal contract fields exist but are not populated at source.

The goal is strict machine-safe interoperability for black-box evaluation.

---

## H1: Guaranteed Machine Handshake For All Non-Crash Outcomes

### Problem Statement
When `--machine-output jsonl` or `--result-json-path` is used, some failure paths return before a `prompt.run.started`/`prompt.run.finished` pair is emitted. This breaks evaluator assumptions about deterministic lifecycle records.

### Normative Requirements
1. If machine output is requested, the process MUST emit exactly one terminal machine record for every non-crash execution path.
2. If machine output is requested, the process SHOULD emit `prompt.run.started` and MUST emit `prompt.run.finished`.
3. For preflight failures that occur before full prompt setup:
   - `prompt.run.finished` MUST still be emitted.
   - `prompt.run.started` MUST be emitted when enough context is available; if not, `finished` alone is acceptable only for explicit usage-parse hard failures before request envelope creation.
4. `prompt.run.finished` MUST always include:
   - `schema`
   - `event`
   - `request_id`
   - `exit_code`
   - `terminal_status`
   - `terminal_retryable`
   - `error_message` (may be empty)
5. The machine emitter MUST be instantiated before config/backend/auth validation so these errors are covered.

### Request ID Rules For H1
1. Machine lifecycle rows MUST always carry a valid `request_id`.
2. Resolution order:
   - valid `--request-id` if provided,
   - otherwise generated default request id.
3. If user-provided `--request-id` is invalid:
   - CLI still returns usage error,
   - machine `finished` MUST be emitted with generated fallback request_id,
   - `error_message` MUST include invalid-request-id explanation.

### Required JSONL Rows

#### `prompt.run.started` (when available)
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.started",
  "ts": "2026-02-28T12:00:00Z",
  "pid": 12345,
  "request_id": "REQ-...",
  "repo_root": "/abs/repo",
  "build_dir": "/abs/build",
  "run_dir": "/abs/run_dir_or_empty"
}
```

#### `prompt.run.finished` (mandatory)
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.finished",
  "ts": "2026-02-28T12:00:01Z",
  "pid": 12345,
  "request_id": "REQ-...",
  "exit_code": 11,
  "terminal_status": "config_error",
  "terminal_retryable": false,
  "session_status_code": 2,
  "error_message": "bedrock config not found"
}
```

### Acceptance Criteria
1. Running with `--machine-output jsonl` produces a terminal machine record for:
   - invalid CLI argument,
   - invalid request id,
   - config resolution failure,
   - auth failure,
   - normal success.
2. Python harness can always parse a terminal record without scraping human text.

---

## H2: Single Source Of Truth For Exit Semantics Across CLI + Observer

### Problem Statement
The evaluator can see different exit meanings depending on source:
- subprocess return code,
- `prompt.run.finished.exit_code`,
- `event_summary.json` -> `terminal.exit_code`.

These values must be consistent for retry policies and leaderboard stability.

### Normative Requirements
1. Define one canonical terminal outcome object for each prompt run:
   - `terminal_status`
   - `terminal_retryable`
   - `process_exit_code`
   - `session_status_code`
   - `reason_code`
   - `reason_detail`
2. `process_exit_code` MUST be identical across:
   - process return code,
   - `prompt.run.finished.exit_code`,
   - observer `terminal.exit_code` in `event_summary.json`,
   - `FinalReportReadyMessage.exit_code`.
3. `session_status_code` MUST represent raw internal prompt runtime status and MUST NOT be overwritten by mapped exit code.
4. Legacy mode behavior (`--legacy-exit-codes`):
   - `process_exit_code` uses legacy value,
   - all channels still stay identical to that legacy value.
5. Non-legacy mode behavior:
   - use v1 mapped exit code taxonomy (`10/11/12/20/30/31/32/33/50`).

### Canonical Mapping (Non-Legacy)
- `success` -> `0`
- `usage_error` -> `10`
- `config_error` -> `11`
- `auth_error` -> `12`
- `repository_error` -> `20`
- budget statuses (`budget_*`, `no_progress_limit`) -> `30`
- `llm_request_failed` / provider-runtime failure -> `31`
- orchestration contract failure -> `32`
- verification/patch terminal failure -> `33`
- internal fallback -> `50`

### Acceptance Criteria
1. For each failure class, compare:
   - shell exit code,
   - machine-finished `exit_code`,
   - `event_summary.terminal.exit_code`,
   - final message `exit_code`.
   All MUST match.
2. Retry policies derived from any single source produce identical decision.

---

## H3: Populate Terminal Contract At Source (No Observer Guessing In Normal Flow)

### Problem Statement
`FinalReportReadyMessage` already has terminal fields, but producer paths can omit them, forcing observer inference. Inference should be a backfill mechanism only, not primary behavior.

### Normative Requirements
1. Every emitted `FinalReportReadyMessage` MUST populate:
   - `terminal_status`
   - `terminal_retryable`
   - `session_status_code`
   - `exit_code`
   - `error_message`
2. `terminal_status` MUST come from the same canonical classifier used by CLI exit mapping.
3. Observer must prefer source-provided terminal contract when present and valid.
4. `terminal_inferred` in `event_summary.json`:
   - MUST be `false` when source contract is present and valid.
   - MAY be `true` only for backfill/legacy runs or malformed payloads.
5. Optional extension (recommended):
   - add `reason_code`, `reason_detail`, `source_event` to `FinalReportReadyMessage` to eliminate duplicated inference logic in observer.

### Observer Rules Under H3
1. If `FinalReportReadyMessage.terminal_status` is valid enum:
   - use it directly.
   - use `terminal_retryable` directly.
   - copy `exit_code` and `session_status_code` directly.
2. Only if terminal fields are missing/invalid:
   - run inference logic,
   - set `terminal_inferred=true`.

### Backward Compatibility
1. Old binaries may still require inference; evaluator must tolerate `terminal_inferred=true`.
2. New binaries should converge toward `terminal_inferred=false` for normal executions.

### Acceptance Criteria
1. Success and all major fail classes produce `event_summary.terminal_inferred=false`.
2. `terminal.status` in observer summary equals `prompt.run.finished.terminal_status`.
3. No regex parsing of `final.report_text` is required in evaluator for new runs.

---

## Implementation Order (Recommended)
1. Introduce shared `PromptTerminalOutcome` builder (single source of truth).
2. Instantiate machine emitter at top-level `handle_llm` path.
3. Use shared outcome for:
   - process return value,
   - machine finished row,
   - `FinalReportReadyMessage`,
   - observer terminal summary.
4. Keep observer inference only as fallback.

---

## Evaluator Impact
After this spec is implemented, the Python evaluator can:
1. Treat machine `finished` record as authoritative per-process result.
2. Trust observer `terminal` section without custom heuristics.
3. Apply deterministic retry policy using stable status/exit contracts.

