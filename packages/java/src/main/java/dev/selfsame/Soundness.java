package dev.selfsame;

import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * The soundness gate and the observation comparator. Mirrors
 * packages/python/probe/replay.py (_has_opaque, _unsound, _same) and implements
 * SPEC/protocol.md sections 6 and 8. Validated by the cross-language conformance
 * suite (SPEC/conformance). Operates on parsed-JSON structures (List/Map/scalars).
 */
public final class Soundness {
    private Soundness() {}

    /** Structural equality of two canonical forms (Lists of Lists/primitives). */
    @SuppressWarnings("unchecked")
    public static boolean deepEqual(Object a, Object b) {
        if (a == b) return true;
        if (a instanceof List && b instanceof List) {
            List<Object> la = (List<Object>) a, lb = (List<Object>) b;
            if (la.size() != lb.size()) return false;
            for (int i = 0; i < la.size(); i++) if (!deepEqual(la.get(i), lb.get(i))) return false;
            return true;
        }
        return Objects.equals(a, b);
    }

    /** True iff an `opaque` tag appears anywhere in a canonical form's tree. */
    @SuppressWarnings("unchecked")
    public static boolean hasOpaque(Object form) {
        if (!(form instanceof List)) return false;
        List<Object> l = (List<Object>) form;
        if (!l.isEmpty() && "opaque".equals(l.get(0))) return true;
        for (Object el : l) if (el instanceof List && hasOpaque(el)) return true;
        return false;
    }

    private static long asLong(Object o) {
        if (o instanceof Number) return ((Number) o).longValue();
        return 0;
    }

    /**
     * Refusal reason for a list of observations, or null if verifiable. Priority
     * order is normative (SPEC section 6). Each observation is a Map.
     */
    public static String unsound(List<Map<String, Object>> obsList) {
        for (Map<String, Object> o : obsList) {
            if (Boolean.TRUE.equals(o.get("nondet"))) return "nondeterministic";
            if (asLong(o.getOrDefault("io", 0L)) > 0) return "uncontrolled-io";
            if (asLong(o.getOrDefault("threads", 0L)) > 0) return "concurrency";
            if (o.containsKey("val") && hasOpaque(o.get("val"))) return "opaque-return";
            Object self = o.get("self_after");
            if (self != null && hasOpaque(self)) return "opaque-state";
        }
        return null;
    }

    /**
     * Two observations are equal iff: exception-ness matches; if both raised, the
     * error type names match; otherwise the val canonical forms match; AND the
     * post-call receiver state matches (SPEC section 8).
     */
    public static boolean same(Map<String, Object> a, Map<String, Object> b) {
        boolean aExc = a.containsKey("exc");
        boolean bExc = b.containsKey("exc");
        if (aExc != bExc) return false;
        if (aExc) {
            if (!Objects.equals(a.get("exc"), b.get("exc"))) return false;
        } else if (!deepEqual(a.get("val"), b.get("val"))) {
            return false;
        }
        Object aSelf = a.get("self_after");
        Object bSelf = b.get("self_after");
        if (aSelf == null && bSelf == null) return true;
        return deepEqual(aSelf, bSelf);
    }
}
