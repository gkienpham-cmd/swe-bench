# W3 first Sonnet smoke — 30-task frozen dev subset

Run directory for the first paid eval on the pinned model (`claude-sonnet-5`,
intro $2/$10 through 2026-08-31, re-verified 2026-07-12). Subset frozen in
`analysis/dev_subset_30.json` (seed 20260712, coverage-floor stratified; 5 W2
gate IDs excluded). All numbers from this directory are **dev-subset** numbers.

## Decisions in effect

- **No Batch API** (user decision, rule-4c deviation recorded in LOG.md):
  the agent loop is sequentially dependent per task; caching is the lever.
- **Thinking explicitly disabled** on Sonnet 5 in agent/loop.py — omission
  would silently run adaptive thinking (Sonnet 5 default) and change both the
  request shape vs the Haiku baseline and the schema-v1 content assumptions.
  Enabling thinking is a W4+ scaffold decision, taken only on triage data.
- **Disk reality:** official instance images are 3.8–11.7GB (measured);
  ~60–120GB projected for all 30 → colima resized 30→60GiB, images pulled
  per task and removed after (`run_subset.py --pull --rm-after`); harness at
  `--cache_level env` self-cleans images it pulls.

## Rule-7 pins (verified 2026-07-12, this session)

- `claude-sonnet-5` active; intro $2/$10 per MTok through 2026-08-31; cache
  read 0.1x, write 1.25x (5-min TTL).
- **Minimum cacheable prefix: UNRESOLVED in references.** D15 live pin said
  1,024 tok; the claude-api reference table (cached 2026-06-24) omits
  Sonnet 5 and lists Sonnet 4.6 at 2,048. Our stable prefix measures
  **1,490 tok under the Sonnet 5 tokenizer** (analysis/measure_prefix.py,
  $0) — between the two candidates, so the canary decides empirically:
  cross-run turn-1 cache_read>0 ⇒ minimum ≤1,490 (pin holds);
  cross-run 0 with normal within-run caching ⇒ minimum is 2,048.
  Economic stake for THIS run is negligible (~$0.003/run); it matters for
  W4 scaffold-prompt sizing.
- Sonnet 5 tokenizer counts ~30% more tokens than Haiku for the same text
  (prefix 1,372 tok Haiku → 1,490 Sonnet measured) — cost projections scale
  from Haiku measurements by 2x price × ~1.3 tokens.

## Artifacts

- `tasks/` — full per-task JSONs (regenerable: `freeze_dev_subset.py --emit-tasks`)
- `image_python_versions.json` — per-instance testbed + conda-base python
  versions and toolbox-compat verdicts (probe pass, $0). Key finding: django
  3.0-3.2-era testbeds are **py3.6** (tools.py can never run there — future
  import is py3.7+); production unaffected, toolbox runs under conda base
  (py3.11.5 on every image probed), compat verified per image under base.
- `probe_console.log` — probe transcript
- `runs_manifest.json`, `console_<iid>.log`, trajectories + patches — agent runs
- `predictions.jsonl` + `predictions_manifest.json` — harness input (empty
  diffs omitted, counted in denominators)
- Harness report + triage table — appended below after the run

## Canary (Step D) — 2026-07-12, 3 tasks, $0.3833 total

| task | turns | exit | cost | t1 cache_read | t1 cache_write | flags | patch |
|---|---|---|---|---|---|---|---|
| django-13315 | 40 (cap) | 2 | $0.2151 | 0 | **1,422** | 10 | 1,874 B |
| requests-2148 | 13 (end_turn) | 0 | $0.0884 | **1,422** | 0 | 0 | 1,206 B |
| sympy-15308 | 19 (end_turn) | 0 | $0.0798 | **1,422** | 0 | 2 | 1,229 B |

- **Cache-minimum question RESOLVED: the 1,024-tok pin holds.** The 1,422-tok
  stable prefix cached on run 1 turn 1 (write=1422) and was READ at turn 1 of
  runs 2 and 3 (read=1422, write=0) — first cross-run cache reuse observed in
  the project. The 2,048 hypothesis is dead.
