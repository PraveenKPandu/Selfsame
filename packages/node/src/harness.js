'use strict';
/**
 * Determinism control + observe. Mirrors packages/python/probe/harness.py and
 * implements SPEC/protocol.md section 7 for the JS runtime: freeze the clock,
 * seed entropy, and count uncontrolled I/O and worker threads so they can be
 * refused (never silently allowed).
 *
 * observe(fn, args) runs the call under control and returns
 * {value, exception, counts}. The worker runs it twice per input; if the two
 * controlled runs disagree, the input is nondeterministic and refused.
 */

const { canonical } = require('./canonical');

const FROZEN_NOW_MS = 1700000000000; // mirrors Python FROZEN_NOW (seconds) * 1000

// Deterministic PRNG (mulberry32), reseeded at the start of every observe so the
// entropy stream is identical across the two determinism-guard runs.
function makeRng(seed) {
  let a = seed >>> 0;
  return function rng() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function controlEnter(counts) {
  const saved = {};
  const rng = makeRng(0x9e3779b9);

  // --- clock ---
  const RealDate = Date;
  saved.Date = RealDate;
  class FrozenDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(FROZEN_NOW_MS);
      else super(...args);
    }
    static now() { return FROZEN_NOW_MS; }
  }
  globalThis.Date = FrozenDate;

  saved.perfNow = null;
  if (globalThis.performance && globalThis.performance.now) {
    saved.perfNow = globalThis.performance.now;
    try {
      Object.defineProperty(globalThis.performance, 'now', {
        value: () => 0, configurable: true, writable: true,
      });
    } catch (e) {
      saved.perfNow = null; // couldn't override; leave it (best-effort)
    }
  }

  saved.hrtime = process.hrtime;
  const frozenHrtime = (prev) => (prev ? [0, 0] : [0, 0]);
  frozenHrtime.bigint = () => 0n;
  process.hrtime = frozenHrtime;

  // --- entropy ---
  saved.mathRandom = Math.random;
  Math.random = rng;

  let crypto = null;
  try { crypto = require('node:crypto'); } catch (e) { crypto = null; }
  if (crypto) {
    saved.randomBytes = crypto.randomBytes;
    crypto.randomBytes = (size) => Buffer.alloc(typeof size === 'number' ? size : 0, 7);
    saved.randomFillSync = crypto.randomFillSync;
    crypto.randomFillSync = (buf) => { if (buf && buf.fill) buf.fill(7); return buf; };
    if (crypto.randomUUID) {
      saved.randomUUID = crypto.randomUUID;
      crypto.randomUUID = () => '00000000-0000-4000-8000-000000000000';
    }
    if (crypto.webcrypto && crypto.webcrypto.getRandomValues) {
      saved.getRandomValues = crypto.webcrypto.getRandomValues.bind(crypto.webcrypto);
      crypto.webcrypto.getRandomValues = (arr) => { if (arr && arr.fill) arr.fill(7); return arr; };
    }
  }
  saved.crypto = crypto;

  // --- I/O counting (best-effort: fs + net) ---
  const fs = require('node:fs');
  saved.fs = {};
  const IO_FNS = ['readFileSync', 'writeFileSync', 'openSync', 'appendFileSync',
    'readFile', 'writeFile', 'open', 'appendFile'];
  for (const name of IO_FNS) {
    if (typeof fs[name] === 'function') {
      saved.fs[name] = fs[name];
      const real = fs[name];
      fs[name] = function counted(...a) { counts.io += 1; return real.apply(this, a); };
    }
  }
  let net = null;
  try { net = require('node:net'); } catch (e) { net = null; }
  if (net && net.Socket && net.Socket.prototype.connect) {
    saved.net = net;
    saved.connect = net.Socket.prototype.connect;
    const realConnect = saved.connect;
    net.Socket.prototype.connect = function counted(...a) { counts.io += 1; return realConnect.apply(this, a); };
  }

  // --- thread counting (worker_threads) ---
  let wt = null;
  try { wt = require('node:worker_threads'); } catch (e) { wt = null; }
  if (wt && wt.Worker) {
    saved.wt = wt;
    saved.Worker = wt.Worker;
    const RealWorker = saved.Worker;
    wt.Worker = class CountedWorker extends RealWorker {
      constructor(...a) { counts.threads += 1; super(...a); }
    };
  }

  return saved;
}

function controlExit(saved) {
  globalThis.Date = saved.Date;
  if (saved.perfNow && globalThis.performance) {
    try {
      Object.defineProperty(globalThis.performance, 'now', {
        value: saved.perfNow, configurable: true, writable: true,
      });
    } catch (e) { /* best-effort restore */ }
  }
  process.hrtime = saved.hrtime;
  Math.random = saved.mathRandom;
  if (saved.crypto) {
    const crypto = saved.crypto;
    crypto.randomBytes = saved.randomBytes;
    crypto.randomFillSync = saved.randomFillSync;
    if (saved.randomUUID) crypto.randomUUID = saved.randomUUID;
    if (saved.getRandomValues) crypto.webcrypto.getRandomValues = saved.getRandomValues;
  }
  const fs = require('node:fs');
  for (const name of Object.keys(saved.fs)) fs[name] = saved.fs[name];
  if (saved.net) saved.net.Socket.prototype.connect = saved.connect;
  if (saved.wt) saved.wt.Worker = saved.Worker;
}

function excName(e) {
  if (e && e.constructor && e.constructor.name) return e.constructor.name;
  return typeof e;
}

// Run fn(...args) once under control. Supports sync functions and functions that
// return a thenable (awaited). Returns {value, exception, counts}.
async function observe(fn, args) {
  const counts = { io: 0, threads: 0 };
  const saved = controlEnter(counts);
  let value;
  let exception = null;
  try {
    let r = fn(...args);
    if (r && typeof r.then === 'function') r = await r;
    value = r;
  } catch (e) {
    exception = excName(e);
  } finally {
    controlExit(saved);
  }
  return { value, exception, counts };
}

module.exports = { observe, canonical, FROZEN_NOW_MS, makeRng };
