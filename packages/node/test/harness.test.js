'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { observe, canonical } = require('../src/harness');
const { unsound } = require('../src/soundness');

test('clock is frozen and identical across runs', async () => {
  const f = () => Date.now();
  const a = await observe(f, []);
  const b = await observe(f, []);
  assert.strictEqual(a.value, b.value);
  assert.deepStrictEqual(canonical(a.value), canonical(b.value));
});

test('Math.random is seeded and reproducible across runs', async () => {
  const f = () => [Math.random(), Math.random()];
  const a = await observe(f, []);
  const b = await observe(f, []);
  assert.deepStrictEqual(canonical(a.value), canonical(b.value));
});

test('new Date() with no args is frozen', async () => {
  const f = () => new Date().toISOString();
  const a = await observe(f, []);
  assert.strictEqual(a.value, '2023-11-14T22:13:20.000Z');
});

test('fs read is counted as I/O -> refused', async () => {
  const f = () => require('node:fs').readFileSync(__filename, 'utf8').length;
  const o = await observe(f, []);
  assert.ok(o.counts.io > 0, 'io should be counted');
  const obs = { val: canonical(o.value), io: o.counts.io, threads: o.counts.threads };
  assert.strictEqual(unsound([obs]), 'uncontrolled-io');
});

test('async function is awaited', async () => {
  const f = async (x) => x * 2;
  const o = await observe(f, [21]);
  assert.strictEqual(o.value, 42);
  assert.strictEqual(o.exception, null);
});

test('exception is captured by type name', async () => {
  const f = () => { throw new TypeError('nope'); };
  const o = await observe(f, []);
  assert.strictEqual(o.exception, 'TypeError');
});

test('control is restored after observe', async () => {
  const realNow = Date.now;
  await observe(() => Date.now(), []);
  assert.strictEqual(Date.now, realNow);
  assert.notStrictEqual(Date.now(), 1700000000000);
});
