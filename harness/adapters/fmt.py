from __future__ import annotations

import os
import re
from pathlib import Path

from harness.adapters.base import BaseRepoAdapter, BuildResult, CommandTimeoutError, run_command
from harness.models import TargetTestRunResult, WorkspaceLayout


def parse_gtest_list_output(text: str) -> list[str]:
    tests: list[str] = []
    current_suite = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if not line.startswith(" ") and line.endswith("."):
            current_suite = line.strip()
            continue
        if line.startswith(" ") and current_suite:
            test_name = line.strip().split("#", 1)[0].strip()
            if not test_name:
                continue
            if current_suite.endswith("."):
                tests.append(f"{current_suite}{test_name}")
    return tests


class FmtAdapter(BaseRepoAdapter):
    repo_name = "fmtlib/fmt"

    def framework_info(self) -> dict[str, str]:
        return {
            "framework": "gtest",
            "test_selector": "--gtest_filter",
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
                "-DFMT_TEST=ON",
                "-DFMT_DOC=OFF",
                "-DFMT_FUZZ=OFF",
                "-DFMT_CUDA_TEST=OFF",
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

    def _discover_test_map(self, workspace: WorkspaceLayout, log_dir: Path) -> dict[str, Path]:
        mapping: dict[str, Path] = {}
        binaries = sorted(self._discover_binaries(workspace.build_dir))
        for binary in binaries:
            safe = self._safe_name(binary.name)
            out = log_dir / f"discover_{safe}.stdout.log"
            err = log_dir / f"discover_{safe}.stderr.log"
            result = run_command(
                [str(binary), "--gtest_list_tests"],
                timeout_sec=120,
                stdout_path=out,
                stderr_path=err,
            )
            if result.exit_code != 0 or not out.exists():
                continue
            text = out.read_text(encoding="utf-8", errors="ignore")
            for test_name in parse_gtest_list_output(text):
                mapping.setdefault(test_name, binary)
        return mapping

    def _discover_binaries(self, build_dir: Path) -> list[Path]:
        bins: list[Path] = []
        for candidate in build_dir.rglob("*-test"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                bins.append(candidate)
        return bins

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)

    def _run_single_test(self, binary: Path, test_name: str, *, timeout_sec: int, log_dir: Path) -> bool:
        safe = self._safe_name(test_name)
        cmd = [str(binary), f"--gtest_filter={test_name}"]
        out = log_dir / f"test_{safe}.stdout.log"
        err = log_dir / f"test_{safe}.stderr.log"
        try:
            res = run_command(cmd, timeout_sec=timeout_sec, stdout_path=out, stderr_path=err)
            return res.exit_code == 0
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
        test_map = self._discover_test_map(workspace, log_dir)
        unresolved: list[str] = []
        fail_to_pass_failed: list[str] = []
        pass_to_pass_failed: list[str] = []

        for test_name in fail_to_pass:
            binary = test_map.get(test_name)
            if binary is None:
                unresolved.append(test_name)
                continue
            if not self._run_single_test(binary, test_name, timeout_sec=timeout_sec, log_dir=log_dir):
                fail_to_pass_failed.append(test_name)

        for test_name in pass_to_pass:
            binary = test_map.get(test_name)
            if binary is None:
                unresolved.append(test_name)
                continue
            if not self._run_single_test(binary, test_name, timeout_sec=timeout_sec, log_dir=log_dir):
                pass_to_pass_failed.append(test_name)

        used_fallback = False
        fallback_reason = ""
        if unresolved:
            used_fallback = True
            fallback_reason = "unresolved_gtest_names"
            ctest_out = log_dir / "fallback_ctest.stdout.log"
            ctest_err = log_dir / "fallback_ctest.stderr.log"
            try:
                ctest = run_command(
                    ["ctest", "--test-dir", str(workspace.build_dir), "--output-on-failure"],
                    timeout_sec=timeout_sec,
                    stdout_path=ctest_out,
                    stderr_path=ctest_err,
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
