"""Freeze the 30-task SWE-bench Lite dev subset — W3 D16, run ONCE, never re-picked.

Selection (user decisions, 2026-07-12, recorded in LOG.md):
  * The 5 W2-gate task IDs are EXCLUDED (seen tasks; they remain a labeled
    regression/smoke set) -> 295 candidate rows.
  * Proportional stratified by repo, "coverage-floor" variant:
      - repos with < MIN_ROWS_FOR_SEAT rows get 0 seats (seaborn 4, flask 2);
      - eligible repos whose pure proportional share of 30 is < 1.0 seat are
        PINNED to exactly 1 seat (astropy, requests, xarray, pylint);
      - the remaining seats go to the other eligible repos by largest
        remainder (tie-break: fractional part desc, stratum size desc,
        repo name asc).
    Expected quotas are hardcoded below and asserted, so any drift in the
    cache or the algorithm breaks the freeze loudly instead of silently
    re-picking.
  * Within each stratum: random.Random(f"{SEED}:{repo}").sample(sorted(ids), k)
    - sorting first makes the draw byte-reproducible regardless of cache row
    order; per-repo generators make one stratum's draw independent of the
    others.

Outputs:
  * analysis/dev_subset_30.json  (COMMITTED; ids + metadata + image names,
    no gold patches / problem statements — answer-key material stays out of
    the repo)
  * --emit-tasks DIR: full per-task JSON rows (incl. problem_statement) from
    the git-ignored cache, for the runner. Deterministic, rerunnable.

The committed JSON is the freeze. Re-running this script must reproduce it
byte-for-byte (done-check); it exists for provenance, not for re-picking.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

SEED = 20260712  # freeze date; never change
VARIANT = "coverage-floor"
SUBSET_SIZE = 30
MIN_ROWS_FOR_SEAT = 5  # repos with fewer candidate rows get no seat

# Seen during the W2 gate (results/2026-07-11_w2-gate/) -> excluded, kept as a
# labeled regression/smoke set. Decision recorded LOG.md 2026-07-12.
GATE_EXCLUDED = [
    "pallets__flask-4045",
    "pylint-dev__pylint-7080",
    "pytest-dev__pytest-8906",
    "sphinx-doc__sphinx-11445",
    "sympy__sympy-24066",
]

# Candidate-pool distribution after gate exclusion, verified 2026-07-12
# against the cached 300-row Lite test split. The freeze asserts this so a
# changed cache cannot silently alter the draw.
EXPECTED_POOL = {
    "django/django": 114,
    "sympy/sympy": 76,
    "matplotlib/matplotlib": 23,
    "scikit-learn/scikit-learn": 23,
    "pytest-dev/pytest": 16,
    "sphinx-doc/sphinx": 15,
    "astropy/astropy": 6,
    "psf/requests": 6,
    "pydata/xarray": 5,
    "pylint-dev/pylint": 5,
    "mwaskom/seaborn": 4,
    "pallets/flask": 2,
}

EXPECTED_QUOTAS = {
    "django/django": 11,
    "sympy/sympy": 7,
    "matplotlib/matplotlib": 2,
    "scikit-learn/scikit-learn": 2,
    "pytest-dev/pytest": 2,
    "sphinx-doc/sphinx": 2,
    "astropy/astropy": 1,
    "psf/requests": 1,
    "pydata/xarray": 1,
    "pylint-dev/pylint": 1,
}

DEFAULT_LITE = "results/2026-07-11_w2-gate/lite_instances.json"
DEFAULT_OUT = "analysis/dev_subset_30.json"


def image_name(instance_id: str) -> str:
    # swebench 4.1.0 test_spec.py:106-111 — Docker Hub name, '__' -> '_1776_'.
    return f"swebench/sweb.eval.x86_64.{instance_id.lower()}:latest".replace("__", "_1776_")


def compute_quotas(pool: Counter) -> dict[str, int]:
    eligible = {r: n for r, n in pool.items() if n >= MIN_ROWS_FOR_SEAT}
    pinned = {r for r, n in eligible.items() if n * SUBSET_SIZE / sum(pool.values()) < 1.0}
    quotas = {r: 1 for r in pinned}
    lr_repos = {r: n for r, n in eligible.items() if r not in pinned}
    seats = SUBSET_SIZE - len(pinned)
    total = sum(lr_repos.values())
    shares = {r: n * seats / total for r, n in lr_repos.items()}
    floors = {r: int(shares[r]) for r in lr_repos}
    leftover = seats - sum(floors.values())
    by_remainder = sorted(
        lr_repos,
        key=lambda r: (-(shares[r] - floors[r]), -lr_repos[r], r),
    )
    for r in lr_repos:
        quotas[r] = floors[r]
    for r in by_remainder[:leftover]:
        quotas[r] += 1
    return quotas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lite", default=DEFAULT_LITE, help="cached 300-row Lite JSON (git-ignored)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="committed subset JSON")
    ap.add_argument("--emit-tasks", default=None, metavar="DIR",
                    help="also write full per-task JSONs (incl. problem_statement) here")
    args = ap.parse_args()

    rows = json.loads(Path(args.lite).read_text())
    assert len(rows) == 300, f"expected 300 Lite rows, got {len(rows)}"
    pool_rows = [r for r in rows if r["instance_id"] not in GATE_EXCLUDED]
    assert len(pool_rows) == 295, f"expected 295 candidates post-exclusion, got {len(pool_rows)}"
    pool = Counter(r["repo"] for r in pool_rows)
    assert dict(pool) == EXPECTED_POOL, f"candidate pool drifted: {dict(pool)}"

    quotas = compute_quotas(pool)
    assert quotas == EXPECTED_QUOTAS, f"quota algorithm drifted: {quotas}"
    assert sum(quotas.values()) == SUBSET_SIZE

    by_repo: dict[str, list[str]] = {}
    for r in pool_rows:
        by_repo.setdefault(r["repo"], []).append(r["instance_id"])
    chosen: list[str] = []
    for repo in sorted(quotas):
        ids = sorted(by_repo[repo])
        chosen += random.Random(f"{SEED}:{repo}").sample(ids, quotas[repo])
    chosen.sort()
    assert len(chosen) == SUBSET_SIZE and not set(chosen) & set(GATE_EXCLUDED)

    meta = {r["instance_id"]: r for r in pool_rows}
    subset = {
        "seed": SEED,
        "variant": VARIANT,
        "algorithm_note": (
            "Proportional stratified over the 295 non-gate Lite test rows. Repos with "
            f"<{MIN_ROWS_FOR_SEAT} rows get 0 seats; eligible repos with a proportional share "
            "<1.0 seat are pinned to 1; remaining seats by largest remainder (tie-break: "
            "fraction desc, stratum size desc, repo asc). Per-stratum draw: "
            "random.Random(f'{SEED}:{repo}').sample(sorted(ids), quota). Frozen 2026-07-12 "
            "(W3 D16); see analysis/dev_subset_30_README.md."
        ),
        "excluded_gate_ids": GATE_EXCLUDED,
        "per_repo_quotas": {r: quotas[r] for r in sorted(quotas)},
        "instances": [
            {
                "instance_id": iid,
                "repo": meta[iid]["repo"],
                "version": meta[iid]["version"],
                "base_commit": meta[iid]["base_commit"],
                "image": image_name(iid),
            }
            for iid in chosen
        ],
    }
    Path(args.out).write_text(json.dumps(subset, indent=1) + "\n")
    print(f"wrote {args.out}: {len(chosen)} instances, quotas {subset['per_repo_quotas']}")

    if args.emit_tasks:
        tdir = Path(args.emit_tasks)
        tdir.mkdir(parents=True, exist_ok=True)
        for iid in chosen:
            (tdir / f"{iid}.json").write_text(json.dumps(meta[iid], indent=1) + "\n")
        print(f"wrote {len(chosen)} full task JSONs to {tdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
