"""Tool schemas and dispatch for the agent loop.

All five schemas are defined from day one (W1 D1–2) so schema wiring is
exercised early, but only read_file executes today. The rest return an
explicit is_error result — a loud gap beats a silent success. Full
implementations land D3–4 (edit_file with uniqueness validation, stateless
bash via subprocess.run) and D5–6 (docker exec routing).
"""

from pathlib import Path

# Truncation guard: never dump unbounded file content into context.
# Real windowing strategy is W2 (D8–9) scope.
MAX_READ_CHARS = 50_000

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the repository. Returns the full file content. "
            "Paths are relative to the repository root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace an exact string in a file with a new string. The old string "
            "must appear exactly once in the file. NOT YET IMPLEMENTED — returns an error."
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
            "Run a shell command in the repository. Stateless: each command runs "
            "in a fresh process, so state does not persist between calls. "
            "NOT YET IMPLEMENTED — returns an error."
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
            "Search file contents by regex and/or list files matching a glob pattern. "
            "NOT YET IMPLEMENTED — returns an error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex to search for in file contents."},
                "glob": {"type": "string", "description": "Glob pattern to filter files, e.g. '**/*.py'."},
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

NOT_IMPLEMENTED = {"edit_file", "bash", "grep_glob", "run_tests"}


def read_file(workdir: Path, path: str) -> tuple[str, bool]:
    target = (workdir / path).resolve()
    if not target.is_relative_to(workdir.resolve()):
        return f"Error: path escapes the repository root: {path}", True
    if not target.is_file():
        return f"Error: no such file: {path}", True
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n... [truncated at {MAX_READ_CHARS} chars]"
    return text, False


def dispatch(workdir: Path, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call. Returns (content, is_error)."""
    if name in NOT_IMPLEMENTED:
        return f"Error: tool '{name}' is not implemented yet (D3-4 scope). Use the tools that are available.", True
    if name == "read_file":
        return read_file(workdir, tool_input["path"])
    return f"Error: unknown tool '{name}'", True
