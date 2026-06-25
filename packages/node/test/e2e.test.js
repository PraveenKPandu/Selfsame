'use strict';
/**
 * End-to-end proof: capture real inputs from a run, then replay them across two
 * versions of a module and confirm a silent behavior change is caught (and that
 * an unchanged version reports equivalent).
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { runCapture } = require('../src/capture');
const { runReplay, summarize } = require('../src/replay');

function mktmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-js-'));
}

const V1 = `
exports.applyDiscount = function applyDiscount(price, pct) {
  return Math.round(price * (1 - pct / 100) * 100) / 100;
};
exports.slugify = function slugify(s) { return s.toLowerCase().split(/\\s+/).join('-'); };
`;
// "Harmless" refactor: floor instead of round. slugify unchanged.
const V2 = `
exports.applyDiscount = function applyDiscount(price, pct) {
  return Math.floor(price * (1 - pct / 100) * 100) / 100;
};
exports.slugify = function slugify(s) { return s.toLowerCase().split(/\\s+/).join('-'); };
`;
const RUNNER = `
const { applyDiscount, slugify } = require('./pricing.js');
for (const [p, d] of [[100,10],[19.99,15],[250.0,33],[5.55,50]]) applyDiscount(p, d);
slugify('Hello World');
`;

test('captures inputs, catches a silent regression, leaves the unchanged fn equivalent', () => {
  const before = mktmp();
  const after = mktmp();
  const capdir = mktmp();
  try {
    fs.writeFileSync(path.join(before, 'pricing.js'), V1);
    fs.writeFileSync(path.join(before, 'run.js'), RUNNER);
    fs.writeFileSync(path.join(after, 'pricing.js'), V2);

    // capture from a real run against the v1 source
    const cap = runCapture({
      root: before, outDir: capdir,
      command: [process.execPath, path.join(before, 'run.js')],
    });
    assert.ok(cap.exists, 'captures.json should exist');
    assert.ok(cap.count >= 4, `expected >=4 captured inputs, got ${cap.count}`);

    const rows = runReplay({ capturesFile: cap.capturesFile, beforeRoot: before, afterRoot: after });
    const byName = Object.fromEntries(rows.map((r) => [r.qualname, r]));

    assert.strictEqual(byName.applyDiscount.verdict, 'divergent', JSON.stringify(byName.applyDiscount));
    assert.strictEqual(byName.slugify.verdict, 'equivalent', JSON.stringify(byName.slugify));

    const s = summarize(rows);
    assert.strictEqual(s.divergent, 1);
    assert.strictEqual(s.equivalent, 1);
  } finally {
    for (const d of [before, after, capdir]) fs.rmSync(d, { recursive: true, force: true });
  }
});

test('captures and verifies a bare default function export (module.exports = fn)', () => {
  const before = mktmp();
  const after = mktmp();
  const capdir = mktmp();
  try {
    fs.writeFileSync(path.join(before, 'slug.js'),
      "module.exports = function slugify(s){ return s.toLowerCase().split(/\\s+/).join('-'); };\n");
    fs.writeFileSync(path.join(before, 'run.js'),
      "const slugify = require('./slug.js'); ['Hello World','Hello, World!'].forEach(slugify);\n");
    // changed behavior: also strip non-alphanumerics
    fs.writeFileSync(path.join(after, 'slug.js'),
      "module.exports = function slugify(s){ return s.toLowerCase().replace(/[^a-z0-9]+/g,'-'); };\n");

    const cap = runCapture({
      root: before, outDir: capdir,
      command: [process.execPath, path.join(before, 'run.js')],
    });
    assert.ok(cap.count >= 2, `expected captured inputs, got ${cap.count}`);
    const rows = runReplay({ capturesFile: cap.capturesFile, beforeRoot: before, afterRoot: after });
    const row = rows.find((r) => r.qualname === '(default)');
    assert.ok(row, `default export should be captured: ${JSON.stringify(rows)}`);
    assert.strictEqual(row.verdict, 'divergent', JSON.stringify(row));
  } finally {
    for (const d of [before, after, capdir]) fs.rmSync(d, { recursive: true, force: true });
  }
});

test('identical versions report equivalent (no false positive)', () => {
  const before = mktmp();
  const after = mktmp();
  const capdir = mktmp();
  try {
    fs.writeFileSync(path.join(before, 'pricing.js'), V1);
    fs.writeFileSync(path.join(before, 'run.js'), RUNNER);
    fs.writeFileSync(path.join(after, 'pricing.js'), V1); // same code

    const cap = runCapture({
      root: before, outDir: capdir,
      command: [process.execPath, path.join(before, 'run.js')],
    });
    const rows = runReplay({ capturesFile: cap.capturesFile, beforeRoot: before, afterRoot: after });
    const s = summarize(rows);
    assert.strictEqual(s.divergent, 0, JSON.stringify(rows));
    assert.ok(s.equivalent >= 2);
  } finally {
    for (const d of [before, after, capdir]) fs.rmSync(d, { recursive: true, force: true });
  }
});
