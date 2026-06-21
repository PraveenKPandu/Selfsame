"""Tests for the credibility fixes (phase 2) plus the end-to-end verdict.

Run: python3 -m unittest discover -s tests
"""

import datetime
import math
import secrets
import time
import unittest
import uuid

from probe import harness
from probe.equality import equal
from probe.generators import UnsupportedSignature, generate
from probe.runner import evaluate


class TestEquality(unittest.TestCase):
    def test_identity_object_compared_by_state_not_repr(self):
        class P:  # only identity __eq__
            def __init__(self, x):
                self.x = x
        # The regression: repr-based comparison saw addresses and called these
        # unequal. Structural comparison must call them equal.
        self.assertTrue(equal(P(1), P(1)))
        self.assertFalse(equal(P(1), P(2)))

    def test_slots_object(self):
        class S:
            __slots__ = ("a", "b")
            def __init__(self, a, b):
                self.a, self.b = a, b
        self.assertTrue(equal(S(1, 2), S(1, 2)))
        self.assertFalse(equal(S(1, 2), S(1, 3)))

    def test_float_edge_cases(self):
        self.assertTrue(equal(float("nan"), float("nan")))
        self.assertTrue(equal(-0.0, 0.0))
        self.assertFalse(equal(1.0, 1.0000001))

    def test_dict_order_insensitive_list_order_sensitive(self):
        self.assertTrue(equal({"a": 1, "b": 2}, {"b": 2, "a": 1}))
        self.assertFalse(equal([1, 2], [2, 1]))

    def test_custom_eq_respected(self):
        class V:
            def __init__(self, x):
                self.x = x
            def __eq__(self, other):
                return isinstance(other, V) and self.x == other.x
            def __hash__(self):
                return hash(self.x)
        self.assertTrue(equal(V(1), V(1)))

    def test_opaque_object_not_assumed_equal(self):
        # An object with no introspectable state and identity eq must not be
        # claimed equal (conservative).
        class Opaque:
            __slots__ = ()
        self.assertFalse(equal(Opaque(), Opaque()))

    def test_type_mismatch(self):
        self.assertFalse(equal(1, 1.0))
        self.assertFalse(equal(1, True))


class TestDeterminismControl(unittest.TestCase):
    def test_broad_sources_controlled(self):
        def chaos(n: int) -> tuple:
            return (uuid.uuid4().int % 1000, time.time_ns(),
                    secrets.randbelow(10 ** 6), secrets.token_hex(8),
                    datetime.datetime.now().isoformat())
        sc = harness.self_check(chaos, [(1,)])
        self.assertTrue(sc.deterministic, "uuid/time/secrets/datetime not controlled")

    def test_environment_restored_after_observe(self):
        before = (time.time, uuid.uuid4, getattr(__import__("random"), "_urandom", None))
        harness.observe(lambda n: time.time(), (1,))
        after = (time.time, uuid.uuid4, getattr(__import__("random"), "_urandom", None))
        self.assertEqual(before, after, "controlled env leaked outside observe()")

    def test_concurrency_flagged_unverifiable(self):
        import threading

        def racer(n: int) -> tuple:
            out = []
            b = threading.Barrier(n)

            def w(i):
                b.wait()
                out.append(i)
            ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            return tuple(out)

        sc = harness.self_check(racer, [(48,)])
        self.assertFalse(sc.deterministic)
        self.assertEqual(sc.cause, harness.CAUSE_CONCURRENCY)


class TestGenerators(unittest.TestCase):
    def test_unsupported_custom_type(self):
        class Order:
            pass

        def process(o: Order) -> int:
            return 1
        with self.assertRaises(UnsupportedSignature):
            generate(process)

    def test_unsupported_unannotated(self):
        def f(x):  # no annotation
            return x
        with self.assertRaises(UnsupportedSignature):
            generate(f)

    def test_defaults_left_unset(self):
        def f(a: int, b: int = 5):
            return (a, b)
        # only `a` is generated; `b` keeps its default
        for args in generate(f):
            self.assertEqual(len(args), 1)


class TestEndToEnd(unittest.TestCase):
    def test_corpus_integrity_and_coverage(self):
        from units import ALL_UNITS
        report = evaluate(ALL_UNITS)
        self.assertTrue(report.integrity_ok, "integrity check tripped")
        self.assertEqual(report.false_positives, 0)
        self.assertEqual(report.missed_catches, 0)
        self.assertEqual(report.caught, 3, "expected 3 positive controls caught")
        self.assertEqual(report.unverifiable, 2, "expected 2 concurrency units")
        # 17/19 verifiable on the current corpus
        self.assertEqual(report.verifiable, 17)
        self.assertEqual(report.total, 19)

    def test_object_unit_is_equivalent_not_false_positive(self):
        # Direct regression guard for the repr-address bug.
        from units.pure import build_vec_orig, build_vec_ref
        d = harness.diff(build_vec_orig, build_vec_ref, [(3,), (0,)])
        self.assertTrue(d.equivalent)


if __name__ == "__main__":
    unittest.main()
