# High-Priority Reliability Spec (H1-H2 Machine Handshake Edge Cases)

## Document Status
- Version: `v3`
- Scope: `cpp-code-agent prompt` machine handshake contract for external evaluators
- Audience: C++ CLI maintainers, observer maintainers, Python evaluator maintainers
- Supersedes: `v2` of this document

## Purpose
Define a strict, low-level contract so a black-box evaluator can always retrieve one terminal machine result (`prompt.run.finished`) for every non-crash process execution, including malformed CLI invocations and sink initialization failures.

## Out Of Scope
1. Prompt-loop business logic.
2. LLM/provider behavior.
3. Observer status taxonomy itself.

## Definitions
1. `machine contract`:
   evaluator expectation that process emits machine-readable terminal outcome.
2. `machine contract requested`:
   true when invocation contains any machine-related flag token, regardless of value validity.
3. `terminal machine row`:
   JSON object with `event="prompt.run.finished"` and schema `cpp_code_agent.prompt.v1`.
4. `sink`:
   target location used to write machine rows (file JSONL, result JSON, stderr JSONL).

---

## H1: Parse-Edge Handshake Loss For Path-Based Machine Flags

### Problem Statement
Some malformed invocations include machine flags but fail argument parsing before sink activation, resulting in no terminal machine row.

### Canonical Failure Examples
1. `prompt "x" --machine-output-path`
2. `prompt "x" --result-json-path`
3. `prompt "x" --machine-output-path --backend bedrock` (next token is another flag, so value is missing)

### Root Cause
Preflight currently uses successful value capture to infer machine activation. Presence-only flag intent is not preserved on missing-value parse errors.

### Detailed Fix Strategy
H1 fix requires separating two concerns that are currently coupled:
1. intent detection: "caller requested machine contract"
2. sink availability: "where machine rows can be written"

Machine contract intent must be preserved even when a value is missing or invalid.

### Normative Requirements (Detailed)
1. The parser MUST track machine intent at token level before argument validation returns.
2. Machine intent token set is fixed:
   - `--machine-output`
   - `--machine-output-path`
   - `--result-json-path`
3. `machine_contract_requested` MUST be `true` if any machine-intent token is present, regardless of:
   - missing value,
   - invalid value,
   - unsupported value,
   - early usage parse exit.
4. If `machine_contract_requested=true`, process MUST emit exactly one terminal machine row on every non-crash exit path.
5. For preflight parse failures:
   - `prompt.run.started` MAY be omitted.
   - `prompt.run.finished` MUST be emitted.
6. Missing-value parse errors for machine-intent flags MUST NOT disable terminal machine emission.
7. `prompt.run.finished` on parse failure MUST include at minimum:
   - `schema`
   - `event`
   - `request_id`
   - `exit_code`
   - `terminal_status`
   - `error_message`
8. Terminal row emission guarantee applies to:
   - usage errors,
   - invalid request id,
   - unsupported machine mode values,
   - malformed machine path flag value positioning.

### Parsing Contract (Detailed)
1. Machine intent detection MUST run on raw argv tokens.
2. Detection MUST NOT depend on value extraction success.
3. Value-missing rule for value-taking flags:
   - missing when flag is last token, or
   - missing when next token starts with `--`.
4. If value is missing:
   - parser returns usage error,
   - machine contract remains requested if flag is machine-intent flag.

### Required Preflight State Model
The preflight result object MUST expose these fields:
```text
PromptMachinePreflightOptions {
  bool saw_machine_output_flag;
  bool saw_machine_output_path_flag;
  bool saw_result_json_path_flag;
  bool machine_contract_requested;
  optional<path> machine_output_path;
  optional<path> result_json_path;
  optional<string> request_id_override;
  bool legacy_exit_codes;
}
```

Computation rule:
```text
machine_contract_requested =
  saw_machine_output_flag ||
  saw_machine_output_path_flag ||
  saw_result_json_path_flag
```

### Request ID Contract For H1
1. Resolve request id in this order:
   - valid `--request-id`,
   - generated default request id.
2. If provided request id is invalid:
   - process still returns usage error,
   - `prompt.run.finished.request_id` MUST be generated fallback id,
   - `error_message` MUST mention invalid request-id reason.

### Required Behavior Examples

1. Missing machine output path value
```bash
cpp-code-agent prompt "x" --machine-output-path
```
Expected:
1. usage-style non-zero exit.
2. one terminal machine row is emitted.
3. row has `terminal_status="usage_error"` and non-empty `request_id`.

2. Missing result-json path value
```bash
cpp-code-agent prompt "x" --result-json-path
```
Expected:
1. usage-style non-zero exit.
2. one terminal machine row is emitted.
3. row includes parse-related `error_message`.

3. Next token is another flag
```bash
cpp-code-agent prompt "x" --machine-output-path --backend bedrock
```
Expected:
1. machine-output-path value considered missing.
2. usage-style non-zero exit.
3. one terminal machine row emitted.

4. Invalid request id plus machine intent
```bash
cpp-code-agent prompt "x" --machine-output jsonl --request-id "BAD ID"
```
Expected:
1. usage-style non-zero exit.
2. one terminal machine row emitted.
3. row request id is generated fallback, not `"BAD ID"`.

### Expected Terminal Row Example (Parse Failure)
```json
{
  "schema": "cpp_code_agent.prompt.v1",
  "event": "prompt.run.finished",
  "request_id": "REQ-20260301T101500Z-a1b2c3",
  "exit_code": 10,
  "terminal_status": "usage_error",
  "terminal_retryable": false,
  "error_message": "--machine-output-path requires a value"
}
```

