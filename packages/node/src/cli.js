#!/usr/bin/env node
'use strict';
/**
 * selfsame (JavaScript) CLI.
 *
 *   selfsame capture --root <srcdir> --out <capdir> -- <command...>
 *   selfsame replay  --before <dirA> --after <dirB> --captures <capdir|file>
 *
 * `capture` records real inputs by running your command with the capture preload;
 * `replay` re-runs those inputs against two versions and prints a per-function
 * verdict (exit 1 on any divergence). See SPEC/protocol.md.
 */

const path = require('node:path');
const fs = require('node:fs');
const { runCapture } = require('./capture');
const { runReplay, summarize } = require('./replay');

const VERSION = require('../package.json').version;

function parseFlags(args) {
  const flags = {};
  const rest = [];
  for (let i = 0; i < args.length; i += 1) {
    const a = args[i];
    if (a === '--') { rest.push(...args.slice(i + 1)); break; }
    if (a.startsWith('--')) { flags[a.slice(2)] = args[i + 1]; i += 1; } else rest.push(a);
  }
  return { flags, rest };
}

function cmdCapture(args) {
  const { flags, rest } = parseFlags(args);
  if (!flags.root || !flags.out || rest.length === 0) {
    console.error('usage: selfsame capture --root <srcdir> --out <capdir> -- <command...>');
    return 2;
  }
  const res = runCapture({ root: flags.root, outDir: flags.out, command: rest });
  if (!res.exists) {
    console.error('no captures produced — did the command import modules under --root?');
    return 1;
  }
  console.log(`captured ${res.count} input(s) -> ${res.capturesFile}`);
  return 0;
}

function cmdReplay(args) {
  const { flags } = parseFlags(args);
  if (!flags.before || !flags.after || !flags.captures) {
    console.error('usage: selfsame replay --before <dirA> --after <dirB> --captures <capdir|file>');
    return 2;
  }
  let capturesFile = flags.captures;
  if (fs.existsSync(capturesFile) && fs.statSync(capturesFile).isDirectory()) {
    capturesFile = path.join(capturesFile, 'captures.json');
  }
  const rows = runReplay({
    capturesFile,
    beforeRoot: path.resolve(flags.before),
    afterRoot: path.resolve(flags.after),
  });
  let diverged = 0;
  for (const r of rows) {
    if (r.verdict === 'divergent') {
      diverged += 1;
      console.log(`X ${r.qualname}  n=${r.inputs}  divergent  @ input #${r.index}`);
      console.log(`      base : ${r.base}`);
      console.log(`      head : ${r.head}`);
    } else {
      const mark = r.verdict === 'equivalent' ? ' ' : '·';
      console.log(`${mark} ${r.qualname}  n=${r.inputs}  ${r.verdict}${r.note ? ` (${r.note})` : ''}`);
    }
  }
  const s = summarize(rows);
  console.log(`\nselfsame: ${s.equivalent} equivalent · ${s.divergent} divergent · ` +
    `${s.unverifiable} unverifiable · ${s.skipped} skipped · ${s.error} error`);
  return diverged > 0 ? 1 : 0;
}

function main(argv) {
  const [cmd, ...args] = argv;
  if (cmd === 'capture') return cmdCapture(args);
  if (cmd === 'replay') return cmdReplay(args);
  if (cmd === '--version' || cmd === '-v') { console.log(VERSION); return 0; }
  console.log('selfsame (JavaScript implementation of the Selfsame Protocol)\n');
  console.log('Commands:');
  console.log('  capture --root <srcdir> --out <capdir> -- <command...>   record real inputs');
  console.log('  replay  --before <dirA> --after <dirB> --captures <dir>  verify two versions');
  return cmd ? 2 : 0;
}

if (require.main === module) process.exit(main(process.argv.slice(2)));
module.exports = { main };
