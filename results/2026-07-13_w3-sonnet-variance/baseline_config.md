# BASELINE CONFIG — locked W3 D18 (tag: baseline-w3)

The frozen reference configuration every W4+ scaffold run compares against.
Both W3 Sonnet runs (w3-sonnet-smoke n=1, w3-sonnet-variance n=2) ran this
exact configuration; the only inter-run code change was the run_subset
stdout flush fix (f802267 — console I/O only, no request-content effect).

## Agent code

- Git SHA at run 2 launch: agent/ + analysis/ as of `f802267` (flush fix);
  analysis-only commits `5947f7d` (classify_flags) and `617a8bd`
  (compare_runs) landed mid-run and touch no agent code. Tag `baseline-w3`
  points at the post-run commit containing all artifacts.
- Scaffold: raw Messages API tool-use loop (agent/loop.py), NO planning /
  localization / self-verification stages — those are W4.
- Tools (5): read_file (250-line window), edit_file (match-exactly-once),
  bash (30s timeout, 10k/stream truncation), grep_glob, run_tests
  (pytest -q, 120s). All container-side; toolbox runs under conda base,
  bash/run_tests under the testbed env.

## Model & request shape

- Model: `claude-sonnet-5` — intro pricing $2/$10 per MTok through
  2026-08-31 (re-verified 2026-07-12 and 2026-07-13, rule 7); cache
  write 1.25×, read 0.1×.
- `thinking={"type":"disabled"}` pinned (omission = ADAPTIVE on Sonnet 5;
  enabling thinking is a W4 decision awaiting triage data).
- max_tokens per turn: 4096. Temperature: API default (not set).
- Prompt caching: SYSTEM_BLOCKS breakpoint (tools+system, ~1,490 tok under
  the Sonnet 5 tokenizer — above the 1,024 minimum, caches from turn 1)
  + one moving breakpoint on the newest user message's last tool_result.
- Compaction: deterministic tool_result elision at 25k est. prompt tokens,
  low-water 12.5k, PROTECT_LAST_TURNS=3.

## Caps

- --max-turns 40 (hard, meta-logged as max_turns_hit)
- --max-cost-usd 1.00 (hard ceiling, never hit on Sonnet: max observed
  ~$0.28 at the 40-turn cap)

## Sandbox

- Official SWE-bench instance images (per-task pull, --rm-after), preloaded
  /testbed, --network none, no bind mounts, baseline commit-if-dirty.
- No container resource limits (open debt).

## Eval harness

- swebench==4.1.0, `python -m swebench.harness.run_evaluation
  --dataset_name princeton-nlp/SWE-bench_Lite --split test --max_workers 2
  --cache_level env`, colima vz + Rosetta REQUIRED (qemu SIGSEGVs CPython).
- Empty-diff policy: omitted from predictions, recorded in
  predictions_manifest.json, denominators always 30.

## Baseline numbers (dev-subset, official harness)

See README.md in this directory for the n=2 agreement matrix, costs, and
triage. Headline: run1 24/30, run2 (this run) — see README. Rule 9 caveats:
dev-subset, n=2, ~7pp binomial σ at p≈0.8.
