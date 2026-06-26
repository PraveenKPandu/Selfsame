package dev.selfsame;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Round-trippable, type-faithful serialization of method arguments, so captured
 * inputs can be re-invoked against another version. UNLIKE {@link Canonical}
 * (which is lossy/observable, for comparison), ValueCodec must reconstruct the
 * actual values, so each is tagged with its concrete type.
 *
 * Supported (MVP): null, boxed primitives, char, String, BigInteger/BigDecimal,
 * byte[], List, Map, Object[]. Anything else makes encoding return null, so the
 * capture is skipped — sound under-capture, never a wrong reconstruction.
 */
public final class ValueCodec {
    private ValueCodec() {}

    /** Encode an argument array; null if any element is unsupported. */
    public static List<Object> encodeArgs(Object[] args) {
        List<Object> out = new ArrayList<>(args.length);
        for (Object a : args) {
            Object e = encode(a);
            if (e == null) return null; // unsupported -> skip the whole call
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

    /** Returns the tagged encoding, or null if the type is unsupported. */
    static List<Object> encode(Object v) {
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
            for (Object x : (List<?>) v) { Object e = encode(x); if (e == null) return null; items.add(e); }
            return t("list", items);
        }
        if (v instanceof Map) {
            List<Object> items = new ArrayList<>();
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                Object k = encode(e.getKey()); Object val = encode(e.getValue());
                if (k == null || val == null) return null;
                List<Object> pair = new ArrayList<>(2); pair.add(k); pair.add(val); items.add(pair);
            }
            return t("map", items);
        }
        if (v instanceof Object[]) {
            Object[] a = (Object[]) v;
            List<Object> items = new ArrayList<>(a.length);
            for (Object x : a) { Object e = encode(x); if (e == null) return null; items.add(e); }
            return t("arr", items);
        }
        return null; // unsupported
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
            default: throw new IllegalArgumentException("unknown value tag: " + tag);
        }
    }
}
