# W2 D10–11 compaction smoke — forced-threshold A/B on real-scale django (dev smoke, Haiku)

**Not a headline number** (rule 9): dev smoke on a planted bug, n=2 compacted / n=1 control, claude-haiku-4-5, no caching, no batch.

## Task

Same `.git`-stripped django shallow clone + planted typo as the D8–9 smoke
(`more then one` at `django/db/models/query.py:710`), but the prompt first
demands two 200-line orienting reads before the fix — without large
early-turn results, `PROTECT_LAST_TURNS=3` shields everything and grep
results fall under the 500-char elision floor, so nothing would elide on a
short trajectory. Identical prompt for all three runs; sandbox `swb-dev`;
`--max-turns 12 --max-cost-usd 0.25`.

- **A1, A2** — `--compact-at-tokens 3000` (forced low; default is 25,000)
- **B1** — default threshold (25k, never reached): the uncompacted control

## Results

| run | turns | tokens in | tokens out | cost | compaction events | solved | flags |
|---|---|---|---|---|---|---|---|
| A1 | 7 | 27,501 | 1,195 | $0.033476 | 2 (t3: 2 blocks ~3,573 tok; t5: 1 block) | yes | 0 |
| A2 | 6 | 24,446 | 1,023 | $0.029561 | 1 (t3: 2 blocks ~3,573 tok) | yes | 0 |
| B1 | 7 | 38,896 | 1,192 | $0.044856 | 0 | yes | 0 |

Compacted input = **67% of control** (25,974 avg vs 38,896) on the same task;
cost 70%. All runs solved; edit verified in-container (`OK: replaced 1
occurrence`); zero reward-hack flags.

## What this proves (and what it doesn't)

1. **The real API accepts a compacted transcript** — the one thing the 25
   $0 self-tests could not prove. Turns 4+ in both A runs ran on a message
   list with stubbed tool_result blocks; no 400s, no model confusion, both
   solved after compaction.
2. **No window thrash observed**: the elided blocks were the two orienting
   reads; the agent never re-requested them (A turn counts ≤ control's).
3. Post-compaction prompt dropped ~6.4k → ~3.1k est tokens (A1 t3→t5 meta).
4. **Mechanically verified per run**: all JSONL lines valid; every
   `elided_tool_use_ids` entry joins to a logged tool_use; `tool_result_full`
   present on every tool line (elision loses no post-hoc data — rule 5).

Caveats:
- The 3k threshold is artificial. The **25k default never fired live** (B1
  peaked well under it); its benefit at real scale rests on the
  `analysis/measure_context.py` simulation (uncompacted 40-turn stress run
  $3.69 input → $0.77 at 25k/12.5k) until W3 real-task data measures it.
- `target_met` was false on every event — with a 3k threshold the protected
  window + assistant history exceed the low-water mark by construction.
  Expected at forced settings; watch it at 25k on real tasks.
- Meta lines also log trigger-crossings that elide 0 blocks (turns 0–2 in
  the A runs): honest floor visibility, but it means "compaction meta lines"
  ≠ "elision events" — post-hoc analysis must filter on `blocks_elided > 0`.
- n=2/n=1, single mechanical task, prompt deliberately shaped to create
  elidable content.

Step-0 measurement (analysis/measure_context.py over all 11 prior
trajectories): median growth 266 tok/turn, p75 329; even at measured median
growth an uncompacted 40-turn run averages 19.4k prompt ≈ $0.895 — grazing
the $1 cap — and the 4k tok/turn stress case hits the cap at turn 21.
