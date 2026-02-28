from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.dataset import import_dataset, load_instance, list_instances


class DatasetImportTests(unittest.TestCase):
    def test_import_dataset_from_instances(self) -> None:
        with TemporaryDirectory() as td:
            tmp_path = Path(td)
            zip_path = tmp_path / "tasks.zip"
            content = {
                "instance_id": "fmtlib__fmt-0001",
                "repo": "fmtlib/fmt",
                "base_commit": "abc123",
                "problem_statement": "Fix bug",
                "hints_text": "",
                "FAIL_TO_PASS": ["suite.test"],
                "PASS_TO_PASS": ["suite.ok"],
            }
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("cpp_tasks_multilingual/instances/fmtlib__fmt-0001.json", json.dumps(content))

            dataset_dir = tmp_path / "dataset"
            meta = import_dataset(zip_path, dataset_dir)

            self.assertEqual(meta["instance_count"], 1)
            entries = list_instances(dataset_dir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["instance_id"], "fmtlib__fmt-0001")

            inst = load_instance(dataset_dir, "fmtlib__fmt-0001")
            self.assertEqual(inst.repo, "fmtlib/fmt")
            self.assertEqual(inst.fail_to_pass, ["suite.test"])
            self.assertEqual(inst.pass_to_pass, ["suite.ok"])


if __name__ == "__main__":
    unittest.main()
