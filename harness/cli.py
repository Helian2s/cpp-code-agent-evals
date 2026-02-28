from __future__ import annotations

import argparse
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

from harness.agent_runner import run_agent
from harness.config import HarnessConfig, load_config
from harness.dataset import import_dataset, list_instances, load_instance
from harness.models import InstanceAttempt, InstanceResult
from harness.reporting import summarize_run
from harness.scoring import build_bucket, is_solved, is_valid_result_file, read_instance_result, write_instance_result
from harness.test_runner import get_adapter, run_task_tests
from harness.workspace import CommandTimeoutError, collect_git_metadata, create_workspace_layout, materialize_workspace


def _resolve_config(path: str | None) -> HarnessConfig:
    return load_config(Path(path).resolve()) if path else load_config()


def _instance_result_path(config: HarnessConfig, run_id: str, instance_id: str) -> Path:
    return config.runs_dir / run_id / "instances" / instance_id / "result.json"


def _can_retry(error_class: str | None, config: HarnessConfig) -> bool:
    if error_class is None:
        return False
    return error_class in set(config.retry.retry_error_classes)


def run_instance_once(
    config: HarnessConfig,
    run_id: str,
    instance_id: str,
    *,
    resume: bool = False,
    show_patch_only: bool | None = None,
) -> dict:
    result_path = _instance_result_path(config, run_id, instance_id)
    if resume and is_valid_result_file(result_path):
        return read_instance_result(result_path)

    instance = load_instance(config.dataset_dir, instance_id)
    layout = create_workspace_layout(config.runs_dir, run_id, instance_id)

    attempts: list[InstanceAttempt] = []
    final_error: str | None = None
    final_request_id = ""
    final_build_before = False
    final_build_after = False
    final_fail_failed = list(instance.fail_to_pass)
    final_pass_failed = list(instance.pass_to_pass)
    final_metadata: dict[str, object] = {}

    run_started = monotonic()

    max_attempts = max(1, config.retry.max_attempts)
    for attempt_no in range(1, max_attempts + 1):
        attempt_start = monotonic()
        attempt_dir = layout.attempts_dir / f"attempt-{attempt_no}"
        attempt_dir.mkdir(parents=True, exist_ok=True)

        error_class: str | None = None
        solved = False
        request_id = ""
        build_ok_before = False
        build_ok_after = False
        fail_failed = list(instance.fail_to_pass)
        pass_failed = list(instance.pass_to_pass)
        metadata: dict[str, object] = {}

        try:
            source_repo = config.repo_sources.get(instance.repo)
            if source_repo is None:
                raise RuntimeError(f"No source repo mapping for {instance.repo}")

            materialize_workspace(
                layout,
                instance,
                source_repo,
                timeout_sec=config.timeouts.checkout_sec,
                log_dir=attempt_dir / "checkout",
            )

            adapter = get_adapter(instance.repo)

            baseline = adapter.prepare_build(
                layout,
                timeout_sec=config.timeouts.build_sec,
                build_jobs=config.build_jobs,
                log_dir=attempt_dir / "baseline_build",
            )
            build_ok_before = baseline.ok

            if not build_ok_before:
                error_class = "baseline_build_failed"
            else:
                agent = run_agent(
                    config,
                    layout,
                    instance,
                    run_id=run_id,
                    timeout_sec=config.timeouts.agent_sec,
                    log_dir=attempt_dir / "agent",
                    show_patch_only=show_patch_only,
                )
                request_id = agent.request_id
                metadata["observer_counters"] = agent.observer_counters
                metadata["agent_exit_code"] = agent.exit_code
                metadata["agent_timed_out"] = agent.timed_out

                if agent.timed_out or agent.exit_code != 0:
                    error_class = "agent_failed"

                post = adapter.prepare_build(
                    layout,
                    timeout_sec=config.timeouts.build_sec,
                    build_jobs=config.build_jobs,
                    log_dir=attempt_dir / "post_build",
                )
                build_ok_after = post.ok

                if not build_ok_after and error_class is None:
                    error_class = "tests_failed"

                if build_ok_after:
                    tests = run_task_tests(
                        adapter,
                        layout,
                        instance,
                        timeout_sec=config.timeouts.tests_sec,
                        log_dir=attempt_dir / "tests",
                    )
                    fail_failed = tests.fail_to_pass_failed
                    pass_failed = tests.pass_to_pass_failed
                    metadata["tests_used_fallback"] = tests.used_fallback
                    metadata["tests_fallback_reason"] = tests.fallback_reason

                    solved = is_solved(
                        build_ok_after=build_ok_after,
                        fail_to_pass_failed=fail_failed,
                        pass_to_pass_failed=pass_failed,
                        agent_exit_code=agent.exit_code,
                    )
                    if not solved and error_class is None:
                        error_class = "tests_failed"

                metadata.update(collect_git_metadata(layout.repo_dir))
        except CommandTimeoutError:
            error_class = "infra_error"
        except RuntimeError as exc:
            msg = str(exc)
            if "git clone failed" in msg or "git checkout failed" in msg:
                error_class = "checkout_failed"
            else:
                error_class = "infra_error"
            metadata["runtime_error"] = msg
        except Exception as exc:  # pragma: no cover - defensive.
            error_class = "infra_error"
            metadata["exception"] = str(exc)
            metadata["traceback"] = traceback.format_exc(limit=20)

        attempt_duration = monotonic() - attempt_start
        attempts.append(
            InstanceAttempt(
                attempt=attempt_no,
                error_class=error_class,
                solved=solved,
                duration_sec=attempt_duration,
            )
        )

        final_error = error_class
        final_request_id = request_id
        final_build_before = build_ok_before
        final_build_after = build_ok_after
        final_fail_failed = fail_failed
        final_pass_failed = pass_failed
        final_metadata = metadata

        if solved:
            final_error = None
            break
        if attempt_no < max_attempts and _can_retry(error_class, config):
            continue
        break

    total_duration = monotonic() - run_started

    result = InstanceResult(
        instance_id=instance.instance_id,
        repo=instance.repo,
        base_commit=instance.base_commit,
        solved=(final_error is None and len(final_fail_failed) == 0 and len(final_pass_failed) == 0),
        fail_to_pass=build_bucket(instance.fail_to_pass, final_fail_failed),
        pass_to_pass=build_bucket(instance.pass_to_pass, final_pass_failed),
        build_ok_before=final_build_before,
        build_ok_after=final_build_after,
        request_id=final_request_id,
        duration_sec=total_duration,
        error_class=final_error,
        attempt_count=len(attempts),
        attempts=attempts,
        metadata=final_metadata,
    )

    write_instance_result(result_path, result)
    return result.to_json()


