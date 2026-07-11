"""$0 container-mode self-test for agent/sandbox.py — needs Docker, no API.

Run: python -m agent.selftest_sandbox
Covers the D5-6 done-checks: the container has no host-filesystem access
(no mounts, host paths unreadable, no network), all five tools operate on
the container FS, run_tests round-trips a parsed fail-then-pass result on
the toybug fixture, `git diff` yields the patch, and teardown happens even
when the loop body raises.

Exits 2 with a loud message if the Docker daemon is down (skipped, not
green). Builds the swb-dev image on first use.
"""

import subprocess
import sys
from pathlib import Path

from agent.sandbox import Sandbox, SandboxError, WORKSPACE

IMAGE = "swb-dev"
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "docker" / "fixtures" / "toybug"

checks = 0


def ok(cond: bool, label: str):
    global checks
    assert cond, f"FAIL: {label}"
    checks += 1
    print(f"ok: {label}")


def main() -> int:
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("SKIPPED: Docker daemon is not running — start Docker Desktop and re-run. "
              "These checks are the D5-6 done-when; do not ship without them.")
        return 2

    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        print(f"[building {IMAGE} from docker/Dockerfile.dev — first run only]")
        subprocess.run(
            ["docker", "build", "-t", IMAGE, "-f", str(REPO_ROOT / "docker" / "Dockerfile.dev"),
             str(REPO_ROOT / "docker")],
            check=True,
        )

    with Sandbox(IMAGE, FIXTURE) as sb:
        # --- isolation: the done-when, checked mechanically ---
        mounts = subprocess.run(
            ["docker", "inspect", "-f", "{{json .Mounts}}", sb.container],
            capture_output=True, text=True,
        ).stdout.strip()
        ok(mounts == "[]", f"no mounts of any kind (docker inspect .Mounts == []; got {mounts})")
        netmode = subprocess.run(
            ["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", sb.container],
            capture_output=True, text=True,
        ).stdout.strip()
        ok(netmode == "none", "network mode is 'none'")
        content, err = sb.bash(f"test -e {FIXTURE}")
        ok(err, "host filesystem path does not exist inside the container")
        content, err = sb.bash(
            'python3 -c "import socket; socket.setdefaulttimeout(3); socket.getaddrinfo(\'example.com\', 80)"'
        )
        ok(err, "network is unreachable from inside the container")

        # --- all five tools on the container FS ---
        content, err = sb.exec_tool("read_file", {"path": "calc/pricing.py"})
        ok(not err and "apply_discount" in content, "read_file reads the container copy")
        content, err = sb.exec_tool("grep_glob", {"pattern": r"1 \+ percent / 100"})
        ok(not err and "calc/pricing.py" in content and "calc/tax.py" in content,
           "grep_glob finds bug line and decoy in-container")
        content, err = sb.exec_tool("edit_file", {"path": "calc/pricing.py", "old_str": "percent", "new_str": "x"})
        ok(err and "times" in content, "edit_file multi-match rejection round-trips the JSON hop")
        content, err = sb.bash("echo hi && pwd")
        ok(not err and "hi" in content and WORKSPACE in content, "bash execs in /workspace")
        content, err = sb.bash("export FOO=bar")
        content, err = sb.bash("echo FOO=$FOO")
        ok("FOO=bar" not in content, "bash is stateless across docker execs")

        # --- run_tests: fail -> fix -> pass round-trip ---
        content, err = sb.run_tests()
        ok(err and content.startswith("[tests: 1 passed, 1 failed, 0 errors | exit 1]"),
           "run_tests parses the planted failure (1 passed, 1 failed)")
        content, err = sb.exec_tool("edit_file", {
            "path": "calc/pricing.py",
            "old_str": "return price * (1 + percent / 100)",
            "new_str": "return price * (1 - percent / 100)",
        })
        ok(not err, "fix applied in-container (unique within pricing.py despite tax.py decoy)")
        content, err = sb.run_tests()
        ok(not err and content.startswith("[tests: 2 passed, 0 failed, 0 errors | exit 0]"),
           "run_tests parses the pass after the fix")
        content, err = sb.run_tests("tests/test_pricing.py")
        ok(not err and "2 passed" in content, "run_tests accepts a test_path")

        # --- patch extraction (W3 path, proven now) ---
        content, err = sb.bash("git diff")
        ok(not err and "-    return price * (1 + percent / 100)" in content
           and "+    return price * (1 - percent / 100)" in content,
           "git diff against the baseline commit yields the patch")

        # --- git_diff(): schema-v1 patch extraction, incl. untracked files ---
        sb.bash("printf 'new = True\\n' > calc/newmod.py")
        patch = sb.git_diff()
        ok(patch is not None
           and "calc/newmod.py" in patch and "+new = True" in patch
           and "-    return price * (1 + percent / 100)" in patch,
           "git_diff() captures edits AND agent-created (untracked) files in one patch")

    gone = subprocess.run(["docker", "inspect", sb.container], capture_output=True).returncode != 0
    ok(gone, "container removed on clean context exit")

    # --- teardown on exception ---
    try:
        with Sandbox(IMAGE, FIXTURE) as sb2:
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    gone = subprocess.run(["docker", "inspect", sb2.container], capture_output=True).returncode != 0
    ok(gone, "container removed when the body raises")

    # --- loud failure when the image is missing ---
    try:
        Sandbox("swb-no-such-image", FIXTURE).start()
        ok(False, "missing image should raise")
    except SandboxError as e:
        ok("docker run failed" in str(e), "missing image raises a loud SandboxError")

    print(f"\nall {checks} sandbox checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
