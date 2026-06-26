package dev.selfsame.agent;

import dev.selfsame.Json;
import dev.selfsame.ValueCodec;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Buffers captured calls and flushes them to captures.json on JVM shutdown.
 * Called from instrumented (advice-inlined) target methods, so it lives on the
 * system classloader (the -javaagent jar). For an instance method, the receiver
 * (`this`) is recorded as the first encoded element so replay can reconstruct it.
 */
public final class Recorder {
    private Recorder() {}

    private static volatile Path outDir;
    private static final Map<String, Unit> units = new LinkedHashMap<>();
    private static final int MAX_PER_KEY = 200;
    private static volatile boolean reentrant = false;

    private static final class Unit {
        final boolean isMethod;
        final List<String> paramTypes;
        final Set<String> seen = new LinkedHashSet<>();
        Unit(boolean m, List<String> p) { this.isMethod = m; this.paramTypes = p; }
    }

    public static void configure(String out) {
        outDir = Paths.get(out);
        Runtime.getRuntime().addShutdownHook(new Thread(Recorder::flush));
    }

    /** Called on method entry by the advice. `self` is null for static methods. */
    public static void record(Object self, Method method, Object[] args) {
        if (reentrant) return;
        reentrant = true;
        try {
            boolean isMethod = !Modifier.isStatic(method.getModifiers());
            Object[] toEncode = args;
            if (isMethod) {
                toEncode = new Object[args.length + 1];
                toEncode[0] = self;
                System.arraycopy(args, 0, toEncode, 1, args.length);
            }
            List<Object> encoded = ValueCodec.encodeArgs(toEncode);
            if (encoded == null) return; // unreconstructable arg/receiver -> skip (sound)
            String b64 = Base64.getEncoder().encodeToString(
                    Json.serialize(encoded).getBytes("UTF-8"));
            String key = method.getDeclaringClass().getName() + "::" + method.getName();
            Unit u = units.get(key);
            if (u == null) {
                List<String> pt = new ArrayList<>();
                for (Class<?> c : method.getParameterTypes()) pt.add(c.getName());
                u = new Unit(isMethod, pt);
                units.put(key, u);
            }
            if (u.seen.size() < MAX_PER_KEY) u.seen.add(b64);
        } catch (Throwable t) {
            // never let capture break the target program
        } finally {
            reentrant = false;
        }
    }

    static synchronized void flush() {
        if (outDir == null) return;
        try {
            Files.createDirectories(outDir);
            List<Object> records = new ArrayList<>();
            for (Map.Entry<String, Unit> e : units.entrySet()) {
                Unit u = e.getValue();
                for (String b64 : u.seen) {
                    Map<String, Object> rec = new LinkedHashMap<>();
                    rec.put("key", e.getKey());
                    rec.put("is_method", u.isMethod);
                    rec.put("param_types", new ArrayList<Object>(u.paramTypes));
                    rec.put("args_b64", b64);
                    records.add(rec);
                }
            }
            Map<String, Object> doc = new LinkedHashMap<>();
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("lang", "java");
            doc.put("meta", meta);
            doc.put("records", records);
            Path tmp = outDir.resolve(".captures.tmp");
            Files.write(tmp, Json.serialize(doc).getBytes("UTF-8"));
            Files.move(tmp, outDir.resolve("captures.json"),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception e) {
            System.err.println("[selfsame] capture flush failed: " + e);
        }
    }
}
