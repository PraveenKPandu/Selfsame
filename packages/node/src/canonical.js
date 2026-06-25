'use strict';
/**
 * JSON-serializable canonical form of a JavaScript value, for comparing
 * observations across processes. Implements SPEC/protocol.md section 4 for the
 * JS runtime: two values share a canonical form iff they are observationally
 * indistinguishable. Mirrors packages/python/probe/canonical.py, adapted to
 * JS value semantics (NaN/-0, Map/Set, BigInt, Date, RegExp, class instances).
 *
 * The output is a tagged array (e.g. ["int", 1]); equality is plain structural
 * equality of these arrays (set/map children are order-normalized), never
 * toString() or identity.
 */

const MAX_DEPTH = 60;
const ITER_CAP = parseInt(process.env.PROBE_ITER_CAP || '1000', 10);

// Deterministic key for sorting unordered-collection children. Canonical forms
// are arrays of arrays/primitives (no plain objects), so JSON.stringify is
// order-stable.
function sortKey(c) {
  return JSON.stringify(c);
}

function isPlainObject(v) {
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

function ownEntries(obj) {
  // Own enumerable string-keyed properties, read directly (no getters that the
  // author didn't make enumerable own-data — keeps it side-effect-free-ish).
  const out = [];
  for (const k of Object.keys(obj)) out.push([k, obj[k]]);
  return out;
}

function canonical(value, depth = 0) {
  if (depth > MAX_DEPTH) return ['maxdepth'];

  // null vs undefined are observably distinct in JS.
  if (value === null) return ['none'];
  if (value === undefined) return ['singleton', 'undefined'];

  const t = typeof value;

  if (t === 'boolean') return ['bool', value];

  if (t === 'number') {
    if (Number.isNaN(value)) return ['float', 'nan'];
    if (value === Infinity) return ['float', 'inf'];
    if (value === -Infinity) return ['float', '-inf'];
    if (value === 0) return ['float', 0]; // normalizes -0 to 0
    return ['float', value];
  }

  if (t === 'bigint') return ['bigint', value.toString()];

  if (t === 'string') return ['str', value];

  if (t === 'symbol') return ['opaque', 'Symbol', '<unrepresentable>'];

  if (t === 'function') {
    // class or function — identify by name (value comparison is meaningless).
    const isClass = /^class[\s{]/.test(Function.prototype.toString.call(value));
    return [isClass ? 'class' : 'callable', '?', value.name || '?'];
  }

  // From here, t === 'object'.
  // Byte sequences.
  if (value instanceof ArrayBuffer) {
    return ['bytes', Array.from(new Uint8Array(value))];
  }
  if (ArrayBuffer.isView(value) && !(value instanceof DataView)) {
    // Typed arrays (incl. Buffer) -> bytes view of their numeric contents.
    return ['bytes', Array.from(value, (x) => (typeof x === 'bigint' ? Number(x) : x))];
  }

  // Value types by observable form.
  if (value instanceof Date) {
    const ms = value.getTime();
    return ['datetime', Number.isNaN(ms) ? 'invalid' : value.toISOString()];
  }
  if (value instanceof RegExp) {
    return ['pattern', value.source, value.flags];
  }
  if (value instanceof Error) {
    return ['obj', value.name || 'Error', canonical({ message: value.message }, depth + 1)];
  }

  if (Array.isArray(value)) {
    return ['list', value.map((x) => canonical(x, depth + 1))];
  }

  if (value instanceof Set) {
    const items = Array.from(value, (x) => canonical(x, depth + 1));
    items.sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0));
    return ['set', items];
  }

  if (value instanceof Map) {
    const items = Array.from(value, ([k, v]) => [canonical(k, depth + 1), canonical(v, depth + 1)]);
    items.sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0));
    return ['dict', items];
  }

  // Plain object -> dict (order-normalized by key).
  if (isPlainObject(value)) {
    const items = ownEntries(value).map(([k, v]) => [canonical(k, depth + 1), canonical(v, depth + 1)]);
    items.sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0));
    return ['dict', items];
  }

  // A generic iterable (iterator/generator) that isn't a known container: the
  // behavior is the sequence it yields, materialized up to ITER_CAP.
  if (typeof value[Symbol.iterator] === 'function' && typeof value.next === 'function') {
    const items = [];
    let i = 0;
    for (const x of value) {
      if (i >= ITER_CAP) return ['opaque', 'iterator-truncated', '<unrepresentable>'];
      items.push(canonical(x, depth + 1));
      i += 1;
    }
    return ['iter', items];
  }

  // Class instance: compare by its observable own-data state, tagged with the
  // class name so two different classes never collide. An empty-but-present
  // state is empty state (comparable), per protocol section 4.3.
  const className = (value.constructor && value.constructor.name) || 'Object';
  const entries = ownEntries(value);
  if (entries.length > 0 || isIntrospectable(value)) {
    const items = entries.map(([k, v]) => [canonical(k, depth + 1), canonical(v, depth + 1)]);
    items.sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0));
    return ['obj', className, ['dict', items]];
  }

  // No introspectable state at all -> refuse (tagged uniquely so two opaque
  // values never compare equal).
  return ['opaque', className, '<unrepresentable>'];
}

function isIntrospectable(value) {
  // An object whose own-enumerable set is empty but is a real class instance
  // (non-Object prototype) is "empty state", still comparable.
  const proto = Object.getPrototypeOf(value);
  return proto !== null && proto !== Object.prototype;
}

module.exports = { canonical, MAX_DEPTH, ITER_CAP };