### Low-Level Implementation Tasks (H1)
1. Preflight scanner:
   - add explicit flag-presence booleans for all machine-intent tokens.
   - compute `machine_contract_requested` strictly from presence booleans.
2. Parser value validation:
   - apply shared missing-value predicate (`next exists` and `next is not flag`) for machine-intent value flags.
3. Emitter/driver integration:
   - pass `machine_contract_requested` into handshake emitter.
   - force terminal emission for parse exits when contract requested.
4. Error path audit:
   - ensure every parse/usage/invalid-request-id return path routes via common finish helper.
5. Test coverage:
   - unit + integration for missing-value, next-flag-token, unsupported mode, invalid request-id.

### Acceptance Criteria (H1)
1. Each canonical failure example emits exactly one terminal machine row.
2. Row is parseable JSON and contains non-empty `request_id`.
3. No non-crash parse path with machine-intent flag presence exits without terminal row.
4. Request-id fallback behavior is deterministic and test-covered.
5. Evaluator can bind process outcome without scraping human text.

---

## H2: Sink-Initialization Failure Leaves No Terminal Machine Row

### Problem Statement
When `--machine-output-path` initialization fails and `--result-json-path` is absent, process may return error without any machine-readable terminal result.

### Canonical Failure Classes
1. machine output path is directory.
2. parent directory cannot be created.
3. path stat fails.
4. append-open fails.
5. write append fails.

### Root Cause
Primary sink selection disables legacy stderr JSONL when path sink is chosen; if path sink is unusable and result JSON is absent, no fallback sink may remain.

### Normative Requirements
1. Terminal emission MUST use deterministic sink fallback chain:
   - Tier 1: `--machine-output-path` JSONL append.
   - Tier 2: `--result-json-path` final JSON object.
   - Tier 3: emergency stderr JSONL terminal row.
2. Tier traversal MUST be attempted in order for terminal row emission.
3. If Tier N fails, emission MUST continue to Tier N+1.
4. Non-crash process exit MUST still have one terminal row on at least one sink tier.
5. Terminal row emitted via fallback MUST carry warning fields:
   - `output_warning="machine_output_write_failed"`
   - `output_warning_code=<stable enum value>`
   - `output_warning_detail=<human detail>`
6. Exit code semantics MUST NOT change based on sink tier used.

### Required Warning Code Enum
- `machine_output_path_parent_create_failed`
- `machine_output_path_is_directory`
- `machine_output_path_stat_failed`
- `machine_output_path_open_failed`
- `machine_output_path_init_failed`
- `machine_output_path_write_failed`
- `machine_output_stderr_write_failed`
- `result_json_write_failed`
- `terminal_row_unavailable` (only if all tiers fail; should be extremely rare)

### Low-Level Implementation Tasks (H2)
1. Introduce sink abstraction with explicit capabilities:
   - `can_write_started`
   - `can_write_finished`
2. Implement `emit_finished_with_fallback(...)`:
   - tries Tier 1, then Tier 2, then Tier 3.
   - returns sink used + failure diagnostics.
3. Keep existing successful Tier-1 path behavior unchanged.
4. On preflight sink-init failure, still route through fallback emission chain.
5. Add tests for each failure class with:
   - no result-json path,
   - with result-json path.

### Acceptance Criteria (H2)
1. Every sink-init failure class yields one terminal machine row.
2. With `--result-json-path` present, row appears there if Tier 1 fails.
3. Without `--result-json-path`, emergency stderr JSON row is emitted if Tier 1 fails.
4. Warning fields are present and stable for automation.
5. Exit code and `terminal_status` are identical across sink-fallback scenarios.

---

## Shared Execution Contract (H1 + H2)
1. Machine contract requested implies exactly one terminal machine row per process (non-crash).
2. Terminal row identity invariants:
   - one invocation,
   - one resolved `request_id`,
   - one terminal machine row.
3. Evaluator MUST NOT need natural-language stderr scraping for terminal outcome.

## Reference Pseudocode
```text
scan_preflight(argv):
  detect_presence_flags()
  extract_optional_values_if_present()
  machine_contract_requested = saw_machine_output || saw_machine_output_path || saw_result_json_path

on_any_exit(non_crash):
  if !machine_contract_requested:
    return process_exit
  emit_finished_with_fallback(
    tier1=machine_output_path_jsonl,
    tier2=result_json_path_snapshot,
    tier3=stderr_jsonl_emergency
  )
  return process_exit
```

## Test Plan (Detailed)
1. Missing value:
   - `prompt "x" --machine-output-path`
   - expect usage exit + one finished row.
2. Missing value:
   - `prompt "x" --result-json-path`
   - expect usage exit + one finished row.
3. Missing value with next-flag token:
   - `prompt "x" --machine-output-path --backend bedrock`
   - expect usage exit + one finished row.
4. Path-is-directory failure without result-json:
   - expect repository/config exit + emergency stderr finished row.
5. Path-is-directory failure with result-json:
   - expect finished row in result-json + warning fields.
6. Parent-create failure without result-json:
   - expect emergency stderr finished row + warning code.
7. Append-write failure simulation:
   - expect fallback tier row + warning code.
8. Invalid request id + machine intent:
   - expect usage exit + fallback generated request id in finished row.
9. Normal success with valid machine-output-path:
   - expect started+finished in JSONL file, no emergency fallback.

## Rollout Sequence
1. Implement H1 intent-tracking.
2. Implement H2 fallback emission chain.
3. Add/adjust unit tests in prompt CLI handler tests.
4. Add integration tests for sink failure behavior.
5. Update `prompt_terminal_result_contract.md` to include fallback-tier semantics and warning code enum.
