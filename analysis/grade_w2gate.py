"""W2 D14 hand-grading + mechanical validation — $0, no API calls.

Per task in results/2026-07-11_w2-gate/:
  A. Mechanical (rule 9 evidence): every trajectory line validates against
     schema v1; per-run turns/tokens/cost/cache stats; meta events (compaction,
     caps, final_git_diff); reward_hack_flag count.
  B. Hand-grade (harness-style, NOT official): fresh sandbox, apply the agent's
     .patch (git apply --check first), then the gold test_patch, run F2P nodes
     and the P2P set. resolved = patch applies AND all F2P pass AND P2P clean.
     sympy caveat: its dataset F2P/P2P are bare function names — we run the
     gold-patched test FILE in full as the F2P+P2P proxy (documented, hand-graded).

Usage: python -m analysis.grade_w2gate
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema

from agent.sandbox import Sandbox
from agent.tools import parse_pytest_counts
from analysis.envcheck_w2gate import TASKS  # instance_id -> (pkg, f2p_nodes)

RUN_DIR = Path("results/2026-07-11_w2-gate")
SCHEMA = json.load(open("schemas/trajectory.schema.json"))
GRADE_TIMEOUT_S = 900


def mechanical(instance_id: str) -> dict:
    paths = sorted(RUN_DIR.glob(f"*_{instance_id}.jsonl"))
    if not paths:
        return {"error": "no trajectory"}
    path = paths[-1]  # newest
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    violations = 0
    for l in lines:
        try:
            jsonschema.validate(l, SCHEMA)
        except jsonschema.ValidationError:
            violations += 1
    a_lines = [l for l in lines if l["role"] == "assistant"]
    usage = {k: sum(l["usage"][k] for l in lines) for k in ("input", "output", "cache_read", "cache_write")}
    first_cache_read_turn = next(
        (i + 1 for i, l in enumerate(a_lines) if l["usage"]["cache_read"] > 0), None)
    metas = [l["content"] for l in lines if l["role"] == "meta"]
    compactions = [m for m in metas if isinstance(m, dict) and "compaction" in m]
    return {
        "trajectory": path.name,
        "lines": len(lines),
        "schema_violations": violations,
        "turns": len(a_lines),
        "cost_usd": round(sum(l["cost_usd"] for l in lines), 6),
        "usage": usage,
        "first_cache_read_turn": first_cache_read_turn,
        "compaction_events": [
            {k: m.get(k) for k in ("turn", "est_prompt_tokens", "blocks_elided", "chars_removed", "target_met")}
            for m in compactions],
        "budget_ceiling_hit": any(isinstance(m, dict) and "budget_ceiling_hit" in m for m in metas),
        "max_turns_hit": any(isinstance(m, dict) and "max_turns_hit" in m for m in metas),
        "reward_hack_flags": [l["reward_hack_flag"] for l in lines if l["reward_hack_flag"]],
        "final_git_diff_empty": not any(
            isinstance(m, dict) and m.get("final_git_diff") for m in metas),
    }


def _apply_in(sb: Sandbox, patch_text: str, label: str) -> str | None:
    """Copy a patch into the container and git-apply it. Returns error or None."""
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as f:
        f.write(patch_text)
        tmp = f.name
    subprocess.run(["docker", "cp", tmp, f"{sb.container}:/tmp/{label}.patch"],
                   check=True, capture_output=True, timeout=60)
    proc = sb._exec_raw(f"git apply --check /tmp/{label}.patch && git apply /tmp/{label}.patch", 60)
    return None if proc.returncode == 0 else proc.stderr.strip()[:500] or proc.stdout.strip()[:500]


def grade(instance_id: str) -> dict:
    row = json.load(open(RUN_DIR / "tasks" / f"{instance_id}.json"))
    _, f2p_nodes = TASKS[instance_id]
    patches = sorted(RUN_DIR.glob(f"*_{instance_id}.patch"))
    out: dict = {"patch": patches[-1].name if patches else None}
    if not patches:
        out["verdict"] = "no-patch"
        return out
    patch_text = patches[-1].read_text()

    p2p = json.loads(row["PASS_TO_PASS"])
    bare_names = p2p and "::" not in p2p[0]
    with Sandbox(f"swb-lite-{instance_id}", f"checkouts/{instance_id}") as sb:
        err = _apply_in(sb, patch_text, "agent")
        if err:
            out.update(verdict="patch-apply-failure", apply_error=err)
            return out
        err = _apply_in(sb, row["test_patch"], "gold_tests")
        if err:
            out.update(verdict="test-patch-conflict", apply_error=err)
            return out

        def run_pytest(node_ids: list[str]) -> dict:
            # argv-exec, no shell: parametrized ids contain spaces/brackets
            # (e.g. `test_xfail_raises[TypeError-TypeError-*1 failed]`) that
            # sh -c word-splits no matter the quoting.
            argv = ["docker", "exec", "-w", "/workspace", sb.container,
                    "timeout", str(GRADE_TIMEOUT_S),
                    "python3", "-m", "pytest", "-q", "--tb=line", *node_ids]
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=GRADE_TIMEOUT_S + 15)
            counts = parse_pytest_counts(proc.stdout)
            return {"exit": proc.returncode, "counts": counts,
                    "tail": proc.stdout.strip().splitlines()[-3:]}

        if bare_names:
            # sympy: bare names -> run the gold-patched test file(s) in full
            files = sorted({l.split(" b/")[-1] for l in row["test_patch"].splitlines()
                            if l.startswith("diff --git")})
            out["p2p_mode"] = f"whole-file proxy ({', '.join(files)})"
            res = run_pytest(files)
            out["f2p"] = out["p2p"] = res
            ok = res["exit"] == 0
        else:
            # Dataset quirk: parametrized ids containing spaces were split when
            # SWE-bench built the P2P list (e.g. `test_xfail_raises[...-*1` is
            # missing ` failed]`). Repair by prefix-matching against the ids
            # pytest actually collects; unmatched fragments are dropped on record.
            malformed = [n for n in p2p if "[" in n and not n.endswith("]")]
            if malformed:
                files = sorted({n.split("::")[0] for n in p2p})
                proc = subprocess.run(
                    ["docker", "exec", "-w", "/workspace", sb.container,
                     "python3", "-m", "pytest", "--collect-only", "-q", *files],
                    capture_output=True, text=True, timeout=GRADE_TIMEOUT_S)
                collected = set(proc.stdout.splitlines())
                repaired, dropped = [], []
                for n in p2p:
                    if n in malformed:
                        hits = [c for c in collected if c.startswith(n)]
                        (repaired.append(hits[0]) if len(hits) == 1 else dropped.append(n))
                    else:
                        repaired.append(n)
                out["p2p_repaired"] = len(malformed) - len(dropped)
                out["p2p_dropped"] = dropped
                p2p = repaired
            out["f2p"] = run_pytest(f2p_nodes)
            out["p2p"] = run_pytest(p2p) if p2p else {"exit": 0, "counts": None, "tail": ["(no P2P)"]}
            out["p2p_mode"] = f"{len(p2p)} node ids"
            ok = out["f2p"]["exit"] == 0 and out["p2p"]["exit"] == 0
    out["verdict"] = "resolved(hand-checked)" if ok else "not-resolved"
    return out


def main() -> None:
    ids = sys.argv[1:] or list(TASKS)
    report = {}
    for iid in ids:
        print(f"=== {iid} ===", flush=True)
        r = {"mechanical": mechanical(iid)}
        r["grade"] = grade(iid)
        report[iid] = r
        print(json.dumps(r, indent=1), flush=True)
    with open(RUN_DIR / "grading_report.json", "w") as f:
        json.dump(report, f, indent=1)
    print(f"\nwritten: {RUN_DIR}/grading_report.json")


if __name__ == "__main__":
    main()
