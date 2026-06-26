package dev.selfsame.agent;

import java.lang.reflect.Method;

import net.bytebuddy.asm.Advice;

/**
 * Inlined into each instrumented method's entry. Forwards the live arguments to
 * the Recorder. Kept tiny and exception-safe (the Recorder swallows its own
 * errors) so capture can never alter target behavior.
 */
public final class CaptureAdvice {
    private CaptureAdvice() {}

    @Advice.OnMethodEnter
    static void enter(@Advice.Origin Method method, @Advice.AllArguments Object[] args) {
        Recorder.record(method, args);
    }
}
