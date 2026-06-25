'use strict';
/**
 * snapshot/drift end-to-end: freeze the accepted build, then detect a regression
 * after an edit — and confirm no false positive when nothing changed. Plus the
 * agent-consumable report shape.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { runSnapshot, runDrift } = require('../src/snapshot');
const { buildReport } = require('../src/report');

function mktmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-snap-test-')); }

const V1 = "exports.applyDiscount = function applyDiscount(p, d){ return Math.round(p*(1-d/100)*100)/100; };\n";
const V2 = "exports.applyDiscount = function applyDiscount(p, d){ return Math.floor(p*(1-d/100)*100)/100; };\n";
const RUN = "const { applyDiscount } = require('./pricing.js'); for (const [p,d] of [[100,10],[250,33]]) applyDiscount(p,d);\n";

test('snapshot then drift detects a regression', () => {
  const proj = mktmp();
  try {
    fs.writeFileSync(path.join(proj, 'pricing.js'), V1);
    fs.writeFileSync(path.join(proj, 'run.js'), RUN);
    const snapPath = path.join(proj, '.selfsame', 'snapshot.json');

    const snap = runSnapshot({ root: proj, command: [process.execPath, path.join(proj, 'run.js')], snapshotPath: snapPath });
    assert.strictEqual(snap.capturedNothing, false);
    assert.ok(fs.existsSync(snapPath));

    // no change yet -> no drift
    let rows = runDrift({ root: proj, snapshotPath: snapPath });
    assert.strictEqual(rows.find((r) => r.qualname === 'applyDiscount').verdict, 'equivalent');

    // edit the working tree -> drift detected against the frozen baseline
    fs.writeFileSync(path.join(proj, 'pricing.js'), V2);
    rows = runDrift({ root: proj, snapshotPath: snapPath });
    assert.strictEqual(rows.find((r) => r.qualname === 'applyDiscount').verdict, 'divergent');
  } finally {
    fs.rmSync(proj, { recursive: true, force: true });
  }
});

test('report.json shape follows the protocol', () => {
  const rows = [
    { key: 'm::f', qualname: 'f', inputs: 3, verdict: 'divergent', index: 1, base: '1', head: '2' },
    { key: 'm::g', qualname: 'g', inputs: 2, verdict: 'equivalent' },
  ];
  const rep = buildReport(rows, 'a..b');
  assert.strictEqual(rep.tool, 'selfsame');
  assert.strictEqual(rep.schema, 1);
  assert.strictEqual(rep.summary.divergent, 1);
  assert.strictEqual(rep.summary.equivalent, 1);
  assert.strictEqual(rep.summary.functions_checked, 2);
  assert.strictEqual(rep.results[0].key, 'm::f');
  assert.strictEqual(rep.results[0].input_index, 1);
  assert.ok(Array.isArray(rep.unverified_changed));
});
