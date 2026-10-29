"""Regenerate docs/examples from a real run of the pipeline (simulation mode).

Usage: cd backend && .venv/bin/python -m scripts.export_examples
Uses a throwaway database and workspace; requires the terraform binary.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="iap-examples-"))
os.environ.update({"IAP_DATA_DIR": str(tmp), "IAP_DATABASE_URL": f"sqlite:///{tmp / 'x.db'}", "IAP_AI_PROVIDER": "demo",
                   "IAP_PLUGIN_CACHE_PATH": str(Path(__file__).resolve().parent.parent / "var" / "plugin-cache"), "IAP_RATE_LIMIT_PIPELINE_PER_MINUTE": "100"})

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "examples"
ANSWERS = {"environment": "production", "deployment_type": "new", "needs_database": "yes", "traffic": "moderate", "data_sensitivity": "personal",
           "compliance": "none", "data_residency": "none", "region": "us-east-1", "availability": "tolerate_minutes", "tls": "acm",
           "admin_access": "ssm", "audit_logging": "yes", "budget": 400, "industry": "saas", "user_geography": "north_america",
           "app_runtime": "node", "traffic_pattern": "steady", "db_size": "small", "file_uploads": "yes", "recovery_window": "7",
           "log_retention": "90", "ops_team": "some", "alerting": "email", "alert_email": "ops@example.com"}


def wait(c: TestClient, op: str) -> dict:
    while True:
        o = c.get(f"/api/operations/{op}").json()
        if o["status"] not in ("queued", "running"):
            return o
        time.sleep(0.5)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as c:
        c.headers["x-csrf-token"] = c.post("/api/session").json()["csrf_token"]
        pid = c.post("/api/projects", json={"name": "Customer Portal", "request": "I need a secure web application for my customers. It should handle increasing traffic, protect customer information, and cost as little as possible."}).json()["id"]
        while (q := c.get(f"/api/projects/{pid}").json()["interview"]["question"]) is not None:
            c.post(f"/api/projects/{pid}/interview/answer", json={"question_id": q["id"], "value": ANSWERS[q["id"]]})
        comp = c.post(f"/api/projects/{pid}/requirements/compile").json()
        (OUT / "requirements-spec.json").write_text(json.dumps(comp["requirements"], indent=2, default=str))
        c.post(f"/api/projects/{pid}/architecture/select", json={"option_id": "balanced"})
        c.post(f"/api/projects/{pid}/terraform/insecure-change", json={"scenario": "public_database"})
        c.post(f"/api/projects/{pid}/terraform/insecure-change", json={"scenario": "open_ssh"})
        op = wait(c, c.post(f"/api/projects/{pid}/validate").json()["operation_id"])
        assert op["status"] == "succeeded", op
        scan = c.get(f"/api/projects/{pid}/scans/latest").json()
        (OUT / "security-findings-insecure.json").write_text(json.dumps({
            "status": scan["status"], "summary": scan["summary"],
            "failed_policies": [r for r in scan["policy_results"] if r["outcome"] == "fail"],
            "external_advisories_sample": scan["external_findings"][:10],
        }, indent=2))
        for f in ("database.tf", "security_groups.tf"):
            c.delete(f"/api/projects/{pid}/terraform/files/{f}")
        op = wait(c, c.post(f"/api/projects/{pid}/validate").json()["operation_id"])
        assert op["status"] == "succeeded", op
        plan = c.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
        if plan is None:
            print(json.dumps(c.get(f"/api/projects/{pid}/scans/latest").json()["steps"], indent=1)[:3000], file=sys.stderr)
        c.post(f"/api/projects/{pid}/plans/{plan['id']}/approve", json={"plan_sha256": plan["plan_sha256"]})
        wait(c, c.post(f"/api/projects/{pid}/plans/{plan['id']}/apply").json()["operation_id"])
        (OUT / "evidence-report.md").write_text(c.get(f"/api/projects/{pid}/evidence?format=md").text)
        (OUT / "evidence-report.json").write_text(json.dumps(c.get(f"/api/projects/{pid}/evidence").json(), indent=2))
        files = c.get(f"/api/projects/{pid}/terraform").json()["files"]
        tf_dir = OUT / "generated-terraform"
        tf_dir.mkdir(exist_ok=True)
        for name, text in files.items():
            (tf_dir / name).write_text(text)
    print(f"wrote examples to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
