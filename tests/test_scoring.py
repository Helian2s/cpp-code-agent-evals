from __future__ import annotations

import unittest

from harness.scoring import build_bucket, is_solved


class ScoringTests(unittest.TestCase):
    def test_build_bucket(self) -> None:
        bucket = build_bucket(["a", "b", "c"], ["b"])
        self.assertEqual(bucket.total, 3)
        self.assertEqual(bucket.passed, 2)
        self.assertEqual(bucket.list_failed, ["b"])

    def test_is_solved_true(self) -> None:
        self.assertTrue(
            is_solved(
                build_ok_after=True,
                fail_to_pass_failed=[],
                pass_to_pass_failed=[],
                agent_exit_code=0,
            )
        )

    def test_is_solved_false_on_failures(self) -> None:
        self.assertFalse(
            is_solved(
                build_ok_after=True,
                fail_to_pass_failed=["x"],
                pass_to_pass_failed=[],
                agent_exit_code=0,
            )
        )


if __name__ == "__main__":
    unittest.main()
