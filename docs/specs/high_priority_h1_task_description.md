# H1 Task Description: Parse-Edge Machine Handshake Reliability

## Context
This task implements the first High-priority interface fix for `cpp-code-agent prompt`:

`H1`: parse-edge handshake loss for path-based machine flags.

Current risk: malformed CLI invocations that include machine-intent flags can exit without emitting a terminal machine result (`prompt.run.finished`). This breaks black-box evaluator binding between one process run and one machine-readable terminal outcome.

## Objective
Guarantee that every non-crash process execution emits exactly one terminal machine row whenever machine contract intent is present in argv, including usage/parse failures.

## Scope
In scope:
1. Preflight argv token-presence tracking.
2. Machine contract intent derivation independent of value parsing success.
3. Forced terminal machine emission on parse/usage exits.
4. Request ID fallback resolution for parse errors.
5. Unit/integration test coverage for missing-value and next-flag edge cases.

Out of scope:
1. Sink fallback hierarchy details from H2.
2. Observer taxonomy redesign.
3. Prompt-loop runtime behavior.

## Normative Behavior
1. `machine_contract_requested` is `true` if any of these tokens are present in raw argv:
   - `--machine-output`
   - `--machine-output-path`
   - `--result-json-path`
2. Token presence must be recorded even when:
   - value is missing,
   - value is invalid,
   - parser exits with usage error.
3. If `machine_contract_requested=true`, process must emit exactly one `prompt.run.finished` row on every non-crash exit.
4. For preflight/parse failures:
   - `prompt.run.started` is optional.
   - `prompt.run.finished` is mandatory.
5. Parse-failure terminal row must include:
   - `schema`
   - `event`
   - `request_id`
   - `exit_code`
   - `terminal_status`
   - `error_message`

## Value-Missing Rule (Required)
For flags requiring a value (`--machine-output-path`, `--result-json-path`, `--request-id`):
1. value is missing if the flag is the final token, or
2. value is missing if next token begins with `--`.

## Request ID Resolution (H1)
1. Use valid `--request-id` when provided.
2. Otherwise generate fallback request id.
3. If provided request id is invalid or missing in parse-failure path, still emit `prompt.run.finished` with fallback request id.

## Implementation Tasks

### Task 1: Extend Preflight Option Model
Add explicit token-presence booleans and derived intent:
```text
saw_machine_output_flag
saw_machine_output_path_flag
saw_result_json_path_flag
machine_contract_requested
```

Acceptance:
1. `machine_contract_requested` depends only on token presence booleans.
2. It does not depend on successful value extraction.

### Task 2: Refactor Preflight Scanner to Two-Phase Logic
Phase A (scan): detect token presence.
Phase B (parse): validate/extract values.

Acceptance:
1. Presence flags are populated before any early parse return.
2. Missing-value detection uses the required rule (`last token` or `next starts with --`).

### Task 3: Force Terminal Emission on Parse/Usage Exits
Introduce emitter control for parse paths, for example:
```text
force_terminal_machine_row = machine_contract_requested
```
Route all parse/usage early returns through common finish helper when forced.

Acceptance:
1. No parse/usage non-crash return bypasses finish helper when `machine_contract_requested=true`.
2. Exactly one `prompt.run.finished` row is emitted.

### Task 4: Request ID Fallback in Parse-Failure Path
Ensure request-id resolution runs before terminal row emission in parse failure handling.

Acceptance:
1. Terminal row always has non-empty request id.
2. Invalid user request id never propagates as machine request id.

### Task 5: Standardize Parse-Failure Terminal Payload
For H1 paths, enforce payload minimum fields:
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.finished",
  "request_id": "REQ-...",
  "exit_code": 10,
  "terminal_status": "usage_error",
  "error_message": "--machine-output-path requires a value"
}
```

Acceptance:
1. Fields above are always present for H1 parse failures.
2. Payload is valid single-line JSON where machine output is enabled.

### Task 6: Test Coverage (Mandatory)
Add tests for at least these cases:
1. `prompt "x" --machine-output-path`
2. `prompt "x" --result-json-path`
3. `prompt "x" --machine-output-path --backend bedrock`
4. `prompt "x" --machine-output jsonl --request-id "BAD ID"`
5. control case: valid machine flags success path still emits started+finished.

Assertions per H1 failure case:
1. process exits non-zero (usage class).
2. exactly one terminal machine row exists.
3. terminal row has non-empty `request_id`.
4. `terminal_status` is deterministic (`usage_error`).

## Example Invocations and Expected Outcome

### Example A
```bash
cpp-code-agent prompt "x" --machine-output-path
```
Expected:
1. usage error exit.
2. one `prompt.run.finished` row emitted.
3. row contains parse-related `error_message`.

### Example B
```bash
cpp-code-agent prompt "x" --machine-output-path --backend bedrock
```
Expected:
1. missing path value is detected.
2. usage error exit.
3. one terminal machine row emitted.

### Example C
```bash
cpp-code-agent prompt "x" --machine-output jsonl --request-id "BAD ID"
```
Expected:
1. usage error exit.
2. one terminal machine row emitted.
3. `request_id` is generated fallback id.

## Definition of Done
1. All H1 tests pass.
2. Each canonical malformed invocation yields one terminal machine row.
3. No machine-intent parse path exits without machine-readable terminal result.
4. Request-id fallback is deterministic and verified by tests.
5. Interface docs updated to reflect token-presence intent semantics.

## Copy-Ready Engineering Ticket
```markdown
Title: H1 - Guarantee terminal machine row on parse-edge failures with machine-intent flags

Problem
Malformed prompt invocations that include machine-intent flags can fail parsing before sink activation, producing no `prompt.run.finished` record. This breaks evaluator run/result binding.

Goal
If machine-intent flags are present in argv, emit exactly one terminal machine row for every non-crash process exit, including usage/parse failures.

Implementation
1. Add preflight presence booleans for `--machine-output`, `--machine-output-path`, `--result-json-path`.
2. Derive `machine_contract_requested` from token presence only.
3. Apply missing-value rule: flag at end or next token starts with `--`.
4. Route all parse/usage exits through a common finish helper when `machine_contract_requested=true`.
5. Resolve fallback request id before emission when input request id is invalid/missing.
6. Ensure terminal parse-failure row includes: `schema`, `event`, `request_id`, `exit_code`, `terminal_status`, `error_message`.
7. Add tests for missing-value and next-flag permutations.

Acceptance Criteria
1. `prompt "x" --machine-output-path` -> one `prompt.run.finished` row.
2. `prompt "x" --result-json-path` -> one `prompt.run.finished` row.
3. `prompt "x" --machine-output-path --backend bedrock` -> one `prompt.run.finished` row.
4. `prompt "x" --machine-output jsonl --request-id "BAD ID"` -> one `prompt.run.finished` row with generated fallback request id.
5. No non-crash machine-intent parse path exits without terminal row.
```
