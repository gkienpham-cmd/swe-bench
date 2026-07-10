"""Raw Messages API tool-use loop — no frameworks (W1 D1–2).

model -> tool call -> observation -> repeat, until end_turn or the turn cap.
Every step is appended to a JSONL trajectory via tracelog. Cost is computed
per turn from usage fields and printed at exit ($/task is a first-class KPI).
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agent.tools import TOOL_SCHEMAS, dispatch
from agent.tracelog import TraceLog

# $/MTok (input, output) — pricing verified 2026-07-10 against the Claude API
# reference. Cache read ~0.1x input, cache write 1.25x input (5-min TTL).
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
}

SYSTEM_PROMPT = (
    "You are a coding agent working in a git repository. "
    "Use the provided tools to inspect the repository and accomplish the task. "
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


def run(task: str, model: str, workdir: Path, out_dir: Path, task_id: str, max_turns: int) -> int:
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
    log.append("user", task)
    messages = [{"role": "user", "content": task}]
    total_cost = 0.0
    total_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        cost = turn_cost(model, response.usage)
        total_cost += cost
        for k, v in usage_dict(response.usage).items():
            total_usage[k] += v

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
                f"tokens in={total_usage['input']} out={total_usage['output']} | "
                f"cost=${total_cost:.6f} | trajectory={log.path}]"
            )
            return 0

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            content, is_error = dispatch(workdir, tu.name, tu.input)
            results.append(
                {"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error}
            )
            log.append(
                "tool",
                None,
                tool_name=tu.name,
                tool_input=tu.input,
                tool_result_summary=content[:500],
            )
        messages.append({"role": "user", "content": results})

    print(f"[hit max_turns={max_turns} without end_turn | cost=${total_cost:.6f} | trajectory={log.path}]")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal tool-use agent loop")
    parser.add_argument("--task", required=True, help="Task prompt for the agent")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--workdir", default=".", help="Repository root the tools operate in")
    parser.add_argument("--out-dir", default="results/dev", help="Directory for per-run trajectory files")
    parser.add_argument("--task-id", default="dev-smoke", help="Task id stamped on every trajectory line")
    parser.add_argument("--max-turns", type=int, default=5)
    args = parser.parse_args()
    return run(args.task, args.model, Path(args.workdir), Path(args.out_dir), args.task_id, args.max_turns)


if __name__ == "__main__":
    sys.exit(main())
