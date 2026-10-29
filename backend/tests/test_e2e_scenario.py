"""End-to-end scenario through the HTTP API, using the real Terraform binary
in simulation mode (placeholder credentials, no AWS calls)."""

import time

import pytest

from tests.conftest import new_session, requires_terraform

REQUEST = (
    "I need a secure web application for my customers. It should handle increasing traffic, "
    "protect customer information, and cost as little as possible."
)

ANSWERS = {
    "industry": "saas",
    "user_geography": "north_america",
    "app_runtime": "node",
    "traffic_pattern": "steady",
    "db_size": "small",
    "file_uploads": "yes",
    "recovery_window": "7",
    "log_retention": "90",
    "ops_team": "some",
    "alerting": "email",
    "alert_email": "ops@example.com",
    "environment": "production",
    "deployment_type": "new",
    "needs_database": "yes",
    "traffic": "moderate",
    "data_sensitivity": "personal",
    "compliance": "none",
    "data_residency": "none",
    "region": "us-east-1",
    "availability": "tolerate_minutes",
    "tls": "acm",
    "admin_access": "ssm",
    "audit_logging": "yes",
    "budget": 400,
}


def wait(api, op_id, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        op = api.get(f"/api/operations/{op_id}").json()
        if op["status"] not in ("queued", "running"):
            return op
        time.sleep(0.5)
    raise AssertionError(f"operation {op_id} did not finish")


def complete_interview(api, pid):
    for _ in range(30):
        view = api.get(f"/api/projects/{pid}").json()["interview"]
        q = view["question"]
        if view["state"]["complete"] or q is None:
            return view
        r = api.post(f"/api/projects/{pid}/interview/answer", json={"question_id": q["id"], "value": ANSWERS[q["id"]]})
        assert r.status_code == 200, r.text
    raise AssertionError("interview did not complete")


def create_validated_project(api, name="Acme Portal"):
    pid = api.post("/api/projects", json={"name": name, "request": REQUEST}).json()["id"]
    complete_interview(api, pid)
    assert api.post(f"/api/projects/{pid}/requirements/compile").status_code == 200
    assert api.post(f"/api/projects/{pid}/architecture/select", json={"option_id": "balanced"}).status_code == 200
    return pid


@requires_terraform
def test_full_requirements_to_evidence_lifecycle(api):
    # 1-2. Request and adaptive interview
    pid = api.post("/api/projects", json={"name": "Acme Portal", "request": REQUEST}).json()["id"]
    first = api.get(f"/api/projects/{pid}").json()["interview"]
    hints = {h["key"]: h["value"] for h in first["state"]["hints"]}
    assert hints["environment"] == "production" and hints["data_sensitivity"] == "personal"
    assert first["state"]["answers"] == {}, "hints must never be treated as confirmed answers"
    # Free-text answer through the deterministic parser
    r = api.post(
        f"/api/projects/{pid}/interview/answer", json={"question_id": "environment", "text": "it's for real customers, so production"}
    )
    assert r.json()["state"]["answers"]["environment"]["value"] == "production"
    view = complete_interview(api, pid)
    assert view["state"]["complete"]

    # 3. Structured requirements
    comp = api.post(f"/api/projects/{pid}/requirements/compile").json()
    reqs = {r["id"]: r for r in comp["requirements"]["requirements"]}
    assert reqs["REQ-SEC-001"]["policies"] == ["POL-RDS-001", "POL-NET-001", "POL-SG-002"]
    assert all(r["status"] in ("unverified", "not_applicable") for r in reqs.values())

    # 4-6. Architecture options and costs
    arch = comp["architecture"]
    assert {o["id"] for o in arch["options"]} >= {"lean", "balanced"}
    for o in arch["options"]:
        assert o["cost"]["approximate"] is True and o["cost"]["total_monthly_usd"] > 0

    # 7. Generate Terraform
    assert api.post(f"/api/projects/{pid}/architecture/select", json={"option_id": "balanced"}).status_code == 200
    files = api.get(f"/api/projects/{pid}/terraform").json()["files"]
    assert "database.tf" in files and "publicly_accessible    = false" in files["database.tf"]

    # 8. Validation and policy scan pass
    op = wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    assert op["status"] == "succeeded", op
    scan = api.get(f"/api/projects/{pid}/scans/latest").json()
    assert scan["status"] == "passed", scan["summary"]
    steps = {s["name"]: s["status"] for s in scan["steps"]}
    assert steps["terraform validate"] == "passed" and steps["terraform plan"] == "passed"
    project = api.get(f"/api/projects/{pid}").json()
    statuses = {r["id"]: r["status"] for r in project["requirements"]["requirements"]}
    assert statuses["REQ-SEC-001"] == "passing"
    assert all(r["verification_level"] in ("static_config", "estimate", "none") for r in project["requirements"]["requirements"])

    # 9. Deliberately insecure change is caught by a real policy failure
    r = api.post(f"/api/projects/{pid}/terraform/insecure-change", json={"scenario": "public_database"})
    assert r.status_code == 200
    op = wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    scan = api.get(f"/api/projects/{pid}/scans/latest").json()
    assert scan["status"] == "blocked"
    fails = [p for p in scan["policy_results"] if p["outcome"] == "fail"]
    assert any(p["policy_id"] == "POL-RDS-001" and p["resource"] == "aws_db_instance.main" for p in fails)
    project = api.get(f"/api/projects/{pid}").json()
    assert {r["id"]: r["status"] for r in project["requirements"]["requirements"]}["REQ-SEC-001"] == "failing"
    blocked_plan = api.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
    assert blocked_plan["status"] == "rejected"
    r = api.post(f"/api/projects/{pid}/plans/{blocked_plan['id']}/approve", json={"plan_sha256": blocked_plan["plan_sha256"]})
    assert r.status_code == 409

    # 10. Correct the configuration and re-run
    assert api.delete(f"/api/projects/{pid}/terraform/files/database.tf").status_code == 200
    wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    assert api.get(f"/api/projects/{pid}/scans/latest").json()["status"] == "passed"

    # 11-12. Review and approve the exact plan, then simulated apply
    plan = api.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
    assert plan["status"] == "pending_review" and plan["review"]["counts"]["create"] > 40
    assert api.post(f"/api/projects/{pid}/plans/{plan['id']}/apply").status_code == 403, "apply without approval must be refused"
    r = api.post(f"/api/projects/{pid}/plans/{plan['id']}/approve", json={"plan_sha256": plan["plan_sha256"]})
    assert r.status_code == 200, r.text
    op = wait(api, api.post(f"/api/projects/{pid}/plans/{plan['id']}/apply").json()["operation_id"])
    assert op["status"] == "succeeded", op
    dep = api.get(f"/api/projects/{pid}/deployments").json()[0]
    assert dep["mode"] == "simulation" and dep["status"] == "succeeded"
    assert all(r["simulated"] for r in dep["resources"])

    # 13. Traceability: simulated checks are evidence but never raise the level
    project = api.get(f"/api/projects/{pid}").json()
    req = {r["id"]: r for r in project["requirements"]["requirements"]}["REQ-SEC-001"]
    assert req["verification_level"] == "static_config"
    assert any(e["kind"] == "simulated_check" for e in req["evidence"])

    # 14. Evidence export
    rep = api.get(f"/api/projects/{pid}/evidence").json()
    assert rep["simulated"] is True
    assert any("SIMULATED" in item for item in rep["limitations"])
    md = api.get(f"/api/projects/{pid}/evidence?format=md").text
    assert "SIMULATION" in md and "REQ-SEC-001" in md

    # Re-validating after deployment yields a no-change plan against the simulated state
    wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    again = api.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
    assert again["review"]["counts"]["create"] == 0 and not again["review"]["destructive"], again["review"]["headline"]

    # 15. Teardown: destructive plan requires explicit acknowledgement + typed name
    wait(api, api.post(f"/api/projects/{pid}/teardown/plan").json()["operation_id"])
    dplan = api.get(f"/api/projects/{pid}/plans").json()["latest_destroy"]
    assert dplan["review"]["destructive"] is True
    r = api.post(f"/api/projects/{pid}/plans/{dplan['id']}/approve", json={"plan_sha256": dplan["plan_sha256"]})
    assert r.status_code == 400
    r = api.post(
        f"/api/projects/{pid}/plans/{dplan['id']}/approve",
        json={"plan_sha256": dplan["plan_sha256"], "acknowledge_destructive": True, "confirmation_text": "Acme Portal"},
    )
    assert r.status_code == 200, r.text
    op = wait(api, api.post(f"/api/projects/{pid}/plans/{dplan['id']}/apply").json()["operation_id"])
    assert op["status"] == "succeeded", op
    assert api.get(f"/api/projects/{pid}").json()["status"] == "torn_down_simulated"


@requires_terraform
def test_plan_changed_after_approval_is_refused(api):
    pid = create_validated_project(api, "Change Guard")
    wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    plan = api.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
    assert api.post(f"/api/projects/{pid}/plans/{plan['id']}/approve", json={"plan_sha256": plan["plan_sha256"]}).status_code == 200
    # Change configuration after approval (benign edit).
    files = api.get(f"/api/projects/{pid}/terraform").json()["files"]
    api.put(f"/api/projects/{pid}/terraform/files/outputs.tf", json={"content": files["outputs.tf"] + "\n# reviewed later\n"})
    r = api.post(f"/api/projects/{pid}/plans/{plan['id']}/apply")
    assert r.status_code == 409 and "configuration changed" in r.json()["detail"]


@requires_terraform
def test_approval_requires_matching_plan_hash(api):
    pid = create_validated_project(api, "Hash Guard")
    wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    plan = api.get(f"/api/projects/{pid}/plans").json()["latest_apply"]
    r = api.post(f"/api/projects/{pid}/plans/{plan['id']}/approve", json={"plan_sha256": "0" * 64})
    assert r.status_code == 409


def test_other_sessions_cannot_access_project(client, api):
    pid = api.post("/api/projects", json={"name": "Private Project", "request": REQUEST}).json()["id"]
    other = new_session(client)
    assert other.get(f"/api/projects/{pid}").status_code == 404
    assert other.post(f"/api/projects/{pid}/validate").status_code == 404
    assert other.post(f"/api/projects/{pid}/plans/whatever/apply").status_code == 404
    assert all(p["id"] != pid for p in other.get("/api/projects").json())


def test_state_changing_requests_require_csrf(client, api):
    pid = api.post("/api/projects", json={"name": "Csrf Check", "request": REQUEST}).json()["id"]
    token = api.headers.pop("x-csrf-token")
    try:
        r = api.post(f"/api/projects/{pid}/interview/answer", json={"question_id": "environment", "value": "production"})
        assert r.status_code == 403
    finally:
        api.headers["x-csrf-token"] = token


def test_unauthenticated_requests_rejected(client):
    from fastapi.testclient import TestClient

    from app.main import app

    anon = TestClient(app)
    assert anon.get("/api/projects").status_code == 401


def test_real_mode_cannot_be_enabled_from_ui(api):
    pid = api.post("/api/projects", json={"name": "Real Mode", "request": REQUEST}).json()["id"]
    r = api.patch(f"/api/projects/{pid}/settings", json={"deployment_mode": "aws"})
    assert r.status_code == 403


@pytest.mark.parametrize("cidr,ok", [("0.0.0.0/0", False), ("10.0.0.0/8", False), ("203.0.113.0/24", True)])
def test_admin_cidr_validation(api, cidr, ok):
    pid = api.post("/api/projects", json={"name": "Cidr Check", "request": REQUEST}).json()["id"]
    for qid, val in [
        ("environment", "production"),
        ("deployment_type", "new"),
        ("needs_database", "yes"),
        ("traffic", "low"),
        ("data_sensitivity", "personal"),
        ("compliance", "none"),
        ("data_residency", "none"),
        ("region", "us-east-1"),
        ("availability", "tolerate_minutes"),
        ("tls", "acm"),
        ("admin_access", "ssh"),
    ]:
        api.post(f"/api/projects/{pid}/interview/answer", json={"question_id": qid, "value": val})
    view = api.post(f"/api/projects/{pid}/interview/answer", json={"question_id": "admin_cidr", "text": cidr}).json()
    assert ("admin_cidr" in view["state"]["answers"]) is ok
    if not ok:
        assert view["state"]["rejected"][-1]["rejected_by"] == "system"


def test_rate_limit_on_expensive_operations():
    from fastapi import HTTPException

    from app.security import RateLimiter

    rl = RateLimiter()
    for _ in range(3):
        rl.check("s1", "pipeline", 3)
    with pytest.raises(HTTPException) as exc:
        rl.check("s1", "pipeline", 3)
    assert exc.value.status_code == 429
    rl.check("s2", "pipeline", 3)  # other sessions are unaffected


@requires_terraform
def test_code_execution_constructs_never_reach_terraform(api, tmp_path):
    marker = tmp_path / "pwned"
    pid = create_validated_project(api, "Safety Gate")
    files = api.get(f"/api/projects/{pid}/terraform").json()["files"]
    evil = files["outputs.tf"] + f'\ndata "external" "x" {{\n  program = ["sh", "-c", "touch {marker}; echo {{}}"]\n}}\n'
    assert api.put(f"/api/projects/{pid}/terraform/files/outputs.tf", json={"content": evil}).status_code == 200
    op = wait(api, api.post(f"/api/projects/{pid}/validate").json()["operation_id"])
    scan = api.get(f"/api/projects/{pid}/scans/latest").json()
    steps = {s["name"]: s["status"] for s in scan["steps"]}
    assert op["status"] == "succeeded" and scan["status"] == "failed"
    assert steps["Configuration safety gate"] == "failed" and "terraform init" not in steps
    assert not marker.exists()
