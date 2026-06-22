"""Tests for the credibility fixes (phase 2) plus the end-to-end verdict.

Run: python3 -m unittest discover -s tests
"""

import datetime
import os
import secrets
import sys
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


class TestPublicSnapshots(unittest.TestCase):
    """Representation-independent snapshots via the public/observable interface.

    The win: a stateful class compared by its OBSERVABLE contents instead of its
    private internal layout, so an internal refactor that preserves behavior is
    not falsely reported divergent -- without introducing false positives or
    missed catches.
    """

    @staticmethod
    def _seq_class():
        import collections.abc as abc

        class Seq(abc.Sequence):
            # Same public class, two internal layouts (forward vs reversed
            # storage). __dict__ differs; observable contents are identical.
            def __init__(self, data, reversed_storage=False):
                self._rev = reversed_storage
                self._buf = list(reversed(data)) if reversed_storage else list(data)

            def _logical(self):
                return list(reversed(self._buf)) if self._rev else list(self._buf)

            def __getitem__(self, i):
                return self._logical()[i]

            def __len__(self):
                return len(self._buf)
        return Seq

    def test_internal_repr_change_canonicalizes_equal(self):
        # FALSE-POSITIVE guard: internals differ, observable contents identical
        # -> must canonicalize EQUAL (would be reported equivalent).
        from probe.canonical import canonical
        Seq = self._seq_class()
        a = Seq([1, 2, 3], reversed_storage=False)
        b = Seq([1, 2, 3], reversed_storage=True)
        self.assertNotEqual(a.__dict__, b.__dict__)  # internals genuinely differ
        self.assertEqual(canonical(a), canonical(b))
        # And equality.py agrees.
        from probe.equality import equal
        self.assertTrue(equal(a, b))

    def test_different_observable_contents_not_equal(self):
        # MISSED-CATCH guard: genuinely different contents -> NOT equal.
        from probe.canonical import canonical
        from probe.equality import equal
        Seq = self._seq_class()
        a = Seq([1, 2, 3])
        c = Seq([1, 2, 9])
        self.assertNotEqual(canonical(a), canonical(c))
        self.assertFalse(equal(a, c))

    def test_sequence_snapshotted_by_contents_not_opaque(self):
        # A Sequence-like object snapshots by contents and is comparable (not
        # refused). Raises coverage for SortedList-style classes.
        from probe.canonical import canonical
        from probe.replay import _has_opaque
        Seq = self._seq_class()
        c = canonical(Seq([5, 6, 7]))
        self.assertEqual(c[0], "pub-obj")
        self.assertFalse(_has_opaque(c))

    def test_set_like_snapshotted_by_contents_order_independent(self):
        import collections.abc as abc

        from probe.canonical import canonical

        class SetLike(abc.Set):
            def __init__(self, items):
                self._items = set(items)

            def __contains__(self, x):
                return x in self._items

            def __iter__(self):
                return iter(self._items)

            def __len__(self):
                return len(self._items)
        self.assertEqual(canonical(SetLike([1, 2, 3])), canonical(SetLike([3, 2, 1])))
        self.assertNotEqual(canonical(SetLike([1, 2])), canonical(SetLike([1, 2, 3])))

    def test_public_attributes_included_in_snapshot(self):
        # Public (non-underscore) attributes are part of the observable snapshot;
        # differing public attrs -> not equal even with identical contents.
        from probe.canonical import canonical
        from probe.equality import equal
        Seq = self._seq_class()
        a = Seq([1, 2, 3])
        b = Seq([1, 2, 3])
        a.label = "x"
        b.label = "x"
        self.assertEqual(canonical(a), canonical(b))
        self.assertTrue(equal(a, b))
        b.label = "y"
        self.assertNotEqual(canonical(a), canonical(b))
        self.assertFalse(equal(a, b))

    def test_mapping_not_read_via_getitem(self):
        # LRU-safety: a Mapping must NOT be materialized via __getitem__ (which
        # would mutate cache state and corrupt the snapshot). It falls back to
        # private-state comparison instead.
        import collections.abc as abc

        from probe.canonical import canonical

        class LRUish(abc.Mapping):
            def __init__(self):
                self._d = {"x": 1}
                self.gets = 0

            def __getitem__(self, k):
                self.gets += 1            # side effect on read
                return self._d[k]

            def __iter__(self):
                return iter(self._d)

            def __len__(self):
                return len(self._d)
        m = LRUish()
        c = canonical(m)
        self.assertEqual(m.gets, 0, "snapshot mutated the mapping via __getitem__")
        self.assertNotEqual(c[0], "pub-obj")  # took the private/fallback path

    def test_opaque_with_no_observable_still_refuses(self):
        # No public interface, no introspectable state -> must REFUSE (opaque),
        # never guess.
        from probe.canonical import canonical
        from probe.replay import _has_opaque

        class Opaque:
            __slots__ = ()
        self.assertTrue(_has_opaque(canonical(Opaque())))

    def test_private_only_object_still_uses_private_state(self):
        # Non-sequence/non-set object with private state must NOT regress: it
        # still compares by private state (so SortedList-style private paths and
        # the existing "obj" tag are preserved).
        from probe.canonical import canonical

        class Vec:
            def __init__(self, x):
                self._x = x
        c = canonical(Vec(1))
        self.assertEqual(c[0], "obj")
        self.assertEqual(canonical(Vec(1)), canonical(Vec(1)))
        self.assertNotEqual(canonical(Vec(1)), canonical(Vec(2)))


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

        def loaded(obs):
            return {"loaded": True, "error": None, "obs": obs}
        eq = loaded([{"val": ["str", "Q"], "io": 0, "threads": 0}])
        self.assertEqual(replay._verdict(eq, eq, blobs)[0], "equivalent")
        diff = loaded([{"val": ["str", "Z"], "io": 0, "threads": 0}])
        self.assertEqual(replay._verdict(eq, diff, blobs)[0], "divergent")
        io = loaded([{"val": ["str", "Q"], "io": 1, "threads": 0}])
        self.assertEqual(replay._verdict(io, io, blobs)[0], "unverifiable")
        self.assertEqual(replay._verdict({"error": "boom"}, eq, blobs)[0], "error")


