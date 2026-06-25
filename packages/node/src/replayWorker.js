'use strict';
/**
 * Replay worker: load ONE version of a module (from a given version root) and
 * run a function/method over captured arguments, emitting canonical
 * observations. Runs as a subprocess so two versions never share a runtime.
 * Mirrors packages/python/probe/_replay_worker.py.
 *
 * stdin  JSON: {versionRoot, moduleRel, qualname, is_method, args_b64:[...]}
 * stdout JSON: {loaded, error, absent, params, obs:[{val|exc, self_after?, io, threads, nondet?}]}
 */

const path = require('node:path');
const v8 = require('node:v8');
const { observe, canonical } = require('./harness');
const { deepEqual } = require('./soundness');

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { data += c; });
    process.stdin.on('end', () => resolve(data));
  });
}

function resolveTarget(mod, qualname) {
  // "foo" -> {fn: mod.foo}; "Class.method" -> {fn: proto.method, isMethod}
  if (qualname.includes('.')) {
    const [cls, method] = qualname.split('.');
    const klass = mod[cls];
    if (!klass || !klass.prototype) return null;
    const fn = klass.prototype[method];
    return typeof fn === 'function' ? { fn, method: true } : null;
  }
  const fn = mod[qualname];
  return typeof fn === 'function' ? { fn, method: false } : null;
}

async function runOnce(target, isMethod, values) {
  let callThis = null;
  let callArgs = values;
  if (isMethod) {
    callThis = values[0];
    callArgs = values.slice(1);
  }
  const bound = isMethod ? (...a) => target.fn.apply(callThis, a) : (...a) => target.fn(...a);
  const o = await observe(bound, callArgs);
  const ret = o.exception !== null ? ['exc', o.exception] : ['val', canonical(o.value)];
  let state = null;
  if (isMethod) {
    try { state = canonical(callThis); } catch (e) { state = ['opaque', 'self', '<unrepresentable>']; }
  }
  return { ret, state, io: o.counts.io, threads: o.counts.threads };
}

async function main() {
  const out = { loaded: false, error: null, obs: [] };
  try {
    const job = JSON.parse(await readStdin());
    const modPath = path.join(job.versionRoot, job.moduleRel);
    delete require.cache[require.resolve(modPath)];
    const mod = require(modPath);

    const target = resolveTarget(mod, job.qualname);
    if (!target) { out.absent = true; process.stdout.write(JSON.stringify(out)); return; }
    out.loaded = true;
    const isMethod = !!job.is_method && target.method;
    out.params = (target.fn.length != null) ? target.fn.length : null;

    for (const b64 of job.args_b64) {
      let values;
      try {
        values = v8.deserialize(Buffer.from(b64, 'base64'));
      } catch (e) { out.obs.push({ val: ['opaque', 'unpicklable', '<unrepresentable>'], io: 0, threads: 0 }); continue; }
      const r1 = await runOnce(target, isMethod, values);
      const r2 = await runOnce(target, isMethod, values); // determinism guard
      const rec = { io: r1.io, threads: r1.threads };
      if (!deepEqual(r1.ret, r2.ret) || !deepEqual(r1.state, r2.state)) {
        rec.nondet = true;
      } else {
        if (r1.ret[0] === 'exc') rec.exc = r1.ret[1];
        else rec.val = r1.ret[1];
        if (isMethod) rec.self_after = r1.state;
      }
      out.obs.push(rec);
    }
  } catch (e) {
    out.error = `${e && e.constructor ? e.constructor.name : 'Error'}: ${e && e.message}`;
  }
  process.stdout.write(JSON.stringify(out));
}

main();
