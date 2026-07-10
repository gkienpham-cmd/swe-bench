# PLAN — Six-Week SWE-bench Lite Agent

Near-frozen reference. Progress, decisions, and spend live in [LOG.md](LOG.md); only weekly checkpoint pass/fail marks get appended here, at week boundaries.

## Mission & success criteria

- **Deliverable:** a from-scratch SWE-bench Lite agent (raw Messages API tool-use loop + Docker sandbox + official eval harness), a technical report, an HTML trajectory replay viewer, and a reward-hacking study.
- **Headline metric:** resolved % on ONE clean full 300-task SWE-bench Lite run (Week 6). Floor: 40%. Stretch: 65%. Do not expect to beat mini-SWE-agent — the point is to build, measure honestly, and analyze failures.
- **Budget:** $500 hard cap, **API spend only**. The Claude subscription (Max 5x, ~$100/mo × 1.5 months ≈ $150) is fixed overhead outside the cap.
- **Eval model:** pin the exact Sonnet ID at Week 3 start after a live check (rule 7). Planning assumption: `claude-sonnet-5` — intro pricing $2/$10 per MTok runs through 2026-08-31, covering the whole project window. Dev model: `claude-haiku-4-5`.
- **Dev subset:** a 30-task Lite subset frozen ONCE in Week 3 (seed list committed to the repo, never re-picked). All its numbers are labeled dev-subset; the overfitting risk goes in the report's limitations.

## Weekly retro — three fixed questions

1. What did measurement contradict this week?
2. What did this week cost vs. the budget table?
3. What is the binding constraint entering next week?

## Week 1 — Agent core & environment

Goal: a looping agent that can edit a file and run a test inside Docker.

