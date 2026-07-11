"""Per-task Docker sandbox (W1 D5-6).

The task repo lives ONLY inside the container: `docker cp` in, no bind
mounts, `--network none`. No bind mounts means the container has no host
filesystem access AND there is exactly one copy of the repo — a host
mirror would be a coherence problem, and a stale mirror is the silent-
wrong-edit class D3-4 exists to prevent.

read_file / edit_file / grep_glob run in-container through a JSON-over-
stdin toolbox (agent/toolbox.py + agent/tools.py, copied to /opt/toolbox
at start) so old_str payloads never touch shell quoting. bash and
run_tests go through `docker exec`, wrapped in coreutils `timeout` so the
process inside the container dies too — killing only the host-side client
would leave it running.

Patch extraction (W3 need, testable now): the repo is git-initialized
with a baseline commit at start, so `docker exec ... git diff` yields the
agent's patch at any point.
"""

import json
import shlex
import subprocess
import uuid
from pathlib import Path

from agent.tools import (
    BASH_TIMEOUT_S,
    TESTS_TIMEOUT_S,
    bash_timeout_error,
    format_bash_result,
    format_test_result,
)

WORKSPACE = "/workspace"
TOOLBOX_DIR = "/opt/toolbox"
DOCKER_TIMEOUT_S = 120        # docker plumbing (run/cp/rm), not tool execution
TOOLBOX_TIMEOUT_S = 60        # in-container FS tools (grep on a big repo)
_AGENT_DIR = Path(__file__).resolve().parent


class SandboxError(RuntimeError):
    pass


class Sandbox:
    """Context manager for one per-task container. Teardown is guaranteed:
    __exit__ force-removes the container even when the body raises."""

    def __init__(self, image: str, repo_src: str | Path):
        self.image = image
        self.repo_src = Path(repo_src)
        self.container = f"swb-{uuid.uuid4().hex[:12]}"

    # --- lifecycle ---

    def __enter__(self) -> "Sandbox":
        self.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False

    def start(self) -> None:
        if not self.repo_src.is_dir():
            raise SandboxError(f"repo_src is not a directory: {self.repo_src}")
        self._docker(
            "run", "-d", "--network", "none", "--name", self.container,
            self.image, "sleep", "infinity",
        )
        try:
            # mkdir first: docker cp of DIR/. requires the destination to exist,
            # and arbitrary W3 task images may lack /workspace.
            self._exec_raw(f"mkdir -p {WORKSPACE} {TOOLBOX_DIR}", DOCKER_TIMEOUT_S, workdir=None)
            self._docker("cp", f"{self.repo_src}/.", f"{self.container}:{WORKSPACE}")
            for fname in ("tools.py", "toolbox.py"):
                self._docker("cp", str(_AGENT_DIR / fname), f"{self.container}:{TOOLBOX_DIR}/{fname}")
            # Baseline commit so `git diff` is the patch-extraction path.
            proc = self._exec_raw(
                "git config --global --add safe.directory '*' && "
                "if [ ! -d .git ]; then git init -q && git add -A && "
                "git -c user.email=sandbox@local -c user.name=sandbox commit -qm baseline; fi",
                DOCKER_TIMEOUT_S,
            )
            if proc.returncode != 0:
                raise SandboxError(f"git baseline failed: {proc.stderr.strip()[:800]}")
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        # Force-remove by name; idempotent, failure is not actionable here.
        subprocess.run(
            ["docker", "rm", "-f", self.container],
            capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S,
        )

    def git_diff(self) -> str | None:
        """Final in-container patch vs the baseline commit (schema v1 freeze,
        W3 patch-extraction path). `git add -A` first: plain `git diff`
        misses files the agent CREATED (untracked), and a patch that silently
        drops new files is the silent-wrong-edit class again, at extraction
        time. Mutating the index is fine — this runs at end-of-run and the
        container is about to be destroyed. Returns None (never raises) on
        failure: patch capture must not turn a finished run into a crash."""
        try:
            proc = self._exec_raw("git add -A && git diff --cached", DOCKER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None
        return proc.stdout if proc.returncode == 0 else None

    # --- tool surface (each returns (content, is_error) like host tools) ---

    def bash(self, command: str) -> tuple[str, bool]:
        try:
            proc = self._exec_raw(command, BASH_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return bash_timeout_error(command)
        if proc.returncode == 124:  # coreutils timeout; ambiguous with a genuine exit 124, acceptably rare
            return bash_timeout_error(command)
        return format_bash_result(proc.returncode, proc.stdout, proc.stderr)

    def run_tests(self, test_path: str | None = None) -> tuple[str, bool]:
        cmd = "python3 -m pytest -q --tb=short"
        if test_path:
            cmd += " " + shlex.quote(test_path)
        try:
            proc = self._exec_raw(cmd, TESTS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return format_test_result(None, "")
        if proc.returncode == 124:
            return format_test_result(None, proc.stdout)
        output = proc.stdout + (f"\n{proc.stderr}" if proc.stderr.strip() else "")
        return format_test_result(proc.returncode, output)

    def exec_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """read_file / edit_file / grep_glob via the in-container toolbox."""
        request = json.dumps({"name": name, "input": tool_input}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                ["docker", "exec", "-i", self.container, "python3", f"{TOOLBOX_DIR}/toolbox.py"],
                input=request, capture_output=True, text=True, timeout=TOOLBOX_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"Error: sandbox tool '{name}' timed out after {TOOLBOX_TIMEOUT_S}s.", True
        if proc.returncode != 0:
            return (
                f"Error: sandbox toolbox failed for '{name}' (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            ), True
        try:
            resp = json.loads(proc.stdout)
            return resp["content"], bool(resp["is_error"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return f"Error: sandbox toolbox returned malformed JSON ({e}): {proc.stdout[:500]}", True

    # --- plumbing ---

    def _exec_raw(self, command: str, timeout: int, workdir: str | None = WORKSPACE):
        """docker exec, command under coreutils `timeout` inside the container.
        Host-side subprocess timeout is a backstop 15s behind it."""
        argv = ["docker", "exec"]
        if workdir:
            argv += ["-w", workdir]
        argv += [self.container, "timeout", str(timeout), "sh", "-c", command]
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 15)

    def _docker(self, *argv: str) -> str:
        proc = subprocess.run(
            ["docker", *argv], capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S,
        )
        if proc.returncode != 0:
            hint = " (is the Docker daemon running?)" if "daemon" in proc.stderr.lower() else ""
            raise SandboxError(
                f"docker {argv[0]} failed (exit {proc.returncode}){hint}: {proc.stderr.strip()[:800]}"
            )
        return proc.stdout
