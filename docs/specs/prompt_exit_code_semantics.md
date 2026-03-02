# Prompt Exit Code Semantics for Evaluator Automation (v1)

## Purpose
Define stable, machine-usable process exit codes for retry policy and failure analytics.

## Design Principles
- Exit codes classify failure domain, not detailed reason text.
- Detailed reason is carried by machine result JSON (`terminal_status`, `error_message`).
- Codes are stable across releases.

## Exit Code Table
- `0`: success
  - Prompt completed with terminal success contract.
- `10`: usage_error
  - Invalid CLI args, unknown flags, invalid combinations.
- `11`: config_error
  - Missing/invalid runtime config, unsupported backend selection.
- `12`: auth_error
  - Bedrock auth not configured or invalid credentials.
- `20`: repository_error
  - Invalid `repo_root`, missing directories, checkout/worktree preconditions failed.
- `30`: budget_exhausted
  - Max iterations/LLM calls/tool calls/wall-clock/no-progress limits reached.
- `31`: llm_runtime_error
  - Gateway construction failure, provider transport failure, request dispatch failure.
- `32`: orchestration_contract_error
  - Terminal contract violation, invariant violation, malformed internal envelope.
- `33`: patch_or_verification_error
  - Patch application/guardrail terminal failure or verification failure causing terminal stop.
- `50`: internal_error
  - Unhandled exception or unknown failure.

## Retry Guidance
- Retryable by default: `31`, `50`.
- Conditionally retryable: `30` (only if budgets are intentionally increased).
- Non-retryable: `10`, `11`, `12`, `20`, `32`, `33`.

## Mapping Requirement
Every non-zero exit code must map to:
- `terminal_status` (fine-grained enum, see observer taxonomy spec)
- `terminal_retryable` (boolean)
- `error_message` (human-readable short reason)

## Compatibility Strategy
- Introduce `--legacy-exit-codes` to preserve old behavior if needed.
- Default should migrate to v1 semantics.

## Acceptance Criteria
- Evaluator can implement retry policy from exit code alone.
- Evaluator can implement analytics from (`exit_code`, `terminal_status`) pair.

