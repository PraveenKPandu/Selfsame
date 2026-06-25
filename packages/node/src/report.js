'use strict';
/**
 * Agent-consumable report writer. Emits .selfsame/report.json following
 * SPEC/schemas/report.schema.json, so a tool or agent can read the verdicts,
 * witnesses, and soundness reasons of a run. Mirrors the Python report.
 */

const path = require('node:path');
const fs = require('node:fs');

function summarize(rows) {
  const s = {
    equivalent: 0, divergent: 0, unverifiable: 0, interface_change: 0,
    error: 0, timeout: 0, skipped: 0, functions_checked: rows.length,
  };
  for (const r of rows) {
    const k = r.verdict === 'interface-change' ? 'interface_change' : r.verdict;
    if (k in s) s[k] += 1;
  }
  return s;
}

function buildReport(rows, label) {
  return {
    tool: 'selfsame',
    schema: 1,
    label: label || '',
    environment: { lang: 'javascript', node: process.version },
    summary: summarize(rows),
    results: rows.map((r) => ({
      function: r.qualname,
      key: r.key,
      inputs: r.inputs,
      verdict: r.verdict,
      ...(r.note ? { reason: r.note } : {}),
      ...(r.index != null ? { input_index: r.index } : {}),
      ...(r.base != null ? { base: r.base } : {}),
      ...(r.head != null ? { head: r.head } : {}),
    })),
    unverified_changed: [],
  };
}

function writeReport(rows, label, reportPath) {
  const p = path.resolve(reportPath);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(buildReport(rows, label), null, 2));
  return p;
}

module.exports = { buildReport, writeReport };
