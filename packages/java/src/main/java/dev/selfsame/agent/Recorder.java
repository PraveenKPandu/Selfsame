package dev.selfsame.agent;

import dev.selfsame.Json;
import dev.selfsame.ValueCodec;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.Base64;

/**
 * Buffers captured calls and flushes them to captures.json on JVM shutdown.
 * Called from instrumented (advice-inlined) target methods, so it lives on the
 * system classloader (the -javaagent jar). Mirrors the Python/JS capture sink.
 */
public final class Recorder {
    private Recorder() {}

    private static volatile Path outDir;
    // key -> {paramTypes, ordered unique args_b64}
    private static final Map<String, Unit> units = new LinkedHashMap<>();
    private static final int MAX_PER_KEY = 200;
    private static volatile boolean reentrant = false;

    private static final class Unit {
        final List<String> paramTypes;
        final Set<String> seen = new LinkedHashSet<>();
        Unit(List<String> p) { this.paramTypes = p; }
    }

    public static void configure(String out) {
        outDir = Paths.get(out);
        Runtime.getRuntime().addShutdownHook(new Thread(Recorder::flush));
    }

    /** Called on method entry by the advice. Static methods only (MVP). */
    public static void record(Method method, Object[] args) {
        if (reentrant) return;
        reentrant = true;
        try {
            List<Object> encoded = ValueCodec.encodeArgs(args);
            if (encoded == null) return; // unsupported arg type -> skip (sound)
            String b64 = Base64.getEncoder().encodeToString(
                    Json.serialize(encoded).getBytes("UTF-8"));
            String key = method.getDeclaringClass().getName() + "::" + method.getName();
            Unit u = units.get(key);
            if (u == null) {
                List<String> pt = new ArrayList<>();
                for (Class<?> c : method.getParameterTypes()) pt.add(c.getName());
                u = new Unit(pt);
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
                for (String b64 : e.getValue().seen) {
                    Map<String, Object> rec = new LinkedHashMap<>();
                    rec.put("key", e.getKey());
                    rec.put("param_types", new ArrayList<Object>(e.getValue().paramTypes));
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
