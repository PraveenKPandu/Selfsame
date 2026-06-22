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
                deadline = time.time() + 8.0
                cap_path = os.path.join(cap_dir, "cap-%d.pkl" % proc.pid)
                got = False
                while time.time() < deadline:
                    time.sleep(0.2)
                    if proc.poll() is not None:
                        self.skipTest("child exited early; cannot test signal flush")
                    # (re)send the flush signal; handler -> waiter thread -> flush
                    try:
                        attach(proc.pid, "SIGUSR1")
                    except ProcessLookupError:
                        break
                    if os.path.exists(cap_path):
                        got = True
                        break
                self.assertTrue(got, "no cap file produced after sending flush signal")

                import pickle
                with open(cap_path, "rb") as f:
                    recs = pickle.load(f)
                self.assertIn("mymod::f", recs)
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
