"""$0 self-test for the W2 D8-9 token-budget tracker — no API, no Docker.

Run: python -m agent.selftest_budget
Unit-checks BudgetTracker accumulation and ceiling semantics, then drives
_loop with a scripted fake client to prove all three exit paths at $0:
clean end_turn (0), budget ceiling (2, halts before dispatch and before the
next API call), and max_turns (2). Live-ceiling proof against the real API
is a one-off manual run (see LOG 2026-07-11).
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent.loop import BudgetTracker, _loop, turn_cost
from agent.tracelog import TraceLog

checks = 0


def ok(cond: bool, label: str):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"ok: {label}")


def mk_usage(inp=1000, out=100, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
    )


# --- BudgetTracker unit checks ---

t = BudgetTracker("claude-haiku-4-5")
c = t.add(mk_usage())
ok(abs(c - 0.0015) < 1e-12, "add returns the turn's cost (1000 in + 100 out @ $1/$5)")
ok(abs(c - turn_cost("claude-haiku-4-5", mk_usage())) < 1e-12,
   "add matches turn_cost exactly (single pricing source)")
t.add(mk_usage())
ok(abs(t.total_cost - 0.0030) < 1e-12 and t.turns == 2, "totals accumulate across turns")
ok(t.total_usage == {"input": 2000, "output": 200, "cache_read": 0, "cache_write": 0},
   "usage accumulates per key")
ok(not t.over_budget(), "no ceiling set -> never over budget")

t = BudgetTracker("claude-haiku-4-5", max_cost_usd=0.0030)
t.add(mk_usage())
ok(not t.over_budget(), "under ceiling -> not over budget")
t.add(mk_usage())
ok(t.over_budget(), "at exactly the ceiling -> over budget (>= semantics)")
t.add(mk_usage())
ok(t.over_budget(), "past the ceiling -> over budget")

t = BudgetTracker("claude-haiku-4-5", max_cost_usd=1.0)
c = t.add(mk_usage(inp=1000, out=100, cache_read=2000, cache_write=3000))
ok(abs(c - 0.00545) < 1e-12,
   "cache tokens priced at 0.1x read / 1.25x write of input price")
ok(t.total_usage["cache_read"] == 2000 and t.total_usage["cache_write"] == 3000,
   "cache tokens accumulate in usage totals")


# --- fake-client integration: all three _loop exit paths, $0 ---

class FakeBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return dict(self.__dict__)


def text_response(txt):
    return SimpleNamespace(
        content=[FakeBlock(type="text", text=txt)], stop_reason="end_turn", usage=mk_usage(),
    )


def tool_response():
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", name="read_file", input={"path": "nope.txt"}, id="tu_1")],
        stop_reason="tool_use", usage=mk_usage(),
    )


class FakeClient:
    """Yields scripted responses; repeats the last one if the loop keeps asking."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def run_fake(responses, max_turns, max_cost_usd):
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        log = TraceLog(wd / "t.jsonl", task_id="selftest-budget")
        client = FakeClient(responses)
        budget = BudgetTracker("claude-haiku-4-5", max_cost_usd=max_cost_usd)
        rc = _loop(client, log, "fake task", "claude-haiku-4-5", wd, max_turns, None, budget)
        lines = [json.loads(l) for l in (wd / "t.jsonl").read_text().splitlines()]
        return rc, client.calls, budget, lines


rc, calls, budget, lines = run_fake([text_response("done")], max_turns=5, max_cost_usd=None)
ok(rc == 0 and calls == 1, "clean end_turn under budget -> exit 0")

# each fake turn costs $0.0015; ceiling 0.002 is crossed by turn 2
rc, calls, budget, lines = run_fake([tool_response()], max_turns=50, max_cost_usd=0.002)
ok(rc == 2, "ceiling hit -> exit 2")
ok(calls == 2, "loop stops before the API call that would follow the breach")
ok(abs(budget.total_cost - 0.0030) < 1e-12,
   "overshoot bounded by one turn (in-flight turn cannot be un-spent)")
meta = [l for l in lines if l["role"] == "meta" and (l.get("content") or {}).get("budget_ceiling_hit")]
ok(len(meta) == 1 and meta[0]["content"]["turns"] == 2,
   "ceiling hit logged as a meta trajectory line with turn count")
tool_results = [l for l in lines if l["role"] == "tool"]
ok(len(tool_results) == 1,
   "halt happens before dispatch: only the pre-breach turn's tool ran")

# ceiling crossed on the same turn the model finishes -> completed work stays exit 0
rc, calls, budget, lines = run_fake([text_response("done")], max_turns=5, max_cost_usd=0.0001)
ok(rc == 0, "clean finish on the crossing turn -> still exit 0 (ceiling stops spend, not results)")

rc, calls, budget, lines = run_fake([tool_response()], max_turns=3, max_cost_usd=None)
ok(rc == 2 and calls == 3, "max_turns without end_turn -> exit 2 (unchanged contract)")

print(f"\nall {checks} budget checks passed")
