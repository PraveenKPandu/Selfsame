// ESM capture preload (load via `node --import .../esmRegister.mjs <esm entry>`).
//
// Runs in the main thread: installs the recorder (called by the wrapped exports
// the loader generates) and registers the transforming loader. Writes the same
// captures.json format as the CommonJS path, tagged esm:true. Env:
//   PROBE_CAPTURE_ROOT  only modules under here are wrapped
//   PROBE_CAPTURE_DIR   output dir for captures.json
import { register } from 'node:module';
import { serialize } from 'node:v8';
import { mkdirSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';

const OUT = process.env.PROBE_CAPTURE_DIR;
const ROOT = process.env.PROBE_CAPTURE_ROOT;
const MAX = parseInt(process.env.PROBE_CAPTURE_MAX || '200', 10);

const units = new Map(); // key -> Set<base64>

globalThis.__selfsame_record = (key, args) => {
  try {
    const b64 = serialize(args).toString('base64'); // unserializable args -> throw -> skip
    let s = units.get(key);
    if (!s) { s = new Set(); units.set(key, s); }
    if (s.size < MAX) s.add(b64);
  } catch (e) { /* skip (sound under-capture) */ }
};

process.on('exit', () => {
  if (!OUT) return;
  try {
    mkdirSync(OUT, { recursive: true });
    const records = [];
    for (const [key, s] of units) {
      for (const b64 of s) records.push({ key, is_method: false, esm: true, args_b64: b64 });
    }
    const tmp = join(OUT, '.captures.tmp');
    writeFileSync(tmp, JSON.stringify({ meta: { lang: 'javascript', esm: true }, records }));
    renameSync(tmp, join(OUT, 'captures.json'));
  } catch (e) { /* best-effort */ }
});

register('./esmLoader.mjs', { parentURL: import.meta.url, data: { root: ROOT } });
