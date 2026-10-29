"""Per-project Terraform working directories.

Layout: ``<data_dir>/workspaces/<project_id>/<mode>/``. Simulation and real
AWS workspaces never share state. Only files the application wrote are placed
in a workspace; user-edited file names are validated against an allowlist.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.config import Settings

SAFE_NAME = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,60}\.(tf|md|json|example)$")
MANAGED_SUFFIXES = (".tf", ".tfvars", ".example", ".md", ".json")
SIM_OVERRIDE = """# Written by Infrastructure as Prompt for SIMULATION ONLY. Not exported.
# Placeholder credentials are injected by the runner and every account/region
# lookup is skipped, so no request can reach a real AWS account.
provider "aws" {
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  allowed_account_ids         = null
}
"""
MAX_FILE_BYTES = 200_000


class WorkspaceError(ValueError):
    pass


def validate_filename(name: str) -> str:
    if not SAFE_NAME.match(name) or ".." in name or "/" in name or name.startswith("simulation"):
        raise WorkspaceError(f"Invalid file name: {name!r}")
    return name


def effective_files(generated: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    files = dict(generated)
    files.update(overrides)
    return {k: v for k, v in files.items() if v is not None}


def config_hash(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + files[name].encode() + b"\0")
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Workspace:
    def __init__(self, settings: Settings, project_id: str, mode: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise WorkspaceError("invalid project id")
        if mode not in ("simulation", "aws"):
            raise WorkspaceError("invalid mode")
        self.settings = settings
        self.mode = mode
        self.dir = settings.workspaces_dir / project_id / mode
        self.plans_dir = self.dir / "plans"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(exist_ok=True)

    def runtime_files(self, files: dict[str, str], tfvars: dict[str, str]) -> dict[str, str]:
        """All files that make up the planned configuration (project + mode-specific)."""
        out = {k: v for k, v in files.items() if k.endswith(".tf")}
        width = max((len(k) for k in tfvars), default=0)
        lines = [f"{k.ljust(width)} = {json.dumps(v)}" for k, v in sorted(tfvars.items())]  # terraform fmt alignment
        if self.mode == "simulation":
            out["simulation_override.tf"] = SIM_OVERRIDE
            out["simulation.auto.tfvars"] = "# Simulation placeholders — not real values.\n" + "\n".join(lines) + "\n"
        else:
            out["deployment.auto.tfvars"] = "\n".join(lines) + "\n"
        return out

    def write(self, files: dict[str, str], tfvars: dict[str, str]) -> tuple[dict[str, str], str]:
        runtime = self.runtime_files(files, tfvars)
        for existing in self.dir.iterdir():
            if existing.is_file() and existing.name.endswith((".tf", ".tfvars")) and existing.name not in runtime:
                existing.unlink()
        for name, text in runtime.items():
            if len(text.encode()) > MAX_FILE_BYTES:
                raise WorkspaceError(f"{name} exceeds the {MAX_FILE_BYTES} byte limit")
            (self.dir / name).write_text(text)
        return runtime, config_hash(runtime)

    def current_hash(self, files: dict[str, str], tfvars: dict[str, str]) -> str:
        return config_hash(self.runtime_files(files, tfvars))

    def plan_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.tfplan"

    @property
    def state_path(self) -> Path:
        return self.dir / "terraform.tfstate"

    def lock_file(self) -> str | None:
        p = self.dir / ".terraform.lock.hcl"
        return p.read_text() if p.exists() else None
