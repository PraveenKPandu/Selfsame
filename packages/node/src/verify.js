'use strict';
/**
 * One-command verify: capture real inputs by running your command against the
 * working tree, then replay them across two git refs (base vs head) in isolated
 * worktrees. Mirrors packages/python/probe/verify.py.
 *
 * Each version is materialized as a `git worktree`, so two versions of the same
 * module never share a process. node_modules is symlinked into each worktree (if
 * present) so dependencies resolve without a reinstall.
 */

const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { runCapture } = require('./capture');
const { runReplay } = require('./replay');

function git(repo, args, opts = {}) {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8', ...opts });
  if (r.status !== 0 && !opts.allowFail) {
    throw new Error(`git ${args.join(' ')} failed: ${(r.stderr || '').trim()}`);
  }
  return (r.stdout || '').trim();
}

function repoRootOf(dir) {
  return git(dir, ['rev-parse', '--show-toplevel']);
}

function linkNodeModules(repoRoot, worktree) {
  const src = path.join(repoRoot, 'node_modules');
  const dst = path.join(worktree, 'node_modules');
  if (fs.existsSync(src) && !fs.existsSync(dst)) {
    try { fs.symlinkSync(src, dst, 'dir'); } catch (e) { /* best-effort */ }
  }
}

// opts: { cwd, base, head?, root, command:[...] }
// base/head are git refs; head omitted => the working tree.
function runVerify(opts) {
  const cwd = path.resolve(opts.cwd || process.cwd());
  const repoRoot = repoRootOf(cwd); // git returns a realpath
  // realpath so a symlinked CWD/root (e.g. macOS /var -> /private/var) yields the
  // correct relative path under the (realpathed) repo root.
  const realpath = (p) => { try { return fs.realpathSync(p); } catch (e) { return p; } };
  const rootAbs = realpath(path.resolve(opts.root || cwd));
  const rootRel = path.relative(repoRoot, rootAbs); // e.g. "src" or ""

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'selfsame-wt-'));
  const baseWt = path.join(tmp, 'base');
  const worktrees = [];
  let headRoot;
  try {
    git(repoRoot, ['worktree', 'add', '--detach', baseWt, opts.base]);
    worktrees.push(baseWt);
    linkNodeModules(repoRoot, baseWt);

    if (opts.head) {
      const headWt = path.join(tmp, 'head');
      git(repoRoot, ['worktree', 'add', '--detach', headWt, opts.head]);
      worktrees.push(headWt);
      linkNodeModules(repoRoot, headWt);
      headRoot = path.join(headWt, rootRel);
    } else {
      headRoot = rootAbs; // working tree
    }

    // Capture from the working tree (or head ref dir if given).
    const capOut = path.join(tmp, 'caps');
    const captureRoot = opts.head ? path.join(path.join(tmp, 'head'), rootRel) : rootAbs;
    const cap = runCapture({ root: captureRoot, outDir: capOut, command: opts.command });
    if (!cap.exists || cap.count === 0) {
      return { rows: [], capturedNothing: true };
    }

    const rows = runReplay({
      capturesFile: cap.capturesFile,
      beforeRoot: path.join(baseWt, rootRel),
      afterRoot: headRoot,
    });
    return { rows, capturedNothing: false };
  } finally {
    for (const wt of worktrees) {
      try { git(repoRoot, ['worktree', 'remove', '--force', wt], { allowFail: true }); } catch (e) { /* ignore */ }
    }
    try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  }
}

module.exports = { runVerify };
