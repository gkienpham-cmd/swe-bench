# W2 D12–13 caching smoke — n=3 on real-scale django vs the D10 uncached control

**Not a headline number** (rule 9): dev smoke on a planted bug, n=3 cached vs n=1 uncached control (D10 B1), claude-haiku-4-5, no batch.

## Setup

Identical task, prompt, sandbox image (`swb-dev`), and caps as the D10 B1
control (`.git`-stripped django shallow clone, `more then one` planted at
`django/db/models/query.py:710`, prompt forces two 200-line orienting reads;
`--max-turns 12 --max-cost-usd 0.25`, compaction at its 25k default — never
fired). Only change since B1: prompt caching (D12–13) + schema v1 + patch
persistence. Fixture recreated fresh (same plant site, line 710); django HEAD
may differ slightly from the D10 clone — same file, same bug, same prompt.

Step-0 measurement (`analysis/measure_prefix.py`, free): stable prefix
(tools ~1,306 + system ~66) = **~1,372 tok — 2,724 under Haiku's 4,096-tok
minimum cacheable prefix**. Predicted consequences, both observed:
turn 1 writes nothing (prompt ~1.5k < min), and cross-run cache reads are
impossible (runs share only the sub-minimum stable prefix; conversations
diverge at the first model-generated tool_use id).

## Results

| run | turns | fresh in | cache read | cache write | out | cost | solved | flags |
|---|---|---|---|---|---|---|---|---|
| C1 | 7 | 1,528 | 30,359 | 6,847 | 1,064 | $0.018443 | yes | 0 |
| C2 | 6 | 1,523 | 23,654 | 6,731 | 870 | $0.016652 | yes | 0 |
| C3 | 6 | 1,523 | 23,530 | 6,562 | 1,023 | $0.017194 | yes | 0 |
| **mean** | 6.3 | 1,525 | 25,848 | 6,713 | 986 | **$0.017430 ± $0.00091 (±5.2%)** | 3/3 | 0 |
| B1 (D10 control, uncached) | 7 | 38,896 | 0 | 0 | 1,192 | $0.044856 | yes | 0 |

**Cached cost = 39% of the uncached control** on the same task (input-side
token-equivalents: fresh 1×1.5k + write 1.25×6.7k + read 0.1×26k ≈ 12.3k
vs 38.9k ≈ 32%). Per-turn fresh input from turn 3 onward is **5–7 tokens** —
the entire transcript re-read is served from cache; the model pays full
price only for genuinely new bytes.

Per-turn shape (C1, representative — the mechanism, verified per run):
- turn 1: in=1,493, write=0 (prompt below the 4,096 minimum — as measured)
- turn 2: write=5,541, read=0 (first tool_result marked; cumulative prefix
  crossed the minimum; whole prefix written once)
- turns 3–7: read=5,541→6,723 growing, fresh in=5–7, write=new increment only

## What this proves (and what it doesn't)

1. **The real API accepts both breakpoints** (system block + moving
   conversation marker) — `cache_read_input_tokens > 0` from turn 3, i.e.
   PLAN's "verify cache_read>0" check passes on the *within-run* reads.
2. **Cross-run (run-2) cache_read = 0 — expected, not a failure**: the
   Step-0 measurement shows the shared prefix is 2,724 tok under Haiku's
   minimum, and everything past it diverges with model-generated tool_use
   ids. Cross-run reuse becomes real when the stable prefix grows (W4
   scaffold prompts) or on models with lower minimums.
3. **Schema v1 live**: every line of all 3 trajectories validates against
   `schemas/trajectory.schema.json` (0 violations); `final_git_diff` meta
   line present per run.
4. **Patch persistence live**: 3× `.patch` emitted; each is exactly the
   one-line fix and passes `git apply --check` against a fresh fixture copy
   — the W3 patch-extraction path works end-to-end.
5. Cost accounting: printed totals equal per-step sums; write premium
   (1.25×) and read discount (0.1×) visible in per-turn costs (turn 2 is
   the most expensive turn — the cache write — exactly as the economics say).

Caveats:
- Control is n=1 (B1) and ran on the D10 clone; cached runs n=3 on a fresh
  clone of the same repo/file/bug. Same prompt, same caps.
- C2/C3 finished in 6 turns vs B1's 7 — a small part of the saving is a
  shorter run, not caching. The per-turn fresh-input collapse (38.9k total →
  1.5k total) is the caching signal and is turn-count-independent.
- Toy-fixture tasks (W1 gate class) stay below the 4,096 minimum for their
  whole life and cache nothing — caching pays exactly where cost lives, on
  real-scale tasks.
- Each future compaction event will invalidate the conversation cache once
  (rewrites old bytes); not exercised here (25k never fired — W3 will).

## Spend

$0.052289 total (C1+C2+C3). Step-0 `count_tokens` calls are free.
