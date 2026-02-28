from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_results(run_dir: Path) -> list[dict[str, Any]]:
    instances_dir = run_dir / "instances"
    if not instances_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for result_path in sorted(instances_dir.glob("*/result.json")):
        try:
            results.append(_load_result(result_path))
        except Exception:
            continue
    return sorted(results, key=lambda r: str(r.get("instance_id", "")))


def build_summary(run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    solved_count = sum(1 for r in results if bool(r.get("solved")))
    duration_sum = sum(float(r.get("duration_sec", 0.0)) for r in results)
    average_duration = (duration_sum / total) if total else 0.0

    repo_breakdown: dict[str, dict[str, int]] = {}
    retries_total = 0
    retries_used_instances = 0
    recovered_by_retry = 0

    for r in results:
        repo = str(r.get("repo", ""))
        repo_breakdown.setdefault(repo, {"solved": 0, "total": 0})
        repo_breakdown[repo]["total"] += 1
        if r.get("solved"):
            repo_breakdown[repo]["solved"] += 1

        attempt_count = int(r.get("attempt_count", 1))
        retries = max(0, attempt_count - 1)
        retries_total += retries
        if retries > 0:
            retries_used_instances += 1
            attempts = r.get("attempts", [])
            if attempts and not bool(attempts[0].get("solved")) and bool(r.get("solved")):
                recovered_by_retry += 1

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "solved_count": solved_count,
        "total": total,
        "repo_breakdown": repo_breakdown,
        "average_duration_sec": round(average_duration, 3),
        "instability": {
            "retries_total": retries_total,
            "retries_used_instances": retries_used_instances,
            "recovered_by_retry": recovered_by_retry,
        },
    }


def write_summary_json(run_dir: Path, summary: dict[str, Any]) -> Path:
    out = run_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return out


def write_summary_markdown(run_dir: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> Path:
    lines: list[str] = []
    lines.append(f"# Run Summary: {summary['run_id']}")
    lines.append("")
    lines.append(f"- Solved: {summary['solved_count']}/{summary['total']}")
    lines.append(f"- Avg duration (sec): {summary['average_duration_sec']}")
    lines.append("")
    lines.append("## Repo Breakdown")
    lines.append("")
    for repo, stats in sorted(summary.get("repo_breakdown", {}).items()):
        lines.append(f"- {repo}: {stats['solved']}/{stats['total']}")
    lines.append("")
    lines.append("## Instance Results")
    lines.append("")
    lines.append("| Instance | Repo | Solved | Error | Duration (s) | Artifact |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        iid = str(r.get("instance_id", ""))
        repo = str(r.get("repo", ""))
        solved = "yes" if r.get("solved") else "no"
        err = str(r.get("error_class", "") or "")
        duration = f"{float(r.get('duration_sec', 0.0)):.2f}"
        artifact_rel = f"instances/{iid}/result.json"
        lines.append(f"| {iid} | {repo} | {solved} | {err} | {duration} | [{artifact_rel}]({artifact_rel}) |")

    lines.append("")
    lines.append("## Instability")
    lines.append("")
    instability = summary.get("instability", {})
    lines.append(f"- retries_total: {instability.get('retries_total', 0)}")
    lines.append(f"- retries_used_instances: {instability.get('retries_used_instances', 0)}")
    lines.append(f"- recovered_by_retry: {instability.get('recovered_by_retry', 0)}")

    out = run_dir / "summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def summarize_run(run_dir: Path, run_id: str) -> dict[str, Any]:
    results = load_run_results(run_dir)
    summary = build_summary(run_id, results)
    write_summary_json(run_dir, summary)
    write_summary_markdown(run_dir, summary, results)
    return summary
