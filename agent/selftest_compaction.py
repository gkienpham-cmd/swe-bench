"""$0 self-test for W2 D10-11 compaction + cap parity — no API, no Docker.

Run: python -m agent.selftest_compaction
Unit-checks compact_messages invariants on hand-built conversations (dict
tool_result blocks + FakeBlock assistant blocks, mirroring what _loop
actually holds), then drives _loop with a scripted fake client to prove the
trigger fires, the shrunken transcript is what the next API call sees, and
the max_turns exit writes its meta line. The one thing $0 tests cannot
prove — that the real API accepts a compacted message list — is the live
smoke's job.
"""

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from agent.compact import (
    MIN_ELIDE_CHARS, PROTECT_LAST_TURNS, compact_messages, estimate_tokens, prompt_tokens,
)
from agent.loop import BudgetTracker, _loop
from agent.tracelog import TraceLog

checks = 0


def ok(cond: bool, label: str):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"ok: {label}")


class FakeBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return dict(self.__dict__)


def mk_usage(inp=1000, out=100, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
    )


def convo(num_turns=6, result_chars=2000, tool="read_file"):
    """num_turns assistant turns, each followed by one tool_result user msg.
    With PROTECT_LAST_TURNS=3, turns 0..num_turns-4 are eligible."""
    msgs = [{"role": "user", "content": "task prompt"}]
    for t in range(num_turns):
        msgs.append({"role": "assistant", "content": [
            FakeBlock(type="tool_use", name=tool,
                      input={"path": f"f{t}.py", "start_line": 1, "end_line": 50}, id=f"tu_{t}"),
        ]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tu_{t}",
             "content": f"content-{t} " + "x" * result_chars, "is_error": False},
        ]})
    return msgs


def snapshot(msgs):
    """Serializable copy for byte-identical comparisons."""
    out = []
    for m in msgs:
        c = m["content"]
        if isinstance(c, list):
            c = [b.model_dump() if isinstance(b, FakeBlock) else deepcopy(b) for b in c]
        out.append({"role": m["role"], "content": c})
    return json.dumps(out, default=str)


# --- helpers under test ---

ok(prompt_tokens(mk_usage(inp=1000, cache_read=200, cache_write=300)) == 1500,
   "prompt_tokens sums fresh + cache_read + cache_write")
ok(estimate_tokens(1000) == 250, "estimate_tokens is chars//4")


# --- unit: invariants on hand-built conversations ---

msgs = convo()
before = snapshot(msgs)
stats = compact_messages(msgs, target_tokens=0, turn=9)
ok(snapshot(msgs) == before and stats["blocks_elided"] == 0 and stats["target_met"],
   "target 0 -> no-op, byte-identical messages, target trivially met")

msgs = convo()
stats = compact_messages(msgs, target_tokens=400, turn=9)
ok(stats["blocks_elided"] == 1 and stats["elided_tool_use_ids"] == ["tu_0"],
   "oldest eligible block elided first, stops once target reached")
ok("content-1" in msgs[4]["content"][0]["content"],
   "younger eligible block untouched when target already met")

msgs = convo()
stats = compact_messages(msgs, target_tokens=10**6, turn=9)
ok(stats["blocks_elided"] == 3 and not stats["target_met"],
   "unreachable target -> all eligible elided, target_met False (un-elidable floor)")
ok(msgs[0]["content"] == "task prompt", "first user message (the task) never touched")
for t in (3, 4, 5):
    assert f"content-{t}" in msgs[2 + 2 * t]["content"][0]["content"]
ok(True, f"last PROTECT_LAST_TURNS={PROTECT_LAST_TURNS} turns' results never elided")
ok(all(isinstance(m["content"][0], FakeBlock) and m["content"][0].type == "tool_use"
       and m["content"][0].input["path"] == f"f{t}.py"
       for t, m in enumerate(msgs[1::2])),
   "assistant messages (hypotheses + tool_use inputs) never touched")
ok(all(msgs[2 + 2 * t]["content"][0]["tool_use_id"] == f"tu_{t}" for t in range(6))
   and len(msgs) == 13 and all(len(m["content"]) == 1 for m in msgs[1:]),
   "pairing invariant: message count, block counts, and tool_use_id links unchanged")
stub = msgs[2]["content"][0]["content"]
ok("elided at turn 9" in stub and "read_file" in stub and "f0.py:1-50" in stub
   and "2,010 chars" in stub,
   "stub names the turn, tool, target, and original size")
ok(stats["chars_removed"] == sum(2010 - len(msgs[2 + 2 * t]["content"][0]["content"])
                                 for t in range(3))
   and stats["est_tokens_removed"] == stats["chars_removed"] // 4,
   "stats arithmetic: chars_removed exact, est_tokens = chars//4")
again = compact_messages(msgs, target_tokens=10**6, turn=10)
ok(again["blocks_elided"] == 0, "idempotent: stubs fall under MIN_ELIDE_CHARS, second pass no-op")

msgs = convo(result_chars=MIN_ELIDE_CHARS - 60)  # content stays under the floor
before = snapshot(msgs)
stats = compact_messages(msgs, target_tokens=10**6, turn=9)
ok(snapshot(msgs) == before and stats["blocks_elided"] == 0,
   "blocks under MIN_ELIDE_CHARS never elided, however old")

