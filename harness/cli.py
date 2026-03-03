from __future__ import annotations

import argparse
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

from harness.agent_runner import run_agent
from harness.config import DEFAULT_CONFIG_PATH, HarnessConfig, load_config
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


def _bedrock_auth_signals() -> list[str]:
    signals: list[str] = []
    if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        signals.append("env:AWS_BEARER_TOKEN_BEDROCK")
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        signals.append("env:AWS_ACCESS_KEY_ID")
    if os.environ.get("AWS_PROFILE"):
        signals.append("env:AWS_PROFILE")
    if os.environ.get("AWS_REGION"):
        signals.append("env:AWS_REGION")
    if os.environ.get("AWS_DEFAULT_REGION"):
        signals.append("env:AWS_DEFAULT_REGION")

    aws_dir = Path.home() / ".aws"
    if (aws_dir / "credentials").exists():
        signals.append("file:~/.aws/credentials")
    if (aws_dir / "config").exists():
        signals.append("file:~/.aws/config")
    return signals


def cmd_preflight(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    ok = True

    def add_check(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        checks.append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            ok = False

    sut = config.agent.sut_binary
    sut_exists = sut.exists()
    sut_executable = os.access(sut, os.X_OK) if sut_exists else False
    add_check(
        "sut_binary",
        sut_exists and sut_executable,
        f"path={sut} exists={sut_exists} executable={sut_executable}",
    )

    index_path = config.dataset_dir / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            instances = index.get("instances", [])
            count = len(instances) if isinstance(instances, list) else 0
            expected = args.expect_instances
            if expected is None:
                add_check("dataset_index", count > 0, f"path={index_path} instances={count}")
            else:
                add_check(
                    "dataset_index",
                    count == expected,
                    f"path={index_path} instances={count} expected={expected}",
                )
        except Exception as exc:
            add_check("dataset_index", False, f"path={index_path} parse_error={exc}")
    else:
        add_check("dataset_index", False, f"path={index_path} missing")

    for repo_name, repo_path in sorted(config.repo_sources.items()):
        exists = repo_path.exists()
        has_git = (repo_path / ".git").exists() if exists else False
        add_check(
            f"repo_source:{repo_name}",
            exists and has_git,
            f"path={repo_path} exists={exists} has_git={has_git}",
        )

    try:
        config.runs_dir.mkdir(parents=True, exist_ok=True)
        writable = os.access(config.runs_dir, os.W_OK)
        add_check("runs_dir", writable, f"path={config.runs_dir} writable={writable}")
    except Exception as exc:
        add_check("runs_dir", False, f"path={config.runs_dir} create_error={exc}")

    auth_signals = _bedrock_auth_signals()
    auth_ok = len(auth_signals) > 0
    if args.require_bedrock_auth:
        add_check(
            "bedrock_auth",
            auth_ok,
            "signals=" + (", ".join(auth_signals) if auth_signals else "none"),
        )
    else:
        add_check(
            "bedrock_auth",
            True,
            "signals=" + (", ".join(auth_signals) if auth_signals else "none (soft check)"),
        )
        if not auth_ok:
            warnings.append(
                "No Bedrock credential/profile signal was detected; prompt runs may fail with auth_error."
            )

    output = {
        "ok": ok,
        "config_path": str((Path(args.config).resolve() if args.config else DEFAULT_CONFIG_PATH.resolve())),
        "checks": checks,
        "warnings": warnings,
    }
    print(json.dumps(output, indent=2))
    return 0 if ok else 2


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

    p_preflight = sub.add_parser("preflight", help="Validate local prerequisites before run")
    p_preflight.add_argument("--expect-instances", type=int, default=None)
    p_preflight.add_argument("--require-bedrock-auth", action="store_true")
    p_preflight.set_defaults(func=cmd_preflight)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
