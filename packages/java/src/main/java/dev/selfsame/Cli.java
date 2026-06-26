package dev.selfsame;

import java.io.OutputStream;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * selfsame (JVM) CLI.
 *
 *   selfsame capture --target &lt;classPrefix&gt; --cp &lt;classpath&gt; --out &lt;dir&gt; --main &lt;Main&gt; [args...]
 *   selfsame replay  --before &lt;cpA&gt; --after &lt;cpB&gt; --captures &lt;dir|file&gt;
 *
 * `capture` runs your program with the capture agent attached; `replay` re-runs
 * the captured inputs against two compiled versions and prints a per-method
 * verdict (exit 1 on any divergence). MVP: public static methods.
 */
public final class Cli {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) { help(); System.exit(0); }
        String cmd = args[0];
        String[] rest = new String[args.length - 1];
        System.arraycopy(args, 1, rest, 0, rest.length);
        if (cmd.equals("capture")) System.exit(capture(rest));
        else if (cmd.equals("replay")) System.exit(replay(rest));
        else { help(); System.exit(args.length == 0 ? 0 : 2); }
    }

    private static void help() {
        System.out.println("selfsame (JVM implementation of the Selfsame Protocol)\n");
        System.out.println("Commands:");
        System.out.println("  capture --target <classPrefix> --cp <classpath> --out <dir> --main <Main> [args...]");
        System.out.println("  replay  --before <cpA> --after <cpB> --captures <dir|file>");
    }

    // -------- capture --------
    private static int capture(String[] args) throws Exception {
        Map<String, String> f = flags(args);
        List<String> mainArgs = trailing(args);
        if (!f.containsKey("target") || !f.containsKey("cp") || !f.containsKey("main")) {
            System.err.println("usage: selfsame capture --target <prefix> --cp <classpath> --out <dir> --main <Main> [args...]");
            return 2;
        }
        String out = f.getOrDefault("out", ".selfsame");
        String self = selfPath();
        List<String> cmd = new ArrayList<>();
        cmd.add(javaBin());
        cmd.add("-javaagent:" + self + "=target=" + f.get("target") + ",out=" + out);
        cmd.add("-cp");
        cmd.add(f.get("cp"));
        cmd.add(f.get("main"));
        cmd.addAll(mainArgs);
        Process p = new ProcessBuilder(cmd).inheritIO().start();
        p.waitFor();
        Path cap = Paths.get(out, "captures.json");
        if (!Files.exists(cap)) { System.err.println("no captures produced under " + out); return 1; }
        return 0;
    }

    // -------- replay --------
    @SuppressWarnings("unchecked")
    private static int replay(String[] args) throws Exception {
        Map<String, String> f = flags(args);
        if (!f.containsKey("before") || !f.containsKey("after") || !f.containsKey("captures")) {
            System.err.println("usage: selfsame replay --before <cpA> --after <cpB> --captures <dir|file>");
            return 2;
        }
        Path capPath = Paths.get(f.get("captures"));
        if (Files.isDirectory(capPath)) capPath = capPath.resolve("captures.json");
        Map<String, Object> doc = (Map<String, Object>) Json.parse(
                new String(Files.readAllBytes(capPath), "UTF-8"));
        List<Object> records = (List<Object>) doc.get("records");

        // group records by key
        Map<String, Map<String, Object>> byKey = new LinkedHashMap<>();
        for (Object ro : records) {
            Map<String, Object> rec = (Map<String, Object>) ro;
            String key = (String) rec.get("key");
            Map<String, Object> g = byKey.get(key);
            if (g == null) {
                g = new LinkedHashMap<>();
                g.put("param_types", rec.get("param_types"));
                g.put("args", new ArrayList<Object>());
                byKey.put(key, g);
            }
            ((List<Object>) g.get("args")).add(rec.get("args_b64"));
        }

        String self = selfPath();
        int diverged = 0;
        for (Map.Entry<String, Map<String, Object>> e : byKey.entrySet()) {
            String key = e.getKey();
            int sep = key.indexOf("::");
            String className = key.substring(0, sep);
            String method = key.substring(sep + 2);
            List<Object> argsB64 = (List<Object>) e.getValue().get("args");

            Map<String, Object> job = new LinkedHashMap<>();
            job.put("className", className);
            job.put("method", method);
            job.put("param_types", e.getValue().get("param_types"));
            job.put("args_b64", argsB64);
            String jobJson = Json.serialize(job);

            Map<String, Object> base = runWorker(f.get("before"), self, jobJson);
            Map<String, Object> head = runWorker(f.get("after"), self, jobJson);
            String[] v = verdict(base, head);
            if (v[0].equals("divergent")) {
                diverged++;
                System.out.println("X " + method + "  n=" + argsB64.size() + "  divergent  @ input #" + v[1]);
                System.out.println("      base : " + v[2]);
                System.out.println("      head : " + v[3]);
            } else {
                System.out.println((v[0].equals("equivalent") ? "  " : "· ") + method
                        + "  n=" + argsB64.size() + "  " + v[0] + (v[1].isEmpty() ? "" : " (" + v[1] + ")"));
            }
        }
        return diverged > 0 ? 1 : 0;
    }

    // verdict -> [verdict, indexOrNote, base, head]
    @SuppressWarnings("unchecked")
    private static String[] verdict(Map<String, Object> base, Map<String, Object> head) {
        if (base.get("error") != null || head.get("error") != null)
            return new String[]{"error", String.valueOf(base.get("error") != null ? base.get("error") : head.get("error")), "", ""};
        if (Boolean.TRUE.equals(base.get("absent")) || Boolean.TRUE.equals(head.get("absent")))
            return new String[]{"skipped", "added/removed", "", ""};
        if (!Boolean.TRUE.equals(base.get("loaded")) || !Boolean.TRUE.equals(head.get("loaded")))
            return new String[]{"skipped", "not loaded", "", ""};
        List<Map<String, Object>> bo = toObs((List<Object>) base.get("obs"));
        List<Map<String, Object>> ho = toObs((List<Object>) head.get("obs"));
        String bu = Soundness.unsound(bo);
        if (bu != null) return new String[]{"unverifiable", bu, "", ""};
        String hu = Soundness.unsound(ho);
        if (hu != null) return new String[]{"unverifiable", hu, "", ""};
        if (bo.size() != ho.size()) return new String[]{"error", "obs count mismatch", "", ""};
        for (int i = 0; i < bo.size(); i++) {
            if (!Soundness.same(bo.get(i), ho.get(i)))
                return new String[]{"divergent", String.valueOf(i), render(bo.get(i)), render(ho.get(i))};
        }
        return new String[]{"equivalent", "", "", ""};
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> toObs(List<Object> raw) {
        List<Map<String, Object>> o = new ArrayList<>();
        for (Object r : raw) o.add((Map<String, Object>) r);
        return o;
    }

    private static String render(Map<String, Object> o) {
        if (o.containsKey("exc")) return "raise " + o.get("exc");
        return Json.serialize(o.get("val"));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> runWorker(String versionCp, String self, String jobJson) throws Exception {
        List<String> cmd = new ArrayList<>();
        cmd.add(javaBin());
        cmd.add("-cp");
        cmd.add(versionCp + File.pathSeparator + self);
        cmd.add("dev.selfsame.ReplayWorker");
        Process p = new ProcessBuilder(cmd).redirectErrorStream(false).start();
        try (OutputStream os = p.getOutputStream()) { os.write(jobJson.getBytes("UTF-8")); }
        String stdout = readAll(p.getInputStream());
        String stderr = readAll(p.getErrorStream());
        p.waitFor();
        try {
            return (Map<String, Object>) Json.parse(stdout);
        } catch (Exception ex) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "bad worker output: " + (stdout.isEmpty() ? stderr : stdout));
            err.put("obs", new ArrayList<>());
            return err;
        }
    }

    // -------- arg parsing --------
    private static Map<String, String> flags(String[] args) {
        Map<String, String> f = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--")) break;
            if (args[i].startsWith("--") && i + 1 < args.length) { f.put(args[i].substring(2), args[i + 1]); i++; }
        }
        return f;
    }

    private static List<String> trailing(String[] args) {
        List<String> out = new ArrayList<>();
        boolean after = false;
        for (String a : args) {
            if (after) out.add(a);
            else if (a.equals("--")) after = true;
        }
        return out;
    }

    private static String javaBin() {
        return Paths.get(System.getProperty("java.home"), "bin", "java").toString();
    }

    private static String selfPath() throws Exception {
        return new File(Cli.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getPath();
    }

    private static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) bos.write(buf, 0, n);
        return new String(bos.toByteArray(), "UTF-8");
    }

    private Cli() {}
}