class TestCaptureReplayUnits(unittest.TestCase):
    def test_wrap_records_bound_values(self):
        import pickle

        from probe import _capture_hook as hook
        hook._records.clear()
        hook._seen.clear()

        def f(x, y=2):
            return x + y

        wrapped = hook._wrap(f, "m::f")
        self.assertEqual(wrapped(1), 3)       # transparent
        self.assertEqual(wrapped(1, 5), 6)
        vals = [pickle.loads(b) for b in hook._records["m::f"]]
        self.assertIn([1, 2], vals)           # defaults applied
        self.assertIn([1, 5], vals)

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


class TestHardening(unittest.TestCase):
    def test_iterator_materialization(self):
        from probe.canonical import canonical
        gen = (i for i in range(3))
        self.assertEqual(canonical(gen), ["iter", [["int", 0], ["int", 1], ["int", 2]]])
        self.assertEqual(canonical(map(int, ["1", "2"])), ["iter", [["int", 1], ["int", 2]]])
        self.assertEqual(canonical(range(2, 8, 2)), ["range", 2, 8, 2])

    def test_iterator_truncation_is_opaque(self):
        import itertools

        from probe.canonical import canonical
        from probe.replay import _has_opaque
        # an unbounded iterator must be refused, not materialized forever
        c = canonical(itertools.count())
        self.assertTrue(_has_opaque(c))

    def test_test_modules_excluded(self):
        from probe import _capture_hook as hook
        hook._MODULES = ("mypkg",)
        self.assertTrue(hook._module_matches("mypkg.core"))
        self.assertFalse(hook._module_matches("mypkg.tests.test_core"))
        self.assertFalse(hook._module_matches("mypkg.conftest"))
        self.assertFalse(hook._module_matches("mypkg.core_test"))

    def test_method_self_state_compared(self):
        # two observations differing only in post-call self state are not "same"
        from probe import replay
        a = {"val": ["none"], "io": 0, "threads": 0, "self_after": ["obj", "C", 1]}
        b = {"val": ["none"], "io": 0, "threads": 0, "self_after": ["obj", "C", 2]}
        self.assertFalse(replay._same(a, b))
        self.assertTrue(replay._same(a, dict(a)))

    def test_systemexit_is_observable(self):
        from probe import harness

        def bail(x: int) -> int:
            raise SystemExit(2)
        o = harness.observe(bail, (1,))
        self.assertFalse(o.returned)
        self.assertIn("SystemExit", o.exception)


