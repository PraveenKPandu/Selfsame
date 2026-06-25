package dev.selfsame;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal, dependency-free JSON parser + serializer. Selfsame's core stays
 * pure-JDK (no Jackson/Gson), so this covers exactly what the protocol needs:
 * canonical forms (arrays of arrays/primitives) and the conformance vectors.
 *
 * parse() yields: List&lt;Object&gt; for arrays, Map&lt;String,Object&gt; for objects,
 * String, Long (integers), Double (reals), Boolean, or null.
 */
public final class Json {
    private Json() {}

    // ---- parse ----
    public static Object parse(String s) {
        P p = new P(s);
        p.ws();
        Object v = p.value();
        p.ws();
        if (p.i != p.n) throw new IllegalArgumentException("trailing JSON at " + p.i);
        return v;
    }

    private static final class P {
        final String s; int i; final int n;
        P(String s) { this.s = s; this.n = s.length(); }

        void ws() { while (i < n && Character.isWhitespace(s.charAt(i))) i++; }

        Object value() {
            char c = s.charAt(i);
            switch (c) {
                case '{': return obj();
                case '[': return arr();
                case '"': return str();
                case 't': expect("true"); return Boolean.TRUE;
                case 'f': expect("false"); return Boolean.FALSE;
                case 'n': expect("null"); return null;
                default: return num();
            }
        }

        void expect(String lit) {
            if (!s.startsWith(lit, i)) throw new IllegalArgumentException("expected " + lit + " at " + i);
            i += lit.length();
        }

        Map<String, Object> obj() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; ws();
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws();
                String k = str();
                ws();
                if (s.charAt(i) != ':') throw new IllegalArgumentException("expected : at " + i);
                i++; ws();
                m.put(k, value());
                ws();
                char c = s.charAt(i++);
                if (c == '}') break;
                if (c != ',') throw new IllegalArgumentException("expected , or } at " + (i - 1));
            }
            return m;
        }

        List<Object> arr() {
            List<Object> a = new ArrayList<>();
            i++; ws();
            if (s.charAt(i) == ']') { i++; return a; }
            while (true) {
                ws();
                a.add(value());
                ws();
                char c = s.charAt(i++);
                if (c == ']') break;
                if (c != ',') throw new IllegalArgumentException("expected , or ] at " + (i - 1));
            }
            return a;
        }

        String str() {
            if (s.charAt(i) != '"') throw new IllegalArgumentException("expected string at " + i);
            i++;
            StringBuilder b = new StringBuilder();
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    char e = s.charAt(i++);
                    switch (e) {
                        case '"': b.append('"'); break;
                        case '\\': b.append('\\'); break;
                        case '/': b.append('/'); break;
                        case 'b': b.append('\b'); break;
                        case 'f': b.append('\f'); break;
                        case 'n': b.append('\n'); break;
                        case 'r': b.append('\r'); break;
                        case 't': b.append('\t'); break;
                        case 'u': b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                        default: throw new IllegalArgumentException("bad escape \\" + e);
                    }
                } else {
                    b.append(c);
                }
            }
            return b.toString();
        }

        Object num() {
            int start = i;
            boolean real = false;
            while (i < n) {
                char c = s.charAt(i);
                if (c == '-' || c == '+' || (c >= '0' && c <= '9')) { i++; }
                else if (c == '.' || c == 'e' || c == 'E') { real = true; i++; }
                else break;
            }
            String t = s.substring(start, i);
            if (t.isEmpty()) throw new IllegalArgumentException("bad number at " + start);
            return real ? (Object) Double.valueOf(t) : (Object) Long.valueOf(t);
        }
    }

    // ---- serialize (deterministic; used for ordering canonical children) ----
    public static String serialize(Object v) {
        StringBuilder b = new StringBuilder();
        write(v, b);
        return b.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(Object v, StringBuilder b) {
        if (v == null) { b.append("null"); return; }
        if (v instanceof String) { writeStr((String) v, b); return; }
        if (v instanceof Boolean) { b.append(v.toString()); return; }
        if (v instanceof Double) {
            double d = (Double) v;
            if (Double.isNaN(d)) { b.append("\"nan\""); return; }
            if (Double.isInfinite(d)) { b.append(d > 0 ? "\"inf\"" : "\"-inf\""); return; }
            if (d == Math.floor(d) && !Double.isInfinite(d)) { b.append(Long.toString((long) d)); return; }
            b.append(Double.toString(d));
            return;
        }
        if (v instanceof Number) { b.append(v.toString()); return; }
        if (v instanceof List) {
            b.append('[');
            List<Object> a = (List<Object>) v;
            for (int j = 0; j < a.size(); j++) { if (j > 0) b.append(','); write(a.get(j), b); }
            b.append(']');
            return;
        }
        if (v instanceof Map) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet()) {
                if (!first) b.append(','); first = false;
                writeStr(e.getKey(), b); b.append(':'); write(e.getValue(), b);
            }
            b.append('}');
            return;
        }
        writeStr(v.toString(), b);
    }

    private static void writeStr(String s, StringBuilder b) {
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                case '\b': b.append("\\b"); break;
                case '\f': b.append("\\f"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        b.append('"');
    }
}
