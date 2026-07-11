"""Collect per-run .patch files into a SWE-bench predictions JSONL.

W3 D15-16: the bridge from the agent's output convention
(results/<run-dir>/<UTCstamp>_<instance_id>.patch, newest wins — same
convention as grade_w2gate.mechanical) to the official harness input
(one JSON line per attempted instance).

Prediction field names verified from the installed swebench source
(swebench==4.1.0, harness/constants/__init__.py:66-68):
    KEY_INSTANCE_ID = "instance_id"
    KEY_MODEL       = "model_name_or_path"
    KEY_PREDICTION  = "model_patch"

Empty-diff policy (decision, 2026-07-12): instances with no .patch are
OMITTED from predictions.jsonl — the harness treats missing as
not-attempted, which is verdict-equivalent to unresolved, and an empty
patch burns a container run to learn nothing. But silence hides data
(rule 9), so a predictions_manifest.json sidecar records per-instance
status and reported denominators always use the full task list.

Run: python -m analysis.make_predictions --run-dir results/<dir> --model-name <name>
$0 — stdlib only, no API, no Docker.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# <UTC %Y-%m-%dT%H%M%S>_<instance_id>.patch — instance_id is everything
# after the first underscore following the stamp.
PATCH_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{6})_(.+)\.patch$")


def collect_patches(run_dir: Path) -> dict[str, Path]:
    """Newest .patch per instance_id (stamps sort lexicographically)."""
    newest: dict[str, tuple[str, Path]] = {}
    for p in sorted(run_dir.glob("*.patch")):
        m = PATCH_RE.match(p.name)
        if not m:
            continue
        stamp, instance_id = m.groups()
        if instance_id not in newest or stamp > newest[instance_id][0]:
            newest[instance_id] = (stamp, p)
    return {iid: path for iid, (_, path) in newest.items()}


def collect_instances_seen(run_dir: Path) -> set[str]:
    """Every instance with a trajectory in the run dir (attempted or not)."""
    seen = set()
    for p in run_dir.glob("*.jsonl"):
        m = re.match(r"^\d{4}-\d{2}-\d{2}T\d{6}_(.+)\.jsonl$", p.name)
        if m:
            seen.add(m.group(1))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--model-name", required=True,
                    help="model_name_or_path for the harness report; avoid '/'")
    ap.add_argument("--out", type=Path, default=None,
                    help="default: <run-dir>/predictions.jsonl")
    args = ap.parse_args()

    run_dir: Path = args.run_dir
    if not run_dir.is_dir():
        print(f"error: not a directory: {run_dir}")
        return 2
    out = args.out or run_dir / "predictions.jsonl"

    patches = collect_patches(run_dir)
    seen = collect_instances_seen(run_dir)

    lines = []
    manifest = {}
    for iid in sorted(seen | set(patches)):
        if iid in patches:
            diff = patches[iid].read_text()
            if diff.strip():
                lines.append({
                    "instance_id": iid,
                    "model_name_or_path": args.model_name,
                    "model_patch": diff,
                })
                manifest[iid] = {"status": "patched",
                                 "patch_file": patches[iid].name}
            else:
                manifest[iid] = {"status": "empty-diff",
                                 "patch_file": patches[iid].name}
        else:
            manifest[iid] = {"status": "no-patch"}

    with out.open("w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    manifest_path = out.with_name("predictions_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    attempted = len(lines)
    total = len(manifest)
    print(f"wrote {out} ({attempted} predictions)")
    print(f"wrote {manifest_path} ({total} instances: "
          f"{attempted} patched, {total - attempted} without a usable patch)")
    print(f"attempted/total: {attempted}/{total} — report denominators use total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
