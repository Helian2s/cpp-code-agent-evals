from __future__ import annotations

import os
import re
from pathlib import Path

from harness.adapters.base import BaseRepoAdapter, BuildResult, CommandTimeoutError, run_command
from harness.models import TargetTestRunResult, WorkspaceLayout


def split_catch_style_name(name: str) -> tuple[str, str | None]:
    if ">" not in name:
        return name.strip(), None
    parts = [p.strip() for p in name.split(">")]
    case = parts[0]
    subcase = " > ".join(parts[1:]).strip() if len(parts) > 1 else None
    return case, subcase or None


def parse_doctest_list_output(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") or line.startswith("="):
            continue
        out.append(line)
    return out


class NlohmannJsonAdapter(BaseRepoAdapter):
    repo_name = "nlohmann/json"

    def framework_info(self) -> dict[str, str]:
        return {
            "framework": "doctest",
            "test_selector": "--test-case + --subcase",
            "fallback": "ctest --output-on-failure",
        }

    def prepare_build(self, workspace: WorkspaceLayout, *, timeout_sec: int, build_jobs: int, log_dir: Path) -> BuildResult:
        log_dir.mkdir(parents=True, exist_ok=True)
        cfg = run_command(
            [
                "cmake",
                "-S",
                str(workspace.repo_dir),
                "-B",
                str(workspace.build_dir),
                "-DCMAKE_BUILD_TYPE=Release",
                "-DBUILD_TESTING=ON",
                "-DJSON_BuildTests=ON",
                "-DJSON_TestStandards=17",
            ],
            timeout_sec=timeout_sec,
            stdout_path=log_dir / "cmake_configure.stdout.log",
            stderr_path=log_dir / "cmake_configure.stderr.log",
        )
        if cfg.exit_code != 0:
            return BuildResult(ok=False, error="configure_failed")

        build_cmd = ["cmake", "--build", str(workspace.build_dir)]
        build_cmd.extend(self._build_jobs_args(build_jobs))
        bld = run_command(
            build_cmd,
            timeout_sec=timeout_sec,
            stdout_path=log_dir / "cmake_build.stdout.log",
            stderr_path=log_dir / "cmake_build.stderr.log",
        )
        if bld.exit_code != 0:
            return BuildResult(ok=False, error="build_failed")
        return BuildResult(ok=True)

    def _discover_binaries(self, build_dir: Path) -> list[Path]:
        bins: list[Path] = []
        for candidate in build_dir.rglob("test-*"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                bins.append(candidate)
        return sorted(bins)

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)

    def _discover_case_map(self, workspace: WorkspaceLayout, log_dir: Path) -> dict[str, Path]:
        mapping: dict[str, Path] = {}
        for binary in self._discover_binaries(workspace.build_dir):
            safe = self._safe_name(binary.name)
            out = log_dir / f"discover_{safe}.stdout.log"
            err = log_dir / f"discover_{safe}.stderr.log"
            result = run_command(
                [str(binary), "--list-test-cases"],
                timeout_sec=120,
                stdout_path=out,
                stderr_path=err,
            )
            if result.exit_code != 0 or not out.exists():
                continue
            for case in parse_doctest_list_output(out.read_text(encoding="utf-8", errors="ignore")):
                mapping.setdefault(case, binary)
        return mapping

    def _run_single_case(
        self,
        binary: Path,
        case: str,
        subcase: str | None,
        *,
        timeout_sec: int,
        log_dir: Path,
        name: str,
    ) -> bool:
        safe = self._safe_name(name)
        out = log_dir / f"test_{safe}.stdout.log"
        err = log_dir / f"test_{safe}.stderr.log"
        cmd = [str(binary), f"--test-case={case}"]
        if subcase:
            cmd.append(f"--subcase={subcase}")
        try:
            result = run_command(cmd, timeout_sec=timeout_sec, stdout_path=out, stderr_path=err)
            return result.exit_code == 0
        except CommandTimeoutError:
            return False

    def run_target_tests(
        self,
        workspace: WorkspaceLayout,
        fail_to_pass: list[str],
        pass_to_pass: list[str],
        *,
        timeout_sec: int,
        log_dir: Path,
    ) -> TargetTestRunResult:
        log_dir.mkdir(parents=True, exist_ok=True)
        case_map = self._discover_case_map(workspace, log_dir)

        unresolved: list[str] = []
        fail_to_pass_failed: list[str] = []
        pass_to_pass_failed: list[str] = []

        for test_name in fail_to_pass:
            case, subcase = split_catch_style_name(test_name)
            binary = case_map.get(case)
            if binary is None:
                unresolved.append(test_name)
                continue
            ok = self._run_single_case(
                binary,
                case,
                subcase,
                timeout_sec=timeout_sec,
                log_dir=log_dir,
                name=test_name,
            )
            if not ok:
                fail_to_pass_failed.append(test_name)

        for test_name in pass_to_pass:
            case, subcase = split_catch_style_name(test_name)
            binary = case_map.get(case)
            if binary is None:
                unresolved.append(test_name)
                continue
            ok = self._run_single_case(
                binary,
                case,
                subcase,
                timeout_sec=timeout_sec,
                log_dir=log_dir,
                name=test_name,
            )
            if not ok:
                pass_to_pass_failed.append(test_name)

        used_fallback = False
        fallback_reason = ""
        if unresolved:
            used_fallback = True
            fallback_reason = "unresolved_doctest_names"
            out = log_dir / "fallback_ctest.stdout.log"
            err = log_dir / "fallback_ctest.stderr.log"
            try:
                ctest = run_command(
                    ["ctest", "--test-dir", str(workspace.build_dir), "--output-on-failure", "-R", "test-udt"],
                    timeout_sec=timeout_sec,
                    stdout_path=out,
                    stderr_path=err,
                )
                if ctest.exit_code != 0:
                    for name in unresolved:
                        if name in fail_to_pass and name not in fail_to_pass_failed:
                            fail_to_pass_failed.append(name)
                        if name in pass_to_pass and name not in pass_to_pass_failed:
                            pass_to_pass_failed.append(name)
            except CommandTimeoutError:
                fallback_reason = "fallback_ctest_timeout"
                for name in unresolved:
                    if name in fail_to_pass and name not in fail_to_pass_failed:
                        fail_to_pass_failed.append(name)
                    if name in pass_to_pass and name not in pass_to_pass_failed:
                        pass_to_pass_failed.append(name)

        return TargetTestRunResult(
            fail_to_pass_failed=sorted(fail_to_pass_failed),
            pass_to_pass_failed=sorted(pass_to_pass_failed),
            used_fallback=used_fallback,
            fallback_reason=fallback_reason,
        )
