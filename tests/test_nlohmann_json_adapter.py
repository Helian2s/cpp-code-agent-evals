from __future__ import annotations

import unittest

from harness.adapters.nlohmann_json import parse_doctest_list_output, split_catch_style_name


class NlohmannAdapterParsingTests(unittest.TestCase):
    def test_split_catch_style_name(self) -> None:
        case, subcase = split_catch_style_name("basic usage > conversion to json via free-functions")
        self.assertEqual(case, "basic usage")
        self.assertEqual(subcase, "conversion to json via free-functions")

    def test_parse_doctest_list_output(self) -> None:
        text = """
[doctest] listing all test case names
===============================================================================
basic usage
adl_serializer specialization
===============================================================================
"""
        parsed = parse_doctest_list_output(text)
        self.assertEqual(parsed, ["basic usage", "adl_serializer specialization"])


if __name__ == "__main__":
    unittest.main()
