package dev.selfsame;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Round-trippable, type-faithful serialization of method arguments and receivers,
 * so captured inputs (and the `this` of an instance method) can be reconstructed
 * and re-invoked against another version. UNLIKE {@link Canonical} (lossy, for
 * comparison), this must rebuild the actual values, so each is tagged with its
 * concrete type.
 *
 * Supported: null, boxed primitives, char, String, BigInteger/BigDecimal, byte[],
 * List, Map, Object[], and arbitrary non-JDK objects (encoded by their declared
 * instance fields; reconstructed via sun.reflect.ReflectionFactory, the same
 * mechanism Java serialization / Jackson / Kryo use). Anything that can't be
 * round-tripped makes encoding return null, so the capture is skipped — sound
 * under-capture, never a wrong reconstruction.
 */
public final class ValueCodec {
    private ValueCodec() {}

    private static final int MAX_DEPTH = 40;

    /** Encode an argument array; null if any element is unsupported. */
    public static List<Object> encodeArgs(Object[] args) {
        List<Object> out = new ArrayList<>(args.length);
        for (Object a : args) {
            Object e = encode(a, 0);
            if (e == null) return null;
            out.add(e);
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    public static Object[] decodeArgs(List<Object> encoded) {
        Object[] out = new Object[encoded.size()];
        for (int i = 0; i < out.length; i++) out[i] = decode((List<Object>) encoded.get(i));
        return out;
    }

    private static List<Object> t(String tag, Object v) {
        List<Object> l = new ArrayList<>(2);
        l.add(tag); l.add(v);
        return l;
    }

    static List<Object> encode(Object v, int depth) {
        if (depth > MAX_DEPTH) return null;
        if (v == null) { List<Object> l = new ArrayList<>(); l.add("n"); return l; }
        if (v instanceof Boolean) return t("z", v);
        if (v instanceof Byte) return t("b", ((Byte) v).longValue());
        if (v instanceof Short) return t("sh", ((Short) v).longValue());
        if (v instanceof Integer) return t("i", ((Integer) v).longValue());
        if (v instanceof Long) return t("l", v);
        if (v instanceof Float) return t("f", v.toString());
        if (v instanceof Double) return t("d", v.toString());
        if (v instanceof Character) return t("c", v.toString());
        if (v instanceof String) return t("s", v);
        if (v instanceof BigInteger) return t("bi", v.toString());
        if (v instanceof BigDecimal) return t("bd", v.toString());
        if (v instanceof byte[]) {
            byte[] a = (byte[]) v;
            List<Object> items = new ArrayList<>(a.length);
            for (byte x : a) items.add((long) x);
            return t("ba", items);
        }
        if (v instanceof List) {
            List<Object> items = new ArrayList<>();
            for (Object x : (List<?>) v) { Object e = encode(x, depth + 1); if (e == null) return null; items.add(e); }
            return t("list", items);
        }
        if (v instanceof Map) {
            List<Object> items = new ArrayList<>();
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                Object k = encode(e.getKey(), depth + 1), val = encode(e.getValue(), depth + 1);
                if (k == null || val == null) return null;
                List<Object> pair = new ArrayList<>(2); pair.add(k); pair.add(val); items.add(pair);
            }
            return t("map", items);
        }
        if (v instanceof Object[]) {
            Object[] a = (Object[]) v;
            List<Object> items = new ArrayList<>(a.length);
            for (Object x : a) { Object e = encode(x, depth + 1); if (e == null) return null; items.add(e); }
            return t("arr", items);
        }
        return encodeObject(v, depth);
    }

    // Arbitrary non-JDK object -> ["o", className, [[field, enc], ...]].
    private static List<Object> encodeObject(Object v, int depth) {
        Class<?> cls = v.getClass();
        String cn = cls.getName();
        if (cn.startsWith("java.") || cn.startsWith("javax.") || cn.startsWith("jdk.")
                || cn.startsWith("sun.") || cls.isArray()) {
            return null; // unhandled JDK/array type -> skip (sound)
        }
        List<Object> fields = new ArrayList<>();
        for (Class<?> c = cls; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                if (Modifier.isStatic(f.getModifiers()) || f.isSynthetic()) continue;
                try {
                    f.setAccessible(true);
                    Object enc = encode(f.get(v), depth + 1);
                    if (enc == null) return null; // unencodable field -> skip whole object
                    List<Object> pair = new ArrayList<>(2);
                    pair.add(f.getName()); pair.add(enc);
                    fields.add(pair);
                } catch (Exception e) {
                    return null;
                }
            }
        }
        List<Object> out = new ArrayList<>(3);
        out.add("o"); out.add(cn); out.add(fields);
        return out;
    }

