'use strict';
/**
 * Capture driver: run a user command with the capture preload attached, so the
 * real arguments to target modules' functions are recorded. Mirrors
 * packages/python/probe/capture.py.
 */

const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

const REGISTER = path.join(__dirname, 'captureRegister.js');           // CommonJS hook
const ESM_REGISTER = path.join(__dirname, 'esmRegister.mjs');          // ESM loader hook

// opts: { root, outDir, command: [cmd, ...args], esm? }
function runCapture(opts) {
  const root = path.resolve(opts.root);
  const outDir = path.resolve(opts.outDir);
  fs.mkdirSync(outDir, { recursive: true });

  // ESM uses --import (module.register loader, Node >= 20.6); CJS uses --require.
  const preload = opts.esm
    ? `--import ${pathToFileURL(ESM_REGISTER).href}`
    : `--require ${REGISTER}`;
  const [cmd, ...rest] = opts.command;
  const env = {
    ...process.env,
    PROBE_CAPTURE_ROOT: root,
    PROBE_CAPTURE_DIR: outDir,
    NODE_OPTIONS: `${process.env.NODE_OPTIONS ? `${process.env.NODE_OPTIONS} ` : ''}${preload}`,
  };
  const r = spawnSync(cmd, rest, { env, stdio: 'inherit' });

  const capFile = path.join(outDir, 'captures.json');
  const exists = fs.existsSync(capFile);
  let count = 0;
  if (exists) count = (JSON.parse(fs.readFileSync(capFile, 'utf8')).records || []).length;
  return { capturesFile: capFile, exists, count, status: r.status };
}

module.exports = { runCapture };