class TestCallableRepresentation(unittest.TestCase):
    def test_canonical_callables_and_classes(self):
        from probe.canonical import canonical

        def f(x):
            return x
        # same function -> equal; different -> not; functions inside state too
        self.assertEqual(canonical(f), canonical(f))
        self.assertNotEqual(canonical(f), canonical(len))
        self.assertEqual(canonical({"cb": f}), canonical({"cb": f}))
        self.assertEqual(canonical(dict), canonical(dict))
        self.assertNotEqual(canonical(dict), canonical(list))
        # a stored function no longer makes a container opaque
        from probe.replay import _has_opaque
        self.assertFalse(_has_opaque(canonical({"handler": f, "n": 1})))

    def test_equality_compares_callables_by_identity(self):
        from probe.equality import equal

        def g(x):
            return x
        self.assertTrue(equal({"cb": g}, {"cb": g}))
        self.assertFalse(equal({"cb": g}, {"cb": len}))


class TestChangedDetection(unittest.TestCase):
    def test_path_to_module(self):
        from probe.extract import _path_to_module
        self.assertEqual(_path_to_module("src/pkg/__init__.py"), "pkg")
        self.assertEqual(_path_to_module("pkg/sub.py"), "pkg.sub")
        self.assertEqual(_path_to_module("mod.py"), "mod")

    def test_func_segments_includes_methods(self):
        from probe.extract import _func_segments
        src = "def f(x):\n    return x\nclass C:\n    def m(self):\n        return 1\n"
        segs = _func_segments(src)
        self.assertIn("f", segs)
        self.assertIn("C.m", segs)

    def test_func_segments_detects_body_change(self):
        from probe.extract import _func_segments
        a = _func_segments("def f(x):\n    return x\n")
        b = _func_segments("def f(x):\n    return x + 1\n")
        self.assertNotEqual(a["f"], b["f"])


class TestProductionCapture(unittest.TestCase):
    def test_capture_from_arbitrary_command(self):
        import os
        import sys
        import tempfile

        from probe.capture import capture_command
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "mymod.py"), "w") as f:
            f.write("def f(x):\n    return x * 2\n")
        # capture from a plain script run (not a test runner); the target module
        # is imported, so targeted wrapping records its calls.
        code = "import mymod\nfor i in range(3):\n    mymod.f(i)\n"
        recs = capture_command(["mymod"], [sys.executable, "-c", code], cwd=d)
        self.assertIn("mymod::f", recs)
        self.assertEqual(len(recs["mymod::f"]), 3)


