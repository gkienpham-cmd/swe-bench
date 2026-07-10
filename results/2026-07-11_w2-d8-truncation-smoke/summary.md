# W2 D8–9 truncation smoke — before/after on real-scale django (dev smoke, Haiku)

**Not a headline number** (rule 9): dev smoke on a planted bug, n=1 before / n=2 after, claude-haiku-4-5, no caching, no batch.

## Task

Planted grammar typo (`more then one` → `more than one`) at line 710 of
`django/db/models/query.py` (3,063 lines) in a `.git`-stripped django shallow
clone. Identical prompt for all three runs, names the file, forbids running
the test suite (needs a full django install). Sandbox image `swb-dev`,
`--max-turns 12 --max-cost-usd 0.25`.

- **before/** — agent code at commit cca1b95 (pre-windowing), via a git worktree.
- **after/** — same code + D8–9 truncation strategy (MAX_READ_LINES=250 windowing,
  glob directory summary, schema caps in numbers, one system-prompt sentence).

## Results

| run | turns | tokens in | tokens out | cost | solved | flags |
|---|---|---|---|---|---|---|
| before | 6 | 76,947 | 836 | $0.081127 | yes | 0 |
| after-1 | 5 | 9,981 | 684 | $0.013401 | yes | 0 |
| after-2 | 5 | 10,012 | 715 | $0.013587 | yes | 0 |

After-run input tokens = **13% of before** (gate was ≤40%); cost 6.0× lower.

## Trajectory shape

- **before:** turn 1 was `read_file` with **no range** → full 50k-char dump
  (~12.5k tok) re-billed on all 5 later turns. The dump *contained* line 710,
  yet the model still ran `grep_glob` next and then a windowed read — the
  dump contributed nothing but cost.
- **after (both runs):** `grep_glob("more then one")` → `read_file(700–720)`
  → `edit_file` → verify re-read → end_turn. No whole-file read attempted,
  no bash `cat` bypass, no window thrashing.

## Honest caveats

1. The after-runs never hit the 250-line enforcement marker — the win came
   from the prompt-side guidance (schema text + system-prompt sentence).
   The enforcement path is proven only by $0 selftests (oversized explicit
   range, omitted range on a 400-line file, marker through the toolbox hop).
2. Guidance and enforcement changed together; this smoke does not isolate
   their contributions. If W3 triage shows dumps sneaking back, that's the
   ablation to run.
3. n=1 before; before-run variance unmeasured (task is short and mechanical,
   but the number carries that caveat).

Step-0 measurement (analysis/measure_truncation.py on the same clone):
whole-file no-range reads of 4 large django files return the full 50k-char
cap (~12.5k tok) each; a 250-line window is ~2.1–2.3k tok — 5.4–6.0× smaller.
Glob `**/*.py` = 2,924 files: current first-50 list ~419 tok (2% coverage) vs
per-directory summary ~157 tok (100% coverage).
