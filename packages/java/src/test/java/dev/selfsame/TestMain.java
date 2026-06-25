package dev.selfsame;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.Instant;
import java.time.LocalDate;

/**
 * Dependency-free test runner (no JUnit, so the package needs no test framework
 * to download). Runs the cross-language conformance vectors (SPEC/conformance)
 * through Soundness, plus Java-specific canonical golden tests. Exit code is
 * non-zero on any failure.
 */
public final class TestMain {
    private static int failures = 0;
    private static int checks = 0;

    public static void main(String[] args) throws Exception {
        conformance();
        canonicalGolden();
        System.out.println();
        if (failures == 0) {
            System.out.println("OK — " + checks + " checks passed");
        } else {
            System.out.println("FAILED — " + failures + " of " + checks + " checks failed");
            System.exit(1);
        }
    }

    // ---- tiny assert helpers ----
    private static void eq(Object actual, Object expected, String msg) {
        checks++;
        if (!Soundness.deepEqual(actual, expected)) {
            failures++;
            System.out.println("not ok - " + msg);
            System.out.println("    expected: " + Json.serialize(expected));
            System.out.println("    actual:   " + Json.serialize(actual));
        }
    }

    private static void truth(boolean cond, String msg) {
        checks++;
        if (!cond) { failures++; System.out.println("not ok - " + msg); }
    }

    // ---- builders matching canonical's in-memory shapes ----
    private static List<Object> L(Object... xs) { return new ArrayList<>(Arrays.asList(xs)); }

    // ---- conformance ----
    @SuppressWarnings("unchecked")
    private static void conformance() throws Exception {
        Path dir = specDir();
        if (dir == null) {
            System.out.println("# SPEC/conformance not found — skipping conformance");
            return;
        }
        Map<String, Object> comp = (Map<String, Object>) Json.parse(
                Files.readString(dir.resolve("canonical-comparison.json")));
        for (Object co : (List<Object>) comp.get("cases")) {
            Map<String, Object> c = (Map<String, Object>) co;
            boolean got = Soundness.same((Map<String, Object>) c.get("a"), (Map<String, Object>) c.get("b"));
            truth(got == (Boolean) c.get("same"), "comparison vector " + c.get("name"));
        }
        Map<String, Object> snd = (Map<String, Object>) Json.parse(
                Files.readString(dir.resolve("soundness-verdicts.json")));
        for (Object co : (List<Object>) snd.get("cases")) {
            Map<String, Object> c = (Map<String, Object>) co;
            List<Map<String, Object>> obs = new ArrayList<>();
            for (Object o : (List<Object>) c.get("observations")) obs.add((Map<String, Object>) o);
            Object reason = Soundness.unsound(obs);
            truth(java.util.Objects.equals(reason, c.get("reason")), "soundness vector " + c.get("name"));
        }
        System.out.println("# conformance vectors ran");
    }

    // ---- Java-specific value -> canonical golden tests ----
    private static void canonicalGolden() {
        eq(Canonical.canonical(null), L("none"), "null");
        eq(Canonical.canonical(true), L("bool", true), "bool");
        eq(Canonical.canonical(42), L("int", 42L), "int (Integer)");
        eq(Canonical.canonical(42L), L("int", 42L), "int (Long)");
        eq(Canonical.canonical(new BigInteger("42")), L("int", 42L), "BigInteger");
        eq(Canonical.canonical(1.5), L("float", 1.5), "double");
        eq(Canonical.canonical(Double.NaN), L("float", "nan"), "NaN");
        eq(Canonical.canonical(Double.POSITIVE_INFINITY), L("float", "inf"), "inf");
        eq(Canonical.canonical(-0.0), L("float", 0.0), "-0.0 normalized");
        eq(Canonical.canonical(-0.0), Canonical.canonical(0.0), "-0.0 equals 0.0");
        eq(Canonical.canonical("hi"), L("str", "hi"), "string");
        eq(Canonical.canonical(new BigDecimal("1.50")), L("decimal", "1.50"), "BigDecimal keeps scale");
        eq(Canonical.canonical(new byte[]{1, 2}), L("bytes", L(1L, 2L)), "byte[]");
        eq(Canonical.canonical(Arrays.asList(1, "a")), L("list", L(L("int", 1L), L("str", "a"))), "List");

        // Set order-normalized: {2,1} == {1,2}
        eq(Canonical.canonical(new LinkedHashSet<>(Arrays.asList(2, 1))),
           Canonical.canonical(new LinkedHashSet<>(Arrays.asList(1, 2))), "Set order-normalized");

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 1);
        eq(Canonical.canonical(m), L("dict", L(L(L("str", "a"), L("int", 1L)))), "Map -> dict");

        eq(Canonical.canonical(Instant.parse("2020-01-01T00:00:00Z")),
           L("datetime", "2020-01-01T00:00:00Z"), "Instant");
        eq(Canonical.canonical(LocalDate.parse("2020-01-01")), L("date", "2020-01-01"), "LocalDate");

        eq(Canonical.canonical(Color.RED), L("enum", Color.class.getName(), "RED"), "enum");

        eq(Canonical.canonical(new Counter(3)),
           L("obj", "Counter", L("dict", L(L(L("str", "n"), L("int", 3L))))), "POJO by state");
        // empty-but-present state still comparable
        eq(Canonical.canonical(new Empty()), Canonical.canonical(new Empty()), "empty state comparable");
    }

    enum Color { RED, BLUE }
    static final class Counter { final int n; Counter(int n) { this.n = n; } }
    static final class Empty { }

    private static Path specDir() {
        Path d = Paths.get("").toAbsolutePath();
        for (int i = 0; i < 8 && d != null; i++) {
            Path cand = d.resolve("SPEC").resolve("conformance").resolve("cases");
            if (Files.isDirectory(cand)) return cand;
            d = d.getParent();
        }
        return null;
    }
}
