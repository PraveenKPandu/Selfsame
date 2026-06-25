"""Runs the language-neutral conformance vectors (SPEC/conformance/cases/*.json)
against the Python implementation's real comparator and soundness gate.

This is the reference for how every language consumes the conformance suite:
read the JSON, feed each case through compare / soundness, assert the expected
result. See SPEC/conformance/README.md.
"""

import json
import os
import unittest

from probe.replay import _same, _unsound

_HERE = os.path.dirname(os.path.abspath(__file__))
# packages/python/tests -> packages/python -> packages -> repo root -> SPEC
_CASES = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "SPEC", "conformance", "cases")
)


def _load(name):
    with open(os.path.join(_CASES, name), encoding="utf-8") as fh:
        return json.load(fh)["cases"]


@unittest.skipUnless(
    os.path.isdir(_CASES), "SPEC/conformance not present (package built standalone)"
)
class TestConformance(unittest.TestCase):
    def test_canonical_comparison(self):
        for case in _load("canonical-comparison.json"):
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    _same(case["a"], case["b"]),
                    case["same"],
                    msg="comparison vector %r" % case["name"],
                )

    def test_soundness_verdicts(self):
        for case in _load("soundness-verdicts.json"):
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    _unsound(case["observations"]),
                    case["reason"],
                    msg="soundness vector %r" % case["name"],
                )


if __name__ == "__main__":
    unittest.main()
