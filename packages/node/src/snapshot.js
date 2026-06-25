'use strict';
/**
 * snapshot / drift: freeze the current (accepted) build's behavior, then measure
 * how far later code drifts from it — no second branch needed. Mirrors
 * packages/python/probe/snapshot.py. This is the AI-velocity workflow: accept a
 * build once, then `drift` after every change.
 */

const path = require('node:path');
const fs = require('node:fs');
const { runCapture } = require('./capture');
const { groupCaptures, observeVersion, splitKey, verdictFor } = require('./replay');

// Freeze: capture real inputs by running the command, then record the current
// version's observations as the baseline. opts: { root, command, snapshotPath }.
function runSnapshot(opts) {
  const root = path.resolve(opts.root);
  const tmpOut = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'selfsame-snap-'));
  const cap = runCapture({ root, outDir: tmpOut, command: opts.command });
  if (!cap.exists || cap.count === 0) return { capturedNothing: true };

  const data = JSON.parse(fs.readFileSync(cap.capturesFile, 'utf8'));
  const byKey = groupCaptures(data.records);
  const baseline = observeVersion(root, byKey);

  const units = {};
  for (const [key, info] of byKey) {
    units[key] = { is_method: info.is_method, args_b64: info.args, baseline: baseline[key] };
  }
  const snapshot = { meta: { lang: 'javascript', schema: 1 }, units };
  fs.mkdirSync(path.dirname(path.resolve(opts.snapshotPath)), { recursive: true });
  fs.writeFileSync(path.resolve(opts.snapshotPath), JSON.stringify(snapshot));
  fs.rmSync(tmpOut, { recursive: true, force: true });
  return { capturedNothing: false, units: Object.keys(units).length, snapshotPath: opts.snapshotPath };
}

// Measure drift of the current code at `root` against a frozen snapshot.
function runDrift(opts) {
  const root = path.resolve(opts.root);
  const snap = JSON.parse(fs.readFileSync(path.resolve(opts.snapshotPath), 'utf8'));
  const byKey = new Map();
  for (const [key, u] of Object.entries(snap.units)) {
    byKey.set(key, { is_method: u.is_method, args: u.args_b64 });
  }
  const current = observeVersion(root, byKey);

  const rows = [];
  for (const [key, u] of Object.entries(snap.units)) {
    const [, qualname] = splitKey(key);
    const inputs = u.args_b64.length;
    rows.push({ key, qualname, inputs, ...verdictFor(u.baseline, current[key]) });
  }
  return rows;
}

module.exports = { runSnapshot, runDrift };
