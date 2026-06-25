'use strict';
/**
 * Runs the language-neutral conformance vectors (SPEC/conformance/cases/*.json)
 * against the JS implementation's comparator and soundness gate. Mirrors
 * packages/python/tests/test_conformance.py. See SPEC/conformance/README.md.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { same, unsound } = require('../src/soundness');

// packages/node/test -> packages/node -> packages -> repo root -> SPEC
const CASES = path.resolve(__dirname, '..', '..', '..', 'SPEC', 'conformance', 'cases');

function load(name) {
  return JSON.parse(fs.readFileSync(path.join(CASES, name), 'utf8')).cases;
}

const present = fs.existsSync(CASES);

test('conformance: canonical comparison', { skip: present ? false : 'SPEC/conformance not present' }, () => {
  for (const c of load('canonical-comparison.json')) {
    assert.strictEqual(same(c.a, c.b), c.same, `comparison vector ${c.name}`);
  }
});

test('conformance: soundness verdicts', { skip: present ? false : 'SPEC/conformance not present' }, () => {
  for (const c of load('soundness-verdicts.json')) {
    assert.strictEqual(unsound(c.observations), c.reason, `soundness vector ${c.name}`);
  }
});
