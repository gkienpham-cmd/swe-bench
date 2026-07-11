"""$0 self-test for W2 D12-13 prompt caching — no API, no Docker.

Run: python -m agent.selftest_caching
Unit-checks the breakpoint invariants (one static system marker, one moving
conversation marker, never more than the API's 4-breakpoint cap), their
composition with compaction, and — via a scripted fake client — that every
request the loop actually builds carries exactly the expected cache_control
placements. The two things $0 tests cannot prove are the live smoke's job:
that the real API accepts the markers, and that cache_read_input_tokens > 0
once the cumulative prefix crosses Haiku's 4,096-token minimum.
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent.compact import compact_messages
from agent.loop import SYSTEM_BLOCKS, SYSTEM_PROMPT, BudgetTracker, _loop, _move_cache_marker
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


def mk_usage(inp=1000, out=100):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )


def markers(messages):
    """(count, location) of cache_control markers across user messages."""
    found = []
    for i, m in enumerate(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for j, b in enumerate(m["content"]):
                if isinstance(b, dict) and "cache_control" in b:
                    found.append((i, j))
    return found


def result_msg(turn, n_blocks=1, chars=100):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"tu_{turn}_{k}",
         "content": f"r{turn}.{k} " + "x" * chars, "is_error": False}
        for k in range(n_blocks)
    ]}


# --- static breakpoint: SYSTEM_BLOCKS ---

ok(isinstance(SYSTEM_BLOCKS, list) and len(SYSTEM_BLOCKS) == 1
   and SYSTEM_BLOCKS[0]["type"] == "text" and SYSTEM_BLOCKS[0]["text"] == SYSTEM_PROMPT
   and SYSTEM_BLOCKS[0]["cache_control"] == {"type": "ephemeral"},
   "SYSTEM_BLOCKS is one text block wrapping SYSTEM_PROMPT with an ephemeral marker")


# --- unit: _move_cache_marker ---

msgs = [{"role": "user", "content": "task prompt"}]
_move_cache_marker(msgs)
ok(msgs[0]["content"] == "task prompt" and markers(msgs) == [],
   "task-only transcript: string content untouched, no marker to place")

msgs = [{"role": "user", "content": "task prompt"},
        {"role": "assistant", "content": [FakeBlock(type="tool_use", name="bash",
                                                    input={"command": "ls"}, id="tu_0_0")]},
        result_msg(0)]
_move_cache_marker(msgs)
ok(markers(msgs) == [(2, 0)], "first results message: marker on its last (only) block")

msgs.append({"role": "assistant", "content": [FakeBlock(type="tool_use", name="bash",
                                                        input={"command": "ls"}, id="tu_1_0")]})
msgs.append(result_msg(1, n_blocks=3))
_move_cache_marker(msgs)
ok(markers(msgs) == [(4, 2)],
   "second turn: marker MOVED to the last block of the newest message (3-block "
   "parallel-tool result), old marker stripped — exactly one moving marker")
ok("cache_control" not in msgs[2]["content"][0],
   "previous turn's block carries no stale marker")

sys_markers = sum(1 for b in SYSTEM_BLOCKS if "cache_control" in b)
ok(sys_markers + len(markers(msgs)) == 2, "total breakpoints = 2, under the API max of 4")

_move_cache_marker(msgs)
ok(markers(msgs) == [(4, 2)], "idempotent: re-running moves nothing and adds nothing")


# --- composition with compaction ---

msgs = [{"role": "user", "content": "task prompt"}]
for t in range(6):
    msgs.append({"role": "assistant", "content": [
        FakeBlock(type="tool_use", name="read_file",
                  input={"path": f"f{t}.py"}, id=f"tu_{t}_0")]})
    msgs.append(result_msg(t, chars=2000))
_move_cache_marker(msgs)
stats = compact_messages(msgs, target_tokens=10**6, turn=6)
ok(stats["blocks_elided"] == 3, "compaction still elides all eligible old blocks")
ok(markers(msgs) == [(12, 0)],
   "moving marker survives compaction (newest message sits inside the protected window)")
ok(all("cache_control" not in msgs[2 + 2 * t]["content"][0] for t in range(3)),
   "elision stubs carry no stale cache_control")


# --- fake-client integration: what each request actually contains ---

class FakeClient:
    """Scripted responses; snapshots system= and marker placement per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.seen = []  # per call: (system kwarg, marker locations, last-user index/blocks)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        msgs = kw["messages"]
        last_user = max((i for i, m in enumerate(msgs)
                         if m.get("role") == "user" and isinstance(m.get("content"), list)),
                        default=None)
        n_blocks = len(msgs[last_user]["content"]) if last_user is not None else 0
        self.seen.append((kw["system"], markers(msgs), last_user, n_blocks))
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def tool_response():
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", name="read_file", input={"path": "big.txt"}, id="tu_1")],
        stop_reason="tool_use", usage=mk_usage(),
    )


with tempfile.TemporaryDirectory() as td:
    wd = Path(td)
    (wd / "big.txt").write_text("z" * 900)
    log = TraceLog(wd / "t.jsonl", task_id="selftest-caching")
    client = FakeClient([tool_response()])
    rc = _loop(client, log, "fake task", "claude-haiku-4-5", wd, 5, None,
               BudgetTracker("claude-haiku-4-5"), compact_at_tokens=None)
    lines = [json.loads(l) for l in (wd / "t.jsonl").read_text().splitlines()]

ok(client.calls == 5 and rc == 2, "fake run completed all turns")
ok(all(s[0] is SYSTEM_BLOCKS for s in client.seen),
   "every request passes the marked SYSTEM_BLOCKS as system=")
ok(client.seen[0][1] == [], "turn 1 request: no conversation marker yet (task string only)")
for n, (_, mk, last_user, n_blocks) in enumerate(client.seen[1:], start=2):
    assert len(mk) == 1, f"FAIL: request {n} has {len(mk)} moving markers"
    assert mk[0] == (last_user, n_blocks - 1), f"FAIL: request {n} marker not on newest last block"
ok(True, "requests 2..5: exactly one moving marker, always on the newest message's last block")
ok(all(json.dumps(l) and True for l in lines) and len(lines) > 0,
   "trajectory lines still valid JSON with caching enabled")

print(f"\nall {checks} caching checks passed")
