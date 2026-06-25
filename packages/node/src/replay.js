'use strict';
/**
 * Replay orchestrator: given captured inputs and two version roots, run each
 * captured input on both versions (each in its own subprocess) and produce a
 * per-unit verdict. Mirrors packages/python/probe/replay.py (the verdict model
 * is SPEC/protocol.md section 8).
 */

const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { same, unsound } = require('./soundness');

const WORKER = path.join(__dirname, 'replayWorker.js');

function splitKey(key) {
  const i = key.indexOf('::');
  return [key.slice(0, i), key.slice(i + 2)];
}

function runWorker(versionRoot, moduleRel, qualname, isMethod, argsB64) {
  const job = JSON.stringify({ versionRoot, moduleRel, qualname, is_method: isMethod, args_b64: argsB64 });
  const r = spawnSync(process.execPath, [WORKER], {
    input: job, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    env: { ...process.env, PYTHONHASHSEED: '0' },
  });
  if (r.status !== 0 && !r.stdout) {
    return { loaded: false, error: `worker exited: ${(r.stderr || '').slice(0, 300)}`, obs: [] };
  }
  try { return JSON.parse(r.stdout); } catch (e) {
    return { loaded: false, error: `bad worker output: ${(r.stdout || r.stderr || '').slice(0, 300)}`, obs: [] };
  }
}

function render(o) {
  if (!o) return '∅';
  if ('exc' in o) return `raise ${o.exc}`;
  try { return JSON.stringify(o.val); } catch (e) { return String(o.val); }
}

function verdictFor(base, head) {
  if (base.error || head.error) return { verdict: 'error', note: base.error || head.error };
  if (base.absent || head.absent) return { verdict: 'skipped', note: 'added/removed' };
  if (!base.loaded || !head.loaded) return { verdict: 'skipped', note: 'not loaded in both' };
  const bu = unsound(base.obs);
  if (bu) return { verdict: 'unverifiable', note: bu };
  const hu = unsound(head.obs);
  if (hu) return { verdict: 'unverifiable', note: hu };
  if (base.obs.length !== head.obs.length) return { verdict: 'error', note: 'observation count mismatch' };
  for (let i = 0; i < base.obs.length; i += 1) {
    if (!same(base.obs[i], head.obs[i])) {
      return { verdict: 'divergent', index: i, base: render(base.obs[i]), head: render(head.obs[i]) };
    }
  }
  return { verdict: 'equivalent' };
}

function runReplay(opts) {
  const { capturesFile, beforeRoot, afterRoot } = opts;
  const data = JSON.parse(fs.readFileSync(capturesFile, 'utf8'));
  const byKey = new Map();
  for (const rec of data.records) {
    if (!byKey.has(rec.key)) byKey.set(rec.key, { is_method: rec.is_method, args: [] });
    byKey.get(rec.key).args.push(rec.args_b64);
  }

  const rows = [];
  for (const [key, info] of byKey) {
    const [moduleRel, qualname] = splitKey(key);
    const base = runWorker(beforeRoot, moduleRel, qualname, info.is_method, info.args);
    const head = runWorker(afterRoot, moduleRel, qualname, info.is_method, info.args);
    rows.push({ key, qualname, inputs: info.args.length, ...verdictFor(base, head) });
  }
  return rows;
}

function summarize(rows) {
  const c = { equivalent: 0, divergent: 0, unverifiable: 0, skipped: 0, error: 0 };
  for (const r of rows) c[r.verdict] = (c[r.verdict] || 0) + 1;
  return c;
}

module.exports = { runReplay, summarize, render };
