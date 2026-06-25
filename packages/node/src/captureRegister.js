'use strict';
/**
 * Capture preload (load via `node -r .../captureRegister.js <command>`).
 *
 * Wraps the exported functions / class methods of target modules (those resolved
 * under PROBE_CAPTURE_ROOT) as they are required, and records their real
 * arguments while the command runs. Mirrors the Python capture hook
 * (packages/python/probe/_capture_hook.py); the JS analog of pickle is node:v8
 * serialize. Records are flushed to PROBE_CAPTURE_DIR/captures.json on exit.
 *
 * Env:
 *   PROBE_CAPTURE_ROOT  absolute dir; only modules resolved under it are wrapped
 *   PROBE_CAPTURE_DIR   output dir for captures.json
 *   PROBE_CAPTURE_MAX   per-key sample cap (default 200)
 */

const Module = require('node:module');
const path = require('node:path');
const fs = require('node:fs');
const v8 = require('node:v8');

function realpath(p) {
  try { return fs.realpathSync(p); } catch (e) { return p; }
}
// realpath so symlinked roots (e.g. macOS /var -> /private/var tmp dirs) match
// the real paths that Module._resolveFilename returns.
const ROOT = process.env.PROBE_CAPTURE_ROOT ? realpath(path.resolve(process.env.PROBE_CAPTURE_ROOT)) : null;
const OUT = process.env.PROBE_CAPTURE_DIR ? path.resolve(process.env.PROBE_CAPTURE_DIR) : null;
const MAX = parseInt(process.env.PROBE_CAPTURE_MAX || '200', 10);

// key -> { is_method, set: Set<base64>, order: [base64] }
const records = new Map();
const wrapped = new WeakSet();
let reentrant = false;

function underRoot(file) {
  if (!ROOT || !file) return false;
  if (file.includes(`${path.sep}node_modules${path.sep}`)) return false;
  return file === ROOT || file.startsWith(ROOT + path.sep);
}

function relKey(file) {
  return path.relative(ROOT, file).split(path.sep).join('/');
}

function record(key, isMethod, argArray) {
  if (reentrant) return;
  reentrant = true;
  try {
    let b64;
    try {
      b64 = v8.serialize(argArray).toString('base64');
    } catch (e) {
      return; // unserializable args (functions, etc.) -> skip, never crash
    }
    let rec = records.get(key);
    if (!rec) { rec = { is_method: isMethod, set: new Set(), order: [] }; records.set(key, rec); }
    if (rec.set.has(b64)) return;
    if (rec.order.length >= MAX) return;
    rec.set.add(b64);
    rec.order.push(b64);
  } finally {
    reentrant = false;
  }
}

function isClass(fn) {
  return typeof fn === 'function' && /^class[\s{]/.test(Function.prototype.toString.call(fn));
}

function wrapFunction(orig, key) {
  function wrapper(...args) {
    record(key, false, args);
    return orig.apply(this, args);
  }
  Object.defineProperty(wrapper, 'name', { value: orig.name, configurable: true });
  wrapper.__selfsame_orig = orig;
  return wrapper;
}

function wrapClassMethods(cls, moduleRel) {
  const proto = cls.prototype;
  if (!proto) return;
  for (const name of Object.getOwnPropertyNames(proto)) {
    if (name === 'constructor') continue;
    const desc = Object.getOwnPropertyDescriptor(proto, name);
    if (!desc || typeof desc.value !== 'function' || wrapped.has(desc.value)) continue;
    const orig = desc.value;
    const key = `${moduleRel}::${cls.name}.${name}`;
    const wrapper = function wrapper(...args) {
      record(key, true, [this, ...args]);
      return orig.apply(this, args);
    };
    wrapper.__selfsame_orig = orig;
    wrapped.add(wrapper);
    Object.defineProperty(proto, name, { ...desc, value: wrapper });
  }
}

function wrapExports(exports, moduleRel) {
  if (!exports || (typeof exports !== 'object' && typeof exports !== 'function')) return;
  for (const name of Object.keys(exports)) {
    const val = exports[name];
    if (typeof val !== 'function' || wrapped.has(val)) continue;
    if (isClass(val)) {
      wrapClassMethods(val, moduleRel);
    } else {
      const w = wrapFunction(val, `${moduleRel}::${name}`);
      wrapped.add(w);
      try { exports[name] = w; } catch (e) { /* read-only export, skip */ }
    }
  }
}

if (ROOT && OUT) {
  const origLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    const exports = origLoad.apply(this, arguments);
    try {
      const file = Module._resolveFilename(request, parent, isMain);
      if (underRoot(file)) wrapExports(exports, relKey(file));
    } catch (e) { /* resolution failures are not ours to surface */ }
    return exports;
  };

  const flush = () => {
    try {
      fs.mkdirSync(OUT, { recursive: true });
      const out = [];
      for (const [key, rec] of records) {
        for (const b64 of rec.order) out.push({ key, is_method: rec.is_method, args_b64: b64 });
      }
      const tmp = path.join(OUT, `.captures.${process.pid}.tmp`);
      fs.writeFileSync(tmp, JSON.stringify({ meta: { lang: 'javascript' }, records: out }));
      fs.renameSync(tmp, path.join(OUT, 'captures.json'));
    } catch (e) { /* best-effort */ }
  };
  process.on('exit', flush);
}
