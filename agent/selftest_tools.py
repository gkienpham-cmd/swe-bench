"""$0 self-test for agent/tools.py — direct function calls, no API, no Docker.

Run: python -m agent.selftest_tools
Covers the D3-4 done-checks (edit_file rejects 0- and multi-match, bash
captures exit codes and is stateless, read_file ranges are exact,
grep_glob finds and caps) plus the D5-6 host-testable parts: the pytest
summary parser, the rule-6 flag heuristic, and the toolbox JSON protocol
(via TOOLBOX_WORKSPACE against a temp dir). Container-mode checks live in
agent/selftest_sandbox.py.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent.tools import (
    BASH_TIMEOUT_S, MAX_GLOB_FILES, MAX_GREP_MATCHES, MAX_READ_CHARS,
    MAX_READ_LINES, bash, dispatch, edit_file, format_test_result, grep_glob,
    parse_pytest_counts, read_file, reward_hack_flag,
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

    # --- read_file windowing (D8-9: never dump whole files) ---
    (wd / "bigfile.py").write_text("\n".join(f"x{i} = {i}" for i in range(1, 401)) + "\n")
    content, err = read_file(wd, "bigfile.py")
    ok(not err and content.startswith(f"[lines 1-{MAX_READ_LINES} of 400: bigfile.py]")
       and f"x{MAX_READ_LINES} = " in content and f"\nx{MAX_READ_LINES + 1} = " not in content,
       "read_file default on big file serves exactly the first window")
    ok("file has 400 lines" in content and "start_line/end_line" in content,
       "read_file omitted-range marker states total and the recovery move")
    content, err = read_file(wd, "bigfile.py", 300)
    ok(not err and content.startswith("[lines 300-400 of 400:") and "[file has" not in content
       and "capped" not in content,
       "read_file in-window tail range has no marker")
    content, err = read_file(wd, "bigfile.py", 1, 400)
    ok(not err and content.startswith(f"[lines 1-{MAX_READ_LINES} of 400:")
       and f"continue from start_line={MAX_READ_LINES + 1}" in content,
       "read_file explicit oversized range capped with continue-from marker")
    content, err = read_file(wd, "bigfile.py", 100)
    ok(not err and content.startswith(f"[lines 100-{100 + MAX_READ_LINES - 1} of 400:"),
       "read_file start-only pagination serves one window from start")
    (wd / "longline.txt").write_text("y" * (MAX_READ_CHARS + 10_000))
    content, err = read_file(wd, "longline.txt")
    ok(not err and f"truncated at {MAX_READ_CHARS} chars" in content,
       "read_file char backstop still fires on pathological long lines")

    # --- grep_glob directory summary (D8-9: summarize listings over the cap) ---
    for pkg in ("pkg1", "pkg2", "pkg3"):
        (wd / "many" / pkg).mkdir(parents=True)
        for i in range(20):
            (wd / "many" / pkg / f"f_{i:02d}.py").write_text("pass\n")
    content, err = grep_glob(wd, glob="many/**/*.py")
    ok(not err and content.startswith(f"[60 files match — over the {MAX_GLOB_FILES}-file cap"),
       "glob over cap returns summary header with total count")
    ok("many/pkg1  20" in content and "f_00.py" not in content,
       "glob summary has per-directory counts and no individual filenames")
    content, err = grep_glob(wd, glob="many/pkg1/*.py")
    ok(not err and "many/pkg1/f_00.py" in content and "files match" not in content,
       "glob under cap still lists files verbatim")

    # --- dispatch ---
    content, err = dispatch(wd, "run_tests", {})
    ok(err and "requires the Docker sandbox" in content, "run_tests without sandbox is a loud error")
    content, err = dispatch(wd, "edit_file", {"path": "pkg/a.py"})
    ok(err and "missing required argument" in content, "dispatch missing-arg is loud, not a crash")

    # --- pytest summary parser (pure, $0) ---
    counts = parse_pytest_counts("....\n1 failed, 1 passed in 0.05s\n")
    ok(counts == {"failed": 1, "passed": 1}, "parser: failed+passed summary line")
    counts = parse_pytest_counts("===== 3 passed in 0.01s =====")
    ok(counts == {"passed": 3}, "parser: passed-only with = decoration")
    counts = parse_pytest_counts("2 errors in 0.10s")
    ok(counts == {"error": 2}, "parser: 'errors' normalized to 'error'")
    counts = parse_pytest_counts("no tests ran in 0.01s")
    ok(counts == {}, "parser: 'no tests ran' yields empty counts")
    counts = parse_pytest_counts("Traceback (most recent call last):\n  boom\n")
    ok(counts == {}, "parser: collection crash yields empty counts, not garbage")
    counts = parse_pytest_counts("1 failed, 1 passed in 0.05s\nlater noise\n2 passed, 1 warning in 0.2s")
    ok(counts.get("passed") == 2, "parser: LAST summary line wins")

    content, err = format_test_result(1, "F.\n1 failed, 1 passed in 0.05s")
    ok(err and content.startswith("[tests: 1 passed, 1 failed, 0 errors | exit 1]"),
       "format: failing run has parsed header and is_error")
    content, err = format_test_result(0, "..\n2 passed in 0.01s")
    ok(not err and content.startswith("[tests: 2 passed, 0 failed, 0 errors | exit 0]"),
       "format: passing run is non-error")
    content, err = format_test_result(5, "no tests ran in 0.01s")
    ok(err and "no tests collected" in content, "format: exit 5 labeled no-tests-collected")
    content, err = format_test_result(2, "INTERNALERROR> boom")
    ok(err and "summary line not found" in content, "format: unparseable output stays loud")
    content, err = format_test_result(None, "partial")
    ok(err and "timed out" in content, "format: timeout is a loud error")

    # --- rule-6 flag heuristic (log-only instrumentation) ---
    ok(reward_hack_flag("edit_file", {"path": "tests/test_pricing.py"}) == "test-modification-attempt",
       "flag: edit under tests/ flagged")
    ok(reward_hack_flag("edit_file", {"path": "src/deep/conftest.py"}) == "test-modification-attempt",
       "flag: conftest.py flagged")
    ok(reward_hack_flag("edit_file", {"path": "src/utils_test.py"}) == "test-modification-attempt",
       "flag: *_test.py flagged")
    ok(reward_hack_flag("edit_file", {"path": "src/test_helpers.py"}) == "test-modification-attempt",
       "flag: test_*.py flagged even outside tests/")
    ok(reward_hack_flag("edit_file", {"path": "calc/pricing.py"}) is None,
       "flag: normal source edit not flagged")
    ok(reward_hack_flag("edit_file", {"path": "latest/protest.py"}) is None,
       "flag: near-miss names (latest/, protest.py) not flagged")
    ok(reward_hack_flag("bash", {"command": "rm tests/test_x.py"}) is None,
       "flag: bash not covered (documented W4 gap, not a silent one)")

    # --- toolbox JSON protocol (host-side, TOOLBOX_WORKSPACE override) ---
    toolbox = Path(__file__).resolve().parent / "toolbox.py"

    def call_toolbox(req: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, str(toolbox)], input=json.dumps(req),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "TOOLBOX_WORKSPACE": str(wd)},
        )
        assert proc.returncode == 0, f"toolbox exited {proc.returncode}: {proc.stderr}"
        return json.loads(proc.stdout)

    resp = call_toolbox({"name": "read_file", "input": {"path": "notes.txt", "start_line": 5, "end_line": 5}})
    ok(not resp["is_error"] and "line 5" in resp["content"], "toolbox: read_file round-trips JSON")
    resp = call_toolbox({"name": "edit_file", "input": {"path": "pkg/b.py", "old_str": "name = 'beta'", "new_str": "name = 'B'"}})
    ok(not resp["is_error"] and (wd / "pkg" / "b.py").read_text().count("name = 'B'") == 1,
       "toolbox: edit_file applies through the JSON hop")
    resp = call_toolbox({"name": "edit_file", "input": {"path": "pkg/b.py", "old_str": "nope", "new_str": "x"}})
    ok(resp["is_error"] and "not found" in resp["content"],
       "toolbox: match-exactly-once error text preserved verbatim")
    resp = call_toolbox({"name": "grep_glob", "input": {"pattern": "shared = True"}})
    ok(not resp["is_error"] and "pkg/a.py" in resp["content"], "toolbox: grep_glob works through JSON")
    resp = call_toolbox({"name": "read_file", "input": {"path": "bigfile.py"}})
    ok(not resp["is_error"] and "file has 400 lines" in resp["content"],
       "toolbox: windowing marker survives the JSON hop")
    resp = call_toolbox({"name": "bash", "input": {"command": "echo hi"}})
    ok(resp["is_error"] and "does not handle" in resp["content"],
       "toolbox: refuses tools it does not own (bash goes via docker exec)")
    resp = call_toolbox({"name": "edit_file", "input": {"path": "pkg/b.py"}})
    ok(resp["is_error"] and "missing required argument" in resp["content"],
       "toolbox: missing arg is a JSON error, not a traceback")

print(f"\nall {checks} checks passed (timeout check skipped by default — run bash(wd, 'sleep 40') manually; it takes {BASH_TIMEOUT_S}s)")
