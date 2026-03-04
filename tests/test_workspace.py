from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.workspace import collect_git_metadata, create_workspace_layout


class WorkspaceLayoutTests(unittest.TestCase):
    def test_create_workspace_layout_build_dir_is_inside_repo(self) -> None:
        with TemporaryDirectory() as td:
            runs_dir = Path(td) / "runs"
            layout = create_workspace_layout(runs_dir, "run-1", "instance-1")
            self.assertEqual(layout.build_dir, layout.repo_dir / ".harness-build")
            self.assertTrue((runs_dir / "run-1" / "instances" / "instance-1").exists())


class GitMetadataTests(unittest.TestCase):
    def test_collect_git_metadata_ignores_generated_dirs(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir(parents=True, exist_ok=True)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

            tracked = repo / "tracked.txt"
            tracked.write_text("line-1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            # tracked diff (counts for numstat)
            tracked.write_text("line-1\nline-2\n", encoding="utf-8")
            # untracked normal file (should be reported)
            (repo / "note.txt").write_text("note\n", encoding="utf-8")
            # generated dirs (must be ignored)
            (repo / ".cpp-code-agent" / "tmp").mkdir(parents=True, exist_ok=True)
            (repo / ".agent-artifacts" / "tmp").mkdir(parents=True, exist_ok=True)
            (repo / ".harness-build" / "CMakeFiles").mkdir(parents=True, exist_ok=True)

            meta = collect_git_metadata(repo)
            changed = set(meta["changed_files"])

            self.assertIn("tracked.txt", changed)
            self.assertIn("note.txt", changed)
            self.assertFalse(any(path.startswith(".cpp-code-agent") for path in changed))
            self.assertFalse(any(path.startswith(".agent-artifacts") for path in changed))
            self.assertFalse(any(path.startswith(".harness-build") for path in changed))
            self.assertGreaterEqual(int(meta["patch_total_lines"]), 1)


if __name__ == "__main__":
    unittest.main()
