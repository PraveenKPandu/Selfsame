// ESM replay worker: load ONE version of an ES module (dynamic import) and run a
// captured function over its inputs, emitting canonical observations. Runs as a
// subprocess so two versions never share a realm. Counterpart to replayWorker.js
// (CommonJS). MVP: top-level exported functions.
//
// stdin  JSON: {versionRoot, moduleRel, qualname, args_b64:[...]}
// stdout JSON: {loaded, error, absent, obs:[{val|exc, nondet?}]}
import { pathToFileURL } from 'node:url';
import { deserialize } from 'node:v8';
import { join } from 'node:path';
import canonicalMod from './canonical.js';
import soundnessMod from './soundness.js';
import harnessMod from './harness.js';

const { canonical } = canonicalMod;
const { deepEqual } = soundnessMod;
const { observe } = harnessMod;

function readStdin() {
  return new Promise((resolve) => {
    let d = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { d += c; });
    process.stdin.on('end', () => resolve(d));
  });
}

async function runOnce(fn, args) {
  const o = await observe((...a) => fn(...a), args);
  return o.exception !== null ? ['exc', o.exception] : ['val', canonical(o.value)];
}

async function main() {
  const out = { loaded: false, error: null, obs: [] };
  try {
    const job = JSON.parse(await readStdin());
    const url = pathToFileURL(join(job.versionRoot, job.moduleRel)).href;
    const ns = await import(url);
    const fn = job.qualname === '(default)' ? ns.default : ns[job.qualname];
    if (typeof fn !== 'function') { out.absent = true; process.stdout.write(JSON.stringify(out)); return; }
    out.loaded = true;
    for (const b64 of job.args_b64) {
      let args;
      try { args = deserialize(Buffer.from(b64, 'base64')); }
      catch (e) { out.obs.push({ val: ['opaque', 'unpicklable', '<unrepresentable>'], io: 0, threads: 0 }); continue; }
      const r1 = await runOnce(fn, args);
      const r2 = await runOnce(fn, args);
      const rec = {};
      if (!deepEqual(r1, r2)) rec.nondet = true;
      else if (r1[0] === 'exc') rec.exc = r1[1];
      else rec.val = r1[1];
      out.obs.push(rec);
    }
  } catch (e) {
    out.error = `${e && e.constructor ? e.constructor.name : 'Error'}: ${e && e.message}`;
  }
  process.stdout.write(JSON.stringify(out));
}

main();
