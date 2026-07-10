"""In-container tool executor: one JSON request on stdin, one JSON response on stdout.

Copied (with tools.py) to /opt/toolbox inside the sandbox by
agent/sandbox.py. Runs the same pure-Python read_file/edit_file/grep_glob
the host self-tests cover, against /workspace. JSON-over-stdin means
old_str/new_str never touch a shell — no quoting hazards.

Contract: stdout is exactly one JSON object {"content": str, "is_error":
bool}; any internal failure is reported inside that object, never as a
bare traceback (exit != 0 is how the host detects a broken toolbox, not a
failed tool call).
"""

import json
import os
import sys
from pathlib import Path

# Standalone import: inside the container this file sits next to tools.py
# in /opt/toolbox, outside any package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tools  # noqa: E402

# Env override exists so the host self-test can exercise the JSON protocol
# against a temp dir at $0, without Docker.
WORKSPACE = Path(os.environ.get("TOOLBOX_WORKSPACE", "/workspace"))


def handle(request: dict) -> tuple[str, bool]:
    name = request["name"]
    tool_input = request.get("input", {})
    if name == "read_file":
        return tools.read_file(
            WORKSPACE, tool_input["path"],
            tool_input.get("start_line"), tool_input.get("end_line"),
        )
    if name == "edit_file":
        return tools.edit_file(
            WORKSPACE, tool_input["path"], tool_input["old_str"], tool_input["new_str"],
        )
    if name == "grep_glob":
        return tools.grep_glob(WORKSPACE, tool_input.get("pattern"), tool_input.get("glob"))
    return f"Error: toolbox does not handle tool '{name}'", True


def main() -> int:
    try:
        content, is_error = handle(json.load(sys.stdin))
    except KeyError as e:
        content, is_error = f"Error: missing required argument {e}", True
    except Exception as e:  # never leak a traceback onto stdout
        content, is_error = f"Error: toolbox crashed: {type(e).__name__}: {e}", True
    json.dump({"content": content, "is_error": is_error}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
