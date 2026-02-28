from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Mapping

from harness.models import CommandResult, DatasetInstance, WorkspaceLayout


class CommandTimeoutError(RuntimeError):
    pass


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_sec: int | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> CommandResult:
    stdout_handle = None
    stderr_handle = None
    start = time.monotonic()
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_handle = open(stdout_path, "w", encoding="utf-8")
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = open(stderr_path, "w", encoding="utf-8")

        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=dict(os.environ) | dict(env or {}),
            stdout=stdout_handle if stdout_handle else subprocess.PIPE,
            stderr=stderr_handle if stderr_handle else subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            duration_sec=time.monotonic() - start,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(f"Command timed out after {timeout_sec}s: {command}") from exc
    finally:
        if stdout_handle:
            stdout_handle.close()
        if stderr_handle:
            stderr_handle.close()


def create_workspace_layout(runs_dir: Path, run_id: str, instance_id: str) -> WorkspaceLayout:
    run_dir = runs_dir / run_id
    workspace_dir = run_dir / "workspaces" / instance_id
    repo_dir = workspace_dir / "repo"
    build_dir = workspace_dir / "build"
    instance_dir = run_dir / "instances" / instance_id
    attempts_dir = instance_dir / "attempts"
    instance_dir.mkdir(parents=True, exist_ok=True)
    attempts_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workspaces").mkdir(parents=True, exist_ok=True)
    return WorkspaceLayout(
        run_id=run_id,
        instance_id=instance_id,
        run_dir=run_dir,
        workspace_dir=workspace_dir,
        repo_dir=repo_dir,
        build_dir=build_dir,
        instance_dir=instance_dir,
        attempts_dir=attempts_dir,
    )


def materialize_workspace(
    layout: WorkspaceLayout,
    instance: DatasetInstance,
    source_repo: Path,
    *,
    timeout_sec: int,
    log_dir: Path,
) -> None:
    if layout.workspace_dir.exists():
        shutil.rmtree(layout.workspace_dir)
    layout.workspace_dir.mkdir(parents=True, exist_ok=True)

    clone_stdout = log_dir / "clone.stdout.log"
    clone_stderr = log_dir / "clone.stderr.log"
    checkout_stdout = log_dir / "checkout.stdout.log"
    checkout_stderr = log_dir / "checkout.stderr.log"

    clone = run_command(
        ["git", "clone", "--no-hardlinks", str(source_repo), str(layout.repo_dir)],
        timeout_sec=timeout_sec,
        stdout_path=clone_stdout,
        stderr_path=clone_stderr,
    )
    if clone.exit_code != 0:
        raise RuntimeError(f"git clone failed with exit code {clone.exit_code}")

    checkout = run_command(
        ["git", "checkout", "--detach", instance.base_commit],
        cwd=layout.repo_dir,
        timeout_sec=timeout_sec,
        stdout_path=checkout_stdout,
        stderr_path=checkout_stderr,
    )
    if checkout.exit_code != 0:
        raise RuntimeError(f"git checkout failed with exit code {checkout.exit_code}")



def collect_git_metadata(repo_dir: Path) -> dict[str, object]:
    changed_files: list[str] = []
    added = 0
    deleted = 0

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if rel.startswith(".cpp-code-agent/") or rel == ".cpp-code-agent":
            continue
        changed_files.append(rel)

    numstat = subprocess.run(
        ["git", "diff", "--numstat"],
        cwd=str(repo_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    for line in numstat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts
        if path.startswith(".cpp-code-agent/") or path == ".cpp-code-agent":
            continue
        if a.isdigit():
            added += int(a)
        if d.isdigit():
            deleted += int(d)

    return {
        "changed_files": sorted(changed_files),
        "patch_added_lines": added,
        "patch_deleted_lines": deleted,
        "patch_total_lines": added + deleted,
    }
