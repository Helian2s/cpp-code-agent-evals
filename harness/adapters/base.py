from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from harness.models import TargetTestRunResult, WorkspaceLayout
from harness.workspace import CommandTimeoutError, run_command


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    error: str = ""


class BaseRepoAdapter(ABC):
    repo_name: str

    @abstractmethod
    def framework_info(self) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def prepare_build(self, workspace: WorkspaceLayout, *, timeout_sec: int, build_jobs: int, log_dir: Path) -> BuildResult:
        raise NotImplementedError

    @abstractmethod
    def run_target_tests(
        self,
        workspace: WorkspaceLayout,
        fail_to_pass: list[str],
        pass_to_pass: list[str],
        *,
        timeout_sec: int,
        log_dir: Path,
    ) -> TargetTestRunResult:
        raise NotImplementedError

    @staticmethod
    def _build_jobs_args(build_jobs: int) -> list[str]:
        if build_jobs <= 0:
            return []
        return ["--", f"-j{build_jobs}"]


__all__ = [
    "BaseRepoAdapter",
    "BuildResult",
    "CommandTimeoutError",
    "run_command",
]
