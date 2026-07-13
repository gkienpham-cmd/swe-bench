# w3-sonnet-variance — variance re-run of the frozen 30-task dev subset (run 2 of 2)

Identical-config rerun of `results/2026-07-12_w3-sonnet-smoke/` (run 1) for the
rule-9 run-to-run variance estimate before locking the W3 baseline. Same agent
code, prompts, caps, model (`claude-sonnet-5`, thinking disabled); the only
code change between runs is the run_subset stdout flush fix (f802267, console
I/O only). Run interrupted at 5/30 for a user shutdown and resumed with the
identical command (skip-if-exists) — clean split, no partial trajectories;
the resume cold-started the prompt cache once (turn-1 write=1,422 on task 6,
reads thereafter — cross-run caching verified in both segments).

## Headline (official harness, swebench==4.1.0, run_id w3-sonnet-variance)

**21/30 resolved (70%), dev-subset** — vs run 1's 24/30 (80%).
n=2 mean **75% ± 5pp** (spread, not a CI; binomial σ alone is ~7pp at p≈0.8,
so the observed spread is consistent with sampling noise).
28 submitted / 28 completed / 0 harness errors; 2 instances omitted from
predictions (empty final diff — counted unresolved, denominator 30).

## Agreement matrix (the actual variance datum)

| | count | instances |
|---|---|---|
| resolved in both | 21 | — |
| unresolved in both | 6 | django-13448, mpl-23476, pytest-5221, sphinx-8273, sympy-11400, sympy-17630 |
| run 1 only (lost in run 2) | 3 | django-17051, requests-2148, sympy-15308 |
| run 2 only | 0 | — |
| **per-task agreement** | **27/30** | |

The failure core is deterministic: run 1's six failures ALL failed again.
All variance is one-directional (run-2 losses on run-1 solves).

## Triage — run 2's 9 unresolved (rule 2)

| instance | category | one-line cause |
|---|---|---|
| django-13448 | wrong-edit | applied, F2P 0/1, 0 P2P — same gold-semantics miss as run 1 |
| matplotlib-23476 | wrong-edit | applied, F2P 0/1, 0 P2P — repeat of run 1 |
| pytest-5221 | wrong-edit | applied, F2P 1/2, 0 P2P — partial, repeat of run 1 |
| sphinx-8273 | wrong-edit | applied, F2P 0/1, 0 P2P — repeat of run 1 |
| sympy-11400 | wrong-edit | applied, F2P 0/2, 0 P2P — repeat of run 1 |
| sympy-15308 | wrong-edit | applied, F2P 0/1, 0 P2P — run 1 solved it; run 2's edit misses gold semantics |
| psf-requests-2148 | **pass2pass-regression** | plausible socket.error→ConnectionError fix, but broke 24 P2P tests (F2P 1/10) — **first P2P regression on any Sonnet run** |
| django-17051 | loop-without-progress (edits-net-zero) | 6 edit_file calls, 3 applied, final diff EMPTY — applied then reverted its own edits, burned to the 40-turn cap |
| sympy-17630 | loop-without-progress (no-edit) | 0 edit_file calls in 40 turns — pure exploration; run 1 at least attempted a (wrong) edit |

Category counts: wrong-edit 6 · pass2pass-regression 1 · loop-without-progress 2.
Run 1 was 100% wrong-edit; run 2 surfaces the W2-era no-edit/no-progress modes
at low frequency plus the first regression. All three W4 targets: a
self-verification stage (run own repro + P2P sample before finishing) attacks
wrong-edit AND the regression AND edits-net-zero directly.

## Cost / tokens (n=2)

| run | total | $/task | fresh-in/task | out/task | cache-read/task | cache-write/task | end_turn | flags |
|---|---|---|---|---|---|---|---|---|
| run 1 | $4.3914 | $0.1464 | 809 | 5,111 | 247,131 | 17,686 | 23/30 | 45 on 17 |
| run 2 | $4.1695 | $0.1390 | 808 | 4,706 | 241,883 | 16,770 | 23/30 | 38 on 14 |

Cost variance ±2.6% around the $0.143 mean; token profile near-identical;
the same 23/30 runs exit clean (but not the same task set — the capped set
shifted). Flags: 38 (subtypes: add-own-test 20 / modify-existing 14 /
delete 4 — proportions match run 1's 25/15/5; flags_classified.json).

**Billing discrepancy (open, W3 D18):** console balance implies ~$2.6 more
spend than the trajectory-summed cost model (~1.5× ≈ sticker-vs-intro
pricing ratio) — reconcile against the console usage breakdown before the
next paid run; all $ figures above are cost-model figures.

## Baseline locked

`baseline_config.md` in this directory is the frozen reference config;
git tag `baseline-w3`. W4 scaffold runs compare against:
**dev-subset resolved 75% ± 5pp (n=2), $0.143/task ± 2.6%, wrong-edit as
the dominant failure class.**

## Caveats (rule 9)

Dev-subset numbers, n=2, no harness re-grade variance measured (same patch
graded once), temperature-default sampling — per-task flips expected.
Reproduce: `python -m analysis.compare_runs --run-a results/2026-07-12_w3-sonnet-smoke
--report-a .../sonnet-5-w3-smoke.w3-sonnet-smoke.json --run-b results/2026-07-13_w3-sonnet-variance
--report-b .../sonnet-5-w3-variance.w3-sonnet-variance.json`.
