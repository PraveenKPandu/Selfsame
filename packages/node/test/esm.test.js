'use strict';
/**
 * End-to-end test for ESM capture -> replay. Requires Node >= 20.6 (module.register)
 * and es-module-lexer installed; skips otherwise.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const hasRegister = typeof require('node:module').register === 'function';
let hasLexer = true;
try { require.resolve('es-module-lexer'); } catch (e) { hasLexer = false; }
const skip = !hasRegister ? 'needs Node >= 20.6 (module.register)'
  : !hasLexer ? 'needs es-module-lexer installed (npm install)' : false;

const { runCapture } = require('../src/capture');
const { runReplay, summarize } = require('../src/replay');

function mktmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-esm-')); }

test('ESM: capture then replay catches a regression; no false positive', { skip }, () => {
  const before = mktmp();
  const after = mktmp();
  const caps = mktmp();
  try {
    fs.writeFileSync(path.join(before, 'math.mjs'),
      'export function applyDiscount(price, pct){ return Math.round(price*(1-pct/100)); }\n'
      + 'export const TAX = 0.2;\n');
    fs.writeFileSync(path.join(before, 'run.mjs'),
      "import { applyDiscount } from './math.mjs';\n"
      + 'for (const [p,d] of [[100,10],[101,10],[3,10]]) applyDiscount(p,d);\n');
    // floor instead of round
    fs.writeFileSync(path.join(after, 'math.mjs'),
      'export function applyDiscount(price, pct){ return Math.floor(price*(1-pct/100)); }\n'
      + 'export const TAX = 0.2;\n');

    const cap = runCapture({
      root: before, outDir: caps, esm: true,
      command: [process.execPath, path.join(before, 'run.mjs')],
    });
    assert.ok(cap.count >= 3, `expected captured inputs, got ${cap.count}`);

    let rows = runReplay({ capturesFile: cap.capturesFile, beforeRoot: before, afterRoot: after });
    const row = rows.find((r) => r.qualname === 'applyDiscount');
    assert.ok(row, `applyDiscount captured: ${JSON.stringify(rows)}`);
    assert.strictEqual(row.verdict, 'divergent', JSON.stringify(row));

    // identical versions -> equivalent (no false positive)
    rows = runReplay({ capturesFile: cap.capturesFile, beforeRoot: before, afterRoot: before });
    assert.strictEqual(summarize(rows).divergent, 0, JSON.stringify(rows));
  } finally {
    for (const d of [before, after, caps]) fs.rmSync(d, { recursive: true, force: true });
  }
});
