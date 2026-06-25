'use strict';
/** Public API for the Selfsame JS implementation. */

const { canonical } = require('./canonical');
const { same, unsound, hasOpaque, deepEqual } = require('./soundness');
const { observe } = require('./harness');
const { runCapture } = require('./capture');
const { runReplay, summarize } = require('./replay');
const { runVerify } = require('./verify');
const { runSnapshot, runDrift } = require('./snapshot');
const { buildReport, writeReport } = require('./report');

module.exports = {
  canonical, same, unsound, hasOpaque, deepEqual, observe,
  runCapture, runReplay, runVerify, runSnapshot, runDrift,
  buildReport, writeReport, summarize,
};