class TestEntryScriptCapture(unittest.TestCase):
    """Capturing functions/methods defined in the entry-point script (__main__),
    which the import hook cannot wrap because __main__ is executed, not imported.
    A scoped sys.setprofile records them, keyed identically to the import path."""

    def _run(self, body, modules=None):
        import os
        import sys
        import tempfile

        from probe.capture import capture_command
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "the_script.py"), "w") as f:
            f.write(body)
        return capture_command(modules or ["__main__"],
                               [sys.executable, "the_script.py"], cwd=d)

    def test_top_level_function_captured_as_main(self):
        import pickle
        recs = self._run(
            "def add(x, y=10):\n"
            "    return x + y\n"
            "if __name__ == '__main__':\n"
            "    add(1)\n"
            "    add(2, 3)\n"
            "    add(2, 3)\n"  # duplicate -> deduped
        )
        self.assertIn("__main__::add", recs)
        vals = sorted(pickle.loads(b) for b in recs["__main__::add"])
        # defaults applied (y=10) and duplicates collapsed
        self.assertEqual(vals, [[1, 10], [2, 3]])

    def test_static_method_keyed_with_qualname(self):
        import pickle
        recs = self._run(
            "class Calc:\n"
            "    @staticmethod\n"
            "    def helper(z):\n"
            "        return z - 1\n"
            "if __name__ == '__main__':\n"
            "    Calc.helper(9)\n"
        )
        self.assertIn("__main__::Calc.helper", recs)
        self.assertEqual([pickle.loads(b) for b in recs["__main__::Calc.helper"]], [[9]])

    def test_varargs_records_positional_only(self):
        import pickle
        recs = self._run(
            "def variadic(a, *rest, **kw):\n"
            "    return a\n"
            "if __name__ == '__main__':\n"
            "    variadic(7, 8, 9, k=1)\n"
        )
        self.assertIn("__main__::variadic", recs)
        # mirrors _record's varargs fallback: positional values only, kwargs dropped
        self.assertEqual([pickle.loads(b) for b in recs["__main__::variadic"]], [[7, 8, 9]])

    def test_class_body_and_closures_excluded(self):
        recs = self._run(
            "def outer():\n"
            "    def inner(z):\n"  # <locals> closure -> skipped
            "        return z\n"
            "    return inner(1)\n"
            "class C:\n"
            "    X = 1\n"  # class body -> not a function, must not be recorded
            "if __name__ == '__main__':\n"
            "    outer()\n"
        )
        self.assertIn("__main__::outer", recs)
        self.assertNotIn("__main__::C", recs)            # class body excluded
        self.assertNotIn("__main__::outer.<locals>.inner", recs)  # closure excluded
        for k in recs:
            self.assertNotIn("<", k)

    def test_record_format_is_replay_compatible(self):
        # Each value must be a pickled positional list so replay can call
        # fn(*values) (same format as the import-hook path).
        import pickle
        recs = self._run(
            "def f(a, b):\n"
            "    return a - b\n"
            "if __name__ == '__main__':\n"
            "    f(5, 2)\n"
        )
        blobs = recs["__main__::f"]
        self.assertEqual(len(blobs), 1)
        values = pickle.loads(blobs[0])
        self.assertIsInstance(values, list)
        self.assertEqual(values, [5, 2])
        # round-trips through replay's base64 transport unchanged
        import base64
        b64 = base64.b64encode(blobs[0]).decode("ascii")
        self.assertEqual(pickle.loads(base64.b64decode(b64)), [5, 2])

    def test_profile_not_installed_for_imported_targets(self):
        # Soundness/perf guard: when the target is only an imported module (not
        # the entry script), the scoped profile must stay OFF — no global
        # setprofile overhead on a test-runner invocation.
        import os
        import sys
        import tempfile

        from probe.capture import capture_command
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "lib.py"), "w") as f:
            f.write("def g(x):\n    return x + 1\n")
        with open(os.path.join(d, "probe_state.txt"), "w") as f:
            f.write("")
        code = (
            "import sys, lib\n"
            "lib.g(1)\n"
            "import probe._capture_hook as h\n"
            "open('probe_state.txt','w').write('%s,%s' % "
            "(h._profile_installed, sys.getprofile() is not None))\n"
        )
        recs = capture_command(["lib"], [sys.executable, "-c", code], cwd=d)
        self.assertIn("lib::g", recs)  # import hook still works
        with open(os.path.join(d, "probe_state.txt")) as f:
            state = f.read()
        self.assertEqual(state, "False,False")


class TestEntryScriptCaptureUnit(unittest.TestCase):
    def test_frame_values_matches_record_format(self):
        import pickle

        from probe import _capture_hook as hook
        captured = {}

        def f(x, y=2):
            # at entry, reconstruct values from this very frame
            import sys as _sys
            captured["vals"] = hook._frame_values(_sys._getframe())
            return x + y

        f(1)
        self.assertEqual(captured["vals"], [1, 2])  # defaults applied, in order
        f(3, 4)
        self.assertEqual(captured["vals"], [3, 4])
        # confirm picklability (replay transports pickled blobs)
        self.assertEqual(pickle.loads(pickle.dumps(captured["vals"])), [3, 4])


class TestProcReaper(unittest.TestCase):
    def test_run_captures_output(self):
        import sys

        from probe import _procs
        r = _procs.run([sys.executable, "-c", "print('hi')"],
                       capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("hi", r.stdout)

    def test_run_timeout_raises_and_kills(self):
        import subprocess
        import sys

        from probe import _procs
        with self.assertRaises(subprocess.TimeoutExpired):
            _procs.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)

    def test_terminate_all_reaps_tracked_child(self):
        import subprocess
        import sys

        from probe import _procs
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             start_new_session=True)
        with _procs._lock:
            _procs._live.add(p)
        _procs._terminate_all()
        p.wait(timeout=5)
        self.assertIsNotNone(p.returncode)  # child was killed, not orphaned


