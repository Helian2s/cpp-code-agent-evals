from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"


@dataclass(frozen=True)
class TimeoutConfig:
    checkout_sec: int = 300
    build_sec: int = 1800
    agent_sec: int = 3600
    tests_sec: int = 1800


@dataclass(frozen=True)
class AgentConfig:
    sut_binary: Path = Path("/home/val/Documents/cpp-agent/cpp-code-agent/build-codex/cpp-code-agent")
    mode: str = "prompt"
    show_patch_only: bool = False
    campaign_id: str = "swebench-cpp-12"
    max_iterations: int | None = None
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_wall_clock_sec: int | None = None
    extra_args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 1
    retry_error_classes: list[str] = field(default_factory=lambda: ["infra_error", "agent_failed"])


@dataclass(frozen=True)
class HarnessConfig:
    root_dir: Path
    dataset_dir: Path
    runs_dir: Path
    repo_sources: dict[str, Path]
    build_jobs: int = 0
    max_parallel: int = 1
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


def _expand_path(value: str | Path, root_dir: Path) -> Path:
    raw = str(value)
    expanded = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate
    return (root_dir / candidate).resolve()


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded or {}
    except ModuleNotFoundError:
        return json.loads(text)


def load_config(path: Path | None = None) -> HarnessConfig:
    cfg_path = (path or DEFAULT_CONFIG_PATH).resolve()
    root_dir = PROJECT_ROOT
    raw = _load_yaml_or_json(cfg_path)

    dataset_dir = _expand_path(raw.get("dataset_dir", "data/dataset"), root_dir)
    runs_dir = _expand_path(raw.get("runs_dir", "runs"), root_dir)

    repo_sources_raw = raw.get("repo_sources", {})
    repo_sources: dict[str, Path] = {
        key: _expand_path(value, root_dir) for key, value in repo_sources_raw.items()
    }
    if not repo_sources:
        repo_sources = {
            "fmtlib/fmt": Path("/home/val/Documents/cpp-agent/fmt"),
            "nlohmann/json": Path("/home/val/Documents/cpp-agent/json"),
        }

    t_raw = raw.get("timeouts", {})
    timeouts = TimeoutConfig(
        checkout_sec=int(t_raw.get("checkout_sec", TimeoutConfig.checkout_sec)),
        build_sec=int(t_raw.get("build_sec", TimeoutConfig.build_sec)),
        agent_sec=int(t_raw.get("agent_sec", TimeoutConfig.agent_sec)),
        tests_sec=int(t_raw.get("tests_sec", TimeoutConfig.tests_sec)),
    )

    a_raw = raw.get("agent", {})
    agent = AgentConfig(
        sut_binary=_expand_path(a_raw.get("sut_binary", AgentConfig.sut_binary), root_dir),
        mode=str(a_raw.get("mode", AgentConfig.mode)),
        show_patch_only=bool(a_raw.get("show_patch_only", AgentConfig.show_patch_only)),
        campaign_id=str(a_raw.get("campaign_id", AgentConfig.campaign_id)),
        max_iterations=(
            int(a_raw["max_iterations"]) if a_raw.get("max_iterations") is not None else None
        ),
        max_llm_calls=(int(a_raw["max_llm_calls"]) if a_raw.get("max_llm_calls") is not None else None),
        max_tool_calls=(
            int(a_raw["max_tool_calls"]) if a_raw.get("max_tool_calls") is not None else None
        ),
        max_wall_clock_sec=(
            int(a_raw["max_wall_clock_sec"]) if a_raw.get("max_wall_clock_sec") is not None else None
        ),
        extra_args=[str(x) for x in a_raw.get("extra_args", [])],
    )

    r_raw = raw.get("retry", {})
    retry = RetryConfig(
        max_attempts=max(1, int(r_raw.get("max_attempts", RetryConfig.max_attempts))),
        retry_error_classes=[str(x) for x in r_raw.get("retry_error_classes", RetryConfig().retry_error_classes)],
    )

    return HarnessConfig(
        root_dir=root_dir,
        dataset_dir=dataset_dir,
        runs_dir=runs_dir,
        repo_sources=repo_sources,
        build_jobs=int(raw.get("build_jobs", 0)),
        max_parallel=max(1, int(raw.get("max_parallel", 1))),
        timeouts=timeouts,
        agent=agent,
        retry=retry,
    )
