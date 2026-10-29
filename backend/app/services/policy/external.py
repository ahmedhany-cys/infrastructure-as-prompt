"""Optional external scanners (Checkov, Trivy). Findings are advisory: they are
shown with their tool's own severity but do not gate deployment, because their
rule sets include checks that conflict with deliberate, documented design
choices (e.g. an internet-facing load balancer). The deterministic engine is
the gate. Scans run on a copy containing only .tf files."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

from app.config import Settings
from app.domain.findings import ExternalFinding, PipelineStep
from app.services.terraform.runner import base_env, run


def _copy_tf(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="iap-scan-"))
    for f in src.glob("*.tf"):
        if not f.name.startswith("simulation"):
            shutil.copy2(f, tmp / f.name)
    return tmp


def run_checkov(settings: Settings, workdir: Path, cancel: threading.Event | None) -> tuple[PipelineStep, list[ExternalFinding]]:
    argv = settings.checkov_argv()
    if not argv:
        return PipelineStep(
            name="Checkov scan", status="unavailable", summary="Checkov is not installed; install it to add community rule coverage."
        ), []
    tmp = _copy_tf(workdir)
    try:
        res = run(
            [*argv, "-d", str(tmp), "--framework", "terraform", "-o", "json", "--quiet", "--compact", "--skip-download"],
            tmp,
            base_env(settings, "simulation"),
            240,
            settings.tool_output_limit_bytes * 10,
            cancel,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if res.timed_out:
        return PipelineStep(name="Checkov scan", status="error", summary="Checkov timed out.", output=res.combined(2000)), []
    try:
        data = json.loads(res.stdout or "[]")
    except json.JSONDecodeError:
        return PipelineStep(name="Checkov scan", status="error", summary="Could not parse Checkov output.", output=res.combined(2000)), []
    findings: list[ExternalFinding] = []
    for block in data if isinstance(data, list) else [data]:
        for f in (block.get("results") or {}).get("failed_checks", []):
            findings.append(
                ExternalFinding(
                    tool="checkov",
                    rule_id=f.get("check_id", "?"),
                    title=f.get("check_name", "")[:200],
                    severity=(f.get("severity") or "UNRATED").upper(),
                    resource=f.get("resource"),
                    file=(f.get("file_path") or "").lstrip("/"),
                    line=(f.get("file_line_range") or [None])[0],
                    guideline=f.get("guideline"),
                )
            )
    blocks = data if isinstance(data, list) else [data]
    passed = sum(int((b.get("summary") or {}).get("passed", 0)) for b in blocks)
    return PipelineStep(
        name="Checkov scan",
        status="warning" if findings else "passed",
        summary=f"{passed} checks passed, {len(findings)} advisory findings (not gating).",
    ), findings


def run_trivy(settings: Settings, workdir: Path, cancel: threading.Event | None) -> tuple[PipelineStep, list[ExternalFinding]]:
    path = settings.trivy_path()
    if not path:
        return PipelineStep(name="Trivy config scan", status="unavailable", summary="Trivy is not installed."), []
    tmp = _copy_tf(workdir)
    try:
        res = run(
            [path, "config", "--format", "json", "--quiet", "--skip-check-update", str(tmp)],
            tmp,
            base_env(settings, "simulation"),
            180,
            settings.tool_output_limit_bytes * 10,
            cancel,
        )
        if not res.ok and "unknown flag" in res.stderr:
            res = run(
                [path, "config", "--format", "json", "--quiet", str(tmp)],
                tmp,
                base_env(settings, "simulation"),
                180,
                settings.tool_output_limit_bytes * 10,
                cancel,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        return PipelineStep(
            name="Trivy config scan", status="error", summary="Could not parse Trivy output.", output=res.combined(2000)
        ), []
    findings: list[ExternalFinding] = []
    for r in data.get("Results") or []:
        for m in r.get("Misconfigurations") or []:
            meta = m.get("CauseMetadata") or {}
            findings.append(
                ExternalFinding(
                    tool="trivy",
                    rule_id=m.get("ID", "?"),
                    title=m.get("Title", "")[:200],
                    severity=m.get("Severity", "UNKNOWN"),
                    resource=meta.get("Resource"),
                    file=r.get("Target"),
                    line=meta.get("StartLine"),
                    guideline=m.get("PrimaryURL"),
                )
            )
    return PipelineStep(
        name="Trivy config scan", status="warning" if findings else "passed", summary=f"{len(findings)} advisory findings (not gating)."
    ), findings
