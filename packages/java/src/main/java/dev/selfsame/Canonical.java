package dev.selfsame;

import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * JSON-serializable canonical form of a Java value, implementing SPEC/protocol.md
 * section 4 for the JVM: two values share a canonical form iff they are
 * observationally indistinguishable. Mirrors packages/python/probe/canonical.py.
 *
 * Output uses the same in-memory shapes Json.parse yields (List/String/Long/
 * Double/Boolean/null), so it compares directly via Soundness.deepEqual.
 */
public final class Canonical {
    private Canonical() {}

    private static final int MAX_DEPTH = 60;

    public static Object canonical(Object v) { return canonical(v, 0); }

    private static List<Object> list(Object... xs) {
        List<Object> l = new ArrayList<>(xs.length);
        for (Object x : xs) l.add(x);
        return l;
    }

    private static Object canonical(Object v, int depth) {
        if (depth > MAX_DEPTH) return list("maxdepth");
        if (v == null) return list("none");

        if (v instanceof Boolean) return list("bool", v);

        // Integers (note: check before nothing else collides).
        if (v instanceof Byte || v instanceof Short || v instanceof Integer || v instanceof Long) {
            return list("int", ((Number) v).longValue());
        }
        if (v instanceof BigInteger) {
            BigInteger b = (BigInteger) v;
            if (b.bitLength() < 63) return list("int", b.longValue());
            return list("int", b.toString());
        }

        if (v instanceof Float || v instanceof Double) {
            double d = ((Number) v).doubleValue();
            if (Double.isNaN(d)) return list("float", "nan");
            if (d == Double.POSITIVE_INFINITY) return list("float", "inf");
            if (d == Double.NEGATIVE_INFINITY) return list("float", "-inf");
            if (d == 0.0) return list("float", 0.0); // normalizes -0.0
            return list("float", d);
        }

        if (v instanceof Character) return list("str", v.toString());
        if (v instanceof String) return list("str", v);

        if (v instanceof BigDecimal) return list("decimal", v.toString());

        if (v instanceof byte[]) {
            byte[] a = (byte[]) v;
            List<Object> items = new ArrayList<>(a.length);
            for (byte x : a) items.add((long) (x & 0xff));
            return list("bytes", items);
        }

        // java.time value types by observable (ISO) form.
        if (v instanceof Instant || v instanceof OffsetDateTime || v instanceof ZonedDateTime
                || v instanceof LocalDateTime) {
            return list("datetime", v.toString());
        }
        if (v instanceof LocalDate) return list("date", v.toString());
        if (v instanceof LocalTime) return list("time", v.toString());
        if (v instanceof java.util.Date) return list("datetime", ((java.util.Date) v).toInstant().toString());
        if (v instanceof Duration) {
            Duration d = (Duration) v;
            return list("timedelta", d.getSeconds(), (long) d.getNano());
        }

        if (v instanceof Enum) {
            Enum<?> e = (Enum<?>) v;
            return list("enum", e.getDeclaringClass().getName(), e.name());
        }
        if (v instanceof Class) return list("class", ((Class<?>) v).getName());

        // Arrays (any component type) -> list.
        if (v.getClass().isArray()) {
            int len = Array.getLength(v);
            List<Object> items = new ArrayList<>(len);
            for (int i = 0; i < len; i++) items.add(canonical(Array.get(v, i), depth + 1));
            return list("list", items);
        }

        if (v instanceof List) {
            List<Object> items = new ArrayList<>();
            for (Object x : (List<?>) v) items.add(canonical(x, depth + 1));
            return list("list", items);
        }
        if (v instanceof Set) {
            List<Object> items = new ArrayList<>();
            for (Object x : (Set<?>) v) items.add(canonical(x, depth + 1));
            sortByJson(items);
            return list("set", items);
        }
        if (v instanceof Map) {
            List<Object> items = new ArrayList<>();
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                items.add(list(canonical(e.getKey(), depth + 1), canonical(e.getValue(), depth + 1)));
            }
            sortByJson(items);
            return list("dict", items);
        }

        // POJO / record: compare by observable declared instance-field state.
        return objectState(v, depth);
    }

    private static void sortByJson(List<Object> items) {
        items.sort(Comparator.comparing(Json::serialize));
    }

    private static Object objectState(Object v, int depth) {
        Class<?> cls = v.getClass();
        TreeMap<String, Object> fields = new TreeMap<>();
        boolean introspectable = false;
        for (Class<?> c = cls; c != null && c != Object.class; c = c.getSuperclass()) {
            introspectable = true;
            for (Field f : c.getDeclaredFields()) {
                if (Modifier.isStatic(f.getModifiers()) || f.isSynthetic()) continue;
                try {
                    f.setAccessible(true);
                    fields.put(f.getName(), canonical(f.get(v), depth + 1));
                } catch (Exception ex) {
                    return list("opaque", cls.getSimpleName(), "<unrepresentable>");
                }
            }
        }
        if (!introspectable) {
            return list("opaque", cls.getSimpleName(), "<unrepresentable>");
        }
        List<Object> dict = new ArrayList<>();
        for (Map.Entry<String, Object> e : fields.entrySet()) {
            dict.add(list(list("str", e.getKey()), e.getValue()));
        }
        return list("obj", cls.getSimpleName(), list("dict", dict));
    }

    /** Convenience for tests / collections of observations. */
    public static Object of(Collection<?> c) {
        List<Object> out = new ArrayList<>();
        for (Object x : c) out.add(canonical(x));
        return out;
    }
}
