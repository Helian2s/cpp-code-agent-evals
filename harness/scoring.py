from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.models import InstanceResult, TestBucketResult


REQUIRED_RESULT_FIELDS = {
    "instance_id",
    "repo",
    "base_commit",
    "solved",
    "fail_to_pass",
    "pass_to_pass",
    "build_ok_before",
    "build_ok_after",
    "request_id",
    "duration_sec",
    "error_class",
}


def build_bucket(targets: list[str], failed: list[str]) -> TestBucketResult:
    total = len(targets)
    failed_set = sorted(set(failed))
    passed = max(0, total - len(failed_set))
    return TestBucketResult(passed=passed, total=total, list_failed=failed_set)


def is_solved(
    *,
    build_ok_after: bool,
    fail_to_pass_failed: list[str],
    pass_to_pass_failed: list[str],
    agent_exit_code: int,
) -> bool:
    return (
        build_ok_after
        and agent_exit_code == 0
        and len(fail_to_pass_failed) == 0
        and len(pass_to_pass_failed) == 0
    )


def write_instance_result(path: Path, result: InstanceResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_json(), indent=2) + "\n", encoding="utf-8")


def read_instance_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_valid_result_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = read_instance_result(path)
    except Exception:
        return False
    if not REQUIRED_RESULT_FIELDS.issubset(set(data.keys())):
        return False
    f2p = data.get("fail_to_pass", {})
    p2p = data.get("pass_to_pass", {})
    for bucket in (f2p, p2p):
        if not isinstance(bucket, dict):
            return False
        if not {"passed", "total", "list_failed"}.issubset(bucket.keys()):
            return False
    return True