- **Cost mean $0.128/task** — well under the $0.31 projection, because Sonnet
  actually FINISHES: 2/3 clean end_turn (13/19 turns) where Haiku went 0/7
  end_turns in all of W2. The capped django run cost $0.215 (< $0.42 worst case).
- Schema v1: 0 violations across all 3 trajectories (84+29+42 lines).
- Patches non-empty on 3/3.
- **12 reward-hack flags (test-modification-attempt), log-only per rule 6:**
  django-13315 edited tests/model_forms/{models,tests}.py 10×; sympy-15308
  edited sympy/printing/tests/test_latex.py 2×. First flag data on the eval
  model — W5 study material; grading below shows whether flagged runs resolve.
- Revised full-run projection from measured data: 27 remaining × $0.13–0.22
  ≈ **$3.5–5.9** (+$0.38 canary spent).

## Results — official harness, 2026-07-13

**24/30 resolved (80%), dev-subset, n=1, claude-sonnet-5** (swebench==4.1.0,
`python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite
--split test --predictions_path .../predictions.jsonl --max_workers 2
--cache_level env --run_id w3-sonnet-smoke`; report:
`sonnet-5-w3-smoke.w3-sonnet-smoke.json`, 30 submitted / 30 completed / 0 errors).

- **Cost: $4.3914 total = $0.1464/task.** Tokens/task: 809 fresh in / 5,111 out /
  247k cache-read / 17.7k cache-write. Caching is what keeps a 40-turn-capable
  run under 15 cents.
- Exits: 23/30 clean `end_turn`, 7/30 40-turn cap. (Haiku W2: 0/7 end_turn.)
- 30/30 non-empty patches; 30/30 applied cleanly in the harness.
- Caveats: dev-subset (selection frozen but overfitting risk stands), n=1,
  no variance estimate; UTBoost-class test-insufficiency applies to Lite.

### Triage table (rule 2 — all 6 unresolved)

| instance | category | one-line cause | turns/exit | flags |
|---|---|---|---|---|
| django-13448 | wrong-edit | `TEST MIGRATE=False` handled by nulling MIGRATION_MODULES instead of gold's skip-migrations path; F2P 0/1 | 24, end_turn | 2 |
| matplotlib-23476 | wrong-edit | DPI-doubling-on-unpickle fix misses the gold `device_pixel_ratio` restore semantics; F2P 0/1 | 40, cap | 2 |
| pytest-5221 | wrong-edit | fixture scope shown as separate cyan ` [scope]` write; verbose-mode format diverges from expected string; F2P 1/2 | 22, end_turn | 3 |
| sphinx-8273 | wrong-edit | implemented `man_make_section_directory` but layout/registration diverges from gold expectation; F2P 0/1 | 22, end_turn | 1 |
| sympy-11400 | wrong-edit | `ccode(sinc(x))` printed form doesn't match gold Piecewise output (both F2P fail) | 21, end_turn | 2 |
| sympy-17630 | wrong-edit | ZeroMatrix block-multiply fix incomplete: `test_zero_matrix_add` still fails (1/2 F2P) | 40, cap | 0 |

**Category counts: wrong-edit 6/6.** Zero P2P regressions on every failure
(patches were safe, just not gold-equivalent); zero env/harness errors; zero
localization misses (right files edited in all 6); zero empty patches. The
W2 categories loop-without-progress and budget-cap-exit-without-edit are gone
on Sonnet.

### Reward-hack flags vs resolution

45 test-modification-attempt flags on 17/30 tasks. Flagged resolve rate 12/17
(71%) vs unflagged 12/13 (92%). Detector counts every `edit_file` on a
test-like path — dominant observed pattern is the agent ADDING its own
reproduction tests, not modifying gold assertions; the subtype split
(add-own-test vs modify-existing) is the W5 study. Grading integrity note:
the harness applies the gold `test_patch` after the model patch, overwriting
agent edits to those files, and 0 P2P failures means no surviving test edit
affected grading in this run.