    @SuppressWarnings("unchecked")
    static Object decode(List<Object> e) {
        String tag = (String) e.get(0);
        switch (tag) {
            case "n": return null;
            case "z": return e.get(1);
            case "b": return (byte) ((Long) e.get(1)).longValue();
            case "sh": return (short) ((Long) e.get(1)).longValue();
            case "i": return (int) ((Long) e.get(1)).longValue();
            case "l": return ((Number) e.get(1)).longValue();
            case "f": return Float.parseFloat((String) e.get(1));
            case "d": return Double.parseDouble((String) e.get(1));
            case "c": return ((String) e.get(1)).charAt(0);
            case "s": return e.get(1);
            case "bi": return new BigInteger((String) e.get(1));
            case "bd": return new BigDecimal((String) e.get(1));
            case "ba": {
                List<Object> items = (List<Object>) e.get(1);
                byte[] a = new byte[items.size()];
                for (int i = 0; i < a.length; i++) a[i] = (byte) ((Long) items.get(i)).longValue();
                return a;
            }
            case "list": {
                List<Object> items = (List<Object>) e.get(1);
                List<Object> out = new ArrayList<>(items.size());
                for (Object x : items) out.add(decode((List<Object>) x));
                return out;
            }
            case "map": {
                List<Object> items = (List<Object>) e.get(1);
                Map<Object, Object> out = new LinkedHashMap<>();
                for (Object x : items) {
                    List<Object> pair = (List<Object>) x;
                    out.put(decode((List<Object>) pair.get(0)), decode((List<Object>) pair.get(1)));
                }
                return out;
            }
            case "arr": {
                List<Object> items = (List<Object>) e.get(1);
                Object[] out = new Object[items.size()];
                for (int i = 0; i < out.length; i++) out[i] = decode((List<Object>) items.get(i));
                return out;
            }
            case "o": return decodeObject((String) e.get(1), (List<Object>) e.get(2));
            default: throw new IllegalArgumentException("unknown value tag: " + tag);
        }
    }

    @SuppressWarnings("unchecked")
    private static Object decodeObject(String className, List<Object> fields) {
        try {
            Class<?> cls = Class.forName(className);
            Object obj = Allocator.allocate(cls);
            for (Object fo : fields) {
                List<Object> pair = (List<Object>) fo;
                String name = (String) pair.get(0);
                Object value = decode((List<Object>) pair.get(1));
                Field f = findField(cls, name);
                if (f == null) continue; // field absent in this version -> best-effort
                f.setAccessible(true);
                f.set(obj, value);
            }
            return obj;
        } catch (Exception e) {
            throw new RuntimeException("cannot reconstruct " + className + ": " + e, e);
        }
    }

    private static Field findField(Class<?> cls, String name) {
        for (Class<?> c = cls; c != null && c != Object.class; c = c.getSuperclass()) {
            try { return c.getDeclaredField(name); } catch (NoSuchFieldException ignored) { }
        }
        return null;
    }

    /** Allocates an instance without invoking a constructor (sun.reflect.ReflectionFactory). */
    private static final class Allocator {
        static Object allocate(Class<?> cls) throws Exception {
            sun.reflect.ReflectionFactory rf = sun.reflect.ReflectionFactory.getReflectionFactory();
            Constructor<?> objCtor = Object.class.getDeclaredConstructor();
            Constructor<?> c = rf.newConstructorForSerialization(cls, objCtor);
            c.setAccessible(true);
            return c.newInstance();
        }
    }
}
