"""Tool schemas and dispatch for the agent loop.

D3-4: read_file (line ranges), edit_file (match-exactly-once), bash
(stateless subprocess.run), grep_glob (pure Python, bounded output) are
live. run_tests stays a loud not-implemented stub until Docker lands
(D5-6), when bash/run_tests reroute through docker exec.

Every tool bounds its output: unbounded dumps into context are the W2
binding constraint, so the caps land with the tools, not after.
"""

import re
import subprocess
from pathlib import Path

# Truncation guard: never dump unbounded content into context.
# Real windowing strategy is W2 (D8-9) scope.
MAX_READ_CHARS = 50_000
MAX_BASH_CHARS = 10_000       # per stream (stdout, stderr)
BASH_TIMEOUT_S = 30
MAX_GREP_MATCHES = 100
MAX_GLOB_FILES = 50
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".tox", ".eggs"}

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the repository, optionally restricted to a line range. "
            "Output starts with a header line stating the range and total line count. "
            "Paths are relative to the repository root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
                "start_line": {"type": "integer", "description": "First line to read, 1-indexed inclusive. Omit to read from the start."},
                "end_line": {"type": "integer", "description": "Last line to read, 1-indexed inclusive. Omit to read to the end."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace an exact string in a file with a new string. old_str must "
            "appear exactly once in the file — if it matches zero or multiple "
            "times the edit is rejected and nothing is written. Include enough "
            "surrounding context to make the match unique."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
                "old_str": {"type": "string", "description": "Exact text to replace; must match exactly once."},
                "new_str": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command in the repository root. Stateless: each command "
            "runs in a fresh process, so cd, exports, and shell state do not "
            f"persist between calls. Times out after {BASH_TIMEOUT_S}s. Returns "
            "exit code, stdout, and stderr (each truncated if long)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "grep_glob",
        "description": (
            "Search file contents by regex and/or list files matching a glob. "
            "With 'pattern': returns path:lineno: line matches. With only 'glob': "
            "returns the matching file list. Results are capped; narrow the "
            "pattern if you hit the cap. Provide at least one of the two."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex to search for in file contents."},
                "glob": {"type": "string", "description": "Glob pattern to filter files, e.g. '**/*.py'. Defaults to all files."},
            },
            "required": [],
        },
    },
    {
        "name": "run_tests",
        "description": (
            "Run the repository's test suite and return parseable results. "
            "NOT YET IMPLEMENTED — returns an error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Optional path to a specific test file or directory."},
            },
            "required": [],
        },
    },
]

NOT_IMPLEMENTED = {"run_tests"}


def _resolve(workdir: Path, path: str) -> tuple[Path | None, str]:
    """Resolve a repo-relative path; refuse escapes. Returns (path, error)."""
    target = (workdir / path).resolve()
    if not target.is_relative_to(workdir.resolve()):
        return None, f"Error: path escapes the repository root: {path}"
    return target, ""


def read_file(
    workdir: Path, path: str, start_line: int | None = None, end_line: int | None = None
) -> tuple[str, bool]:
    target, err = _resolve(workdir, path)
    if err:
        return err, True
    if not target.is_file():
        return f"Error: no such file: {path}", True
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    total = len(lines)

    start = 1 if start_line is None else start_line
    end = total if end_line is None else end_line
    if start < 1 or (end_line is not None and end < start):
        return f"Error: invalid line range {start}-{end} (file has {total} lines)", True
    if start > total:
        return f"Error: start_line {start} is past the end of the file ({total} lines)", True
    end = min(end, total)

    header = f"[lines {start}-{end} of {total}: {path}]\n"
    body = "".join(lines[start - 1 : end])
    if len(body) > MAX_READ_CHARS:
        body = body[:MAX_READ_CHARS] + f"\n... [truncated at {MAX_READ_CHARS} chars — use a narrower line range]"
    return header + body, False


