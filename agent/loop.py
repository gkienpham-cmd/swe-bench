"""Raw Messages API tool-use loop — no frameworks (W1 D1–2).

model -> tool call -> observation -> repeat, until end_turn, the turn cap,
or the hard cost ceiling (W2 D8-9 budget tracker).
Every step is appended to a JSONL trajectory via tracelog. Cost is computed
per turn from usage fields and printed at exit ($/task is a first-class KPI).
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agent.compact import compact_messages, estimate_tokens, prompt_tokens
from agent.sandbox import Sandbox
from agent.tools import TOOL_SCHEMAS, dispatch, reward_hack_flag
from agent.tracelog import TraceLog

# $/MTok (input, output) — pricing verified 2026-07-10 against the Claude API
# reference. Cache read ~0.1x input, cache write 1.25x input (5-min TTL).
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    # Intro pricing through 2026-08-31 (verified live 2026-07-12; re-verify at
    # each paid launch, rule 7). List price reverts to (3.00, 15.00).
    "claude-sonnet-5": (2.00, 10.00),
}

SYSTEM_PROMPT = (
    "You are a coding agent working in a git repository. "
    "Use the provided tools to inspect the repository and accomplish the task. "
    "Repositories may be large: locate code with grep_glob, then read only the "
    "relevant line range — avoid reading whole files. "
    "When you have completed the task, reply with your final answer as plain text."
)

# Prompt caching (W2 D12-13). Breakpoint 1: the system block caches
# tools+system together (render order is tools -> system -> messages).
# Measured (analysis/measure_prefix.py): tools+system is ~1,372 tok, UNDER
# Haiku 4.5's 4,096-tok minimum cacheable prefix — so this breakpoint never
# caches by itself on Haiku; it costs nothing (below-minimum markers are
# silently ignored) and is kept for models with lower minimums. The working
# breakpoint is the moving conversation marker (_move_cache_marker), whose
# cumulative prefix (tools+system+messages) crosses 4,096 within a few turns.
SYSTEM_BLOCKS = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]

# W4 D22-23 localization stage. Lives in the FIRST USER MESSAGE, not the
# system prompt: SYSTEM_BLOCKS + TOOL_SCHEMAS are the frozen 1,422-token
# cross-run cached prefix (baseline-w3) and must stay byte-identical across
# both W5 ablation arms. Targets the measured wrong-FILE failures
# (mpl-23476, sympy-17630, django-17051 run 2): the agent committed to one
# hypothesis without ever enumerating an alternative at the symptom site.
# Joined by string concatenation, never str.format — problem statements
# contain literal {} in code snippets.
LOCALIZATION_PREFIX = """\
You will fix a bug in this repository. Work in two phases.

PHASE 1 - LOCALIZE (required before any edit; the edit_file tool is locked \
until you post the plan below):
Investigate the repository and determine WHERE the fix belongs. The most \
common mistake is editing where the symptom is manipulated instead of where \
the defect actually lives. You must consider at least 2 distinct candidate \
locations, and at least one candidate must be in the code path where the \
reported symptom is produced (e.g. where the failing object is created, \
serialized, converted, or returned). Gather concrete evidence for each \
candidate: code you actually read, call paths you traced.

Then post a message containing exactly this structure:
LOCALIZATION:
- candidate: <path/to/file.py>::<function_or_class> -- evidence: <what you read that supports this>
- candidate: <path/to/other_file.py>::<symbol> -- evidence: <...>
CHOSEN: <path/to/file.py>::<symbol> -- reason: <why this beats every alternative you listed>

PHASE 2 - FIX:
Make the smallest change that fixes the root cause at the chosen location. \
If your fix turns out to be wrong, you may revise by posting a new \
LOCALIZATION block and editing again.

