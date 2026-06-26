package dev.selfsame;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Replay worker: load ONE version of a class (from this process's classpath) and
 * run a static method over captured arguments, emitting canonical observations.
 * Runs as a subprocess so two versions never share a JVM. Mirrors the Python/JS
 * replay workers. Determinism is enforced by the run-twice guard (a method whose
 * two runs disagree is reported nondeterministic and refused).
 *
 * stdin  JSON: {className, method, param_types:[...], args_b64:[...]}
 * stdout JSON: {loaded, error, absent, obs:[{val|exc, nondet?}]}
 */
public final class ReplayWorker {
    public static void main(String[] args) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("loaded", false);
        out.put("error", null);
        List<Object> obs = new ArrayList<>();
        out.put("obs", obs);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> job = (Map<String, Object>) Json.parse(readStdin());
            String className = (String) job.get("className");
            String methodName = (String) job.get("method");
            @SuppressWarnings("unchecked")
            List<Object> paramTypes = (List<Object>) job.get("param_types");
            @SuppressWarnings("unchecked")
            List<Object> argsB64 = (List<Object>) job.get("args_b64");

            boolean isMethod = Boolean.TRUE.equals(job.get("is_method"));
            Class<?> cls = Class.forName(className);
            Method m = resolve(cls, methodName, paramTypes, isMethod);
            if (m == null) { out.put("absent", true); print(out); return; }
            m.setAccessible(true);
            out.put("loaded", true);

            for (Object b64o : argsB64) {
                String b64 = (String) b64o;
                // Decode fresh each run: an instance method may mutate the receiver,
                // so both the determinism guard and the post-call state need a clean
                // copy reconstructed from the captured encoding.
                Object[] r1 = runOnce(m, isMethod, b64);
                Object[] r2 = runOnce(m, isMethod, b64);
                Map<String, Object> rec = new LinkedHashMap<>();
                if (!Soundness.deepEqual(r1[0], r2[0]) || !Soundness.deepEqual(r1[1], r2[1])) {
                    rec.put("nondet", true);
                } else {
                    putResult(rec, r1[0]);
                    if (isMethod) rec.put("self_after", r1[1]);
                }
                obs.add(rec);
            }
        } catch (Throwable t) {
            out.put("error", t.getClass().getName() + ": " + t.getMessage());
        }
        print(out);
    }

    // Decodes the captured input fresh and runs it. Returns [result, selfAfter]
    // where result is ["val", canonical] or ["exc", typeName], and selfAfter is
    // the canonical post-call receiver state (null for static methods).
    @SuppressWarnings("unchecked")
    private static Object[] runOnce(Method m, boolean isMethod, String b64) throws Exception {
        List<Object> encoded = (List<Object>) Json.parse(
                new String(Base64.getDecoder().decode(b64), "UTF-8"));
        Object[] values = ValueCodec.decodeArgs(encoded);
        Object receiver = null;
        Object[] callArgs = values;
        if (isMethod) {
            receiver = values[0];
            callArgs = Arrays.copyOfRange(values, 1, values.length);
        }
        Object result;
        try {
            Object ret = m.invoke(receiver, callArgs);
            result = Arrays.asList("val", Canonical.canonical(ret));
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause() == null ? e : e.getCause();
            result = Arrays.asList("exc", cause.getClass().getName());
        } catch (Throwable t) {
            result = Arrays.asList("exc", t.getClass().getName());
        }
        Object selfAfter = isMethod ? Canonical.canonical(receiver) : null;
        return new Object[]{result, selfAfter};
    }

    @SuppressWarnings("unchecked")
    private static void putResult(Map<String, Object> rec, Object r) {
        List<Object> pair = (List<Object>) r;
        if ("exc".equals(pair.get(0))) rec.put("exc", pair.get(1));
        else rec.put("val", pair.get(1));
    }

    private static Method resolve(Class<?> cls, String name, List<Object> paramTypes, boolean isMethod) {
        for (Method m : cls.getDeclaredMethods()) {
            if (!m.getName().equals(name)) continue;
            if (Modifier.isStatic(m.getModifiers()) == isMethod) continue; // static iff !isMethod
            Class<?>[] p = m.getParameterTypes();
            if (p.length != paramTypes.size()) continue;
            boolean match = true;
            for (int i = 0; i < p.length; i++) {
                if (!p[i].getName().equals(paramTypes.get(i))) { match = false; break; }
            }
            if (match) return m;
        }
        return null;
    }

    private static String readStdin() throws Exception {
        InputStream in = System.in;
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) bos.write(buf, 0, n);
        return new String(bos.toByteArray(), "UTF-8");
    }

    private static void print(Map<String, Object> out) {
        System.out.println(Json.serialize(out));
    }

    private ReplayWorker() {}
}
