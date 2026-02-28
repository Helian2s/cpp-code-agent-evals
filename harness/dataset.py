from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from harness.models import DatasetInstance


def _json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _find_instance_members(zf: zipfile.ZipFile) -> list[str]:
    members = [m for m in zf.namelist() if m.endswith(".json") and "/instances/" in m]
    if members:
        return sorted(members)
    # Fallback: use all_cpp_tasks.jsonl if instance files are missing.
    jsonl_members = [m for m in zf.namelist() if m.endswith("all_cpp_tasks.jsonl")]
    if jsonl_members:
        return jsonl_members
    raise FileNotFoundError("No dataset instances found in zip archive")


def import_dataset(zip_path: Path, dataset_dir: Path) -> dict[str, Any]:
    zip_path = zip_path.resolve()
    dataset_dir = dataset_dir.resolve()
    instances_dir = dataset_dir / "instances"
    instances_dir.mkdir(parents=True, exist_ok=True)

    imported: list[DatasetInstance] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = _find_instance_members(zf)
        if members and members[0].endswith(".json") and "/instances/" in members[0]:
            for member in members:
                raw = json.loads(zf.read(member).decode("utf-8"))
                inst = DatasetInstance.from_raw(raw)
                if not inst.instance_id:
                    continue
                imported.append(inst)
        else:
            # Parse JSONL fallback.
            text = zf.read(members[0]).decode("utf-8")
            for line in text.splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                inst = DatasetInstance.from_raw(raw)
                if not inst.instance_id:
                    continue
                imported.append(inst)

    imported = sorted(imported, key=lambda x: x.instance_id)

    for inst in imported:
        _json_dump(instances_dir / f"{inst.instance_id}.json", inst.to_json())

    index = [
        {
            "instance_id": inst.instance_id,
            "repo": inst.repo,
            "base_commit": inst.base_commit,
            "path": f"instances/{inst.instance_id}.json",
        }
        for inst in imported
    ]
    meta = {
        "dataset_zip": str(zip_path),
        "instance_count": len(imported),
        "instances": index,
    }
    _json_dump(dataset_dir / "index.json", meta)
    return meta


def load_index(dataset_dir: Path) -> dict[str, Any]:
    path = dataset_dir / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset index not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_instances(dataset_dir: Path) -> list[dict[str, str]]:
    idx = load_index(dataset_dir)
    return list(idx.get("instances", []))


def load_instance(dataset_dir: Path, instance_id: str) -> DatasetInstance:
    path = dataset_dir / "instances" / f"{instance_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Instance not found: {instance_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DatasetInstance.from_raw(raw)
