"""Sequential runner: agent/loop.py over the frozen dev subset — W3 D16.

Dumb and observable by design: one task at a time, sorted by instance_id,
no parallelism, no retries — a failed task is a finding, not something to
paper over. Sequential back-to-back runs also keep the shared prompt prefix
inside the 5-min cache TTL, which is exactly the cross-run cache reuse the
first Sonnet smoke must verify (LOG.md 2026-07-12).

Resumable: a task with an existing trajectory (*_<instance_id>.jsonl in
--out-dir) is skipped, so an interrupted run continues where it stopped.

Inputs: full per-task JSONs (incl. problem_statement) as emitted by
`freeze_dev_subset.py --emit-tasks DIR`, plus the committed subset JSON for
image names. The problem statement is passed to loop.py as a single argv
element — statements run to 24.7k chars, so it never goes through a shell
string.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SUBSET = Path("analysis/dev_subset_30.json")


def main() -> int:
    # Line-buffer both streams: under nohup/pipe redirection stdout is
    # block-buffered, so progress prints lagged the run by minutes and the
    # manifest was the only live signal (D16 finding, LOG 2026-07-12).
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks-dir", required=True, help="dir of <instance_id>.json full task rows")
    ap.add_argument("--out-dir", required=True, help="run directory (trajectories, patches, console logs)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--only", nargs="*", default=None, help="restrict to these instance_ids")
    ap.add_argument("--subset", default=str(SUBSET), help="committed subset JSON (for image names)")
    # Official instance images are 3.8-11.7GB each (measured 2026-07-12) and
    # cannot all coexist on the 60GiB VM — pull per task, remove after.
    ap.add_argument("--pull", action="store_true", help="docker pull the image before each task if absent")
    ap.add_argument("--rm-after", action="store_true",
                    help="docker rmi the image after each task (only if this run pulled it)")
    ap.add_argument("--max-turns", type=int, default=None,
                    help="forwarded to agent.loop (plumbing tests only; eval runs use the default cap)")
    # W4 localization stage / W5 ablation A. Always forwarded EXPLICITLY to
    # agent.loop — an eval arm must never depend on a silent loop.py default.
    ap.add_argument("--localization", action=argparse.BooleanOptionalAction, default=True,
                    help="two-phase LOCALIZE/FIX directive + edit_file soft gate; "
                    "--no-localization is the ablation-A / baseline-w3 arm")
    ap.add_argument("--localization-max-turns", type=int, default=None,
                    help="forwarded to agent.loop when set (default: loop.py's 12)")
    args = ap.parse_args()

    subset = json.loads(Path(args.subset).read_text())
    images = {i["instance_id"]: i["image"] for i in subset["instances"]}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    task_files = sorted(Path(args.tasks_dir).glob("*.json"))
    if args.only:
        want = set(args.only)
        task_files = [p for p in task_files if p.stem in want]
        missing = want - {p.stem for p in task_files}
        if missing:
            print(f"ERROR: --only ids not found in --tasks-dir: {sorted(missing)}", file=sys.stderr)
            return 1

    manifest_path = out / "runs_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    done_before = {m["instance_id"] for m in manifest}

    for i, tf in enumerate(task_files, 1):
        iid = tf.stem
        if list(out.glob(f"*_{iid}.jsonl")):
            print(f"[{i}/{len(task_files)}] {iid}: trajectory exists, skipping")
            continue
        if iid not in images:
            print(f"[{i}/{len(task_files)}] {iid}: not in subset JSON, skipping", file=sys.stderr)
            continue
        row = json.loads(tf.read_text())
        pulled_here = False
        if args.pull:
            have = subprocess.run(["docker", "image", "inspect", images[iid]],
                                  capture_output=True).returncode == 0
            if not have:
                print(f"[{i}/{len(task_files)}] {iid}: pulling {images[iid]}")
                pull = subprocess.run(["docker", "pull", "-q", images[iid]],
                                      capture_output=True, text=True)
                if pull.returncode != 0:
                    print(f"[{i}/{len(task_files)}] {iid}: PULL FAILED, recording and continuing: "
                          f"{pull.stderr.strip()[:300]}", file=sys.stderr)
                    manifest = [m for m in manifest if m["instance_id"] != iid]
                    manifest.append({"instance_id": iid, "exit_code": None,
                                     "error": "pull-failed", "model": args.model})
                    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
                    continue
                pulled_here = True
        argv = [
            sys.executable, "-m", "agent.loop",
            "--task", row["problem_statement"],
            "--model", args.model,
            "--out-dir", str(out),
            "--task-id", iid,
            "--sandbox-image", images[iid],
            "--sandbox-workdir", "/testbed",
            "--sandbox-preloaded",
        ]
        if args.max_turns is not None:
            argv += ["--max-turns", str(args.max_turns)]
        argv += ["--localization" if args.localization else "--no-localization"]
        if args.localization_max_turns is not None:
            argv += ["--localization-max-turns", str(args.localization_max_turns)]
        print(f"[{i}/{len(task_files)}] {iid}: starting ({images[iid]})")
        t0 = time.monotonic()
        with open(out / f"console_{iid}.log", "w") as log:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                log.write(line)
                log.flush()
                sys.stdout.write(line)
            rc = proc.wait()
        wall = round(time.monotonic() - t0, 1)
        print(f"[{i}/{len(task_files)}] {iid}: exit {rc} in {wall}s")
        manifest = [m for m in manifest if m["instance_id"] != iid]
        # localization recorded here AND in the trajectory's run-config meta
        # line — the W5 ablation arm must be identifiable from two
        # independent places.
        manifest.append({"instance_id": iid, "exit_code": rc, "wall_s": wall,
                         "model": args.model, "localization": args.localization})
        manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
        if args.rm_after and pulled_here:
            subprocess.run(["docker", "rmi", images[iid]], capture_output=True)

    ran = {m["instance_id"] for m in manifest} - done_before
    print(f"done: {len(ran)} ran this invocation, manifest at {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
