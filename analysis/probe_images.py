"""Probe all dev-subset images: python versions + toolbox compat, $0 — W3 D16.

Disk reality (measured 2026-07-12): official instance images are 3.8-11.7GB
each, ~60-120GB for all 30 — they cannot coexist even on the resized 60GiB
VM. So this pass pulls each image once, records BOTH interpreter versions
(testbed env = task-era python; conda base = the toolbox interpreter per
agent/sandbox.py), runs the in-container toolbox round-trip under conda base
(production-faithful — SWB_COMPAT_PY=base), then removes the image again.

Upgrade over the original plan ("compat smoke on the oldest image only"):
every image gets the toolbox round-trip before a paid turn runs on it.

Output: <out>/image_python_versions.json — the per-instance interpreter
table that previously didn't exist anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SUBSET = Path("analysis/dev_subset_30.json")


def sh(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_python(image: str, exe: str) -> str | None:
    r = sh(["docker", "run", "--rm", image, exe, "-c",
            "import sys; print('%d.%d.%d' % sys.version_info[:3])"], timeout=120)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subset", default=str(SUBSET))
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--keep", nargs="*", default=[],
                    help="instance_ids whose images are NOT removed after probing")
    args = ap.parse_args()

    instances = json.loads(Path(args.subset).read_text())["instances"]
    out_path = Path(args.out)
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    for i, inst in enumerate(instances, 1):
        iid, image = inst["instance_id"], inst["image"]
        if iid in results and results[iid].get("compat_base") == "pass":
            print(f"[{i}/{len(instances)}] {iid}: already probed, skipping", flush=True)
            continue
        t0 = time.monotonic()
        preexisting = sh(["docker", "image", "inspect", image], timeout=60).returncode == 0
        if not preexisting:
            print(f"[{i}/{len(instances)}] {iid}: pulling {image}", flush=True)
            pull = sh(["docker", "pull", "-q", image])
            if pull.returncode != 0:
                print(f"[{i}/{len(instances)}] {iid}: PULL FAILED: {pull.stderr.strip()[:300]}", flush=True)
                results[iid] = {"image": image, "pull": "FAILED", "error": pull.stderr.strip()[:300]}
                out_path.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
                continue

        testbed = (probe_python(image, "/opt/miniconda3/envs/testbed/bin/python")
                   or probe_python(image, "/opt/conda/envs/testbed/bin/python"))
        base = (probe_python(image, "/opt/miniconda3/bin/python3")
                or probe_python(image, "/opt/conda/bin/python3"))

        env = dict(os.environ, SWB_COMPAT_IMAGE=image, SWB_COMPAT_PY="base")
        smoke = subprocess.run([sys.executable, "-m", "agent.selftest_toolbox_compat"],
                               capture_output=True, text=True, timeout=600, env=env)
        compat = "pass" if smoke.returncode == 0 else "FAIL"
        if compat == "FAIL":
            print(f"[{i}/{len(instances)}] {iid}: COMPAT FAIL\n{smoke.stdout[-500:]}\n{smoke.stderr[-500:]}", flush=True)

        results[iid] = {"image": image, "pull": "ok",
                        "python_testbed": testbed, "python_conda_base": base,
                        "compat_base": compat, "probe_wall_s": round(time.monotonic() - t0, 1)}
        out_path.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
        print(f"[{i}/{len(instances)}] {iid}: testbed={testbed} base={base} "
              f"compat={compat} ({results[iid]['probe_wall_s']}s)", flush=True)

        if not preexisting and iid not in args.keep:
            sh(["docker", "rmi", image], timeout=300)

    bad = {k: v for k, v in results.items() if v.get("pull") == "FAILED" or v.get("compat_base") == "FAIL"}
    print(f"done: {len(results)}/{len(instances)} probed, {len(bad)} problems"
          + (f": {sorted(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
