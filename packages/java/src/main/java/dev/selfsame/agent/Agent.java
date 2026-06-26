package dev.selfsame.agent;

import java.lang.instrument.Instrumentation;

import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;

import static net.bytebuddy.matcher.ElementMatchers.isConstructor;
import static net.bytebuddy.matcher.ElementMatchers.isMethod;
import static net.bytebuddy.matcher.ElementMatchers.isPublic;
import static net.bytebuddy.matcher.ElementMatchers.isSynthetic;
import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.nameStartsWith;
import static net.bytebuddy.matcher.ElementMatchers.not;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

/**
 * The Selfsame capture agent. Attach with
 *   -javaagent:selfsame.jar=target=&lt;classNamePrefix&gt;,out=&lt;dir&gt;
 * It instruments public methods (static and instance) of classes whose name
 * starts with the target prefix, recording their real arguments — and, for
 * instance methods, the receiver — while the program runs.
 */
public final class Agent {
    public static void premain(String arg, Instrumentation inst) {
        String target = "";
        String out = "selfsame-captures";
        if (arg != null) {
            for (String kv : arg.split(",")) {
                int eq = kv.indexOf('=');
                if (eq < 0) continue;
                String k = kv.substring(0, eq), v = kv.substring(eq + 1);
                if (k.equals("target")) target = v;
                else if (k.equals("out")) out = v;
            }
        }
        Recorder.configure(out);
        new AgentBuilder.Default()
                .type(nameStartsWith(target))
                .transform((builder, td, cl, module, pd) -> builder.visit(
                        Advice.to(CaptureAdvice.class)
                                .on(isMethod().and(isPublic()).and(not(isConstructor())).and(not(isSynthetic()))
                                        // never the JVM entry point (the launcher, not code under test)
                                        .and(not(named("main").and(takesArguments(String[].class)))))))
                .installOn(inst);
        System.out.println("[selfsame] capture agent installed (target prefix: '" + target + "')");
    }

    private Agent() {}
}