header = "[tests: 1 passed, 2 failed, 0 errors | exit 1]"
msgs = convo(tool="run_tests")
msgs[2]["content"][0]["content"] = header + "\n" + "traceback line\n" * 200
stats = compact_messages(msgs, target_tokens=10**6, turn=9)
kept = msgs[2]["content"][0]["content"]
ok(kept.startswith(header) and "elided at turn 9" in kept and len(kept) < 200,
   "run_tests result keeps its parsed summary header, tail elided — never fully gone")
msgs = convo(tool="run_tests")
msgs[2]["content"][0]["content"] = header + "\nshort tail"
msgs[2]["content"][0]["content"] += " " * (MIN_ELIDE_CHARS - len(msgs[2]["content"][0]["content"]) + 1)
whole = msgs[2]["content"][0]["content"]
compact_messages(msgs, target_tokens=10**6, turn=9)
ok(msgs[2]["content"][0]["content"] == whole,
   "run_tests with a short tail left verbatim (tail under the floor)")

msgs = convo()
msgs[2]["content"][0]["content"] = [{"type": "text", "text": "y" * 5000}]
stats = compact_messages(msgs, target_tokens=10**6, turn=9)
ok(isinstance(msgs[2]["content"][0]["content"], list) and stats["blocks_elided"] == 2,
   "non-str tool_result content skipped without crashing")

msgs = convo()
msgs[2]["content"][0]["is_error"] = True
compact_messages(msgs, target_tokens=10**6, turn=9)
ok(msgs[2]["content"][0]["is_error"] is True
   and "(was an error)" in msgs[2]["content"][0]["content"],
   "is_error preserved on the block and named in the stub")

msgs = convo(num_turns=PROTECT_LAST_TURNS)
before = snapshot(msgs)
stats = compact_messages(msgs, target_tokens=10**6, turn=9)
ok(snapshot(msgs) == before and stats["blocks_elided"] == 0,
   "conversation shorter than the protected window -> nothing eligible")


# --- fake-client integration: trigger + transcript shrink + max_turns parity ---

class FakeClient:
    """Scripted responses; snapshots what each API call actually saw."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.seen = []  # per call: (total tool_result chars, any-stub-present)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        chars, stubbed = 0, False
        for m in kw["messages"]:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("content"), str):
                        chars += len(b["content"])
                        stubbed = stubbed or "[elided at turn" in b["content"]
        self.seen.append((chars, stubbed))
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def run_fake(responses, max_turns, compact_at_tokens, big_chars=8000):
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        (wd / "big.txt").write_text("z" * big_chars)
        log = TraceLog(wd / "t.jsonl", task_id="selftest-compaction")
        client = FakeClient(responses)
        budget = BudgetTracker("claude-haiku-4-5")
        rc = _loop(client, log, "fake task", "claude-haiku-4-5", wd, max_turns, None, budget,
                   compact_at_tokens=compact_at_tokens)
        lines = [json.loads(l) for l in (wd / "t.jsonl").read_text().splitlines()]
        return rc, client, lines


def tool_response():
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", name="read_file", input={"path": "big.txt"}, id="tu_1")],
        stop_reason="tool_use", usage=mk_usage(inp=30_000),
    )


rc, client, lines = run_fake([tool_response()], max_turns=6, compact_at_tokens=5_000)
comp = [l for l in lines if l["role"] == "meta" and (l.get("content") or {}).get("compaction")]
ok(len(comp) >= 1, "over-threshold run -> compaction meta line(s) emitted")
c0 = next(c["content"] for c in comp if c["content"]["blocks_elided"] > 0)
ok(all(k in c0 for k in ("turn", "est_prompt_tokens", "threshold", "low_water",
                         "blocks_elided", "chars_removed", "est_tokens_removed",
                         "target_met", "elided_tool_use_ids"))
   and c0["threshold"] == 5_000 and c0["low_water"] == 2_500,
   "compaction meta line carries every field the post-hoc analysis joins on")
# Steady state: each turn adds one fresh 8k result and elides one old, so
# compare the last call against its UNCOMPACTED counterfactual, not the peak.
uncompacted = (client.calls - 1) * 8000
ok(client.seen[-1][0] < uncompacted - 8000 and client.seen[-1][1],
   "the last API call saw a transcript well under the uncompacted size, "
   "with elision stubs present (compaction ran before the call)")
tool_lines = [l for l in lines if l["role"] == "tool"]
ok(all(len(l["tool_result_full"]) >= 8000 for l in tool_lines),
   "trajectory keeps the FULL result on every tool line even after elision (rule 5)")

rc, client, lines = run_fake([tool_response()], max_turns=4, compact_at_tokens=10**9)
ok(not any((l.get("content") or {}).get("compaction") for l in lines if l["role"] == "meta"),
   "below-threshold run -> zero compaction meta lines")
mt = [l for l in lines if l["role"] == "meta" and (l.get("content") or {}).get("max_turns_hit")]
ok(rc == 2 and len(mt) == 1 and mt[0]["content"]["max_turns"] == 4,
   "max_turns exit logs its meta line (parity with the cost-ceiling exit)")

print(f"\nall {checks} compaction checks passed")
