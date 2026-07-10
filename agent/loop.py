"""Raw Messages API tool-use loop — no frameworks (W1 D1–2).

model -> tool call -> observation -> repeat, until end_turn, the turn cap,
or the hard cost ceiling (W2 D8-9 budget tracker).
Every step is appended to a JSONL trajectory via tracelog. Cost is computed
per turn from usage fields and printed at exit ($/task is a first-class KPI).
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agent.sandbox import Sandbox
from agent.tools import TOOL_SCHEMAS, dispatch, reward_hack_flag
from agent.tracelog import TraceLog

# $/MTok (input, output) — pricing verified 2026-07-10 against the Claude API
# reference. Cache read ~0.1x input, cache write 1.25x input (5-min TTL).
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
}

SYSTEM_PROMPT = (
    "You are a coding agent working in a git repository. "
    "Use the provided tools to inspect the repository and accomplish the task. "
    "Repositories may be large: locate code with grep_glob, then read only the "
    "relevant line range — avoid reading whole files. "
    "When you have completed the task, reply with your final answer as plain text."
)


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
            sandbox = Sandbox(sandbox_image, workdir)
            sandbox.start()
            print(f"[sandbox: image={sandbox_image} container={sandbox.container}]")
            log.append("meta", {"sandbox_image": sandbox_image, "container": sandbox.container})
        budget = BudgetTracker(model, max_cost_usd=max_cost_usd)
        return _loop(client, log, task, model, workdir, max_turns, sandbox, budget)
    finally:
        if sandbox is not None:
            sandbox.stop()


def _loop(client, log, task: str, model: str, workdir: Path, max_turns: int, sandbox, budget) -> int:
    log.append("user", task)
    messages = [{"role": "user", "content": task}]
    hack_flags = 0

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
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
                reward_hack_flag=flag,
            )
        messages.append({"role": "user", "content": results})

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
    # Default 10, not 5: the W1 gate measured a 6-turn minimum on even the
    # toy task (a default-5 run solved it, then died before end_turn —
    # results/2026-07-11_w1-gate/summary.md). Real caps are W2 D10-11 scope.
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument(
        "--max-cost-usd", type=float, default=None,
        help="Hard cost ceiling for the run; the loop halts (exit 2) instead of "
        "starting another turn once total cost reaches it. Default: no ceiling.",
    )
    parser.add_argument(
        "--sandbox-image", default=None,
        help="Run all tools inside a per-task Docker container of this image; "
        "the repo at --workdir is copied in (no bind mounts, no network).",
    )
    args = parser.parse_args()
    return run(
        args.task, args.model, Path(args.workdir), Path(args.out_dir), args.task_id,
        args.max_turns, sandbox_image=args.sandbox_image, max_cost_usd=args.max_cost_usd,
    )


if __name__ == "__main__":
    sys.exit(main())
