# Prompt `run_dir` CLI Contract (v1)

## Purpose
Expose deterministic `run_dir` control in `prompt` mode so external evaluators can place all observer artifacts in run-scoped locations.

## Current Gap
- `UserPromptReceivedMessage` has `run_dir`.
- `prompt` CLI does not accept or set `run_dir`.
- Evaluator cannot enforce deterministic artifact paths.

## CLI Additions
- `--run-dir <path>`
  - Absolute path, or path relative to `--repo-root` (or resolved repo root).
- `--run-id <id>` (optional convenience)
  - Derives run dir as `<runs-root>/<run-id>`.
- `--runs-root <path>` (used with `--run-id`, default from policy/project config).

## Precedence
1. `--run-dir` (highest)
2. `--run-id` + `--runs-root`
3. unset (legacy behavior)

`--run-dir` and `--run-id` are mutually exclusive.

## Validation Rules
- Resolved `run_dir` is normalized absolute path.
- Directory is created if missing.
- If path exists and is a file, fail with usage/config error.
- Optional strict mode:
  - `--require-empty-run-dir` fails if directory contains files.

## Propagation Requirements
When resolved, set:
- `request.run_dir` in `UserPromptReceivedMessage`.
- `turn_request.run_dir` in LLM turns (already supported).
- Observer writes under:
  - `<run_dir>/observers/<request_id>/event_summary.json`
  - `<run_dir>/observers/<request_id>/event_trajectory.jsonl`
  - `<run_dir>/observers/<request_id>/llm_details.jsonl`
  - `<run_dir>/observers/latest_request_id.txt`

## Machine Output Requirement
When machine output is enabled, both start and finish records must include resolved `run_dir`.

## Compatibility
- If no new flags are used, behavior remains unchanged.
- Existing `--repo-root`, `--build-dir`, and experiment tags are unaffected.

## Acceptance Criteria
- Evaluator passes `--run-dir /abs/runs/<run_id>/<instance_id>` and gets all observer files there.
- Two parallel evaluator processes with distinct `run_dir` values never collide.

