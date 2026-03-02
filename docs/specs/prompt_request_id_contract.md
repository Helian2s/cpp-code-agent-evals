# Prompt `request_id` Contract (v1)

## Purpose
Define a machine-safe identifier contract so an external evaluator can reliably bind one `cpp-code-agent prompt` process run to one request identity and its artifacts.

## Identifier Model
- `request_id`
  - Session-scoped ID for one prompt invocation.
  - Constant for all LLM turns/tool calls within that prompt run.
- `correlation_id`
  - Turn/tool-scoped ID.
  - Changes across LLM turns and tool executions.
- `provider_request_id` (optional)
  - Upstream LLM provider request ID (for diagnostics only).
  - Never used as primary evaluator key.

## Current Behavior Baseline
- `request_id` is generated once per prompt process run when not supplied.
- `correlation_id` is generated per LLM turn.

## Required CLI Contract
- Add `--request-id <id>` to `prompt`.
  - If provided, agent must use it as the exact session `request_id`.
  - If omitted, agent auto-generates one.
- Add `--print-request-id` (optional convenience).
  - Prints only resolved `request_id` and exits `0`.

## Validation Rules
- Allowed chars: `[A-Za-z0-9._:-]`
- Length: `1..128`
- Invalid value -> usage/config exit class (non-retryable).
- No silent normalization that changes semantic identity.

## Machine Handshake Requirement
When machine output mode is enabled, emit:
1. `prompt.run.started` with resolved `request_id` before heavy work.
2. `prompt.run.finished` with same `request_id` before process exit.

This handshake is the authoritative process-to-request binding.

## Artifact Binding Requirements
All per-request artifacts must include the same `request_id`:
- `event_summary.json` root `request_id`
- `event_trajectory.jsonl` entries `request_id`
- `llm_details.jsonl` entries `request_id`

If `run_dir` is provided, artifact paths are:
- `<run_dir>/observers/<request_id>/event_summary.json`
- `<run_dir>/observers/<request_id>/event_trajectory.jsonl`
- `<run_dir>/observers/<request_id>/llm_details.jsonl`

## Evaluator Mapping Contract
Evaluator should store:
- `external_invocation_id` (harness-generated, one per subprocess launch)
- `agent_request_id` (from `prompt.run.started`)

Mapping cardinality:
- one `external_invocation_id` -> one `agent_request_id`
- one `agent_request_id` -> one prompt process run

Retries must use a new `external_invocation_id` and should use a new `request_id` unless explicitly replaying.

## Failure Semantics
- If prompt fails after start handshake, `prompt.run.finished` still must be emitted with same `request_id`.
- If crash occurs before start handshake, evaluator marks run as `infra_error` (unbound process failure).

## Non-Goals
- `request_id` is not per-LLM-call.
- `latest_request_id.txt` is not a concurrency-safe primary binding mechanism.

## Acceptance Criteria
- Evaluator can deterministically bind logs/artifacts to one process run without scraping human text.
- Parallel runs never rely on global mutable files for request identity.

