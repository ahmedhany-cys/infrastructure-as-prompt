"""Interview engine, requirements compiler, architecture engine, cost model and traceability."""

from typing import Any

import pytest

from app.domain.findings import PolicyResult
from app.domain.requirements import RequirementStatus, Severity, VerificationLevel
from app.services import interview_engine as ie
from app.services.architect import build_architecture
from app.services.compiler import CompileError, compile_requirements
from app.services.pricing import estimate
from app.services.traceability import apply_scan, apply_verification

BASE = {
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


def interview(overrides: dict[str, Any] | None = None, text: str = "A web app for my customers") -> ie.InterviewState:
    answers = {**BASE, **(overrides or {})}
    st = ie.start(text, ie.extract_hints(text), "demo")
    for _ in range(30):
        q = st.current_question
        if q is None or st.complete:
            break
        ie.record_answer(st, q, answers[q], "user", None, "option")
        if st.current_question == q:  # refused or conflicting
            break
    return st


# --- interview -----------------------------------------------------------------


def test_hints_are_suggestions_not_answers():
    text = "I need a secure web application for my customers that stores customer data and must stay in the EU, about $500/month"
    hints = {h.key: h.value for h in ie.extract_hints(text)}
    assert hints["environment"] == "production" and hints["data_residency"] == "eu" and hints["budget"] == "500"
    st = ie.start(text, ie.extract_hints(text), "demo")
    assert st.answers == {} and st.current_question == "industry"


def test_completes_with_all_answers():
    st = interview()
    assert st.complete and st.current_question is None
    assert set(st.answers) == set(BASE)


def test_adaptive_questions_depend_on_previous_answers():
    st = interview({"data_sensitivity": "public"})
    assert "compliance" not in st.answers  # not asked for public data
    st = interview({"admin_access": "ssh", "admin_cidr": "198.51.100.0/24"})
    assert st.answers["admin_cidr"].value == "198.51.100.0/24"
    st = interview({"compliance": "pci", "data_sensitivity": "regulated", "recovery_window": "35", "log_retention": "365"})
    assert "audit_logging" not in st.answers  # mandatory for PCI, so not asked


def test_unsafe_answers_are_refused_and_recorded():
    st = interview({"tls": "http_only"})
    assert "tls" not in st.answers
    assert st.rejected[-1].question_id == "tls" and st.rejected[-1].rejected_by == "system"


def test_http_only_allowed_for_public_dev():
    st = interview(
        {"environment": "development", "data_sensitivity": "public", "tls": "http_only", "availability": "best_effort", "budget": 200}
    )
    assert st.complete and st.answers["tls"].value == "http_only"
    spec = compile_requirements(st)
    assert spec.by_id("REQ-SEC-003").status == RequirementStatus.not_applicable


def test_contradictory_residency_blocks_completion():
    st = interview({"data_residency": "eu"})
    # region options are filtered to the EU, so us-east-1 is not even a valid option
    assert "region" not in st.answers
    st2 = interview()
    ie.record_answer(st2, "data_residency", "eu", "user", None, "option")
    assert any(c.id == "CF-RESIDENCY" and c.severity == "blocking" for c in st2.conflicts)
    assert not st2.complete


def test_infeasible_budget_is_a_blocking_conflict_with_suggestions():
    st = interview({"budget": 50})
    conflict = next(c for c in st.conflicts if c.id == "CF-BUDGET")
    assert conflict.severity == "blocking" and not st.complete
    assert any("Security controls" in s for s in conflict.suggestions)
    ie.record_answer(st, "budget", 400, "user", None, "option")
    assert st.complete and not st.conflicts


def test_revising_an_answer_prunes_answers_that_no_longer_apply():
    st = interview({"admin_access": "ssh", "admin_cidr": "198.51.100.0/24"})
    ie.record_answer(st, "admin_access", "ssm", "user", None, "option")
    assert "admin_cidr" not in st.answers and st.complete


def test_declined_recommendations_are_tracked():
    st = interview({"admin_access": "none"})
    assert any(r.question_id == "admin_access" and r.rejected_by == "user" for r in st.rejected)


@pytest.mark.parametrize(
    "text,kind,value",
    [
        ("it's for real customers, so production", "answer", "production"),
        ("$1.2k", "answer", 1200.0),
        ("what does that mean?", "explain", None),
        ("whatever you recommend", "accept_recommendation", None),
        ("purple elephants", "unclear", None),
    ],
)
def test_deterministic_free_text_parser(text, kind, value):
    qid = "budget" if "$" in text else "environment"
    st = interview({"budget": 400})
    q = ie.QUESTION_INDEX[qid]
    res = ie.deterministic_interpret(q.view(st), q, text)
    assert res.kind == kind and (value is None or res.value == value)


def test_ambiguous_free_text_is_unclear_not_guessed():
    st = ie.start("x", [], "demo")
    q = ie.QUESTION_INDEX["environment"]
    assert ie.deterministic_interpret(q.view(st), q, "dev or prod").kind == "unclear"


# --- compiler --------------------------------------------------------------------


def test_compiler_refuses_incomplete_interview():
    st = ie.start("x", [], "demo")
    with pytest.raises(CompileError):
        compile_requirements(st)


def test_compiler_produces_traceable_requirements():
    spec = compile_requirements(interview())
    ids = {r.id for r in spec.requirements}
    assert {"REQ-SEC-001", "REQ-SEC-002", "REQ-SEC-003", "REQ-SEC-004", "REQ-CST-001", "REQ-AUD-001", "REQ-OPS-001"} <= ids
    for r in spec.requirements:
        assert r.status in (RequirementStatus.unverified, RequirementStatus.not_applicable)
        assert r.verification_level == VerificationLevel.none
        assert r.policies or r.id == "REQ-CST-001" or r.status == RequirementStatus.not_applicable
    assert spec.by_id("REQ-SEC-001").origin.value == "confirmed"
    assert any(a.id == "A-00" for a in spec.assumptions)


def test_compliance_and_availability_add_requirements():
    spec = compile_requirements(
        interview(
            {
                "data_sensitivity": "regulated",
                "compliance": "pci",
                "availability": "high",
                "budget": 2000,
                "recovery_window": "35",
                "log_retention": "365",
            }
        )
    )
    ids = {r.id for r in spec.requirements}
    assert {"REQ-SEC-009", "REQ-NET-002", "REQ-AVL-002"} <= ids
    assert spec.facts["backup_days"] == 35
    assert any("PCI" in u for u in spec.unresolved)


def test_no_database_means_no_database_requirements():
    spec = compile_requirements(interview({"needs_database": "no"}))
    assert spec.by_id("REQ-SEC-001") is None and spec.by_id("REQ-AVL-003") is None


# --- architecture & cost -----------------------------------------------------------


def test_high_availability_excludes_single_az_option():
    arch = build_architecture(compile_requirements(interview({"availability": "high", "budget": 2000})))
    assert "lean" not in {o.id for o in arch.options}
    assert any(e.id == "lean" and "REQ-AVL-002" in e.reason for e in arch.excluded)


def test_development_excludes_resilient_option():
    arch = build_architecture(compile_requirements(interview({"environment": "development", "budget": 500})))
    assert "resilient" not in {o.id for o in arch.options}


def test_recommendation_respects_budget():
    arch = build_architecture(compile_requirements(interview({"budget": 150})))
    assert arch.recommended == "lean"
    assert next(o for o in arch.options if o.id == "balanced").cost.within_budget is False


def test_cost_estimate_is_labelled_approximate_and_itemised():
    arch = build_architecture(compile_requirements(interview()))
    opt = next(o for o in arch.options if o.id == "balanced")
    c = opt.cost
    assert c.approximate and "not retrieved live" in c.pricing_source
    assert abs(sum(line.monthly_usd for line in c.lines) - c.total_monthly_usd) < 0.05
    items = " ".join(line.item for line in c.lines)
    for expected in ("NAT gateway", "Public IPv4", "Multi-AZ", "Application Load Balancer", "egress"):
        assert expected in items
    assert c.variable_monthly_usd > 0 and c.top_drivers


def test_regional_price_multiplier():
    arch = build_architecture(compile_requirements(interview()))
    p = next(o for o in arch.options if o.id == "lean").params
    us = estimate(p, "moderate", None).total_monthly_usd
    eu = estimate(p.model_copy(update={"region": "eu-central-1"}), "moderate", None).total_monthly_usd
    assert eu > us


def test_diagram_components_reference_generated_terraform():
    from app.services.terraform.generator import generate

    spec = compile_requirements(interview())
    arch = build_architecture(spec)
    opt = next(o for o in arch.options if o.id == "balanced")
    tf = "\n".join(v for k, v in generate("a" * 32, "Acme", spec, opt).items() if k.endswith(".tf"))
    for comp in opt.components:
        for addr in comp.terraform_addresses:
            if addr == "provider.aws":
                continue
            rtype, name = addr.split(".")
            assert f'resource "{rtype}" "{name}"' in tf, f"{comp.id} references missing {addr}"


# --- traceability ----------------------------------------------------------------------


def _result(pid: str, outcome: str) -> PolicyResult:
    return PolicyResult(policy_id=pid, title=pid, severity=Severity.high, category="x", outcome=outcome, message="m")  # type: ignore[arg-type]


def test_traceability_rules():
    spec = compile_requirements(interview())
    opt = next(o for o in build_architecture(spec).options if o.id == "balanced")
    results = [
        _result("POL-RDS-001", "pass"),
        _result("POL-NET-001", "pass"),
        _result("POL-SG-002", "fail"),
        _result("POL-EC2-001", "not_applicable"),
    ]
    spec = apply_scan(spec, results, "scan1", None, opt)
    assert spec.by_id("REQ-SEC-001").status == RequirementStatus.failing
    assert spec.by_id("REQ-SEC-007").status == RequirementStatus.failing  # nothing implements it
    assert spec.by_id("REQ-CST-001").verification_level == VerificationLevel.estimate
    spec = apply_scan(spec, None, None, "terraform validate failed.", opt)
    assert spec.by_id("REQ-SEC-001").status == RequirementStatus.blocked


def test_simulated_checks_never_raise_verification_level():
    spec = compile_requirements(interview())
    opt = next(o for o in build_architecture(spec).options if o.id == "balanced")
    spec = apply_scan(spec, [_result(p, "pass") for p in ("POL-RDS-001", "POL-NET-001", "POL-SG-002")], "s", None, opt)
    check = [{"requirement": "REQ-SEC-001", "check": "c", "source": "simulated-state", "outcome": "pass", "detail": "ok"}]
    spec = apply_verification(spec, check, simulated=True)
    req = spec.by_id("REQ-SEC-001")
    assert req.verification_level == VerificationLevel.static_config
    assert any(e.kind == "simulated_check" and "SIMULATED" in e.detail for e in req.evidence)
    spec = apply_verification(spec, [{**check[0], "source": "aws:rds"}], simulated=False)
    assert spec.by_id("REQ-SEC-001").verification_level == VerificationLevel.live_inspection
    spec = apply_verification(spec, [{**check[0], "outcome": "fail", "source": "aws:rds"}], simulated=False)
    assert spec.by_id("REQ-SEC-001").status == RequirementStatus.failing


# --- customer tailoring ------------------------------------------------------------


def _first_view(text: str, answers: dict[str, Any] | None = None) -> ie.InterviewView:
    st = ie.start(text, ie.extract_hints(text), "demo")
    for qid, value in (answers or {}).items():
        assert ie.record_answer(st, qid, value, "user", None, "option") is None, qid
    return ie.view(st, "demo")


def test_request_text_suggests_customer_profile():
    text = "We run an online store for customers in Europe, built with Django. Users upload images and we expect Black Friday spikes. No dedicated ops team."
    hints = {h.key: h.value for h in ie.extract_hints(text)}
    assert hints["industry"] == "ecommerce" and hints["user_geography"] == "europe" and hints["app_runtime"] == "python"
    assert hints["traffic_pattern"] == "spiky" and hints["file_uploads"] == "yes" and hints["ops_team"] == "none"
    v = _first_view(text)
    assert v.question.id == "industry" and v.question.recommended == "ecommerce" and v.state.answers == {}


def test_industry_and_geography_shape_recommendations():
    st = ie.start("x", [], "demo")
    ie.record_answer(st, "industry", "healthcare", "user", None, "option")
    ie.record_answer(st, "user_geography", "north_america", "user", None, "option")
    assert ie.QUESTION_INDEX["data_sensitivity"].view(st).recommended == "regulated"
    assert ie.record_answer(st, "data_sensitivity", "regulated", "user", None, "option") is None
    assert ie.QUESTION_INDEX["compliance"].view(st).recommended == "hipaa"
    assert ie.QUESTION_INDEX["log_retention"].view(st).recommended == "2192"
    st2 = ie.start("x", [], "demo")
    ie.record_answer(st2, "user_geography", "middle_east_africa", "user", None, "option")
    assert ie.QUESTION_INDEX["region"].view(st2).recommended == "eu-central-1"


def test_tailoring_answers_below_minimums_are_refused():
    st = interview({"recovery_window": "1"})  # production needs >= 7 days
    assert "recovery_window" not in st.answers and st.rejected[-1].question_id == "recovery_window"
    st = interview({"compliance": "pci", "data_sensitivity": "regulated", "recovery_window": "35", "log_retention": "90"})
    assert "log_retention" not in st.answers and "PCI DSS" in st.rejected[-1].reason
    st = interview({"alert_email": "not-an-email"})
    assert "alert_email" not in st.answers


def test_off_hours_question_only_for_business_hours_non_production():
    st = interview({"traffic_pattern": "business_hours"})
    assert "off_hours" not in st.answers  # production
    st = interview({"environment": "staging", "traffic_pattern": "business_hours", "off_hours": "yes"})
    assert st.complete and st.answers["off_hours"].value == "yes"
    spec = compile_requirements(st)
    assert spec.by_id("REQ-CST-002") is not None and spec.facts["schedule_timezone"] == "America/New_York"


def test_free_text_email_answer_is_extracted():
    st = interview({"alerting": "email"})
    q = ie.QUESTION_INDEX["alert_email"]
    view = q.view(st)
    assert ie.deterministic_interpret(view, q, "send them to Team-Ops@example.co.uk please").value == "Team-Ops@example.co.uk"


def test_sections_report_progress():
    v = _first_view("A web app", {"industry": "saas"})
    by_id = {s.id: s for s in v.sections}
    assert list(by_id)[0] == "business" and by_id["business"].answered == 1 and by_id["business"].current
    assert sum(s.total for s in v.sections) == v.progress["total"]
    assert v.question_sections["budget"] == "budget"


def test_tailored_answers_change_architecture_and_cost():
    base = build_architecture(compile_requirements(interview()))
    bal = next(o for o in base.options if o.id == "balanced")
    assert bal.params.app_port == 3000 and bal.params.uploads_bucket and bal.params.alerts
    assert any(c.id == "uploads" for c in bal.components) and any(c.id == "alerts" for c in bal.components)

    java = next(o for o in build_architecture(compile_requirements(interview({"app_runtime": "java"}))).options if o.id == "balanced")
    assert java.params.instance_type == "t4g.large" and java.params.app_port == 8080
    spiky = next(o for o in build_architecture(compile_requirements(interview({"traffic_pattern": "spiky"}))).options if o.id == "balanced")
    assert spiky.params.asg_max == 2 * bal.params.asg_max and spiky.params.scale_out_cpu == 50

    staging = {"environment": "staging", "traffic_pattern": "business_hours"}
    on = build_architecture(compile_requirements(interview({**staging, "off_hours": "no"})))
    off = build_architecture(compile_requirements(interview({**staging, "off_hours": "yes"})))
    on_lean, off_lean = (next(o for o in a.options if o.id == "lean") for a in (on, off))
    ec2 = lambda o: next(line.monthly_usd for line in o.cost.lines if line.item.startswith("EC2"))  # noqa: E731
    assert off_lean.params.scheduled_scaling and ec2(off_lean) < ec2(on_lean) * 0.4

    big_logs = next(o for o in build_architecture(compile_requirements(interview({"log_retention": "365"}))).options if o.id == "lean")
    assert big_logs.params.log_retention_days == 365


def test_no_alerts_in_production_is_flagged():
    st = interview({"alerting": "none"})
    assert st.complete and any(c.id == "CF-NO-ALERTS" and c.severity == "warning" for c in st.conflicts)
