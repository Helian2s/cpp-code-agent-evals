from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.adapters.base import BaseRepoAdapter
from harness.adapters.fmt import FmtAdapter
from harness.adapters.nlohmann_json import NlohmannJsonAdapter
from harness.models import DatasetInstance, TargetTestRunResult, WorkspaceLayout


@dataclass(frozen=True)
class TestRunSummary:
    fail_to_pass_failed: list[str]
    pass_to_pass_failed: list[str]
    used_fallback: bool
    fallback_reason: str


def get_adapter(repo: str) -> BaseRepoAdapter:
    if repo == FmtAdapter.repo_name:
        return FmtAdapter()
    if repo == NlohmannJsonAdapter.repo_name:
        return NlohmannJsonAdapter()
    raise ValueError(f"Unsupported repo: {repo}")


def run_task_tests(
    adapter: BaseRepoAdapter,
    workspace: WorkspaceLayout,
    instance: DatasetInstance,
    *,
    timeout_sec: int,
    log_dir: Path,
) -> TestRunSummary:
    result: TargetTestRunResult = adapter.run_target_tests(
        workspace,
        instance.fail_to_pass,
        instance.pass_to_pass,
        timeout_sec=timeout_sec,
        log_dir=log_dir,
    )
    return TestRunSummary(
        fail_to_pass_failed=result.fail_to_pass_failed,
        pass_to_pass_failed=result.pass_to_pass_failed,
        used_fallback=result.used_fallback,
        fallback_reason=result.fallback_reason,
    )
