from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetInstance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str = ""
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    patch: str = ""
    test_patch: str = ""
    created_at: str = ""
    version: str = ""

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> "DatasetInstance":
        return DatasetInstance(
            instance_id=str(raw.get("instance_id", "")).strip(),
            repo=str(raw.get("repo", "")).strip(),
            base_commit=str(raw.get("base_commit", "")).strip(),
            problem_statement=str(raw.get("problem_statement", "")).strip(),
            hints_text=str(raw.get("hints_text", "")).strip(),
            fail_to_pass=[str(x) for x in raw.get("FAIL_TO_PASS", [])],
            pass_to_pass=[str(x) for x in raw.get("PASS_TO_PASS", [])],
            patch=str(raw.get("patch", "")),
            test_patch=str(raw.get("test_patch", "")),
            created_at=str(raw.get("created_at", "")),
            version=str(raw.get("version", "")),
        )

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["FAIL_TO_PASS"] = data.pop("fail_to_pass")
        data["PASS_TO_PASS"] = data.pop("pass_to_pass")
        return data


@dataclass(frozen=True)
class WorkspaceLayout:
    run_id: str
    instance_id: str
    run_dir: Path
    workspace_dir: Path
    repo_dir: Path
    build_dir: Path
    instance_dir: Path
    attempts_dir: Path


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    exit_code: int
    duration_sec: float
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class TestBucketResult:
    passed: int
    total: int
    list_failed: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total": self.total,
            "list_failed": list(self.list_failed),
        }


@dataclass(frozen=True)
class TargetTestRunResult:
    fail_to_pass_failed: list[str]
    pass_to_pass_failed: list[str]
    used_fallback: bool = False
    fallback_reason: str = ""


@dataclass(frozen=True)
class AgentRunResult:
    exit_code: int
    duration_sec: float
    stdout_path: Path
    stderr_path: Path
    request_id: str = ""
    timed_out: bool = False
    observer_summary_path: Path | None = None
    observer_trajectory_path: Path | None = None
    llm_details_path: Path | None = None
    observer_counters: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class InstanceAttempt:
    attempt: int
    error_class: str | None
    solved: bool
    duration_sec: float

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstanceResult:
    instance_id: str
    repo: str
    base_commit: str
    solved: bool
    fail_to_pass: TestBucketResult
    pass_to_pass: TestBucketResult
    build_ok_before: bool
    build_ok_after: bool
    request_id: str
    duration_sec: float
    error_class: str | None
    attempt_count: int
    attempts: list[InstanceAttempt] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "solved": self.solved,
            "fail_to_pass": self.fail_to_pass.to_json(),
            "pass_to_pass": self.pass_to_pass.to_json(),
            "build_ok_before": self.build_ok_before,
            "build_ok_after": self.build_ok_after,
            "request_id": self.request_id,
            "duration_sec": self.duration_sec,
            "error_class": self.error_class,
            "attempt_count": self.attempt_count,
            "attempts": [a.to_json() for a in self.attempts],
            "metadata": self.metadata,
        }
