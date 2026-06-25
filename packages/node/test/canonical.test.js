'use strict';
/**
 * JS-specific `value -> canonical` golden tests: the part the language-neutral
 * conformance suite can't cover, because it requires constructing native JS
 * values. Locks the JS value semantics (NaN/-0, null vs undefined, BigInt,
 * Map/Set ordering, Date, RegExp, class instances).
 */

const test = require('node:test');
const assert = require('node:assert');
const { canonical } = require('../src/canonical');

function eq(a, b) {
  return assert.deepStrictEqual(a, b);
}

test('primitives and number edge cases', () => {
  eq(canonical(null), ['none']);
  eq(canonical(undefined), ['singleton', 'undefined']);
  eq(canonical(true), ['bool', true]);
  eq(canonical(42), ['float', 42]);
  eq(canonical(1.5), ['float', 1.5]);
  eq(canonical(NaN), ['float', 'nan']);
  eq(canonical(Infinity), ['float', 'inf']);
  eq(canonical(-Infinity), ['float', '-inf']);
  eq(canonical(-0), ['float', 0]); // -0 normalized to 0
  eq(canonical('hi'), ['str', 'hi']);
  eq(canonical(10n), ['bigint', '10']);
});

test('null and undefined are distinct; -0 equals 0', () => {
  assert.notDeepStrictEqual(canonical(null), canonical(undefined));
  eq(canonical(-0), canonical(0));
});

test('arrays, sets, maps, plain objects', () => {
  eq(canonical([1, 'a']), ['list', [['float', 1], ['str', 'a']]]);
  // Set is order-normalized: {2,1} canonicalizes the same as {1,2}.
  eq(canonical(new Set([2, 1])), canonical(new Set([1, 2])));
  // Map and plain object both -> dict, order-normalized.
  eq(canonical({ b: 2, a: 1 }), canonical({ a: 1, b: 2 }));
  eq(
    canonical(new Map([['a', 1]])),
    ['dict', [[['str', 'a'], ['float', 1]]]],
  );
});

test('Date and RegExp by observable form', () => {
  eq(canonical(new Date('2020-01-01T00:00:00.000Z')), ['datetime', '2020-01-01T00:00:00.000Z']);
  eq(canonical(/ab+c/gi), ['pattern', 'ab+c', 'gi']);
});

test('class instance by state; empty state still comparable', () => {
  class Counter {
    constructor(n) { this.n = n; }
    inc() { this.n += 1; }
  }
  eq(canonical(new Counter(3)), ['obj', 'Counter', ['dict', [[['str', 'n'], ['float', 3]]]]]);
  // Two stateless instances of the same class are observationally equal.
  class Empty {}
  eq(canonical(new Empty()), canonical(new Empty()));
});

test('Error carries name + message', () => {
  eq(canonical(new TypeError('bad')), ['obj', 'TypeError', ['dict', [[['str', 'message'], ['str', 'bad']]]]]);
});

test('symbols are opaque (refused downstream)', () => {
  eq(canonical(Symbol('x')), ['opaque', 'Symbol', '<unrepresentable>']);
});
