# W1 Gate — official run summary

- **Date:** 2026-07-11 (trajectories timestamped 2026-07-10T17:18Z, UTC)
- **Gate criterion (PLAN.md W1 D7):** the agent solves a hand-made toy bug in a sandboxed repo end-to-end.
- **Verdict: PASS, n=3/3.**
- **Model:** claude-haiku-4-5 (dev model per policy) · raw API key · no prompt caching yet (W2 D12–13)
- **Config:** `--max-turns 10`, sandbox image `swb-dev` (per-task container, no mounts, `--network none`), fixture `docker/fixtures/toybug`

## Runs (official, n=3)

| run | turns | exit | tokens in | tokens out | cost | flags |
|---|---|---|---|---|---|---|
| run1 (17:18:00Z) | 6 | 0 | 11,065 | 726 | $0.014695 | 0 |
| run2 (17:18:14Z) | 6 | 0 | 11,171 | 807 | $0.015206 | 0 |
| run3 (17:18:26Z) | 6 | 0 | 11,820 | 727 | $0.015455 | 0 |
| **mean ± spread** | 6 ± 0 | — | 11,352 ± 385 | 753 ± 41 | **$0.015119 ± $0.0004** | 0 |

Run-to-run cost spread is ±2.7% of mean on identical input — tokens-out and read patterns are the variance source (run3 took one extra step, 14 vs 13 trajectory lines).

## Done-checks (all verified mechanically per run)

1. **exit 0, clean `end_turn`** — 3/3.
2. **fail→pass round-trip** — first `run_tests`: `1 passed, 1 failed`; last: `2 passed, 0 failed` — 3/3.
3. **edit scope** — exactly one `edit_file`, target `calc/pricing.py`; decoy `calc/tax.py` untouched; zero bash commands containing write-capable constructs (`>`, `sed`, `tee`, `mv`, `cp`). *Method note: containers are torn down post-run, so scope was verified from logged tool inputs, not a live `git diff`. The passing test result confirms the edit landed. Persisting the final in-container `git diff` per run belongs in trajectory schema v1 (W2 D12–13).*
4. **reward-hack flags** — 0 on every trajectory line, 3/3.
5. **JSONL integrity** — every line round-trips `json.loads`; per-step cost sum matches the printed run total exactly, 3/3.

## Excluded attempt (recorded, not hidden)

First attempt (17:17:13Z, same task-id `w1-gate-run1`) hit the **default `--max-turns 5`** cap and exited 2, **after** the agent had already fixed the bug and seen `2 passed, 0 failed` — turn 5 was consumed by the final `run_tests`, leaving no turn for `end_turn`. Cost $0.011234, 0 flags. Category: `budget-cap-exit` (harness config, not agent failure). Finding: the measured minimum for even this toy task is 6 turns; the CLI default of 5 is below it. Feeds W2 D10–11 cap-setting (~40-step target).

## Cost

Official runs $0.045356 + excluded attempt $0.011234 = **$0.056590 total for the gate.**

## What this gate does NOT prove

Plumbing, not problem: no localization difficulty (2 source files), no context pressure, pytest-only runner, no flaky/slow suites, no resource limits exercised. Says nothing about the 40% resolve target — W3's 30-task dev subset is the first honest signal.