def edit_file(workdir: Path, path: str, old_str: str, new_str: str) -> tuple[str, bool]:
    target, err = _resolve(workdir, path)
    if err:
        return err, True
    if not target.is_file():
        return f"Error: no such file: {path}", True
    if old_str == new_str:
        return "Error: old_str and new_str are identical — nothing to change.", True
    if not old_str:
        return "Error: old_str is empty — provide the exact text to replace.", True
    text = target.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_str)
    if count == 0:
        return (
            f"Error: old_str not found in {path} — no edit made. "
            "Re-read the file and copy the exact text, including whitespace."
        ), True
    if count > 1:
        return (
            f"Error: old_str matches {count} times in {path} — no edit made. "
            "Include more surrounding context so it matches exactly once."
        ), True
    target.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
    return f"OK: replaced 1 occurrence in {path}.", False


def _truncate(stream: str, label: str) -> str:
    if len(stream) > MAX_BASH_CHARS:
        return stream[:MAX_BASH_CHARS] + f"\n... [{label} truncated at {MAX_BASH_CHARS} chars]"
    return stream


def bash(workdir: Path, command: str) -> tuple[str, bool]:
    # Host-side until D5-6, when this body swaps to docker exec.
    try:
        proc = subprocess.run(
            command, shell=True, cwd=workdir, capture_output=True, text=True,
            timeout=BASH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {BASH_TIMEOUT_S}s and was killed: {command}", True
    out = _truncate(proc.stdout, "stdout")
    errout = _truncate(proc.stderr, "stderr")
    content = f"exit code: {proc.returncode}\nstdout:\n{out}\nstderr:\n{errout}"
    return content, proc.returncode != 0


def grep_glob(workdir: Path, pattern: str | None = None, glob: str | None = None) -> tuple[str, bool]:
    if not pattern and not glob:
        return "Error: provide 'pattern' and/or 'glob'.", True
    if pattern:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex: {e}", True
    root = workdir.resolve()
    # rglob prepends "**/" itself, so a user glob already containing "**" goes
    # through plain glob to avoid double-recursion duplicates.
    if glob is None:
        candidates = root.rglob("*")
    elif "**" in glob:
        candidates = root.glob(glob)
    else:
        candidates = root.rglob(glob)
    files = (
        p for p in sorted(candidates)
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    )

    if not pattern:
        listed = []
        for p in files:
            listed.append(str(p.relative_to(root)))
            if len(listed) >= MAX_GLOB_FILES:
                listed.append(f"[capped at {MAX_GLOB_FILES} files — narrow the glob]")
                break
        return "\n".join(listed) if listed else f"No files match glob: {glob}", False

    matches = []
    capped = False
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append(f"{p.relative_to(root)}:{lineno}: {line.strip()[:200]}")
                if len(matches) >= MAX_GREP_MATCHES:
                    capped = True
                    break
        if capped:
            break
    if capped:
        matches.append(f"[capped at {MAX_GREP_MATCHES} matches — narrow the pattern]")
    return "\n".join(matches) if matches else "No matches.", False


def dispatch(workdir: Path, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call. Returns (content, is_error)."""
    if name in NOT_IMPLEMENTED:
        return f"Error: tool '{name}' is not implemented yet (D5-6 scope). Use the tools that are available.", True
    try:
        if name == "read_file":
            return read_file(
                workdir, tool_input["path"],
                tool_input.get("start_line"), tool_input.get("end_line"),
            )
        if name == "edit_file":
            return edit_file(workdir, tool_input["path"], tool_input["old_str"], tool_input["new_str"])
        if name == "bash":
            return bash(workdir, tool_input["command"])
        if name == "grep_glob":
            return grep_glob(workdir, tool_input.get("pattern"), tool_input.get("glob"))
    except KeyError as e:
        return f"Error: missing required argument {e} for tool '{name}'", True
    return f"Error: unknown tool '{name}'", True