--- PROBLEM STATEMENT ---
"""

LOCALIZATION_LOCKED_MSG = (
    "edit_file is locked: you have not yet posted a LOCALIZATION plan. Post a "
    'plain-text message containing a "LOCALIZATION:" block with at least 2 '
    'candidate locations (file::symbol -- evidence) and a "CHOSEN:" line, '
    "then retry this edit."
)

LOCALIZATION_NUDGE = (
    "You have used many turns without posting a LOCALIZATION plan. Commit now: "
    "post the LOCALIZATION block with your best current candidates and a "
    "CHOSEN line, then implement the fix at the chosen location. edit_file is "
    "now unlocked either way."
)

# Candidate/chosen extraction for the localization_plan meta line. Parse
# failure must NOT block the unlock — the gate keys off sentinel presence
# only; raw_block on the meta line keeps W5 analysis computable even if
# these regexes regress (rule 5 spirit).
_CANDIDATE_RE = re.compile(r"^\s*-\s*candidate:\s*(\S+)", re.MULTILINE)
_CHOSEN_RE = re.compile(r"^\s*CHOSEN:\s*(\S+)", re.MULTILINE)


def _plan_emitted(content) -> str | None:
    """Return the first text block containing both plan sentinels, else None."""
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", "") or ""
        lines = [ln.strip() for ln in text.splitlines()]
        if any(ln.startswith("LOCALIZATION:") for ln in lines) and any(
            ln.startswith("CHOSEN:") for ln in lines
        ):
            return text
    return None


def _parse_plan(block_text: str) -> dict:
    """Best-effort structure for the meta line; never raises."""
    candidates = _CANDIDATE_RE.findall(block_text)
    chosen_m = _CHOSEN_RE.search(block_text)
    chosen = chosen_m.group(1) if chosen_m else None
    return {
        "n_candidates": len(candidates),
        "candidate_files": [c.split("::")[0] for c in candidates],
        "candidates": candidates,
        "chosen": chosen,
        "parse_ok": bool(candidates) and chosen is not None,
    }


def _move_cache_marker(messages: list) -> None:
    """Breakpoint 2: strip cache_control from every user tool_result block,
    then mark the last block of the newest user message. One moving marker +
    the system marker = 2 breakpoints (max 4). Old prefixes stay readable —
    markers are write points; removing one evicts nothing. Assistant content
    is SDK objects and never carries markers."""
    last_user = None
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
            last_user = msg
    if last_user is not None:
        last_user["content"][-1]["cache_control"] = {"type": "ephemeral"}


def turn_cost(model: str, usage) -> float:
    in_price, out_price = PRICING[model]
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        usage.input_tokens * in_price
        + usage.output_tokens * out_price
        + cache_read * 0.1 * in_price
        + cache_write * 1.25 * in_price
    ) / 1_000_000


def usage_dict(usage) -> dict:
    return {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


class BudgetTracker:
    """Per-turn token/cost accumulator with a hard cost ceiling (W2 D8-9).

    add() after every API response; over_budget() decides whether the loop
    may start another turn. The check is post-turn — a request in flight
    cannot be un-spent — so actual spend can overshoot the ceiling by at
    most one turn's cost. A run that finishes cleanly on the turn that
    crosses the ceiling still counts as clean: the ceiling stops further
    spend, it does not retroactively fail completed work.
    """

    def __init__(self, model: str, max_cost_usd: float | None = None):
        self.model = model
        self.max_cost_usd = max_cost_usd
        self.total_cost = 0.0
        self.total_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self.turns = 0

    def add(self, usage) -> float:
        cost = turn_cost(self.model, usage)
        self.total_cost += cost
        for k, v in usage_dict(usage).items():
            self.total_usage[k] += v
        self.turns += 1
        return cost

    def over_budget(self) -> bool:
        return self.max_cost_usd is not None and self.total_cost >= self.max_cost_usd


def run(
    task: str, model: str, workdir: Path, out_dir: Path, task_id: str, max_turns: int,
    sandbox_image: str | None = None, max_cost_usd: float | None = None,
    compact_at_tokens: int | None = None,
    sandbox_workdir: str = "/workspace", sandbox_preloaded: bool = False,
    localization: bool = False, localization_max_turns: int = 12,
) -> int:
    # Rule 4c: raw metered API key only. Pin it explicitly so the SDK cannot
    # silently fall back to an OAuth profile or auth token.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY is not set. Export a raw API key (never subscription OAuth).", file=sys.stderr)
        return 1
    client = anthropic.Anthropic(api_key=api_key)

    # One file per run: a failed run can never leave stale steps in a later
    # run's trajectory (measured D1 failure).
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    out_path = out_dir / f"{stamp}_{task_id}.jsonl"
    print(f"[trajectory: {out_path}]")

    log = TraceLog(out_path, task_id=task_id)

    # Per-task container: repo copied in, no host-FS access. Teardown is
    # guaranteed by try/finally — a crashed run must not leak containers.
    sandbox = None
    try:
        if sandbox_image:
            # Preloaded (official SWE-bench eval images): the repo already
            # lives in the image at sandbox_workdir — nothing is copied in.
            sandbox = Sandbox(sandbox_image, None if sandbox_preloaded else workdir,
                              workdir=sandbox_workdir)
            sandbox.start()
            print(f"[sandbox: image={sandbox_image} container={sandbox.container} "
                  f"workdir={sandbox_workdir} preloaded={sandbox_preloaded}]")
            log.append("meta", {"sandbox_image": sandbox_image, "container": sandbox.container,
                                "sandbox_workdir": sandbox_workdir,
                                "sandbox_preloaded": sandbox_preloaded})
        budget = BudgetTracker(model, max_cost_usd=max_cost_usd)
        rc = _loop(client, log, task, model, workdir, max_turns, sandbox, budget,
                   compact_at_tokens=compact_at_tokens,
                   localization=localization,
                   localization_max_turns=localization_max_turns)
        # Schema v1: persist the final in-container patch on EVERY exit path
        # (_loop returns on clean finish, cost ceiling, and max-turns alike).
        # Logged as a meta line AND written as a .patch beside the trajectory
        # — this is the W3 patch-extraction path. Host-mode runs log null.
        diff = sandbox.git_diff() if sandbox is not None else None
        log.append("meta", {"final_git_diff": diff})
        if diff:
            patch_path = out_path.with_suffix(".patch")
            patch_path.write_text(diff, encoding="utf-8")
            print(f"[patch: {patch_path} ({len(diff)} bytes)]")
        elif sandbox is not None:
            print("[patch: empty or extraction failed — final_git_diff meta line logged]")
        return rc
    finally:
        if sandbox is not None:
            sandbox.stop()


def _loop(client, log, task: str, model: str, workdir: Path, max_turns: int, sandbox, budget,
          compact_at_tokens: int | None = None,
          localization: bool = False, localization_max_turns: int = 12) -> int:
    # The trajectory's index-0 user line is the WRAPPED message — what the
    # model actually saw (index 0 is compaction-protected by construction).
    task_message = LOCALIZATION_PREFIX + task if localization else task
    log.append("user", task_message)
    messages = [{"role": "user", "content": task_message}]
    hack_flags = 0
    plan_emitted = False      # gate unlocks on sentinel presence only
    forced_unlock = False     # turn-K commit nudge fired
    last_plan_block = None    # re-plans are logged once per distinct block
    if localization:
        log.append("meta", {
            "scaffold_stage": "localization",
            "localization": True,
            "localization_max_turns": localization_max_turns,
            "prefix_untouched": True,
        })

    # Sonnet 5 runs ADAPTIVE thinking when the `thinking` param is omitted
    # (Haiku: omission = no thinking). Disable it explicitly so the W3 baseline
    # keeps the Haiku-identical request shape: no thinking blocks (schema v1
    # never saw them), no thinking spend inside the 4096-token turn cap.
    # Enabling thinking is a scaffold change that waits for triage data (rule 1).
    extra = {"thinking": {"type": "disabled"}} if model == "claude-sonnet-5" else {}

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_BLOCKS,
            tools=TOOL_SCHEMAS,
            messages=messages,
            **extra,
        )
        cost = budget.add(response.usage)

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        log.append(
            "assistant",
            [b.model_dump() for b in response.content],
            tool_name=tool_uses[0].name if tool_uses else None,
            tool_input=tool_uses[0].input if tool_uses else None,
            usage=usage_dict(response.usage),
            cost_usd=cost,
        )

        if localization:
            block_text = _plan_emitted(response.content)
            if block_text is not None and block_text != last_plan_block:
                last_plan_block = block_text
                plan_emitted = True
                log.append("meta", {
                    "localization_plan": True,
                    "turn": turn,
                    "raw_block": block_text,
                    **_parse_plan(block_text),
                })

        if response.stop_reason != "tool_use":
            final = next((b.text for b in response.content if b.type == "text"), "")
            print(final)
            print(
                f"\n[{response.stop_reason} after {turn + 1} turn(s) | "
                f"tokens in={budget.total_usage['input']} out={budget.total_usage['output']} | "
                f"cost=${budget.total_cost:.6f} | reward-hack flags={hack_flags} | trajectory={log.path}]"
            )
            return 0

        # Hard cost ceiling: halt before dispatching tools — their results
        # would only feed an API call we are not going to make. The emitted
        # tool calls are already on the assistant trajectory line, so the
        # halt loses no post-hoc analysis data.
        if budget.over_budget():
            log.append("meta", {
                "budget_ceiling_hit": True,
                "max_cost_usd": budget.max_cost_usd,
                "total_cost_usd": budget.total_cost,
                "turns": budget.turns,
            })
            print(
                f"[BUDGET CEILING HIT: cost=${budget.total_cost:.6f} >= max=${budget.max_cost_usd:.6f} "
                f"after {budget.turns} turn(s) | reward-hack flags={hack_flags} | trajectory={log.path}]"
            )
            return 2

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            flag = reward_hack_flag(tu.name, tu.input)
            if flag:
                hack_flags += 1
                print(f"[REWARD-HACK FLAG: {flag} — {tu.name} on {tu.input.get('path')}]")
            # Soft localization gate: reject edit_file with a corrective
            # error until a plan is posted (or the turn-K unlock fires).
            # dispatch() never runs, so nothing is written; the attempt is
            # still a full tool line (and reward_hack_flag above still
            # fires on gated attempts — attempts are findings, rule 6).
            if localization and not plan_emitted and not forced_unlock and tu.name == "edit_file":
                content, is_error = LOCALIZATION_LOCKED_MSG, True
                log.append("meta", {"localization_gate_reject": True, "turn": turn})
            else:
                content, is_error = dispatch(workdir, tu.name, tu.input, sandbox=sandbox)
            results.append(
                {"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error}
            )
            log.append(
                "tool",
                None,
                tool_name=tu.name,
                tool_input=tu.input,
                tool_result_summary=content[:500],
                tool_result_full=content,
                reward_hack_flag=flag,
            )
        # Turn-K commit nudge: past localization_max_turns without a plan,
        # unlock editing unconditionally and demand commitment — the gate
        # must never manufacture a zero-edit cap burn (sympy-17630 run-2
        # mode). Appended as an extra text block on this turn's tool_results
        # user message, preserving role alternation.
        if (localization and not plan_emitted and not forced_unlock
                and turn + 1 >= localization_max_turns):
            results.append({"type": "text", "text": LOCALIZATION_NUDGE})
            forced_unlock = True
            log.append("meta", {
                "localization_forced_unlock": True,
                "turn": turn,
                "plan_emitted": False,
            })

        messages.append({"role": "user", "content": results})
        _move_cache_marker(messages)

        # Compaction check, once per turn. Last-response usage measures the
        # prompt BEFORE this turn's assistant content and tool results were
        # appended — one turn stale, and a single multi-read turn can add
        # tens of k tokens — so estimate the just-appended tail on top.
        if compact_at_tokens:
            est_prompt = (
                prompt_tokens(response.usage) + response.usage.output_tokens
                + estimate_tokens(sum(len(r.get("content", r.get("text", ""))) for r in results))
            )
            if est_prompt >= compact_at_tokens:
                low_water = compact_at_tokens // 2
                stats = compact_messages(messages, target_tokens=est_prompt - low_water, turn=turn)
                log.append("meta", {
                    "compaction": True,
                    "turn": turn,
                    "est_prompt_tokens": est_prompt,
                    "threshold": compact_at_tokens,
                    "low_water": low_water,
                    **stats,
                })
                print(
                    f"[COMPACTION at turn {turn}: ~{est_prompt} tok >= {compact_at_tokens} -> "
                    f"elided {stats['blocks_elided']} blocks, ~{stats['est_tokens_removed']} tok removed"
                    f"{'' if stats['target_met'] else ' (target NOT met — un-elidable floor)'}]"
                )

    # Meta-line parity with the cost-ceiling exit: both cap exits must be
    # classifiable post-hoc as `budget-cap-exit` from the trajectory alone.
    log.append("meta", {
        "max_turns_hit": True,
        "max_turns": max_turns,
        "total_cost_usd": budget.total_cost,
        "turns": budget.turns,
    })
    print(
        f"[hit max_turns={max_turns} without end_turn | cost=${budget.total_cost:.6f} | "
        f"reward-hack flags={hack_flags} | trajectory={log.path}]"
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal tool-use agent loop")
    parser.add_argument("--task", required=True, help="Task prompt for the agent")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--workdir", default=".", help="Repository root the tools operate in")
    parser.add_argument("--out-dir", default="results/dev", help="Directory for per-run trajectory files")
    parser.add_argument("--task-id", default="dev-smoke", help="Task id stamped on every trajectory line")
    # Per-task caps (W2 D10-11): ~40 steps / ~$1, tighter than mini-SWE-agent's
    # 250/$3 defaults. Grounded in analysis/measure_context.py: at the 4k
    # tok/turn stress growth an uncapped, uncompacted run costs $3.69 input
    # over 40 turns; with 25k-threshold compaction the same run is ~$0.77, so
    # $1 binds on turns, not mid-task. (The W1 gate measured a 6-turn minimum
    # on even the toy task — results/2026-07-11_w1-gate/summary.md.)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument(
        "--max-cost-usd", type=float, default=1.00,
        help="Hard cost ceiling for the run; the loop halts (exit 2) instead of "
        "starting another turn once total cost reaches it. Default $1.00; "
        "pass 0 or a negative value to disable the ceiling.",
    )
    parser.add_argument(
        "--compact-at-tokens", type=int, default=25_000,
        help="Compact the conversation (elide old tool results) when the "
        "estimated prompt reaches this many tokens, down to half of it. "
        "Default 25000 (analysis/measure_context.py: keeps a 40-turn run "
        "under the $1 cap even at 4k tok/turn growth). Pass 0 to disable.",
    )
    parser.add_argument(
        "--sandbox-image", default=None,
        help="Run all tools inside a per-task Docker container of this image; "
        "the repo at --workdir is copied in (no bind mounts, no network).",
    )
    parser.add_argument(
        "--sandbox-workdir", default="/workspace",
        help="Repo directory inside the container (official SWE-bench eval "
        "images ship the repo at /testbed).",
    )
    parser.add_argument(
        "--sandbox-preloaded", action="store_true",
        help="The image already contains the repo at --sandbox-workdir; skip "
        "the --workdir copy-in (use with official sweb.eval images).",
    )
    # W4 D22-23 localization stage. Cited failures (rule 1): mpl-23476 and
    # sympy-17630 edited the wrong FILE in both baseline runs (verified
    # against gold patches), django-17051 run 2 likewise then reverted to an
    # empty diff. --no-localization is the W5 ablation-A arm and is
    # byte-identical to baseline-w3 behavior (selftest-enforced).
    parser.add_argument(
        "--localization", action=argparse.BooleanOptionalAction, default=True,
        help="Wrap the task in the two-phase LOCALIZE/FIX directive and soft-"
        "lock edit_file until a LOCALIZATION plan (>=2 candidates + CHOSEN) "
        "is posted. --no-localization reproduces the baseline-w3 arm.",
    )
    parser.add_argument(
        "--localization-max-turns", type=int, default=12,
        help="Turn at which an un-posted plan force-unlocks editing and a "
        "commit nudge is injected. Default 12: baseline resolved tasks' "
        "median first edit is turn 4-4.5 (p75 9); the two wrong-file "
        "failures first edited at turns 17 and 24.",
    )
    args = parser.parse_args()
    # <=0 means "no ceiling" now that the default is a real number.
    max_cost = args.max_cost_usd if args.max_cost_usd and args.max_cost_usd > 0 else None
    return run(
        args.task, args.model, Path(args.workdir), Path(args.out_dir), args.task_id,
        args.max_turns, sandbox_image=args.sandbox_image, max_cost_usd=max_cost,
        compact_at_tokens=args.compact_at_tokens if args.compact_at_tokens > 0 else None,
        sandbox_workdir=args.sandbox_workdir, sandbox_preloaded=args.sandbox_preloaded,
        localization=args.localization, localization_max_turns=args.localization_max_turns,
    )


if __name__ == "__main__":
    sys.exit(main())