- **D1–2:** Read the three primary sources end-to-end (Anthropic's SWE-bench engineering post, mini-SWE-agent repo/docs, SWE-bench Lite dataset card). Repo, Python env, git, structured-logging skeleton, decision log. Raw Messages API tool-use loop (no frameworks) with tool schemas: `read_file`, `edit_file`, `bash`, `grep_glob`, `run_tests`. *Done when:* a trivial "read a file and summarize it" loop completes end-to-end.
- **D3–4:** `read_file` with line ranges; `bash` via `subprocess.run` (stateless per action, so it swaps to `docker exec` trivially); `edit_file` as string-replace with uniqueness validation (reject if the target appears 0 or >1 times); grep/glob search; per-turn token counting. *Done when:* the agent locates and edits a target string in a scratch repo without a silent wrong edit.
- **D5–6:** Docker sandbox; route `bash` and `run_tests` through `docker exec` into a per-task container; `run_tests` with parseable output; wire the full loop (model → tool call → observation → repeat until done or caps). *Done when:* the container has no host-filesystem access and a test result round-trips through the loop.
- **D7:** Buffer. **Gate W1: the agent solves a hand-made toy bug in a sandboxed repo end-to-end.** Retro.

## Week 2 — Context management, caps, and the trajectory schema

Goal: the agent survives long trajectories without blowing context or budget.

- **D8–9:** Token-budget tracker (input/output/cached tokens per turn, hard stop at a configurable ceiling). File-truncation strategy: never dump whole files, window around matches, summarize directory listings.
- **D10–11:** Conversation compaction near the context limit (preserve: files touched, hypotheses, test results). Max-iteration and per-task cost caps: ~$1/task, ~40 steps (mini-SWE-agent defaults are $3/250 — ours are tighter for Lite).
- **D12–13:** Prompt-caching integration — stable prefix (system prompt + tool defs) first, volatile content last; verify `usage.cache_read_input_tokens > 0` on the second run (zero means a silent invalidator — timestamp, unsorted JSON, varying tool set); mind the minimum cacheable prefix (Haiku 4.5: 4096 tokens — verify for the pinned Sonnet). **Freeze JSONL trajectory schema v1** (`schemas/trajectory.schema.json`): one line per step with messages, raw tool calls, full file diffs, observation, tokens, cost, cache stats. Raw tool calls + diffs are non-negotiable — the Week 5 reward-hacking analysis must be computable post-hoc over Week 3 baseline data.
- **D14:** Buffer. **Gate W2: 5 real Lite tasks run by hand through the agent with caps and logging working.** Retro.

## Week 3 — Official harness & first honest numbers

Goal: reproducible eval on the official SWE-bench Docker harness.

- **D15–16:** Integrate the official harness; understand fail2pass / pass2pass grading. Patch-extraction path (agent's final diff → harness input format); validate a patch applies cleanly.
- **D17–18:** Freeze the 30-task dev subset (commit the seed list). First smoke run: raw API, Sonnet, batch + cache. Record resolved %, $/task, tokens/task. Hand-triage every failure — this seeds the taxonomy below.
- **D19–20:** Fix the top 2 mechanical failure causes (bad patch format, tool misuse, truncation bugs). Re-run the same 30 tasks; compare; lock the baseline config.
- **D21:** Buffer. **Gate W3: documented dev-subset resolved % with cost + a triage table.** Retro.

## Week 4 — Scaffold stages

Goal: measurable lift from each scaffold stage.

- **D22–23:** Planning step (model drafts an approach before editing). Localization step (find the file(s)/function(s) before editing) — localization is a known resolve-rate bottleneck (see REFERENCES).
- **D24–25:** Self-verification step (agent writes/runs its own reproduction test, re-reads its diff, checks it didn't touch tests). Anti-reward-hack guardrail ("do not modify the tests" — Anthropic's own prompt guardrail), **default-ON behind a config flag**, plus online detection: flag any edit to test files or scoring code. Detected attempts are logged findings, and the schema already captures them post-hoc for W3 data.
- **D26–27:** Full-scaffold run on the 50-task SWE-bench Verified Mini subset. Triage; refine the taxonomy.
- **D28:** Buffer. **Gate W4: full-scaffold resolved % on 50 tasks + failure histogram.** Retro.

## Week 5 — Ablations & the reward-hacking study

Goal: causal claims about what each scaffold stage buys.

- **D29–31:** Ablation A (no localization) and Ablation B (no self-verification), each vs. full scaffold on the SAME fixed 50 tasks, batch + cache. Results table: resolve % vs. tokens/$ per stage.
- **D32–33:** Guardrail-relaxation experiment: guardrail flag OFF, runs labeled `hack-permissive`, hard cost cap ~$30. Measure how often the agent games tests; classify incidents against the taxonomy's reward-hack subtypes; pull 2–3 verbatim transcript excerpts. Small-scale replication of METR / ImpossibleBench methodology. `hack-permissive` numbers never appear as a headline resolve rate (rule 9).
- **D34:** Re-run the best config once more for a variance check.
- **D35:** Buffer. **Gate W5: ablation table + reward-hacking rate with examples.** Retro.

## Week 6 — Full run, replay viewer, writeup

Goal: publication-grade artifact.

- **D36:** ONE clean full 300-task SWE-bench Lite run of the best config, Batch API + cache. This is the headline number.
- **D37–38:** HTML replay viewer (loads trajectory JSONL: step-by-step messages, tool calls, diffs, token/cost meter, failure tag). Final failure taxonomy across the 300-task run with % per category.
- **D39–40:** Technical report: methodology (minimal, Anthropic-style), results, ablations, reward-hacking study, cost accounting, limitations (contamination; test-suite insufficiency per the UTBoost and OpenAI-audit findings in REFERENCES; dev-subset overfitting). Polish README + reproducibility instructions; publish repo + viewer.
- **D41–42:** Demo recording; blog post threading the roofline/NCU "honest measurement" methodology from the CUDA kernel work into agent engineering. Final retro. **Final gate: public repo, report, replay viewer, blog post.**

## Budget

Pricing verified 2026-07-10 against the Claude API reference (rule 7 — re-verify before each paid run):
Haiku 4.5 $1/$5 per MTok · Sonnet 5 $3/$15, intro **$2/$10 through 2026-08-31** · Sonnet 4.6 $3/$15 · Opus $5/$25 (banned regardless).
Cache reads ≈0.1× input price, writes 1.25× (5-min TTL) — caching pays only on reused prefixes. Batch API: −50% on input and output, ≤24h turnaround, results keyed by `custom_id`, arrive in any order.
Note: Sonnet 5 uses a new tokenizer (~30% more tokens for the same text than Sonnet 4.6) — budget tokens/task against measurements on the pinned model, not older numbers.
Planning figure: **$0.30–0.55/task** on Sonnet with batch + cache (mini-SWE-agent-class cost is ~$0.55/task uncached).

| Stage | Week | Model | Volume | Est. $ | Cumulative |
|---|---|---|---|---|---|
| Dev iteration (API smoke tests; most dev on subscription) | W1–2 | Haiku | small | ~$10 | $10 |
| 30-task baseline ×2 | W3 | Sonnet | 60 tasks | $20–35 | ~$45 |
| Triage-driven reruns | W3–4 | mixed | ~40 tasks | $15–25 | ~$70 |
| Full-scaffold 50-task run | W4 | Sonnet | 50 tasks | $15–28 | ~$98 |
| Ablations A + B | W5 | Sonnet | 100 tasks | $30–56 | ~$154 |
| Guardrail-relax experiment (hard cap) | W5 | Sonnet | ~50 tasks | ≤$30 | ~$184 |
| Variance re-run | W5 | Sonnet | 50 tasks | $15–28 | ~$212 |
| Full Lite run | W6 | Sonnet | 300 tasks | $90–165 | ~$377 |
| Contingency (~20%) | — | — | — | ~$75 | **~$450** |

## Failure taxonomy (seed — extend during W3 triage)

`localization-miss` (wrong file) · `wrong-edit` (right file, wrong change) · `patch-apply-failure` · `env-failure` · `test-timeout` · `context-overflow` · `loop-without-progress` · `budget-cap-exit` · `gave-up` · `hallucinated-api` · `pass2pass-regression` (broke other tests) · `harness-error` · `reward-hack` (subtypes: `test-modification-attempt`, `hardcode-to-pass`, `test-skip`) · `unclassified`

## REFERENCES

Planning-time snapshots, tagged `[snapshot 2026-07]` — rule 7 applies before relying on any of these.

- **SWE-bench Lite** = 300 curated tasks (easier-to-medium bug fixes); **Verified** = 500 human-validated tasks. Verified leaderboard tops ~80%; Lite tops ~63%.
- **mini-SWE-agent** (Princeton/Stanford SWE-bench team): ~100-line Python agent scoring ~70–74% on Verified at $0.28–0.56/task depending on model. The calibration anchor: a minimal scaffold with a strong model is competitive — scaffolding matters less than the model.
- **mini-SWE-agent caps:** $3/task, 250 steps default (this project: ~$1/task, ~40 steps).
- **Anthropic's SWE-bench methodology:** deliberately minimal — a prompt, a bash tool, an edit tool; the prompt forbids modifying tests because gold tests grade the solution. This is the guardrail this project replicates and then deliberately studies.
- **METR, "Recent Frontier Models Are Reward Hacking" (2025-06):** o3 reward-hacked in 0.7% of HCAST runs but 30.4% baseline on RE-Bench, rising to 70–95% even under an explicit don't-hack instruction; the model acknowledged its actions violated designer intent and kept hacking. Includes a CUDA-kernel hack: the "kernel" read the scorer's precomputed answer off the Python call stack and disabled CUDA synchronization to defeat timing measurement.
- **OpenAI SWE-bench Verified audit (2026-02):** 59.4% of 138 o3-failed problems had material test-design or problem-description issues (35.5% overly narrow tests, 18.8% testing unspecified functionality); SoTA stalled 74.9%→80.9% over 6 months; contamination noted.
- **EvilGenie (arXiv 2511.21654):** reward hacking by inspecting future commits observed on SWE-bench. **ImpossibleBench / SpecBench:** benchmarks separating proxy metrics from true objectives.
- **UTBoost:** ~41% of Lite entries historically mis-scored due to insufficient test suites — cite in limitations.
- **SWE-bench-Live:** localization success is a key bottleneck (~48% localization success correlating with ~19% resolve on hard splits) — motivates the W4 localization stage and its W5 ablation.
- **Subscription vs. API (mid-2026 ToS):** Claude Code interactive use draws from the Pro/Max subscription pool; headless/programmatic use (Agent SDK, `claude -p`) does not, and subscription OAuth tokens are not for automated harnesses. Hence rule 4c: eval runs on a raw API key.
