"""Compare two eval runs: per-task agreement matrix + cost/token stats — W3 D18.

The agreement matrix is the actual variance datum (rule 9): which instances
flipped between runs, not just the two headline rates. Costs and tokens are
summed from the newest trajectory per instance (same policy as
make_predictions); resolve verdicts come from the official harness report
JSONs only.

Usage:
  python -m analysis.compare_runs \
      --run-a DIR --report-a REPORT.json --label-a run1 \
      --run-b DIR --report-b REPORT.json --label-b run2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.classify_flags import FLAG, newest_per_instance


def run_stats(run_dir: Path) -> dict:
    trajs = newest_per_instance(run_dir, "jsonl")
    total = {"cost": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
             "flags": 0, "flagged_tasks": 0, "end_turn": 0, "tasks": len(trajs)}
    for iid, path in trajs.items():
        flags_here = 0
        capped = False
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            total["cost"] += rec.get("cost_usd") or 0.0
            u = rec.get("usage") or {}
            for k in ("input", "output", "cache_read", "cache_write"):
                total[k] += u.get(k) or 0
            if rec.get("reward_hack_flag") == FLAG:
                flags_here += 1
            content = rec.get("content")
            # Cap exits write an explicit meta line (max_turns_hit /
            # budget_ceiling_hit); a clean end_turn run writes neither.
            if rec.get("role") == "meta" and isinstance(content, dict) \
                    and (content.get("max_turns_hit") or content.get("budget_ceiling_hit")):
                capped = True
        total["end_turn"] += not capped
        total["flags"] += flags_here
        total["flagged_tasks"] += bool(flags_here)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-a", required=True)
    ap.add_argument("--report-a", required=True)
    ap.add_argument("--label-a", default="run-a")
    ap.add_argument("--run-b", required=True)
    ap.add_argument("--report-b", required=True)
    ap.add_argument("--label-b", default="run-b")
    args = ap.parse_args()

    ra = json.loads(Path(args.report_a).read_text())
    rb = json.loads(Path(args.report_b).read_text())
    res_a, res_b = set(ra["resolved_ids"]), set(rb["resolved_ids"])
    all_ids = sorted(set(ra["submitted_ids"]) | set(rb["submitted_ids"])
                     | set(ra.get("empty_patch_ids", [])) | set(rb.get("empty_patch_ids", [])))

    both = sorted(res_a & res_b)
    neither = [i for i in all_ids if i not in res_a and i not in res_b]
    only_a = sorted(res_a - res_b)
    only_b = sorted(res_b - res_a)

    la, lb = args.label_a, args.label_b
    print(f"n={len(all_ids)} instances")
    print(f"{la}: {len(res_a)} resolved · {lb}: {len(res_b)} resolved")
    print(f"\nAgreement matrix:")
    print(f"  resolved in both:     {len(both)}")
    print(f"  unresolved in both:   {len(neither)}  {neither}")
    print(f"  {la} only:            {len(only_a)}  {only_a}")
    print(f"  {lb} only:            {len(only_b)}  {only_b}")
    print(f"  per-task agreement:   {len(both) + len(neither)}/{len(all_ids)}")

    print(f"\nCost / tokens (from trajectories, newest per instance):")
    for label, run_dir in ((la, args.run_a), (lb, args.run_b)):
        s = run_stats(Path(run_dir))
        n = s["tasks"] or 1
        print(f"  {label}: ${s['cost']:.4f} total (${s['cost']/n:.4f}/task, n={s['tasks']}) · "
              f"tokens/task: {s['input']//n} fresh-in / {s['output']//n} out / "
              f"{s['cache_read']//n} cache-read / {s['cache_write']//n} cache-write · "
              f"end_turn {s['end_turn']}/{s['tasks']} · "
              f"flags {s['flags']} on {s['flagged_tasks']} tasks")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
