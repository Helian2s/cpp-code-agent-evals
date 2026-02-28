from __future__ import annotations

import unittest

from harness.adapters.fmt import parse_gtest_list_output


class FmtAdapterParsingTests(unittest.TestCase):
    def test_parse_gtest_list_output(self) -> None:
        text = """
FormatTest.
  HandlesNan
  HandlesInf
UtilTest.
  BitCast
"""
        parsed = parse_gtest_list_output(text)
        self.assertIn("FormatTest.HandlesNan", parsed)
        self.assertIn("FormatTest.HandlesInf", parsed)
        self.assertIn("UtilTest.BitCast", parsed)


if __name__ == "__main__":
    unittest.main()
