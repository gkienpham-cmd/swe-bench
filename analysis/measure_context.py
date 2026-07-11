"""W2 D10-11 Step-0 measurement: context growth per turn from real trajectories,
and a 40-turn cost simulation under candidate compaction thresholds (rule 1).

Usage: python -m analysis.measure_context [results_dir ...]

Per-turn prompt size is exact (usage.input + cache_read + cache_write from
assistant lines). The growth decomposition is exact too: the prompt delta
between consecutive assistant turns is prev_output + tool-result tokens, so
tool-result tokens = delta - prev_output — no full tool results needed.
Numbers go to stdout for LOG.md; nothing is written anywhere.
"""

import json
import statistics
import sys
from pathlib import Path

# Haiku 4.5 $/MTok, matching agent.loop.PRICING (verified 2026-07-10).
IN_PRICE, OUT_PRICE = 1.00, 5.00
SIM_TURNS = 40
OUT_PER_TURN = 600            # est output tok/turn (measured runs: 90-300, gate margin)
CAP_USD = 1.00
THRESHOLDS = [None, 15_000, 20_000, 25_000, 30_000]   # None = no compaction


def prompt_tokens(usage: dict) -> int:
    return usage["input"] + usage["cache_read"] + usage["cache_write"]


def measure_run(path: Path) -> list[int]:
    """Print per-turn growth for one trajectory; return the per-turn deltas."""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    turns = [r for r in rows if r["role"] == "assistant"]
    if len(turns) < 2:
        print(f"\n{path.name}: {len(turns)} assistant turn(s) — too short, skipped")
        return []
    print(f"\n{path.name}")
    print("  turn  prompt_tok  delta  =prev_out  +tool_results")
    deltas = []
    for i, t in enumerate(turns):
        p = prompt_tokens(t["usage"])
        if i == 0:
            print(f"  {i:>4}  {p:>10}      -          -              -")
            continue
        prev = turns[i - 1]
        delta = p - prompt_tokens(prev["usage"])
        tool_part = delta - prev["usage"]["output"]
        deltas.append(delta)
        print(f"  {i:>4}  {p:>10}  {delta:>5}  {prev['usage']['output']:>9}  {tool_part:>13}")
    print(f"  median growth: {statistics.median(deltas):.0f} tok/turn over {len(deltas)} deltas")
    return deltas


def simulate(growth: int, start: int) -> None:
    """Saw-tooth simulation: prompt grows by `growth`/turn; at >= threshold it
    drops to threshold//2 (low-water). Cost billed per turn, no caching."""
    print(f"\n40-turn simulation: start={start} tok, growth={growth} tok/turn, "
          f"output={OUT_PER_TURN} tok/turn, no caching")
    print(f"  {'threshold':>10}  {'avg_prompt':>10}  {'input_$':>8}  {'total_$':>8}  cap-$1 hits at turn")
    for th in THRESHOLDS:
        prompt, cost, cap_turn = start, 0.0, None
        prompts = []
        for turn in range(1, SIM_TURNS + 1):
            prompts.append(prompt)
            cost += (prompt * IN_PRICE + OUT_PER_TURN * OUT_PRICE) / 1e6
            if cap_turn is None and cost >= CAP_USD:
                cap_turn = turn
            prompt += growth + OUT_PER_TURN
            if th is not None and prompt >= th:
                prompt = th // 2
        in_cost = sum(prompts) * IN_PRICE / 1e6
        label = "none" if th is None else f"{th//1000}k/{th//2000}k"
        hit = str(cap_turn) if cap_turn else "never"
        print(f"  {label:>10}  {statistics.mean(prompts):>10.0f}  {in_cost:>8.3f}  {cost:>8.3f}  {hit:>6}")


def main() -> None:
    roots = [Path(a) for a in sys.argv[1:]] or [Path("results")]
    paths = sorted(p for root in roots for p in root.rglob("*.jsonl"))
    all_deltas = []
    for p in paths:
        all_deltas += measure_run(p)
    if not all_deltas:
        sys.exit("no multi-turn trajectories found")
    med = int(statistics.median(all_deltas))
    hi = int(statistics.quantiles(all_deltas, n=4)[2])  # p75
    print(f"\nacross {len(paths)} runs: median delta {med} tok/turn, p75 {hi} tok/turn")
    # Simulate at measured median, measured p75, and a real-task stress figure:
    # multi-tool turns on Lite repos (several 250-line windows + grep per turn).
    for growth in sorted({med, hi, 4_000}):
        simulate(growth, start=2_500)


if __name__ == "__main__":
    main()
