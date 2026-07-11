"""Fetch SWE-bench Lite (test split, 300 rows) via the HF datasets-server JSON API.

Stdlib only (urllib) — no `datasets`/`huggingface_hub` dep; this is a one-shot
metadata pull for hand-run task selection (W2 D14), not harness integration (W3).

Usage: python -m analysis.fetch_lite [out.json]
Writes the full row list (instance_id, repo, base_commit, problem_statement,
FAIL_TO_PASS, PASS_TO_PASS, version, ...) as one JSON array.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://datasets-server.huggingface.co/rows"
DATASET = "princeton-nlp/SWE-bench_Lite"
PAGE = 100  # server max rows per request


def fetch_split(split: str = "test") -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode(
            {"dataset": DATASET, "config": "default", "split": split,
             "offset": offset, "length": PAGE}
        )
        with urllib.request.urlopen(f"{API}?{q}", timeout=60) as resp:
            payload = json.load(resp)
        batch = [r["row"] for r in payload["rows"]]
        rows.extend(batch)
        total = payload["num_rows_total"]
        offset += len(batch)
        print(f"fetched {offset}/{total}", file=sys.stderr)
        if offset >= total or not batch:
            return rows
        time.sleep(1)  # be polite; 3 requests total for 300 rows


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "results/2026-07-11_w2-gate/lite_instances.json"
    rows = fetch_split()
    with open(out, "w") as f:
        json.dump(rows, f, indent=1)
    print(f"{len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
