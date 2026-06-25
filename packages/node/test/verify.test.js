'use strict';
/**
 * End-to-end test for `verify`: capture inputs from the working tree, then
 * replay across two git refs in isolated worktrees.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const { runVerify } = require('../src/verify');

function git(repo, ...args) {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`);
  return r.stdout.trim();
}

const V1 = `exports.applyDiscount = function applyDiscount(price, pct) {
  return Math.round(price * (1 - pct / 100) * 100) / 100;
};\n`;
const V2 = `exports.applyDiscount = function applyDiscount(price, pct) {
  return Math.floor(price * (1 - pct / 100) * 100) / 100;
};\n`;
const RUNNER = `const { applyDiscount } = require('./pricing.js');
for (const [p, d] of [[100,10],[19.99,15],[250,33],[5.55,50]]) applyDiscount(p, d);\n`;

test('verify catches a regression between a committed base and the working tree', () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-verify-'));
  try {
    git(repo, 'init', '-q');
    git(repo, 'config', 'user.email', 't@t.t');
    git(repo, 'config', 'user.name', 't');
    fs.writeFileSync(path.join(repo, 'pricing.js'), V1);
    fs.writeFileSync(path.join(repo, 'run.js'), RUNNER);
    git(repo, 'add', '-A');
    git(repo, 'commit', '-qm', 'v1');

    // The "AI refactor": edit the working tree (uncommitted).
    fs.writeFileSync(path.join(repo, 'pricing.js'), V2);

    const res = runVerify({
      cwd: repo, base: 'HEAD', root: repo,
      command: [process.execPath, path.join(repo, 'run.js')],
    });
    assert.strictEqual(res.capturedNothing, false);
    const row = res.rows.find((r) => r.qualname === 'applyDiscount');
    assert.ok(row, 'applyDiscount should be in the results');
    assert.strictEqual(row.verdict, 'divergent', JSON.stringify(row));
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test('verify reports equivalent when the working tree matches base', () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-verify-'));
  try {
    git(repo, 'init', '-q');
    git(repo, 'config', 'user.email', 't@t.t');
    git(repo, 'config', 'user.name', 't');
    fs.writeFileSync(path.join(repo, 'pricing.js'), V1);
    fs.writeFileSync(path.join(repo, 'run.js'), RUNNER);
    git(repo, 'add', '-A');
    git(repo, 'commit', '-qm', 'v1');

    const res = runVerify({
      cwd: repo, base: 'HEAD', root: repo,
      command: [process.execPath, path.join(repo, 'run.js')],
    });
    const row = res.rows.find((r) => r.qualname === 'applyDiscount');
    assert.strictEqual(row.verdict, 'equivalent', JSON.stringify(row));
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});
