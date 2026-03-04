# cpp-code-agent external eval harness

This repository contains a black-box benchmark harness for evaluating:
- SUT binary: `/home/val/Documents/cpp-agent/cpp-code-agent/build-codex/cpp-code-agent`
- Dataset: `/home/val/Desktop/cpp_tasks_multilingual.zip`
- Source repos:
  - `fmtlib/fmt` from `/home/val/Documents/cpp-agent/fmt`
  - `nlohmann/json` from `/home/val/Documents/cpp-agent/json`

The harness does not modify `/home/val/Documents/cpp-agent/cpp-code-agent`.

## Layout

- `harness/` Python package for CLI, adapters, execution, scoring, and reporting
- `configs/default.yaml` default runtime config
- `scripts/run_one.sh` one-instance wrapper
- `scripts/run_all.sh` full benchmark wrapper
- `data/dataset/` normalized imported task data
- `runs/<run_id>/` workspaces, per-instance artifacts, and summaries

## Quickstart

1. Create/activate a Python 3.10+ environment.
2. Install this package in editable mode:

```bash
python3 -m pip install -e .
```

3. Import dataset:

```bash
python3 -m harness.cli import-dataset --zip /home/val/Desktop/cpp_tasks_multilingual.zip
```

4. List instances:

```bash
python3 -m harness.cli list
```

## CLI

```bash
python3 -m harness.cli import-dataset --zip <zip_path>
python3 -m harness.cli list
python3 -m harness.cli preflight [--expect-instances 12] [--require-bedrock-auth]
python3 -m harness.cli run --instance <instance_id> --run-id <run_id> [--resume] [--show-patch-only]
python3 -m harness.cli run-all --run-id <run_id> [--max-parallel 1] [--resume] [--show-patch-only]
python3 -m harness.cli summarize --run-id <run_id>
```

## Reproduction commands

Dry-run `fmt` instance:

```bash
scripts/run_one.sh dryrun-fmt fmtlib__fmt-2310
```

Dry-run `nlohmann/json` instance:

```bash
scripts/run_one.sh dryrun-json nlohmann__json-4237
```

Run all 12 tasks (deterministic sequential mode):

```bash
scripts/run_all.sh sweep-12 --max-parallel 1
```

Resume a partially completed run:

```bash
scripts/run_all.sh sweep-12 --max-parallel 1 --resume
```

Regenerate reports:

```bash
python3 -m harness.cli summarize --run-id sweep-12
```

`scripts/run_one.sh` and `scripts/run_all.sh` now run a strict preflight check by default before execution:
- SUT binary present + executable
- dataset index present with expected task count
- source repo mappings present and git-initialized
- Bedrock auth/profile signal present

To bypass preflight intentionally, add `--skip-preflight` to the wrapper command.

## Artifacts

Per instance:
- `runs/<run_id>/instances/<instance_id>/result.json`
- `runs/<run_id>/instances/<instance_id>/observer/event_summary.json` (if available)
- `runs/<run_id>/instances/<instance_id>/observer/event_trajectory.jsonl` (if available)
- `runs/<run_id>/instances/<instance_id>/observer/llm_details.jsonl` (if available)
- `runs/<run_id>/instances/<instance_id>/attempts/attempt-*/` logs for checkout/build/agent/tests

Run-level:
- `runs/<run_id>/summary.json`
- `runs/<run_id>/summary.md`

## Success criteria implemented

An instance is marked `solved=true` when:
- all `FAIL_TO_PASS` tests pass,
- all `PASS_TO_PASS` tests pass,
- agent execution does not crash (`exit_code == 0`),
- post-agent build succeeds.

## Error taxonomy

- `checkout_failed`
- `baseline_build_failed`
- `agent_failed`
- `tests_failed`
- `infra_error`

A `result.json` is always written, even for failures.

## Determinism and resilience

- Per-instance isolated workspace: `runs/<run_id>/workspaces/<instance_id>/repo`
- Per-instance build dir is inside repo: `runs/<run_id>/workspaces/<instance_id>/repo/.harness-build`
- Fixed processing order in sequential runs
- Resume mode skips instances with valid `result.json`
- Configurable timeouts for checkout/build/agent/tests
- Prompt-loop guardrails enabled by default (`max_iterations`, `max_llm_calls`, `max_tool_calls`, `max_wall_clock_sec`)
- Live terminal progress:
  - stage updates (checkout/build/agent/tests),
  - periodic agent heartbeat while prompt execution is running
- Retry support via `configs/default.yaml` (`retry.max_attempts` + error-class allowlist)

## Configuration

Edit `configs/default.yaml` to override paths/timeouts/agent flags.

Key fields:
- `repo_sources`
- `agent.sut_binary`
- `agent.progress_heartbeat_sec`
- `agent.max_iterations`
- `agent.max_llm_calls`
- `agent.max_tool_calls`
- `agent.max_wall_clock_sec`
- `timeouts.*`
- `retry.max_attempts`
- `retry.retry_error_classes`

The file is JSON-compatible YAML for zero-dependency parsing.
