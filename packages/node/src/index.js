'use strict';
/** Public API for the Selfsame JS implementation. */

const { canonical } = require('./canonical');
const { same, unsound, hasOpaque, deepEqual } = require('./soundness');
const { observe } = require('./harness');
const { runCapture } = require('./capture');
const { runReplay, summarize } = require('./replay');
const { runVerify } = require('./verify');

module.exports = {
  canonical, same, unsound, hasOpaque, deepEqual, observe,
  runCapture, runReplay, runVerify, summarize,
};
