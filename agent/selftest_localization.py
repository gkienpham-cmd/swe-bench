"""$0 self-test for the W4 D22-23 localization stage — no API, no Docker.

Run: python -m agent.selftest_localization
Drives _loop with a scripted fake client to prove: the soft gate rejects
edit_file before a LOCALIZATION plan is posted (dispatch never runs), a
sentinel-bearing plan unlocks it (parse failure must not block the unlock),
the turn-K nudge force-unlocks and enters the conversation, the
--no-localization arm is byte-identical to baseline-w3 behavior, and the
frozen request prefix (SYSTEM_BLOCKS + TOOL_SCHEMAS) is untouched in BOTH
arms. Every emitted line validates against frozen schema v1 — the new
localization_* payloads ride the intentionally-open meta content object.
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from agent.loop import (
    LOCALIZATION_LOCKED_MSG,
    LOCALIZATION_NUDGE,
    LOCALIZATION_PREFIX,
    SYSTEM_BLOCKS,
    BudgetTracker,
    _loop,
    _parse_plan,
    _plan_emitted,
)
from agent.tools import TOOL_SCHEMAS
from agent.tracelog import TraceLog

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "trajectory.schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))

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


def mk_usage():
    return SimpleNamespace(
        input_tokens=1000, output_tokens=100,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )


def text_response(txt, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[FakeBlock(type="text", text=txt)], stop_reason=stop_reason, usage=mk_usage(),
    )


def tool_response(name, tool_input, tu_id="tu_1"):
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", name=name, input=tool_input, id=tu_id)],
        stop_reason="tool_use", usage=mk_usage(),
    )


class FakeClient:
    """Scripted responses; repeats the last one. Captures every create() kw
    so prefix invariance is checkable per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def run_fake(responses, task="fake task", max_turns=10, **loop_kw):
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        (wd / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        log = TraceLog(wd / "t.jsonl", task_id="selftest-localization")
        client = FakeClient(responses)
        budget = BudgetTracker("claude-haiku-4-5")
        rc = _loop(client, log, task, "claude-haiku-4-5", wd, max_turns, None, budget, **loop_kw)
        lines = [json.loads(l) for l in (wd / "t.jsonl").read_text().splitlines()]
        app_text = (wd / "app.py").read_text(encoding="utf-8")
        return rc, client, lines, app_text


def metas(lines, key):
    return [l for l in lines if l["role"] == "meta" and key in (l.get("content") or {})]


def validate_all(lines, label):
    for l in lines:
        VALIDATOR.validate(l)
    ok(True, f"schema v1: all {len(lines)} lines validate ({label})")


EDIT = {"path": "app.py", "old_str": "VALUE = 1", "new_str": "VALUE = 2"}

PLAN_TEXT = """Investigation done.

LOCALIZATION:
- candidate: lib/pkg/figure.py::__getstate__ -- evidence: dpi is restored here on unpickle
- candidate: lib/pkg/backend.py::set_dpi -- evidence: symptom manipulated here
CHOSEN: lib/pkg/figure.py::__getstate__ -- reason: symptom site beats manipulation site
"""

# --- 1. gate blocks a pre-plan edit_file; dispatch never runs ---

rc, client, lines, app_text = run_fake(
    [tool_response("edit_file", EDIT), text_response("giving up")],
    localization=True,
)
tool_lines = [l for l in lines if l["role"] == "tool"]
ok(len(tool_lines) == 1 and tool_lines[0]["tool_result_full"] == LOCALIZATION_LOCKED_MSG,
   "gated edit_file logs the rejection text as the full tool result")
ok(app_text == "VALUE = 1\n", "gated edit never dispatched: target file unchanged")
ok(len(metas(lines, "localization_gate_reject")) == 1,
   "gate rejection logged as a localization_gate_reject meta line")
ok(len(metas(lines, "scaffold_stage")) == 1
   and metas(lines, "scaffold_stage")[0]["content"]["prefix_untouched"] is True,
   "run-config meta line emitted when the stage is on")
ok(lines[0]["role"] == "user" and lines[0]["content"] == LOCALIZATION_PREFIX + "fake task",
   "index-0 user line is the WRAPPED task (what the model saw)")
validate_all(lines, "gate-reject run")

# --- 2. a valid plan unlocks the gate; edit dispatches; meta parses ---

def plan_and_edit_response(plan_text):
    """Realistic plan turn: the text block AND the first edit in one response.
    Plan detection runs before dispatch, so the same-turn edit must pass."""
    return SimpleNamespace(
        content=[FakeBlock(type="text", text=plan_text),
                 FakeBlock(type="tool_use", name="edit_file", input=EDIT, id="tu_2")],
        stop_reason="tool_use", usage=mk_usage(),
    )

rc, client, lines, app_text = run_fake(
    [tool_response("grep_glob", {"pattern": "VALUE"}),
     plan_and_edit_response(PLAN_TEXT),
     text_response("done")],
    localization=True,
)
ok(app_text == "VALUE = 2\n",
   "edit in the SAME response as the plan dispatches (detection precedes dispatch)")
plan_metas = metas(lines, "localization_plan")
ok(len(plan_metas) == 1, "plan detected exactly once (no duplicate re-logs)")
pm = plan_metas[0]["content"]
ok(pm["n_candidates"] == 2
   and pm["candidate_files"] == ["lib/pkg/figure.py", "lib/pkg/backend.py"]
   and pm["chosen"] == "lib/pkg/figure.py::__getstate__"
   and pm["parse_ok"] is True
   and pm["raw_block"] == PLAN_TEXT,
   "localization_plan meta carries parsed candidates, chosen, and the raw block verbatim")
validate_all(lines, "plan-unlock run")

# --- 3. malformed-but-sentineled plan still unlocks; parse_ok false ---

MALFORMED = "LOCALIZATION:\nit is probably the figure file\nCHOSEN:\n"
ok(_plan_emitted([FakeBlock(type="text", text=MALFORMED)]) == MALFORMED,
   "sentinel presence alone satisfies _plan_emitted (parse failure cannot block unlock)")
p = _parse_plan(MALFORMED)
ok(p["parse_ok"] is False and p["n_candidates"] == 0 and p["chosen"] is None,
   "_parse_plan degrades to parse_ok=false on an unparseable block")

rc, client, lines, app_text = run_fake(
    [plan_and_edit_response(MALFORMED),
     text_response("done")],
    localization=True,
)
ok(app_text == "VALUE = 2\n", "edit after a malformed-but-sentineled plan dispatches for real")
ok(metas(lines, "localization_plan")[0]["content"]["parse_ok"] is False,
   "malformed plan logged with parse_ok=false")
ok(len(metas(lines, "localization_gate_reject")) == 0,
   "no gate rejection once the sentinels have appeared")
validate_all(lines, "malformed-plan run")

# --- 4. turn-K nudge: fires once, enters the conversation, unlocks edits ---

rc, client, lines, app_text = run_fake(
    [tool_response("grep_glob", {"pattern": "a"}),
     tool_response("grep_glob", {"pattern": "b"}),
     tool_response("grep_glob", {"pattern": "c"}),
     tool_response("edit_file", EDIT),
     text_response("done")],
    localization=True, localization_max_turns=3,
)
fu = metas(lines, "localization_forced_unlock")
ok(len(fu) == 1 and fu[0]["content"]["turn"] == 2 and fu[0]["content"]["plan_emitted"] is False,
   "forced unlock fires exactly once, at turn K")
# the conversation the model sees must carry the nudge text block inside a
# tool_results user message (kw["messages"] is the live list — search all)
post_nudge_msgs = client.calls[-1]["messages"]
ok(any(isinstance(b, dict) and b.get("type") == "text" and b.get("text") == LOCALIZATION_NUDGE
       for m in post_nudge_msgs if m["role"] == "user" and isinstance(m["content"], list)
       for b in m["content"]),
   "nudge text block is inside a tool_results user message the model sees")
ok(app_text == "VALUE = 2\n", "edit after the forced unlock dispatches for real")
validate_all(lines, "forced-unlock run")

# --- 5. ablation-arm invariance: --no-localization is byte-identical baseline ---

rc, client, lines, app_text = run_fake(
    [tool_response("edit_file", EDIT), text_response("done")],
    localization=False,
)
ok(lines[0]["content"] == "fake task",
   "localization off: index-0 user line is the raw task, byte-equal")
ok(not any(k.startswith("localization") or k == "scaffold_stage"
           for l in lines if l["role"] == "meta" for k in (l.get("content") or {})),
   "localization off: zero localization_*/scaffold_stage meta lines")
ok(app_text == "VALUE = 2\n", "localization off: edit_file dispatches on turn 1 (no gate)")
validate_all(lines, "ablation-off run")

# --- 6. prefix invariance: frozen cached prefix untouched in BOTH arms ---

for loc in (True, False):
    _, client, _, _ = run_fake(
        [tool_response("grep_glob", {"pattern": "x"}), text_response("done")],
        localization=loc,
    )
    ok(all(kw["system"] is SYSTEM_BLOCKS and kw["tools"] is TOOL_SCHEMAS
           for kw in client.calls),
       f"every API call uses the frozen SYSTEM_BLOCKS/TOOL_SCHEMAS objects (localization={loc})")

# --- 7. template safety: problem statements with {} / {foo} / %s ---

HOSTILE = 'Traceback in config: {"key": {}} and {placeholder} and %s and {0}'
rc, client, lines, _ = run_fake([text_response("done")], task=HOSTILE, localization=True)
ok(lines[0]["content"] == LOCALIZATION_PREFIX + HOSTILE
   and lines[0]["content"].endswith(HOSTILE),
   "brace/percent-laden problem statement survives wrapping verbatim (concatenation, not format)")

print(f"\nall {checks} localization checks passed")
