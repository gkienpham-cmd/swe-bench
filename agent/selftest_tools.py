"""$0 self-test for agent/tools.py — direct function calls, no API.

Run: python -m agent.selftest_tools
Covers the D3-4 done-checks: edit_file rejects 0- and multi-match, bash
captures exit codes and is stateless, read_file ranges are exact,
grep_glob finds and caps.
"""

import tempfile
from pathlib import Path

from agent.tools import (
    BASH_TIMEOUT_S, MAX_GREP_MATCHES, bash, dispatch, edit_file, grep_glob, read_file,
)

checks = 0


def ok(cond: bool, label: str):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"ok: {label}")


with tempfile.TemporaryDirectory() as td:
    wd = Path(td)
    (wd / "pkg").mkdir()
    (wd / "pkg" / "a.py").write_text("VALUE = 1\nname = 'alpha'\nshared = True\n")
    (wd / "pkg" / "b.py").write_text("VALUE = 2\nname = 'beta'\nshared = True\n")
    (wd / "notes.txt").write_text("\n".join(f"line {i}" for i in range(1, 21)) + "\n")

    # --- read_file ---
    content, err = read_file(wd, "notes.txt", 5, 7)
    ok(not err and content == "[lines 5-7 of 20: notes.txt]\nline 5\nline 6\nline 7\n",
       "read_file returns exactly the requested range with header")
    content, err = read_file(wd, "notes.txt")
    ok(not err and content.startswith("[lines 1-20 of 20: notes.txt]\nline 1\n"),
       "read_file whole-file default")
    _, err = read_file(wd, "notes.txt", 25)
    ok(err, "read_file start past EOF is a loud error")
    _, err = read_file(wd, "notes.txt", 7, 3)
    ok(err, "read_file inverted range is a loud error")
    content, err = read_file(wd, "notes.txt", 15, 999)
    ok(not err and content.startswith("[lines 15-20 of 20:"), "read_file end clamps to EOF")
    _, err = read_file(wd, "../outside.txt")
    ok(err, "read_file path escape rejected")

    # --- edit_file ---
    _, err = edit_file(wd, "pkg/a.py", "no_such_string", "x")
    ok(err, "edit_file 0-match rejected")
    (wd / "pkg" / "a.py").write_text("VALUE = 1\nVALUE = 1\n")
    msg, err = edit_file(wd, "pkg/a.py", "VALUE = 1", "VALUE = 9")
    ok(err and "2 times" in msg, "edit_file multi-match rejected, nothing written")
    ok((wd / "pkg" / "a.py").read_text() == "VALUE = 1\nVALUE = 1\n",
       "edit_file multi-match left file untouched")
    (wd / "pkg" / "a.py").write_text("VALUE = 1\nname = 'alpha'\n")
    msg, err = edit_file(wd, "pkg/a.py", "name = 'alpha'", "name = 'omega'")
    ok(not err and (wd / "pkg" / "a.py").read_text() == "VALUE = 1\nname = 'omega'\n",
       "edit_file 1-match applied exactly")
    _, err = edit_file(wd, "pkg/a.py", "same", "same")
    ok(err, "edit_file old==new rejected")
    _, err = edit_file(wd, "../../etc/hosts", "a", "b")
    ok(err, "edit_file path escape rejected")

    # --- bash ---
    content, err = bash(wd, "echo hello && exit 0")
    ok(not err and "exit code: 0" in content and "hello" in content, "bash success captures stdout")
    content, err = bash(wd, "echo oops >&2; exit 3")
    ok(err and "exit code: 3" in content and "oops" in content, "bash nonzero exit is error with stderr")
    content, err = bash(wd, "python3 -c 'print(\"x\" * 50000)'")
    ok(not err and "truncated" in content, "bash long stdout truncated with marker")
    content, err = bash(wd, "pwd")
    ok(str(wd) in content or Path(content.split("stdout:\n")[1].splitlines()[0]).resolve() == wd.resolve(),
       "bash runs in workdir")
    content, err = bash(wd, "export FOO=bar"); content, err = bash(wd, "echo FOO=$FOO")
    ok("FOO=\n" in content or "FOO=bar" not in content, "bash is stateless across calls")

    # --- grep_glob ---
    (wd / "pkg" / "a.py").write_text("VALUE = 1\nname = 'omega'\nshared = True\n")
    content, err = grep_glob(wd, pattern="shared = True")
    ok(not err and "pkg/a.py:3" in content and "pkg/b.py:3" in content, "grep finds matches with path:lineno")
    content, err = grep_glob(wd, pattern="shared", glob="*.txt")
    ok(not err and content == "No matches.", "grep respects glob filter; empty is non-error")
    content, err = grep_glob(wd, glob="**/*.py")
    ok(not err and "pkg/a.py" in content and "pkg/b.py" in content and "notes.txt" not in content,
       "glob-only lists matching files")
    _, err = grep_glob(wd)
    ok(err, "grep_glob with no args rejected")
    _, err = grep_glob(wd, pattern="([unclosed")
    ok(err, "grep_glob invalid regex is loud")
    big = wd / "big.txt"
    big.write_text("needle\n" * (MAX_GREP_MATCHES + 50))
    content, err = grep_glob(wd, pattern="needle")
    ok(not err and f"capped at {MAX_GREP_MATCHES}" in content, "grep cap message appears")

    # --- dispatch ---
    content, err = dispatch(wd, "run_tests", {})
    ok(err and "not implemented" in content, "run_tests still a loud stub")
    content, err = dispatch(wd, "edit_file", {"path": "pkg/a.py"})
    ok(err and "missing required argument" in content, "dispatch missing-arg is loud, not a crash")

print(f"\nall {checks} checks passed (timeout check skipped by default — run bash(wd, 'sleep 40') manually; it takes {BASH_TIMEOUT_S}s)")
