"""W2 D14 env sanity gate — $0, no API calls.

Per task, in a scratch Sandbox (the REAL production path: docker cp overlay of the
host checkout, then git_diff()):
  1. `git status --porcelain` empty  → no egg-info/artifact pollution in future patches
  2. Sandbox.git_diff() == ""        → extraction path clean incl. encoding-attr files
  3. package imports
  4. gold test_patch applied, F2P runs and FAILS → env actually reproduces the bug
The agent's paid runs use a fresh sandbox WITHOUT test_patch — the agent never sees
gold tests; this scratch container is destroyed after the check.

Usage: python -m analysis.envcheck_w2gate [instance_id ...]
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from agent.sandbox import Sandbox

RUN_DIR = Path("results/2026-07-11_w2-gate")

# instance_id -> (import name, [resolved F2P pytest node ids])
TASKS = {
    "pallets__flask-4045": ("flask", [
        "tests/test_blueprints.py::test_dotted_name_not_allowed",
        "tests/test_blueprints.py::test_route_decorator_custom_endpoint_with_dots",
    ]),
    "pytest-dev__pytest-8906": ("pytest", [
        "testing/test_skipping.py::test_module_level_skip_error",
    ]),
    "sphinx-doc__sphinx-11445": ("sphinx", [
        "tests/test_util_rst.py::test_prepend_prolog_with_roles_in_sections_with_newline",
        "tests/test_util_rst.py::test_prepend_prolog_with_roles_in_sections_without_newline",
    ]),
    # dataset F2P is the bare name `test_issue_24062`; file resolved from test_patch
    "sympy__sympy-24066": ("sympy", [
        "sympy/physics/units/tests/test_quantities.py::test_issue_24062",
    ]),
    "pylint-dev__pylint-7080": ("pylint", [
        "tests/test_self.py::TestRunTC::test_ignore_path_recursive_current_dir",
    ]),
}


def check(instance_id: str) -> bool:
    pkg, f2p_nodes = TASKS[instance_id]
    row = json.load(open(RUN_DIR / "tasks" / f"{instance_id}.json"))
    ok = True
    with Sandbox(f"swb-lite-{instance_id}", f"checkouts/{instance_id}") as sb:
        out = sb._exec_raw("git status --porcelain", 60).stdout
        if out.strip():
            print(f"  FAIL dirty tree after overlay:\n{out[:400]}")
            ok = False
        diff = sb.git_diff()
        if diff != "":
            print(f"  FAIL git_diff not empty: {repr(diff)[:200]}")
            ok = False
        content, is_err = sb.bash(f"python3 -c 'import {pkg}; print({pkg}.__name__)'")
        if is_err:
            print(f"  FAIL import {pkg}: {content[:300]}")
            ok = False
        # apply gold test_patch, F2P must fail pre-fix
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as f:
            f.write(row["test_patch"])
            tmp = f.name
        subprocess.run(["docker", "cp", tmp, f"{sb.container}:/tmp/test.patch"],
                       check=True, capture_output=True, timeout=60)
        content, is_err = sb.bash("git apply /tmp/test.patch && echo APPLIED")
        if "APPLIED" not in content:
            print(f"  FAIL test_patch apply: {content[:300]}")
            ok = False
        else:
            for node in f2p_nodes:
                content, _ = sb.run_tests(node)
                header = content.splitlines()[0] if content else ""
                failed = ("0 failed" not in header and "failed" in header) or "exit 0" not in header
                print(f"  {'ok  ' if failed else 'FAIL(passed pre-fix!)'} F2P {node}: {header}")
                ok = ok and failed
    return ok


def main() -> None:
    ids = sys.argv[1:] or list(TASKS)
    results = {}
    for iid in ids:
        print(f"=== {iid} ===")
        results[iid] = check(iid)
    print("\n" + "\n".join(f"{'PASS' if v else 'FAIL'} {k}" for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
