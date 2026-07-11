"""$0 self-test: the container-side toolbox stays runnable on old Pythons.

W3 D15-16. The toolbox (tools.py + toolbox.py) executes under whatever
interpreter lives in the task image — official SWE-bench images go back
to Python 3.6-3.8 eras. The W2 gate already proved one silent-portability
kill (PEP 604 unions at def time on py3.9, fixed with the future import);
this session found a second (`Path.is_relative_to`, py3.9+, called at
RUNTIME in _resolve — annotations don't shield it). This test makes both
classes a permanent regression check:

1. ast.parse(feature_version=(3, 7)) on both files — catches 3.8+ SYNTAX
   (walrus, positional-only params) forever.
2. Regex denylist of syntax-invisible RUNTIME constructs added in 3.8+
   stdlib — a denylist can't enumerate every future addition (named
   failure mode); check 3 is the backstop.
3. If Docker is up and an official sweb.eval image exists locally:
   a full JSON round-trip (read_file/edit_file/grep_glob) through
   toolbox.py inside that image, under the image's own interpreters
   (conda testbed env if present, else python3). Skips (exit 0, loud)
   when Docker or the image is absent, so the suite stays $0/CI-safe.

Run: python -m agent.selftest_toolbox_compat
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
TOOLBOX_FILES = [AGENT_DIR / "tools.py", AGENT_DIR / "toolbox.py"]

checks = 0


def ok(cond: bool, label: str):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"ok: {label}")


# --- 1. syntax floor: parses as Python 3.7 ---

for f in TOOLBOX_FILES:
    src = f.read_text()
    try:
        ast.parse(src, filename=str(f), feature_version=(3, 7))
        ok(True, f"{f.name} parses with feature_version=(3,7)")
    except SyntaxError as e:
        ok(False, f"{f.name} uses 3.8+ syntax: {e}")

# --- 2. denylist: runtime constructs invisible to the syntax check ---
# Each entry: (regex on source, why it breaks). Extend when a new one is
# observed; the in-container smoke below is the catch-all for the rest.

DENYLIST = [
    (r"\.is_relative_to\(", "Path.is_relative_to is py3.9+ (runtime)"),
    (r"\.removeprefix\(", "str.removeprefix is py3.9+"),
    (r"\.removesuffix\(", "str.removesuffix is py3.9+"),
    (r"functools\.cache\b", "functools.cache is py3.9+ (use lru_cache)"),
    (r"\bzoneinfo\b", "zoneinfo is py3.9+"),
    (r"math\.(lcm|nextafter|ulp)\b", "py3.9+ math additions"),
    (r"^\s*match\s+\w.*:\s*$", "match statement is py3.10+"),
]

for f in TOOLBOX_FILES:
    src = f.read_text()
    for pattern, why in DENYLIST:
        hits = [
            i + 1
            for i, line in enumerate(src.splitlines())
            if re.search(pattern, line) and not line.lstrip().startswith("#")
        ]
        ok(not hits, f"{f.name}: no `{pattern}` ({why}); lines={hits or '-'}")

# --- 3. in-container round-trip on an official image (skip-not-fail) ---


def _run(cmd: list[str], timeout: int = 60, input_: str | None = None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, input=input_)


def container_smoke() -> None:
    probe = _run(["docker", "info"], timeout=15)
    if probe.returncode != 0:
        print("skip: Docker not available — in-container smoke not run")
        return
    imgs = _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    candidates = [l for l in imgs.stdout.splitlines() if "sweb.eval" in l]
    if not candidates:
        print("skip: no official sweb.eval image present locally — "
              "in-container smoke not run (pull/build one via the harness)")
        return
    image = sorted(candidates)[0]
    name = f"swb-compat-{uuid.uuid4().hex[:8]}"
    try:
        r = _run(["docker", "run", "-d", "--network", "none", "--name", name,
                  image, "sleep", "300"])
        ok(r.returncode == 0, f"compat container started on {image}")
        _run(["docker", "exec", name, "mkdir", "-p", "/opt/toolbox"])
        for f in TOOLBOX_FILES:
            _run(["docker", "cp", str(f), f"{name}:/opt/toolbox/{f.name}"])
        # Prefer the testbed env python (the era interpreter — the hostile
        # one); fall back to python3 on PATH.
        pick = _run(["docker", "exec", name, "sh", "-c",
                     "for p in /opt/miniconda3/envs/testbed/bin/python "
                     "/opt/conda/envs/testbed/bin/python python3; do "
                     "command -v $p >/dev/null 2>&1 && { echo $p; break; }; done"])
        py = pick.stdout.strip() or "python3"
        ver = _run(["docker", "exec", name, py, "-c",
                    "import sys; print('%d.%d' % sys.version_info[:2])"])
        print(f"info: toolbox smoke under {py} (Python {ver.stdout.strip()}) in {image}")

        def toolbox(req: dict) -> dict:
            r = _run(["docker", "exec", "-i", "-e", "TOOLBOX_WORKSPACE=/testbed",
                      name, py, "/opt/toolbox/toolbox.py"],
                     input_=json.dumps(req))
            assert r.returncode == 0, f"toolbox exited {r.returncode}: {r.stderr[:500]}"
            return json.loads(r.stdout)

        out = toolbox({"name": "read_file", "input": {"path": "setup.py", "start_line": 1, "end_line": 5}})
        ok(not out.get("is_error") or "setup.py" in out.get("content", ""),
           "read_file round-trips in-container (no interpreter crash)")
        out = toolbox({"name": "grep_glob", "input": {"pattern": "def ", "glob": "*.py"}})
        ok("is_error" in out and "content" in out,
           "grep_glob returns well-formed JSON in-container")
        marker = f"compat-{uuid.uuid4().hex[:8]}"
        _run(["docker", "exec", name, "sh", "-c",
              f"printf 'alpha\\nbeta\\n' > /testbed/{marker}.txt"])
        out = toolbox({"name": "edit_file", "input": {
            "path": f"{marker}.txt", "old_str": "beta", "new_str": "gamma"}})
        ok(not out.get("is_error"), "edit_file round-trips in-container")
    finally:
        _run(["docker", "rm", "-f", name])


container_smoke()

print(f"\nselftest_toolbox_compat: {checks} checks passed")
