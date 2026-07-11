"""Append-only JSONL trajectory log — one line per agent step.

Schema v1, FROZEN W2 D12-13 — the contract is schemas/trajectory.schema.json;
selftest_schema validates real lines against it. Raw tool calls and results
are logged in full so the Week 5 reward-hacking analysis stays computable
post-hoc over any trajectory ever written (rule 5). Field additions after
the freeze are a v2 negotiation, not a quiet edit.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"

EMPTY_USAGE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


class TraceLog:
    """Appends one JSON line per step; never truncates an existing file."""

    def __init__(self, path: str | Path, task_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task_id = task_id
        self.step = 0

    def append(
        self,
        role: str,
        content,
        *,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        tool_result_summary: str | None = None,
        tool_result_full: str | None = None,
        usage: dict | None = None,
        cost_usd: float = 0.0,
        reward_hack_flag: str | None = None,
    ) -> dict:
        record = {
            "schema_version": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step": self.step,
            "role": role,
            "content": content,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_result_summary": tool_result_summary,
            # Rule 5 / schema v1: the FULL result. Compaction (D10-11) elides
            # results from the model's context; this field is then the only
            # complete copy, so post-hoc analysis never depends on what the
            # model still saw.
            "tool_result_full": tool_result_full,
            "usage": usage if usage is not None else dict(EMPTY_USAGE),
            "cost_usd": cost_usd,
            # Rule 5: reward-hack signals live on every trajectory line so the
            # W5 analysis is computable post-hoc over any run ever logged.
            "reward_hack_flag": reward_hack_flag,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self.step += 1
        return record


if __name__ == "__main__":
    # Smoke: two appends, then re-open the file and prove every line
    # round-trips json.loads and the file only ever grows.
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/tracelog-smoke.jsonl")
    before = path.stat().st_size if path.exists() else 0

    log = TraceLog(path, task_id="smoke")
    log.append("user", "smoke task prompt")
    log.append(
        "assistant",
        [{"type": "tool_use", "name": "read_file", "input": {"path": "PLAN.md"}}],
        tool_name="read_file",
        tool_input={"path": "PLAN.md"},
        usage={"input": 1200, "output": 45, "cache_read": 0, "cache_write": 0},
        cost_usd=0.001425,
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in lines]  # raises if any line is invalid
    assert path.stat().st_size > before, "file did not grow — truncation bug"
    print(f"ok: {len(records)} valid lines in {path} (grew from {before} bytes)")
