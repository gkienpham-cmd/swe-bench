# W2 Gate run — 5 real Lite tasks by hand (D14)

Gate criterion (PLAN.md D14): 5 real SWE-bench Lite tasks run end-to-end through the
agent with caps + caching + schema-v1 logging + patch extraction live. Resolve rate is
NOT the gate metric; any resolved count here is hand-checked, not harness-graded.

## Task selection — biased by design, on record

Policy (user-approved this session): easy-env, pytest-friendly, ≥4 distinct repos.
These are NOT a random draw from the 300 — selection optimized for validating the
machinery (envs built by hand in the W2 buffer day), not for estimating resolve rate.
The W3 dev-subset freeze must treat these 5 IDs as already-seen (they influenced no
scaffold changes yet, but exclusion/inclusion should be decided explicitly at freeze).

| instance_id | repo | version | base_commit | why |
|---|---|---|---|---|
| pallets__flask-4045 | pallets/flask | 2.0 | d8c37f43 | smallest problem statement (230 ch); easy env |
| pytest-dev__pytest-8906 | pytest-dev/pytest | 7.0 | 69356d20 | self-hosting case: agent edits the test runner itself |
| sphinx-doc__sphinx-11445 | sphinx-doc/sphinx | 7.1 | 71db08c0 | modern sphinx, light F2P (util_rst), no doc-build heaviness |
| sympy__sympy-24066 | sympy/sympy | 1.12 | 514579c6 | pure-python giant repo; localization stressor |
| pylint-dev__pylint-7080 | pylint-dev/pylint | 2.15 | 3c5eca2d | 24,770-char problem statement + big repo → natural candidate for the first live 25k compaction fire |

Rejected: psf/requests (era test suites hit httpbin.org live; sandbox is --network none →
F2P would error on connection, not fail on the bug), django (run_tests is pytest-only
until W3), scikit-learn/matplotlib/astropy (compiled builds; env wall-clock, W3 harness
images cover them).

## Environment approach — throwaway by design

Per-task `docker/lite/<instance_id>/Dockerfile`: era-appropriate `python:<ver>-slim`,
clone at base_commit into /workspace, `pip install -e .` + era-pinned test deps at build
time (network available at build only), then `rm -rf /workspace/.git` — so the container's
.git comes solely from the host checkout via `docker cp` at sandbox start, guaranteeing
`git_diff()` is exactly vs base_commit. Containers still run `--network none`.
Replaced by official harness images in W3 D15–16; a "resolved" here can still fail
official grading (test config / version drift) — pipeline validation only.

Env sanity gate before any paid run, per task: container starts; package imports;
F2P test runs under pytest and FAILS pre-patch; `git status --porcelain` clean after
a simulated sandbox start (docker cp overlay) so no egg-info/artifact leaks into patches.