class TestMutation(unittest.TestCase):
    def test_reaches_edge_values_tests_miss(self):
        from probe._mutate import value_mutations
        # the whole point: mutating a normal seed reaches the edge inputs that
        # break things (0 for ints, "" for strings) which tests often skip.
        self.assertIn(0, value_mutations(3))
        self.assertIn("", value_mutations("hi"))
        self.assertEqual(value_mutations(True), [False])

    def test_excludes_original_and_is_type_aware(self):
        from probe._mutate import value_mutations
        self.assertNotIn(5, value_mutations(5))
        self.assertTrue(all(isinstance(x, int) for x in value_mutations(5)))
        self.assertTrue(all(isinstance(x, str) for x in value_mutations("x")))

    def test_arg_set_mutations_perturb_one_position(self):
        from probe._mutate import arg_set_mutations
        muts = arg_set_mutations((3, "hi"))
        self.assertIn((0, "hi"), muts)        # first position -> 0
        self.assertIn((3, ""), muts)          # second position -> ""
        # each mutation differs from the seed in exactly one position
        for m in muts:
            diffs = sum(1 for a, b in zip(m, (3, "hi")) if a != b)
            self.assertEqual(diffs, 1)

    def test_havoc_introduces_novel_chars(self):
        import random

        from probe._mutate import alphabet_from, mutate_one
        # havoc (byte-level) mutation can introduce characters absent from the
        # seed — the thing the fixed one-shot set cannot do.
        alpha = alphabet_from([["abc"]])
        rng = random.Random(0)
        produced = set()
        for _ in range(300):
            produced.update(mutate_one(["abc"], rng, alpha)[0])
        self.assertTrue(produced - set("abc"))

    def test_mutate_one_keeps_arity(self):
        import random

        from probe._mutate import mutate_one
        m = mutate_one([3, "hi"], random.Random(0), list("xyz"))
        self.assertEqual(len(m), 2)

    def test_alphabet_includes_seed_and_base(self):
        from probe._mutate import alphabet_from
        a = alphabet_from([["q!"]])
        self.assertIn("q", a)   # from seed
        self.assertIn("!", a)   # from seed
        self.assertIn("a", a)   # from base alphabet

    def test_tokens_from_source_mines_literals(self):
        from probe._mutate import tokens_from_source
        src = 'def f(c):\n    if c == "deploy":\n        return 42\n    return 3.5\n'
        toks = tokens_from_source(src)
        self.assertIn("deploy", toks["str"])
        self.assertIn(42, toks["int"])
        self.assertIn(3.5, toks["float"])
        # bools are not mined as int tokens
        self.assertNotIn(True, toks["int"])

    def test_tokens_from_source_bad_syntax(self):
        from probe._mutate import tokens_from_source
        self.assertEqual(tokens_from_source("def ::: bad"),
                         {"str": [], "int": [], "float": []})

    def test_crossover_combines_two_parents(self):
        import random

        from probe._mutate import mutate_one
        # two parents, each "rich" in one position only; crossover must be able to
        # produce a child rich in BOTH (a from p1, b from p2).
        p1 = ["A" * 8, "x"]
        p2 = ["y", "B" * 8]
        rng = random.Random(0)
        hit = False
        for _ in range(400):
            c = mutate_one(p1, rng, list("xyz"), None, p2)
            if len(c) == 2 and c[0].count("A") >= 8 and c[1].count("B") >= 8:
                hit = True
                break
        self.assertTrue(hit)

    def test_crossover_skipped_without_partner(self):
        import random

        from probe._mutate import mutate_one
        # no partner -> never produces a both-rich child from a single parent
        p1 = ["A" * 8, "x"]
        rng = random.Random(1)
        for _ in range(400):
            c = mutate_one(p1, rng, list("xyz"), None, None)
            self.assertFalse(c[1].count("B") >= 8)

    def test_structural_list_ops(self):
        import random

        from probe._mutate import mutate_one
        rng = random.Random(0)
        grew_by_more_than_one = reversed_ = False
        base = [1, 2, 3]
        for _ in range(400):
            out = mutate_one([list(base)], rng, list("xyz"))[0]
            if len(out) - len(base) >= 2:          # dup_range / multi-insert
                grew_by_more_than_one = True
            if out == base[::-1]:                  # reverse op
                reversed_ = True
        self.assertTrue(grew_by_more_than_one)
        self.assertTrue(reversed_)

    def test_structural_dict_ops(self):
        import random

        from probe._mutate import mutate_one
        rng = random.Random(0)
        grew = shrank = False
        base = {"a": 1, "b": 2}
        for _ in range(400):
            out = mutate_one([dict(base)], rng, list("xyz"))[0]
            if len(out) > len(base):               # add key
                grew = True
            if len(out) < len(base):               # del key
                shrank = True
        self.assertTrue(grew)
        self.assertTrue(shrank)

    def test_mutate_one_injects_dictionary_token(self):
        import random

        from probe._mutate import mutate_one
        # a magic string havoc would essentially never spell; with it in the
        # dictionary, token injection produces it exactly.
        tokens = {"str": ["deploy"], "int": [], "float": []}
        rng = random.Random(0)
        produced = set()
        for _ in range(300):
            produced.add(mutate_one(["status"], rng, list("xyz"), tokens)[0])
        self.assertIn("deploy", produced)


