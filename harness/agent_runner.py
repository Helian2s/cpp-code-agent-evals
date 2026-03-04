from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import json
import shutil
import time
from pathlib import Path
from typing import Any

from harness.config import HarnessConfig
from harness.models import AgentRunResult, DatasetInstance, WorkspaceLayout
from harness.workspace import CommandTimeoutError, run_command


def _compose_prompt(instance: DatasetInstance) -> str:
    prompt = instance.problem_statement.strip()
    hints = instance.hints_text.strip()
    if hints:
        prompt = f"{prompt}\n\nHints:\n{hints}"
    return prompt


def _observer_root(repo_dir: Path) -> Path:
    return repo_dir / ".cpp-code-agent"


def _read_latest_request_id(repo_dir: Path) -> tuple[str, Path | None]:
    root = _observer_root(repo_dir)
    if not root.exists():
        return "", None
    candidates = sorted(
        root.rglob("latest_request_id.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        rid = path.read_text(encoding="utf-8", errors="ignore").strip()
        if rid:
            return rid, path
    return "", None


def _find_request_dir(repo_dir: Path, request_id: str, latest_marker: Path | None) -> Path | None:
    root = _observer_root(repo_dir)
    candidates: list[Path] = []
    if latest_marker is not None:
        # Expected location: <...>/observers/latest_request_id.txt -> <...>/observers/<request_id>/
        candidates.append(latest_marker.parent / request_id)
    if root.exists():
        for path in root.rglob(request_id):
            if path.is_dir():
                candidates.append(path)
    for path in candidates:
        if (path / "event_summary.json").exists() or (path / "event_trajectory.jsonl").exists():
            return path
    return None


def _recursive_find_int(data: Any, key: str) -> int | None:
    if isinstance(data, dict):
        if key in data and isinstance(data[key], int):
            return data[key]
        for value in data.values():
            found = _recursive_find_int(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _recursive_find_int(value, key)
            if found is not None:
                return found
    return None


def _copy_observer_artifacts(repo_dir: Path, artifact_dir: Path) -> tuple[str, dict[str, int], dict[str, Path | None]]:
    request_id, marker = _read_latest_request_id(repo_dir)
    counters: dict[str, int] = {}
    copied: dict[str, Path | None] = {
        "event_summary.json": None,
        "event_trajectory.jsonl": None,
        "llm_details.jsonl": None,
    }
    if not request_id:
        return "", counters, copied

    request_dir = _find_request_dir(repo_dir, request_id, marker)
    if request_dir is None:
        return request_id, counters, copied

    observer_out = artifact_dir / "observer"
    observer_out.mkdir(parents=True, exist_ok=True)

    for name in ("event_summary.json", "event_trajectory.jsonl", "llm_details.jsonl"):
        src = request_dir / name
        if not src.exists():
            # Some builds write llm_details alongside observers root.
            alt = request_dir.parent / name
            src = alt if alt.exists() else src
        if src.exists():
            dst = observer_out / name
            shutil.copy2(src, dst)
            copied[name] = dst

    summary_path = copied.get("event_summary.json")
    if summary_path and summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            for key in (
                "invalid_json_count",
                "repair_count",
                "out_of_range_read_count",
                "path_rewrite_count",
                "apply_patch_arg_mismatch_count",
            ):
                value = _recursive_find_int(summary, key)
                if value is not None:
                    counters[key] = value
        except Exception:
            pass

    return request_id, counters, copied


def run_agent(
    config: HarnessConfig,
    workspace: WorkspaceLayout,
    instance: DatasetInstance,
    *,
    run_id: str,
    timeout_sec: int,
    log_dir: Path,
    show_patch_only: bool | None = None,
) -> AgentRunResult:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "agent.stdout.log"
    stderr_path = log_dir / "agent.stderr.log"

    mode = config.agent.mode
    if mode != "prompt":
        raise ValueError(f"Unsupported agent mode: {mode}")

    prompt = _compose_prompt(instance)
    cmd = [
        str(config.agent.sut_binary),
        "prompt",
        prompt,
        "--repo-root",
        str(workspace.repo_dir),
        "--build-dir",
        str(workspace.build_dir),
        "--test-case-id",
        instance.instance_id,
        "--variant-id",
        run_id,
        "--campaign-id",
        config.agent.campaign_id,
    ]

    flag_patch_only = config.agent.show_patch_only if show_patch_only is None else show_patch_only
    if flag_patch_only:
        cmd.append("--show-patch-only")

    if config.agent.max_iterations is not None:
        cmd.extend(["--max-iterations", str(config.agent.max_iterations)])
    if config.agent.max_llm_calls is not None:
        cmd.extend(["--max-llm-calls", str(config.agent.max_llm_calls)])
    if config.agent.max_tool_calls is not None:
        cmd.extend(["--max-tool-calls", str(config.agent.max_tool_calls)])
    if config.agent.max_wall_clock_sec is not None:
        cmd.extend(["--max-wall-clock-sec", str(config.agent.max_wall_clock_sec)])
    if config.agent.extra_args:
        cmd.extend(config.agent.extra_args)

    start = time.monotonic()
    timed_out = False
    exit_code = -1

    try:
        heartbeat_sec = max(5, config.agent.progress_heartbeat_sec)
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                run_command,
                cmd,
                timeout_sec=timeout_sec,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                env={
                    # Keep agent artifacts local to this workspace for deterministic, isolated runs.
                    "CPP_CODE_AGENT_DATA_HOME": str(workspace.repo_dir),
                },
            )
            while True:
                try:
                    result = fut.result(timeout=heartbeat_sec)
                    break
                except FutureTimeoutError:
                    elapsed = time.monotonic() - start
                    print(
                        f"[{instance.instance_id}] agent running: {int(elapsed)}s elapsed",
                        flush=True,
                    )
        exit_code = result.exit_code
    except CommandTimeoutError:
        timed_out = True

    duration = time.monotonic() - start

    request_id, counters, copied = _copy_observer_artifacts(workspace.repo_dir, workspace.instance_dir)

    return AgentRunResult(
        exit_code=exit_code,
        duration_sec=duration,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        request_id=request_id,
        timed_out=timed_out,
        observer_summary_path=copied.get("event_summary.json"),
        observer_trajectory_path=copied.get("event_trajectory.jsonl"),
        llm_details_path=copied.get("llm_details.jsonl"),
        observer_counters=counters,
    )
