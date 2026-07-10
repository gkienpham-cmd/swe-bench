# Primary-source design notes

Build-facing extracts from the three primary sources (fetched live 2026-07-10). Read the originals end-to-end; these notes exist so design decisions cite a source, not a memory. Each section ends with the PLAN.md decisions it informs.

## 1. Anthropic SWE-bench engineering post

- **Tool set is two tools:** a `bash` tool (persistent shell env in their case; schema is just `command`) and a `str_replace_editor` edit tool (`view` / `create` / `str_replace` / `insert` / `undo_edit`). Their `str_replace` fails unless `old_str` matches **exactly once** — the same uniqueness rule PLAN.md D3–4 specifies for our `edit_file`.
- **Absolute paths required** in the edit tool, explicitly to prevent relative-path errors. Tool descriptions get "significant attention for error-proofing" — description text is a first-class engineering surface, not boilerplate.
- **Prompt structure:** repo location + PR description + a *suggested* (not enforced) workflow: explore → reproduce → edit → verify → edge cases. Philosophy stated outright: "give as much control as possible to the language model itself, and keep the scaffolding minimal."
- **Test-modification guardrail, verbatim:** "I've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way!" — framed as *you don't need to*, not *you must not*. That framing choice is itself a variable the W5 guardrail-relaxation experiment can discuss.
- **Stopping:** sample until the model declares completion or hits the 200k context limit. No step cap mentioned — context *is* their cap.
- **informs:** D3–4 `edit_file` uniqueness validation (exact match, fail loud on 0 or >1); D1–2 tool-description quality bar; D24–25 guardrail prompt wording (replicate this phrasing as the default-ON flag); W2 context-ceiling-as-stop-condition design.

## 2. mini-SWE-agent (SWE-bench team's minimal agent)

- **Bash-only, no custom tools, ~100 lines.** Even the edit tool is dropped; the model does everything through shell commands. Scores >74% on Verified — the standing proof that **the model, not the scaffold, carries the resolve rate**. Our five-tool design is already *more* scaffold than the calibration anchor; every stage past it must buy a measured lift (rule 1).
- **Completely linear history:** every observation appends to one message list; what the model sees is exactly what happened. No branching, no summarization in the base design. Our W2 compaction is a deliberate departure — worth an ablation note if compaction ever looks like it hurts.
- **Stateless execution via `subprocess.run`, no persistent shell** — called out in their docs as "a big deal": stability, and the sandbox swap becomes trivial (subprocess → docker exec). Note the split: *Anthropic's* bash tool is persistent, mini-SWE-agent's is stateless. PLAN.md D3–4 follows mini-SWE-agent here, accepting the cost that `cd`/env state doesn't survive between actions (each command must be self-contained).
- **Caps:** default $3/task, 250 steps per PLAN.md REFERENCES [snapshot 2026-07] — not re-confirmable from the FAQ today; **re-verify live at W2 D10–11** before finalizing our ~$1/~40 caps against it.
- **informs:** D1–2/D3–4 stateless `bash` via `subprocess.run`; W2 linear-history-first (compaction only when measurement demands it); D10–11 cap calibration; report framing (scaffold-vs-model attribution).

## 3. SWE-bench Lite dataset card + swebench.com/lite

- **323 instances: 300 test (the benchmark) + 23 dev.** 11 Python repos (sqlfluff, marshmallow, pvlib, astroid, pyvista, pydicom, …; distribution skews heavily — verify per-repo counts when freezing the dev subset).
- **Instance fields:** `instance_id`, `repo`, `base_commit` (checkout point), `problem_statement` (issue title+body — the agent's *only* task input), `patch` (gold solution, non-test), `test_patch` (the grading tests, applied by the harness — **never shown to the agent**), `FAIL_TO_PASS` (tests the fix must make pass), `PASS_TO_PASS` (tests the fix must not break), `environment_setup_commit`, `hints_text` (unused in standard evals).
- **Lite filtering:** removed instances with images/links/SHA-or-PR references, <40-word problem statements, multi-file or file-create/delete edits, gold patches >3 hunks, and tests that check error-message strings. Net effect: **every Lite task is a single-file, ≤3-hunk edit with a self-contained problem statement.**
- **Consequences for us:** (a) localization is simpler than full SWE-bench but still the bottleneck per SWE-bench-Live — one file, but which one; (b) patch format only ever needs single-file diffs; (c) `pass2pass-regression` grading means the harness runs PASS_TO_PASS too — a "fix" that breaks neighbors fails; (d) the 23-instance dev split exists but PLAN.md draws the 30-task dev subset from the 300 test tasks — dev-subset overlap with the headline number is a known limitation to state in the report.
- **informs:** D3–4 `edit_file` scope (single-file string-replace suffices for Lite); D15–16 fail2pass/pass2pass grading; D17–18 dev-subset freeze (check per-repo distribution); report limitations (UTBoost test-insufficiency + dev-subset overfit).

## Open verification items (rule 7)

- mini-SWE-agent exact default caps and patch-extraction path — read the source, not the FAQ, at W2 D10–11.
- Per-repo distribution of the 300 Lite test tasks — compute from the dataset itself at D17–18 freeze time.