def cmd_import_dataset(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    meta = import_dataset(Path(args.zip), config.dataset_dir)
    print(json.dumps(meta, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    instances = list_instances(config.dataset_dir)
    for item in instances:
        print(f"{item['instance_id']}\t{item['repo']}\t{item['base_commit']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    result = run_instance_once(
        config,
        args.run_id,
        args.instance,
        resume=args.resume,
        show_patch_only=args.show_patch_only,
    )
    run_dir = config.runs_dir / args.run_id
    summarize_run(run_dir, args.run_id)
    print(json.dumps(result, indent=2))
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    instances = [x["instance_id"] for x in list_instances(config.dataset_dir)]
    run_id = args.run_id
    max_parallel = args.max_parallel if args.max_parallel is not None else config.max_parallel

    results: list[dict] = []
    if max_parallel <= 1:
        for instance_id in instances:
            result = run_instance_once(
                config,
                run_id,
                instance_id,
                resume=args.resume,
                show_patch_only=args.show_patch_only,
            )
            print(f"{instance_id}: solved={result.get('solved')} error={result.get('error_class')}")
            results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {
                pool.submit(
                    run_instance_once,
                    config,
                    run_id,
                    instance_id,
                    resume=args.resume,
                    show_patch_only=args.show_patch_only,
                ): instance_id
                for instance_id in instances
            }
            for fut in as_completed(futures):
                iid = futures[fut]
                result = fut.result()
                print(f"{iid}: solved={result.get('solved')} error={result.get('error_class')}")
                results.append(result)

    run_dir = config.runs_dir / run_id
    summary = summarize_run(run_dir, run_id)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    run_dir = config.runs_dir / args.run_id
    summary = summarize_run(run_dir, args.run_id)
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="cpp-code-agent SWE-bench C++ harness")
    parser.add_argument("--config", default=None, help="Path to config YAML/JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import-dataset", help="Import dataset zip into normalized local storage")
    p_import.add_argument("--zip", required=True, help="Path to dataset zip")
    p_import.set_defaults(func=cmd_import_dataset)

    p_list = sub.add_parser("list", help="List imported instances")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="Run one instance")
    p_run.add_argument("--instance", required=True)
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--resume", action="store_true")
    p_run.add_argument("--show-patch-only", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_run_all = sub.add_parser("run-all", help="Run all instances")
    p_run_all.add_argument("--run-id", required=True)
    p_run_all.add_argument("--max-parallel", type=int, default=None)
    p_run_all.add_argument("--resume", action="store_true")
    p_run_all.add_argument("--show-patch-only", action="store_true")
    p_run_all.set_defaults(func=cmd_run_all)

    p_summarize = sub.add_parser("summarize", help="Build summary artifacts for run")
    p_summarize.add_argument("--run-id", required=True)
    p_summarize.set_defaults(func=cmd_summarize)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
