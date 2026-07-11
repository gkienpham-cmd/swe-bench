"""$0 self-test for trajectory schema v1 (W2 D12-13 freeze) — no API, no Docker.

Run: python -m agent.selftest_schema
Validates real lines (produced by driving _loop with a fake client, plus
hand-appended meta variants) against schemas/trajectory.schema.json with the
real jsonschema validator — proving both that the writer conforms and that
the schema file itself is well-formed. Negative checks prove the schema
actually rejects the failure modes it exists to prevent (a tool line missing
tool_result_full is rule 5 data loss, not a style nit).
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from agent.loop import BudgetTracker, _loop
from agent.tracelog import SCHEMA_VERSION, TraceLog

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "trajectory.schema.json"

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


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.messages = SimpleNamespace(create=lambda **kw: self._response)


schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)
ok(True, "schema file parses and is itself a valid 2020-12 schema")
ok(SCHEMA_VERSION == "1" and schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION,
   "tracelog SCHEMA_VERSION and the schema's const agree: v1")


def errors(record):
    return [e.message for e in validator.iter_errors(record)]


# --- real lines from a fake-client run (user, assistant, tool, meta) ---

with tempfile.TemporaryDirectory() as td:
    wd = Path(td)
    (wd / "big.txt").write_text("z" * 900)
    log = TraceLog(wd / "t.jsonl", task_id="selftest-schema")
    response = SimpleNamespace(
        content=[FakeBlock(type="text", text="looking"),
                 FakeBlock(type="tool_use", name="read_file", input={"path": "big.txt"}, id="tu_1")],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                              cache_read_input_tokens=250, cache_creation_input_tokens=50),
    )
    rc = _loop(FakeClient(response), log, "fake task", "claude-haiku-4-5", wd, 3, None,
               BudgetTracker("claude-haiku-4-5"), compact_at_tokens=None)
    # the meta variants _loop itself can't produce in this run
    log.append("meta", {"sandbox_image": "swb-dev", "container": "swb-abc123"})
    log.append("meta", {"final_git_diff": "diff --git a/x b/x\n+fixed\n"})
    log.append("meta", {"final_git_diff": None})
    lines = [json.loads(l) for l in (wd / "t.jsonl").read_text().splitlines()]

roles = {l["role"] for l in lines}
ok(roles == {"user", "assistant", "tool", "meta"},
   f"fake run + appended variants cover all four roles ({len(lines)} lines)")
bad = [(l["step"], l["role"], errors(l)) for l in lines if errors(l)]
ok(not bad, f"every line the writer produces validates against v1 (violations: {bad})")
ok(any(l["role"] == "meta" and (l["content"] or {}).get("max_turns_hit") for l in lines),
   "max_turns meta variant covered")
assistant = next(l for l in lines if l["role"] == "assistant")
ok(assistant["usage"]["cache_read"] == 250 and assistant["usage"]["cache_write"] == 50,
   "cache stats flow into the validated usage object")

# --- negative: the schema rejects what it exists to reject ---

tool_line = json.loads(json.dumps(next(l for l in lines if l["role"] == "tool")))
tool_line["tool_result_full"] = None
ok(errors(tool_line), "tool line with null tool_result_full REJECTED (rule 5 guarantee)")

tampered = json.loads(json.dumps(assistant))
tampered["schema_version"] = "0-draft"
ok(errors(tampered), "old 0-draft version string rejected by v1")

tampered = json.loads(json.dumps(assistant))
del tampered["reward_hack_flag"]
ok(errors(tampered), "missing reward_hack_flag key rejected (present on every line)")

tampered = json.loads(json.dumps(assistant))
tampered["usage"].pop("cache_read")
ok(errors(tampered), "usage without cache_read rejected (cache economics auditable per turn)")

tampered = json.loads(json.dumps(assistant))
tampered["extra_field"] = 1
ok(errors(tampered), "unknown extra field rejected — additions are a v2 negotiation")

print(f"\nall {checks} schema checks passed")
