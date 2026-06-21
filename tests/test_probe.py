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


class TestExtract(unittest.TestCase):
    def test_pairing(self):
        from probe.extract import pair_functions
        before = "def a(x):\n return x\ndef b(x):\n return x\ndef gone(x):\n return x\n"
        after = "def a(x):\n return x\ndef b(x, y=1):\n return x\ndef added(x):\n return x\n"
        p = pair_functions(before, after)
        self.assertEqual(p.matched, ["a"])
        self.assertEqual(p.sig_changed, ["b"])
        self.assertEqual(p.added, ["added"])
        self.assertEqual(p.removed, ["gone"])

    def test_build_function(self):
        from probe.extract import build_function
        fn = build_function("import math\ndef f(n: int) -> int:\n return int(math.sqrt(n))\n", "f")
        self.assertEqual(fn(9), 3)


class TestCheckPipeline(unittest.TestCase):
    def test_example_refactor_end_to_end(self):
        import io
        import os
        from contextlib import redirect_stdout

        from probe import check
        root = check._repo_root()
        before = check.source_from_file(os.path.join(root, "examples/calc_before.py"))
        after = check.source_from_file(os.path.join(root, "examples/calc_after.py"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = check.run(before, after, "test", root)
        out = buf.getvalue()
        self.assertEqual(code, 1, "should exit 1 when a divergence is caught")
        self.assertIn("apply_discount", out)
        self.assertRegex(out, r"apply_discount\s+divergent")
        self.assertRegex(out, r"score\s+unsupported")
        self.assertIn("summarize", out)  # signature-changed note


class TestSoundness(unittest.TestCase):
    def test_real_io_refused_even_if_stable(self):
        # Reading a missing file raises the same error every run (stable), but
        # it is uncontrolled I/O — must be refused, not certified.
        def read_it(path: str) -> str:
            with open(path) as f:
                return f.read()
        sc = harness.self_check(read_it, [("definitely_missing_file_xyz",)])
        self.assertFalse(sc.deterministic)
        self.assertEqual(sc.cause, harness.CAUSE_IO)

    def test_threads_refused_even_when_not_flickering(self):
        import threading
        # Tiny n: the race won't manifest, runs agree — but thread use alone
        # must make it unverifiable.
        def tiny(n: int) -> int:
            box = {"v": 0}

            def w():
                box["v"] += 1
            ts = [threading.Thread(target=w) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            return box["v"]
        sc = harness.self_check(tiny, [(1,)])
        self.assertFalse(sc.deterministic)
        self.assertEqual(sc.cause, harness.CAUSE_CONCURRENCY)

    def test_literal_mining_catches_magic_value_bug(self):
        from probe.generators import literal_seeds, mine_literals

        def parser(s: str) -> bool:
            return s in ("yes", "on")
        lits = mine_literals('def parser(s):\n return s in ("yes", "on")\n', "parser")
        self.assertIn("on", lits[str])
        seeds = literal_seeds(parser, lits)
        self.assertIn(("on",), seeds)

    def test_static_io_capability_detected(self):
        from probe.extract import io_capability
        src = ("def f(u: str) -> int:\n"
               "    from urllib.request import urlopen\n"
               "    return urlopen(u).getcode()\n")
        self.assertIsNotNone(io_capability(src, "f"))
        pure = "def g(x: int) -> int:\n    return x + 1\n"
        self.assertIsNone(io_capability(pure, "g"))


class TestCanonical(unittest.TestCase):
    def test_object_and_edge_cases(self):
        from probe.canonical import canonical

        class P:
            def __init__(self, x):
                self.x = x
        self.assertEqual(canonical(P(1)), canonical(P(1)))
        self.assertNotEqual(canonical(P(1)), canonical(P(2)))
        self.assertEqual(canonical(float("nan")), canonical(float("nan")))
        self.assertEqual(canonical(-0.0), canonical(0.0))
        self.assertEqual(canonical({"a": 1, "b": 2}), canonical({"b": 2, "a": 1}))
        self.assertNotEqual(canonical([1, 2]), canonical([2, 1]))
        self.assertNotEqual(canonical(1), canonical(1.0))  # type matters


class TestReplayLogic(unittest.TestCase):
    def test_same_and_unsound(self):
        from probe import replay
        a = {"val": ["int", 1], "io": 0, "threads": 0}
        b = {"val": ["int", 1], "io": 0, "threads": 0}
        c = {"val": ["int", 2], "io": 0, "threads": 0}
        self.assertTrue(replay._same(a, b))
        self.assertFalse(replay._same(a, c))
        self.assertFalse(replay._same(a, {"exc": "ValueError: x", "io": 0, "threads": 0}))
        self.assertEqual(replay._unsound([{"io": 1, "threads": 0}]), "uncontrolled-io")
        self.assertEqual(replay._unsound([{"io": 0, "threads": 2}]), "concurrency")
        self.assertIsNone(replay._unsound([{"io": 0, "threads": 0, "val": ["str", "x"]}]))

    def test_verdict(self):
        import pickle

        from probe import replay
        blobs = [pickle.dumps(["q"])]
        loaded = lambda obs: {"loaded": True, "error": None, "obs": obs}
        eq = loaded([{"val": ["str", "Q"], "io": 0, "threads": 0}])
        self.assertEqual(replay._verdict(eq, eq, blobs)[0], "equivalent")
        diff = loaded([{"val": ["str", "Z"], "io": 0, "threads": 0}])
        self.assertEqual(replay._verdict(eq, diff, blobs)[0], "divergent")
        io = loaded([{"val": ["str", "Q"], "io": 1, "threads": 0}])
        self.assertEqual(replay._verdict(io, io, blobs)[0], "unverifiable")
        self.assertEqual(replay._verdict({"error": "boom"}, eq, blobs)[0], "error")


class TestCaptureReplayUnits(unittest.TestCase):
    def test_qualname_function_method_classmethod(self):
        from probe import _capture_hook as hook

        def f(x):
            return x

        class C:
            def m(self, x):
                return x

            def cm(cls, x):  # name only; first param 'cls' is what matters
                return x

        # method -> <class qualname>.<name>; classmethod uses the class arg;
        # plain function -> just its name.
        self.assertEqual(hook._qualname(f.__code__, [1]), "f")
        self.assertEqual(hook._qualname(C.m.__code__, [C(), 1]), C.__qualname__ + ".m")
        self.assertEqual(hook._qualname(C.cm.__code__, [C, 1]), C.__qualname__ + ".cm")

    def test_module_prefix_match(self):
        from probe import _capture_hook as hook
        hook._MODULES = ("pkg",)
        self.assertTrue(hook._module_matches("pkg"))
        self.assertTrue(hook._module_matches("pkg.sub"))
        self.assertFalse(hook._module_matches("pkgother"))
        self.assertFalse(hook._module_matches("other"))

    def test_merge_dedups_and_keys(self):
        import os
        import pickle
        import tempfile

        from probe import capture
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "cap-1.pkl"), "wb") as f:
            pickle.dump({"m::f": [pickle.dumps([1]), pickle.dumps([2])]}, f)
        with open(os.path.join(d, "cap-2.pkl"), "wb") as f:
            pickle.dump({"m::f": [pickle.dumps([2]), pickle.dumps([3])]}, f)
        merged = capture._merge(d)
        self.assertEqual(len(merged["m::f"]), 3)  # 1,2,3 — the duplicate 2 dropped

    def test_split_key_and_resolve(self):
        from probe import replay
        from probe._replay_worker import _resolve
        self.assertEqual(replay._split_key("mod::Class.method"), ("mod", "Class.method"))

        import types
        m = types.ModuleType("m")

        class Class:
            def method(self):
                return 1
        m.Class = Class
        self.assertIs(_resolve(m, "Class.method"), Class.method)


if __name__ == "__main__":
    unittest.main()
