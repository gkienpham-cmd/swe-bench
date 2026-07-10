"""W2 D8-9 Step-0 measurement: quantify whole-file reads vs windowed reads
on a real Lite-scale repo BEFORE changing the tools (rule 1).

Usage: python -m analysis.measure_truncation <repo_root> [file ...]

Token estimates are chars/4 (+/-20% — good enough to size a cap, not to
bill). Numbers go to stdout for LOG.md; nothing is written anywhere.
"""

import sys
from pathlib import Path

from agent.tools import MAX_READ_CHARS, MAX_GLOB_FILES, SKIP_DIRS, read_file, grep_glob

WINDOW_LINES = 250          # candidate MAX_READ_LINES under evaluation
TURNS = 10                  # compounding view: a result is re-billed as input
READ_AT_TURN = 2            # on every turn after the one that produced it

DEFAULT_FILES = [
    "django/db/models/query.py",
    "django/db/models/base.py",
    "django/forms/models.py",
    "django/contrib/admin/options.py",
]


def est_tokens(chars: int) -> int:
    return chars // 4


def measure_file(root: Path, rel: str) -> None:
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    total_lines, total_chars = len(lines), len(text)
    capped_chars = min(total_chars, MAX_READ_CHARS)
    window_chars = len("".join(lines[:WINDOW_LINES]))

    whole, capped, window = (est_tokens(c) for c in (total_chars, capped_chars, window_chars))
    rebill = TURNS - READ_AT_TURN  # times the result is re-sent as input, no caching
    print(f"\n{rel}")
    print(f"  {total_lines} lines, {total_chars} chars")
    print(f"  est tokens/read: whole-file {whole} | current 50k cap {capped} | {WINDOW_LINES}-line window {window}")
    print(f"  cap/window ratio: {capped / window:.1f}x")
    print(f"  compounding (read at turn {READ_AT_TURN} of {TURNS}, re-billed x{rebill}): "
          f"cap {capped * rebill} tok vs window {window * rebill} tok")

    # Sanity: what the CURRENT tool actually returns for a no-range read.
    out, is_err = read_file(root, rel)
    print(f"  current read_file(no range): {len(out)} chars returned, is_error={is_err}, "
          f"truncation marker={'yes' if '[truncated' in out else 'no'}")


def measure_glob(root: Path) -> None:
    files = [
        p for p in sorted(root.rglob("*.py"))
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    ]
    out, _ = grep_glob(root, glob="**/*.py")
    dirs = {}
    for p in files:
        parts = p.relative_to(root).parts
        key = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")
        dirs[key] = dirs.get(key, 0) + 1
    summary_rows = sorted(dirs.items(), key=lambda kv: -kv[1])[:25]
    summary_chars = sum(len(f"{k} {v}") + 1 for k, v in summary_rows) + 120  # + header/footer
    print(f"\nglob **/*.py: {len(files)} candidate files across {len(dirs)} dir groups")
    print(f"  current output (first-{MAX_GLOB_FILES} list): {len(out)} chars "
          f"(~{est_tokens(len(out))} tok), shows {min(len(files), MAX_GLOB_FILES)}/{len(files)} files, alphabetical")
    print(f"  proposed summary (25 count rows): ~{summary_chars} chars (~{est_tokens(summary_chars)} tok), covers all {len(files)}")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python -m analysis.measure_truncation <repo_root> [file ...]")
    root = Path(sys.argv[1]).resolve()
    rels = sys.argv[2:] or DEFAULT_FILES
    print(f"repo: {root}  (token est = chars/4, +/-20%)")
    for rel in rels:
        measure_file(root, rel)
    measure_glob(root)


if __name__ == "__main__":
    main()
