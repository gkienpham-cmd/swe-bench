# Dev subset — 30 SWE-bench Lite tasks, FROZEN 2026-07-12 (W3 D16)

`dev_subset_30.json` is the freeze. It is never re-picked (PLAN.md W3); every
number measured on it is labeled **dev-subset**, and the overfitting risk goes
in the report's limitations. `freeze_dev_subset.py` exists for provenance —
re-running it must reproduce the JSON byte-for-byte (verified at freeze time),
and its assertions make any drift in the cached dataset or the algorithm a
loud failure instead of a silent re-pick.

## Selection

- **Pool:** the 300-row Lite test split minus the 5 W2-gate tasks
  (flask-4045, pylint-7080, pytest-8906, sphinx-11445, sympy-24066) — those
  were seen during Gate W2 and become a labeled regression/smoke set
  (decision recorded in LOG.md, 2026-07-12). Pool = 295 rows.
- **Method:** proportional stratified by repo, **coverage-floor variant**
  (user decision 2026-07-12, corrected from an earlier allocation that
  mis-summed to 32):
  - repos with <5 candidate rows get 0 seats — seaborn (4) and flask (2)
    are uncovered (6 of 300 Lite tasks, accepted);
  - eligible repos whose proportional share of 30 is <1.0 seat are pinned to
    exactly 1 — astropy, requests, xarray, pylint;
  - the remaining 26 seats go to the big six by largest remainder
    (tie-break: fractional part desc, stratum size desc, repo name asc):
    **django 11, sympy 7, matplotlib 2, scikit-learn 2, pytest 2, sphinx 2**.
  - Pure largest-remainder was rejected because it would zero out xarray and
    pylint too; one django and one sympy seat were traded for repo coverage
    (triage signal from 10 of 12 repos).
- **Draw:** per stratum, `random.Random(f"{SEED}:{repo}").sample(sorted(ids), quota)`
  with `SEED = 20260712`. Sorting before sampling makes the draw independent
  of cache row order; per-repo generators make strata independent.

## Contents

Committed JSON carries `instance_id, repo, version, base_commit, image`
(Docker Hub name per swebench 4.1.0: `swebench/sweb.eval.x86_64.<id>` with
`__ → _1776_`). Gold patches and problem statements are deliberately NOT
committed — answer-key material stays out of the repo; regenerate full task
files with `--emit-tasks` from the git-ignored Lite cache
(`results/2026-07-11_w2-gate/lite_instances.json`, refetchable via
`analysis/fetch_lite.py`).
