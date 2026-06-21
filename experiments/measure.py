"""Measure verifiable coverage on the phase-3 stratified corpus.

Runs probe.check's isolated pipeline over every paired function and tallies how
many got a trustworthy verdict, broken down by stratum and by failure reason.
The headline % is indicative (the sample is constructed, not a random GitHub
draw); the failure-mode breakdown is the durable finding.

Run:  python3 experiments/measure.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe.check import _check_one, _repo_root  # noqa: E402
from probe.extract import pair_functions, source_from_file  # noqa: E402

# What is actually true about each refactor (author ground truth), so we can
# tell a trustworthy verdict from a confidently-wrong one.
GROUND_TRUTH = {
    "clamp": "divergent",          # differs when lo > hi
    "to_snake_case": "equivalent",
    "parse_bool": "divergent",     # dropped the "on" token
    "running_total": "equivalent",
    "capwords": "equivalent",
    "commonprefix": "equivalent",
    "order_total": "equivalent",
    "session_token": "equivalent",
    "backoff_delay": "equivalent",
    "read_first_line": "io",       # behavior depends on the real filesystem
    "fetch_status": "io",          # behavior depends on the real network
    "parallel_sum": "unverifiable",  # concurrent; race may not manifest
}

STRATUM = {
    "clamp": "pure-typed",
    "to_snake_case": "pure-typed",
    "parse_bool": "pure-typed",
    "running_total": "pure-typed",
    "capwords": "pure-untyped",
    "commonprefix": "pure-untyped",
    "order_total": "pure-domain-typed",
    "session_token": "time/rng",
    "backoff_delay": "time/rng",
    "read_first_line": "io-direct",
    "fetch_status": "io-direct",
    "parallel_sum": "concurrency",
}


def main() -> int:
    root = _repo_root()
    here = os.path.dirname(os.path.abspath(__file__))
    before = source_from_file(os.path.join(here, "corpus_before.py"))
    after = source_from_file(os.path.join(here, "corpus_after.py"))
    pairing = pair_functions(before, after)

    def kind(name, verdict):
        """Classify the probe's verdict against ground truth."""
        truth = GROUND_TRUTH.get(name)
        if verdict in ("unsupported", "error", "timeout"):
            return "refused"          # honest "I can't check this"
        if verdict == "unverifiable":
            return "refused"          # honest "not deterministic"
        # verdict is equivalent/divergent — did it match reality?
        if truth in ("equivalent", "divergent"):
            return "sound" if verdict == truth else "UNSOUND"
        # truth is io/unverifiable but the probe gave a confident verdict
        return "UNSOUND"

    rows = []
    for name in pairing.matched:
        r = _check_one(before, after, name, root)
        rows.append((name, STRATUM.get(name, "?"), r["verdict"],
                     r.get("cause"), kind(name, r["verdict"])))

    print("Phase-3 real-coverage measurement")
    print("=" * 78)
    print("%-18s %-18s %-12s %-9s %s"
          % ("function", "stratum", "verdict", "vs truth", "note"))
    print("-" * 78)
    for name, stratum, verdict, cause, k in rows:
        flag = "  <-- FALSE CONFIDENCE" if k == "UNSOUND" else ""
        print("%-18s %-18s %-12s %-9s %s%s"
              % (name, stratum, verdict, k, cause or "", flag))

    matched = len(rows)
    naive = sum(1 for r in rows if r[2] in ("equivalent", "divergent"))
    sound = sum(1 for r in rows if r[4] == "sound")
    unsound = sum(1 for r in rows if r[4] == "UNSOUND")
    refused = sum(1 for r in rows if r[4] == "refused")

    print("\n" + "-" * 78)
    print("Matched functions          : %d  (sig-changed/added/removed: %d/%d/%d)"
          % (matched, len(pairing.sig_changed), len(pairing.added),
             len(pairing.removed)))
    print("Naive 'verifiable' coverage: %d/%d = %.0f%%   <- what a naive tally reports"
          % (naive, matched, 100.0 * naive / matched))
    print("TRUSTWORTHY coverage       : %d/%d = %.0f%%   <- verdicts that match reality"
          % (sound, matched, 100.0 * sound / matched))
    print("FALSE CONFIDENCE           : %d/%d = %.0f%%   <- DANGEROUS: wrong 'equivalent'"
          % (unsound, matched, 100.0 * unsound / matched))
    print("Honest refusals            : %d/%d = %.0f%%   <- unsupported/unverifiable"
          % (refused, matched, 100.0 * refused / matched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
