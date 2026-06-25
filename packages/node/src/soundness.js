'use strict';
/**
 * The soundness gate and the observation comparator. Mirrors
 * packages/python/probe/replay.py (_has_opaque, _unsound, _same) and implements
 * SPEC/protocol.md sections 6 and 8. These are the pieces validated by the
 * cross-language conformance suite (SPEC/conformance).
 */

// Structural equality of two canonical forms (arrays of arrays/primitives).
function deepEqual(a, b) {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) if (!deepEqual(a[i], b[i])) return false;
    return true;
  }
  return false;
}

// True iff an `opaque` tag appears anywhere in a canonical form's tree.
function hasOpaque(form) {
  if (!Array.isArray(form)) return false;
  if (form[0] === 'opaque') return true;
  for (const el of form) if (Array.isArray(el) && hasOpaque(el)) return true;
  return false;
}

// Returns the refusal reason for a list of observations, or null if verifiable.
// Priority order is normative (SPEC section 6).
function unsound(obsList) {
  for (const o of obsList) {
    if (o.nondet) return 'nondeterministic';
    if ((o.io || 0) > 0) return 'uncontrolled-io';
    if ((o.threads || 0) > 0) return 'concurrency';
    if ('val' in o && hasOpaque(o.val)) return 'opaque-return';
    if (o.self_after != null && hasOpaque(o.self_after)) return 'opaque-state';
  }
  return null;
}

// Two observations are equal iff: exception-ness matches; if both raised, the
// error type names match; otherwise the val canonical forms match; AND the
// post-call receiver state matches (SPEC section 8).
function same(a, b) {
  const aExc = 'exc' in a;
  const bExc = 'exc' in b;
  if (aExc !== bExc) return false;
  if (aExc) {
    if (a.exc !== b.exc) return false;
  } else if (!deepEqual(a.val, b.val)) {
    return false;
  }
  const aSelf = a.self_after == null ? null : a.self_after;
  const bSelf = b.self_after == null ? null : b.self_after;
  if (aSelf === null && bSelf === null) return true;
  return deepEqual(aSelf, bSelf);
}

module.exports = { deepEqual, hasOpaque, unsound, same };
