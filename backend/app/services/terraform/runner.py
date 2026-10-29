"""Controlled execution of external tools (terraform, checkov, trivy).

- Only an allowlist of terraform subcommands can run; arguments are built by
  the application, never by a model or directly from user text.
- No shell is involved (argv lists only).
- A minimal environment is passed: simulation runs get placeholder AWS
  credentials and have shared AWS config/credential files disabled, so they
  cannot reach a real account even if the host has credentials.
- Timeouts, cooperative cancellation and output limits are enforced; the whole
  process group is killed on timeout or cancel.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings

ALLOWED_TF_SUBCOMMANDS = {"version", "fmt", "init", "validate", "plan", "show", "apply", "providers"}


class ToolUnavailable(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def combined(self, limit: int = 20_000) -> str:
        text = (self.stdout + ("\n" if self.stdout and self.stderr else "") + self.stderr).strip()
        return text if len(text) <= limit else text[:limit] + "\n… (output truncated)"


def base_env(settings: Settings, mode: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"),
        "HOME": os.environ.get("HOME", tempfile.gettempdir()),
        "LANG": "C.UTF-8",
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
        "CHECKPOINT_DISABLE": "1",
        "TF_PLUGIN_CACHE_DIR": str(settings.plugin_cache_dir),
    }
    if mode == "simulation":
        env.update(
            {
                "AWS_ACCESS_KEY_ID": "SIMULATIONONLY",
                "AWS_SECRET_ACCESS_KEY": "simulation-only-not-a-credential",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_CONFIG_FILE": os.devnull,
                "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            }
        )
    elif mode == "aws":
        # Real mode: use the operator-configured profile from the host's AWS
        # config (SSO/assume-role recommended). Keys are never accepted via the UI.
        if settings.aws_profile:
            env["AWS_PROFILE"] = settings.aws_profile
        for key in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_REGION"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def run(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    output_limit: int,
    cancel: threading.Event | None = None,
    stdin: str | None = None,
) -> RunResult:
    start = time.monotonic()
    proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    timed_out = False
    stdout, stderr = "", ""
    try:
        deadline = start + timeout
        comm_input = stdin
        while True:
            try:
                out, err = proc.communicate(input=comm_input, timeout=0.5)
                stdout, stderr = out or "", err or ""
                break
            except subprocess.TimeoutExpired:
                comm_input = None
                if cancel is not None and cancel.is_set():
                    _kill(proc)
                    proc.communicate()
                    raise Cancelled(f"{argv[0]} cancelled") from None
                if time.monotonic() > deadline:
                    timed_out = True
                    _kill(proc)
                    out, err = proc.communicate()
                    stdout, stderr = out or "", (err or "") + f"\nTimed out after {timeout}s."
                    break
    finally:
        if proc.poll() is None:
            _kill(proc)
    truncated = len(stdout) > output_limit or len(stderr) > output_limit
    return RunResult(
        argv=argv,
        returncode=proc.returncode if not timed_out else -1,
        stdout=stdout[:output_limit],
        stderr=stderr[:output_limit],
        duration_s=round(time.monotonic() - start, 2),
        timed_out=timed_out,
        truncated=truncated,
    )


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class Terraform:
    def __init__(self, settings: Settings, workdir: Path, mode: str, cancel: threading.Event | None = None) -> None:
        path = settings.terraform_path()
        if not path:
            raise ToolUnavailable(f"Terraform binary '{settings.terraform_bin}' not found on PATH")
        self.bin = path
        self.settings = settings
        self.workdir = workdir
        self.mode = mode
        self.cancel = cancel

    def __call__(self, *args: str, timeout: int | None = None, stdin: str | None = None) -> RunResult:
        """Run an allowlisted subcommand. Machine-readable JSON commands (show,
        providers schema) get a larger output cap and fail loudly if truncated."""
        if not args or args[0] not in ALLOWED_TF_SUBCOMMANDS:
            raise ValueError(f"terraform subcommand not allowed: {args[:1]}")
        if args[0] == "apply" and self.mode not in ("aws",):
            raise PermissionError("terraform apply is only permitted in real AWS mode through the approval workflow")
        argv = [self.bin, *args]
        json_cmd = args[0] in ("show", "providers")
        limit = 64_000_000 if json_cmd else self.settings.tool_output_limit_bytes
        res = run(
            argv, self.workdir, base_env(self.settings, self.mode), timeout or self.settings.tool_timeout_seconds, limit, self.cancel, stdin
        )
        if json_cmd and res.truncated:
            raise RuntimeError(f"terraform {args[0]} output exceeded {limit} bytes")
        return res

    def fmt_text(self, text: str) -> str | None:
        res = run([self.bin, "fmt", "-no-color", "-"], self.workdir, base_env(self.settings, "simulation"), 30, 2_000_000, None, stdin=text)
        return res.stdout if res.ok else None