class TestBucketing(unittest.TestCase):
    def test_bucket_boundaries(self):
        from probe._cgfuzz_worker import _bucket
        self.assertEqual([_bucket(n) for n in (1, 2, 3)], [1, 2, 3])
        self.assertEqual([_bucket(n) for n in (4, 7)], [4, 4])
        self.assertEqual([_bucket(n) for n in (8, 15)], [8, 8])
        self.assertEqual([_bucket(n) for n in (16, 31)], [16, 16])
        self.assertEqual([_bucket(n) for n in (32, 127)], [32, 32])
        self.assertEqual([_bucket(n) for n in (128, 5000)], [128, 128])

    def test_bucket_distinguishes_loop_depth(self):
        # same edge, different hit counts -> different coverage keys
        from probe._cgfuzz_worker import _bucket
        edge = (10, 11)
        self.assertNotEqual((edge, _bucket(2)), (edge, _bucket(5)))


class TestWorktreePrep(unittest.TestCase):
    def _git(self, repo, *args):
        import subprocess
        subprocess.check_call(["git", "-C", repo] + list(args),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_copies_gitignored_generated_module_into_worktree(self):
        import subprocess
        import tempfile

        from probe import replay
        repo = tempfile.mkdtemp(prefix="probe_test_repo_")
        try:
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "t@t.t")
            self._git(repo, "config", "user.name", "t")
            os.makedirs(os.path.join(repo, "foo"))
            # package imports a build-generated module...
            with open(os.path.join(repo, "foo", "__init__.py"), "w") as f:
                f.write("from foo._version import __version__\n")
            # ...which is git-ignored (setuptools-scm/hatch-vcs style)
            with open(os.path.join(repo, ".gitignore"), "w") as f:
                f.write("foo/_version.py\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "base")
            # generated AFTER commit, not tracked
            with open(os.path.join(repo, "foo", "_version.py"), "w") as f:
                f.write("__version__ = '1.2.3'\n")

            # a plain worktree lacks the generated file; prep must copy it in
            wt = replay._add_worktree(repo, "HEAD", modules=["foo"])
            try:
                gen = os.path.join(wt, "foo", "_version.py")
                self.assertTrue(os.path.isfile(gen),
                                "generated _version.py not copied into worktree")
                # and the package now imports there
                out = subprocess.check_output(
                    [sys.executable, "-c",
                     "import foo;print(foo.__version__)"],
                    cwd=wt, text=True).strip()
                self.assertEqual(out, "1.2.3")
            finally:
                replay._rm_worktree(repo, wt)
        finally:
            import shutil
            shutil.rmtree(repo, ignore_errors=True)

    def test_no_modules_means_no_copy(self):
        from probe import replay
        # _pkg_dirs returns nothing for unknown modules -> safe no-op
        self.assertEqual(replay._copy_generated_sources(".", ".", ["nope_xyz"]), [])


class TestCaptureGuards(unittest.TestCase):
    def test_benchmark_disabled_for_pytest(self):
        from probe.capture import _maybe_disable_benchmark
        for cmd in (["python", "-m", "pytest", "-q"], ["pytest"], ["pytest3", "-x"]):
            out, skipped = _maybe_disable_benchmark(cmd)
            self.assertTrue(skipped, cmd)
            self.assertIn("no:benchmark", " ".join(out))

    def test_benchmark_untouched_for_non_pytest(self):
        from probe.capture import _maybe_disable_benchmark
        out, skipped = _maybe_disable_benchmark(["python", "-m", "unittest"])
        self.assertFalse(skipped)
        self.assertNotIn("no:benchmark", " ".join(out))

    def test_benchmark_idempotent_and_optout(self):
        from probe.capture import _maybe_disable_benchmark
        _, s = _maybe_disable_benchmark(["pytest", "-p", "no:benchmark"])
        self.assertFalse(s)
        os.environ["PROBE_KEEP_BENCHMARK"] = "1"
        try:
            _, s2 = _maybe_disable_benchmark(["pytest"])
            self.assertFalse(s2)
        finally:
            del os.environ["PROBE_KEEP_BENCHMARK"]

    def test_capture_budget_stops_runaway(self):
        from probe import capture
        old = capture._CAPTURE_TIMEOUT
        capture._CAPTURE_TIMEOUT = 2
        try:
            t0 = time.monotonic()
            rec = capture.capture_command(
                ["nomod_xyz"],
                [sys.executable, "-c", "import time; time.sleep(60)"])
            dt = time.monotonic() - t0
            self.assertLess(dt, 30, "budget did not stop a 60s runaway")
            self.assertEqual(rec, {})
        finally:
            capture._CAPTURE_TIMEOUT = old


class TestCLI(unittest.TestCase):
    def test_dispatch(self):
        import io
        from contextlib import redirect_stdout

        from probe import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["--help"]), 0)
            self.assertEqual(cli.main([]), 2)
            self.assertEqual(cli.main(["bogus-cmd"]), 2)
        out = buf.getvalue()
        self.assertIn("probe verify", out)
        self.assertIn("probe attach", out)


