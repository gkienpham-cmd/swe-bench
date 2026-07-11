"""W3 D15-16 one-off: hand-grade vs official-harness verdict table.

Hand grades come from the W2 gate (analysis/grade_w2gate.py, 2026-07-11;
agent patch + gold test_patch -> F2P+P2P in-container — NOT the harness).
Harness verdicts come from logs/run_evaluation/<run_id>/. Any divergence
is a finding (rule 2), written up in the results dir, not reconciled
silently.

Run: python -m analysis.crosscheck_verdicts --run-id w2gate-crosscheck --model-name haiku-4.5-w2gate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HAND_GRADES = {  # W2 gate hand-check, LOG 2026-07-11 W2D14
    "pallets__flask-4045": False,
    "pytest-dev__pytest-8906": False,
    "sphinx-doc__sphinx-11445": True,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model-name", required=True)
    args = ap.parse_args()

    base = Path("logs/run_evaluation") / args.run_id / args.model_name
    rows = []
    for iid, hand in sorted(HAND_GRADES.items()):
        rp = base / iid / "report.json"
        if not rp.exists():
            rows.append((iid, hand, None, "NO REPORT"))
            continue
        rep = json.loads(rp.read_text())[iid]
        harness = rep["resolved"]
        rows.append((iid, hand, harness,
                     "agree" if hand == harness else "DIVERGE"))

    w = max(len(r[0]) for r in rows) + 2
    print(f"{'instance':<{w}} {'hand-grade':<11} {'harness':<9} verdict")
    for iid, hand, harness, verdict in rows:
        print(f"{iid:<{w}} {str(hand):<11} {str(harness):<9} {verdict}")
    diverge = [r for r in rows if r[3] != "agree"]
    print(f"\n{len(rows) - len(diverge)}/{len(rows)} agree"
          + (f" — {len(diverge)} DIVERGENCE(S): a finding, write it up" if diverge else ""))
    return 1 if diverge else 0


if __name__ == "__main__":
    raise SystemExit(main())
