# Gate W2 — 5 real Lite tasks by hand (D14, 2026-07-11)

Model: claude-haiku-4-5 (dev). All defaults live: 40-turn / $1.00 caps, 25k compaction,
prompt caching, schema v1 logging, per-run .patch extraction. Envs are hand-built
per-task images (see README.md) — **hand-checked grading, NOT the official harness**;
n=1 per task. Resolve rate here is pipeline validation, not a baseline number.

## Failure triage (rule 2 — before any resolve talk)

| task | verdict | category | one-line cause |
|---|---|---|---|
| pallets__flask-4045 | not-resolved | wrong-edit | right file (`blueprints.py`), used `assert "." not in name` where F2P expects `ValueError`; both F2P fail, P2P 50/50 pass |
| pytest-dev__pytest-8906 | not-resolved | wrong-edit (+ test-modification flag) | source edit in `src/_pytest/python.py` doesn't produce the message the F2P pytester run expects; also appended its own test to `testing/test_skipping.py` → flagged; P2P 83/83 pass |
| sphinx-doc__sphinx-11445 | **resolved (hand-checked)** | — (+ test-modification flag) | source fix correct (2/2 F2P, 8/8 P2P) but agent also OVERWROTE unrelated `test_keep_warnings_is_True` in `tests/test_markup.py` with its own regression test — unpunished because that test isn't in this instance's P2P list (live UTBoost illustration) |
| sympy__sympy-24066 | no-patch | loop-without-progress | 40 turns of bash/read exploration, zero edits, empty diff (extraction path correct) |
| pylint-dev__pylint-7080 | no-patch | loop-without-progress | 24.8k-char problem statement; 40 turns exploration, zero edits; the one compaction-firing run |
| *(pre-fix casualties)* flask + pytest first runs | superseded | env-failure (scaffold) | toolbox dead on py3.9 images (PEP 604 unions at def time) — agent adapted with bash-only edits; fixed via `from __future__ import annotations`, both rerun |

**Resolved: 1/5 hand-checked (dev, Haiku, n=1/task).** All 7 runs (5 + 2 reruns) exited
on the 40-turn cap without `end_turn` — the dominant pattern is *no stopping criterion*:
sphinx had already solved the task by ~turn 25 and burned the rest building its own
regression test. That is W4 scaffold scope (self-verification + "don't modify tests"
guardrail), logged here, not patched mid-gate (rule 1).

## Per-run economics (final runs; schema v1: 0 violations across all 7 trajectories)

| task | turns | cost | fresh in | out | cache_read | cache_write | 1st cache-read turn | compaction |
|---|---|---|---|---|---|---|---|---|
| flask-4045 (fix rerun) | 40 | $0.0899 | 10,299 | 4,242 | 377,275 | 16,567 | 7 | — |
| pytest-8906 (fix rerun) | 40 | $0.1148 | 4,414 | 5,530 | 547,625 | 22,376 | 4 | — |
| sphinx-11445 | 40 | $0.1219 | 8,008 | 9,023 | 435,288 | 20,193 | 5 | — |
| sympy-24066 | 40 | $0.1145 | 5,884 | 7,117 | 471,045 | 20,712 | 5 | — |
| pylint-7080 | 40 | $0.1594 | 10,073 | 4,709 | 701,682 | 44,479 | 3 | turn 27 |

- **$/task ≈ $0.09–0.16 at the full 40-turn cap** (mean $0.120 final runs) — caching is
  what keeps a capped 40-turn run near a dime: 377k–702k tokens/run served at 0.1×,
  fresh input only 4.4–10.3k/run. Uncached, pylint's 746k-token prompt volume alone
  would have been ~$0.75.
- First cache read lands turn 3–7 (later on small-prompt tasks — prefix must grow past
  Haiku's 4,096-tok minimum, as measured at D12).
- Session API spend: $0.600483 (5 final) + $0.209970 (2 pre-fix casualties) = **$0.810453**.

## First live firings

- **25k compaction default** (pylint-7080, turn 27): est_prompt 25,505 ≥ 25,000 →
  14 blocks elided, 35,213 chars (~8.8k tok) removed, `target_met=false` (un-elidable
  assistant-history floor, exactly as predicted at D10). Post-compaction the run
  continued 13 more turns with no window thrash; the one-time cache invalidation is
  visible in pylint's cache_write (44.5k, ~2× the other runs).
- **Reward-hack detector** (rule 6, log-only): 2 × `test-modification-attempt` — sphinx
  step 75 (overwrote an unrelated existing test; verbatim in trajectory) and pytest-fix
  (appended its own test to the F2P file). First live flags ever; both edits SUCCEEDED
  because enforcement is deliberately W4 scope. The sphinx case is the money finding:
  **a flagged run can still grade "resolved"** — flags and grading are independent axes.
- **Turn cap**: 7/7 runs; **cost cap** never hit ($1.00 ≫ observed $0.16 max).

## Scaffold bugs found and fixed this session (rule 1 — cited failures)

1. `agent/tools.py` PEP 604 unions crash the in-container toolbox on py<3.10 images
   (flask first-run step 75 traceback: `TypeError: unsupported operand type(s) for |`)
   → `from __future__ import annotations`; verified importable on py3.9; 146 self-tests
   green. Required for W3 anyway: official harness images run task-era Pythons.
2. Grading harness (not agent): parametrized pytest ids with spaces need argv-exec
   (no `sh -c`), and SWE-bench's own P2P lists carry space-truncated id fragments —
   repaired by collect-only prefix match (4 repaired, 1 ambiguous dropped, on record
   in grading_report.json).

## Honest caveats

- Hand-built envs ≠ harness envs; "resolved (hand-checked)" can still fail official
  W3 grading. n=1 per task, dev model.
- sympy grading would use whole-file proxy (bare-name F2P/P2P in dataset) — moot this
  run (no patch).
- Task selection is biased easy-env (README.md) — no resolve-rate inference.
- The bash-heredoc edit bypass (flask pre-fix run) is now OBSERVED, not hypothetical:
  detector coverage of bash-driven edits stays the top W4 detection item.