class TestAttach(unittest.TestCase):
    def test_resolve_signal_forms(self):
        import signal

        from probe.attach import _resolve_signal
        self.assertEqual(_resolve_signal("SIGUSR1"), int(signal.SIGUSR1))
        self.assertEqual(_resolve_signal("USR1"), int(signal.SIGUSR1))
        self.assertEqual(_resolve_signal(str(int(signal.SIGUSR1))),
                         int(signal.SIGUSR1))
        with self.assertRaises(ValueError):
            _resolve_signal("NOT_A_SIGNAL")

    def test_attach_no_such_pid_exits_1(self):
        import io
        from contextlib import redirect_stderr

        from probe import attach
        # A PID that almost certainly doesn't exist.
        buf = io.StringIO()
        with redirect_stderr(buf):
            code = attach.main(["2147483646"])
        self.assertEqual(code, 1)
        self.assertIn("no process", buf.getvalue())

    def test_attach_unknown_signal_exits_2(self):
        import io
        import os
        from contextlib import redirect_stderr

        from probe import attach
        buf = io.StringIO()
        with redirect_stderr(buf):
            code = attach.main([str(os.getpid()), "--signal", "NOPE"])
        self.assertEqual(code, 2)


class TestOnDemandFlush(unittest.TestCase):
    def test_resolve_flush_signal(self):
        import signal

        from probe import _capture_hook as hook
        old = hook._FLUSH_SIGNAL_NAME
        try:
            hook._FLUSH_SIGNAL_NAME = "SIGUSR1"
            self.assertEqual(hook._resolve_flush_signal(), int(signal.SIGUSR1))
            hook._FLUSH_SIGNAL_NAME = "USR2"
            self.assertEqual(hook._resolve_flush_signal(), int(signal.SIGUSR2))
            for disabled in ("", "none", "off", "0"):
                hook._FLUSH_SIGNAL_NAME = disabled
                self.assertIsNone(hook._resolve_flush_signal())
            hook._FLUSH_SIGNAL_NAME = "TOTALLY_BOGUS"
            self.assertIsNone(hook._resolve_flush_signal())
        finally:
            hook._FLUSH_SIGNAL_NAME = old

    def test_signal_handler_installed_when_configured(self):
        import signal

        from probe import _capture_hook as hook
        old_name = hook._FLUSH_SIGNAL_NAME
        prev = signal.getsignal(signal.SIGUSR2)
        try:
            hook._FLUSH_SIGNAL_NAME = "SIGUSR2"
            signum = hook._install_flush_signal()
            self.assertEqual(signum, int(signal.SIGUSR2))
            handler = signal.getsignal(signal.SIGUSR2)
            self.assertTrue(callable(handler))
            self.assertIsNot(handler, prev)
        finally:
            signal.signal(signal.SIGUSR2, prev)
            hook._FLUSH_SIGNAL_NAME = old_name

    def test_signal_dump_from_running_hook_process(self):
        """Spawn a long-running subprocess under the capture hook, send the flush
        signal, and confirm cap-<pid>.pkl appears with the captured call — the
        process is never stopped to do it."""
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        import time

        if sys.platform == "win32":
            self.skipTest("POSIX signals not available on Windows")

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        work = tempfile.mkdtemp(prefix="probe_attach_test_")
        try:
            cap_dir = os.path.join(work, "caps")
            os.makedirs(cap_dir)
            # sitecustomize installs the hook for the child.
            with open(os.path.join(work, "sitecustomize.py"), "w") as f:
                f.write("import probe._capture_hook\n")
            # a target module to capture + a long-running loop that calls it.
            with open(os.path.join(work, "mymod.py"), "w") as f:
                f.write("def f(x):\n    return x * 2\n")
            script = (
                "import time, mymod\n"
                "mymod.f(7)\n"            # one captured call, then idle
                "while True:\n"
                "    time.sleep(0.05)\n")

            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                [work, repo_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
            env["PROBE_CAPTURE_DIR"] = cap_dir
            env["PROBE_CAPTURE_MODULES"] = "mymod"
            # disable periodic flush so the ONLY way a file appears is our signal
            env["PROBE_CAPTURE_FLUSH_SECS"] = "0"
            env["PROBE_CAPTURE_FLUSH_SIGNAL"] = "SIGUSR1"

            proc = subprocess.Popen(
                [sys.executable, "-c", script], env=env, cwd=work)
            try:
                from probe.attach import attach
                # Let the child fully import and install the handler before any
                # signal. SIGUSR1's default disposition is to terminate, so a
                # signal that races ahead of install() would kill the child.
                time.sleep(1.5)
                if proc.poll() is not None:
                    self.skipTest("child exited during startup; cannot test")
                import pickle
                deadline = time.time() + 8.0
                cap_path = os.path.join(cap_dir, "cap-%d.pkl" % proc.pid)
                recs = None
                while time.time() < deadline:
                    time.sleep(0.2)
                    if proc.poll() is not None:
                        self.skipTest("child exited early; cannot test signal flush")
                    # (re)send the flush signal; handler -> waiter thread -> flush
                    try:
                        attach(proc.pid, "SIGUSR1")
                    except ProcessLookupError:
                        break
                    # The file may exist mid-write; only accept it once it loads
                    # cleanly with the expected key (avoids an EOFError race).
                    if os.path.exists(cap_path):
                        try:
                            with open(cap_path, "rb") as f:
                                loaded = pickle.load(f)
                        except (EOFError, pickle.UnpicklingError):
                            continue
                        if "mymod::f" in loaded:
                            recs = loaded
                            break
                self.assertIsNotNone(recs, "no readable cap file after flush signal")
                vals = [pickle.loads(b) for b in recs["mymod::f"]]
                self.assertIn([7], vals)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        finally:
            shutil.rmtree(work, ignore_errors=True)


class TestVersionSupport(unittest.TestCase):
    def test_requires_python_from_pyproject(self):
        import os
        import tempfile

        from probe.verify import _requires_python
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "pyproject.toml"), "w") as f:
            f.write('[project]\nname = "x"\nrequires-python = ">= 3.10"\n')
        self.assertEqual(_requires_python(d), (3, 10))
        self.assertIsNone(_requires_python(tempfile.mkdtemp()))  # nothing declared

    def test_requires_python_from_setup_cfg(self):
        import os
        import tempfile

        from probe.verify import _requires_python
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "setup.cfg"), "w") as f:
            f.write("[options]\npython_requires = >=3.8\n")
        self.assertEqual(_requires_python(d), (3, 8))

    def test_py_version_of_self(self):
        import sys

        from probe.verify import _py_version
        self.assertEqual(_py_version(sys.executable), tuple(sys.version_info[:2]))

    def test_replay_arg_cap_is_read(self):
        from probe import replay
        self.assertIsInstance(replay._REPLAY_MAX_ARGS, int)
        self.assertGreater(replay._REPLAY_MAX_ARGS, 0)


if __name__ == "__main__":
    unittest.main()
