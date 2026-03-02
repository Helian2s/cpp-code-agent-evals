# Observer `terminal_status` Taxonomy (v1)

## Purpose
Add explicit terminal status classification to `event_summary.json` so external evaluators do not infer outcome from ad-hoc fields.

## Required New Fields in `event_summary.json`
```json
{
  "terminal": {
    "status": "success",
    "category": "success",
    "retryable": false,
    "exit_code": 0,
    "session_status_code": 0,
    "reason_code": "final_answer_accepted",
    "reason_detail": "",
    "source_event": "final_report_ready"
  }
}
```

## `terminal.status` Enum
- `success`
- `budget_max_iterations`
- `budget_max_llm_calls`
- `budget_max_tool_calls`
- `budget_max_wall_clock`
- `no_progress_limit`
- `llm_request_failed`
- `verification_failed`
- `patch_apply_failed`
- `patch_guardrail_failed`
- `final_answer_rejected`
- `config_error`
- `auth_error`
- `repository_error`
- `internal_error`
- `unknown_failure`

## Derivation Rules
1. If final report is ok and session status is success: `success`.
2. Else if last terminal prompt-loop event is budget event:
   - `max_iterations_reached` -> `budget_max_iterations`
   - `max_llm_calls_reached` -> `budget_max_llm_calls`
   - `max_tool_calls_reached` -> `budget_max_tool_calls`
   - `max_wall_clock_reached` -> `budget_max_wall_clock`
3. Else if `no_progress_streak_limit_reached`: `no_progress_limit`.
4. Else if `llm_request_failed`: `llm_request_failed`.
5. Else if verification terminal fail is present: `verification_failed`.
6. Else if terminal patch apply/guardrail failure event present:
   - `patch_apply_failed` -> `patch_apply_failed`
   - guardrail-related terminal event -> `patch_guardrail_failed`
7. Else classify by process/domain code:
   - config/auth/repository/internal mappings.
8. Fallback: `unknown_failure`.

## `terminal.category` Enum
- `success`
- `budget`
- `llm`
- `verification`
- `patch`
- `config`
- `auth`
- `repository`
- `infra`
- `unknown`

## Retryability Rules
- `retryable=true` for transient infra/LLM classes (`llm_request_failed`, `internal_error`).
- `retryable=false` for deterministic config/repo/contract/verification failures.
- Budget classes are `false` unless evaluator explicitly changes budgets.

## Backfill Behavior
If older runs lack `terminal`, summarizer should:
- infer best-effort status from existing fields,
- mark `"terminal_inferred": true`,
- preserve original raw summary unchanged.

## Acceptance Criteria
- Evaluator can compute solved/failed and retryability from `event_summary.json` alone.
- No regex parsing of `report_text` is required.

