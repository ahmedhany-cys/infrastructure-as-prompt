"""Adaptive requirements interview.

The question bank, applicability rules, recommendations and conflict checks are
deterministic. An optional AI provider may help interpret free-text answers,
but its output is validated against the current question's allowed values and
can never confirm an answer the user did not give.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.domain.interview import Answer, Hint, InterviewState, InterviewView, Option, QuestionView, SectionProgress, TranscriptEntry
from app.domain.requirements import Conflict, RejectedSuggestion

REGION_LABELS = {
    "us-east-1": "US East (N. Virginia)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
}
EU = ["eu-west-1", "eu-central-1"]
US = ["us-east-1", "us-west-2"]


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Question:
    id: str
    prompt: str
    help: str
    kind: str
    options: list[Option] = field(default_factory=list)
    applies: Callable[[InterviewState], bool] = lambda s: True
    recommend: Callable[[InterviewState], tuple[str | None, str | None]] = lambda s: (None, None)
    affects: list[str] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    unit: str | None = None
    dynamic_options: Callable[[InterviewState], list[Option]] | None = None
    section: str = "business"

    def view(self, state: InterviewState) -> QuestionView:
        rec, why = self.recommend(state)
        return QuestionView(
            id=self.id,
            section=self.section,
            prompt=self.prompt,
            help=self.help,
            kind=self.kind,  # type: ignore[arg-type]
            options=self.dynamic_options(state) if self.dynamic_options else self.options,
            recommended=rec,
            recommendation_reason=why,
            affects=self.affects,
            unit=self.unit,
        )


def _hint(state: InterviewState, key: str) -> Hint | None:
    return next((h for h in state.hints if h.key == key), None)


def _rec_env(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "environment")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    return "production", "Customer-facing services are usually production; choose development if this is for testing."


def _rec_db(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "needs_database")
    return ("yes", f"Your description mentioned “{h.evidence}”.") if h else ("yes", "Most customer-facing applications store data.")


def _rec_traffic(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "traffic")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”; auto scaling handles growth either way."
    return "low", "Start small; auto scaling adds capacity as traffic grows."


def _rec_sensitivity(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "data_sensitivity")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    if s.value("industry") in ("healthcare", "finance"):
        return "regulated", "Health and financial records usually come with legal obligations."
    return "personal", "If you store customer names, emails or accounts, treat it as personal data."


def _rec_compliance(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "compliance")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    industry, geo = s.value("industry"), s.value("user_geography")
    if industry == "healthcare" and geo != "europe":
        return "hipaa", "US healthcare data is usually covered by HIPAA."
    if industry == "finance" and s.value("data_sensitivity") == "regulated":
        return "pci", "Financial services that handle card data are usually in scope for PCI DSS."
    if geo == "europe" and s.value("data_sensitivity") in ("personal", "regulated"):
        return "gdpr", "Personal data of people in Europe is covered by GDPR."
    if s.value("data_sensitivity") == "regulated":
        return None, "Regulated data usually comes with a specific framework; pick the one that applies."
    if industry == "ecommerce":
        return "none", "If a payment provider (for example Stripe) handles card details, your own PCI scope is minimal."
    return "none", "Choose a framework only if a customer, contract or regulator requires it."


def _rec_residency(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "data_residency")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    if s.value("compliance") == "gdpr":
        return "eu", "GDPR does not strictly require EU hosting, but keeping data in the EU simplifies compliance."
    if s.value("industry") == "public_sector" and s.value("user_geography") == "europe":
        return "eu", "European public-sector contracts commonly require EU hosting."
    return "none", "Choose a restriction only if a law or contract requires it."


def _region_options(s: InterviewState) -> list[Option]:
    res = s.value("data_residency")
    allowed = EU if res == "eu" else US if res == "us" else list(REGION_LABELS)
    return [Option(value=r, label=f"{REGION_LABELS[r]} — {r}") for r in allowed]


_REGION_BY_GEOGRAPHY = {
    "north_america": ("us-east-1", "N. Virginia is close to most North American users and has the lowest prices."),
    "europe": ("eu-west-1", "Ireland is central for European users and has the broadest EU service availability."),
    "middle_east_africa": ("eu-central-1", "Frankfurt is the closest supported region to the Middle East and Africa."),
    "asia_pacific": ("us-west-2", "Oregon is the closest supported region to Asia-Pacific users."),
    "global": ("us-east-1", "N. Virginia has the broadest service availability; a CDN can bring content closer to users later."),
}


def _rec_region(s: InterviewState) -> tuple[str | None, str | None]:
    res = s.value("data_residency")
    geo = s.value("user_geography")
    if res == "eu":
        if geo == "middle_east_africa":
            return "eu-central-1", "Frankfurt is the EU region closest to your users."
        return "eu-west-1", "Ireland offers the broadest service availability in the EU."
    if res == "us":
        if geo == "asia_pacific":
            return "us-west-2", "Oregon is the US region closest to your users."
        return "us-east-1", "N. Virginia has the lowest prices and broadest service availability."
    if geo in _REGION_BY_GEOGRAPHY:
        return _REGION_BY_GEOGRAPHY[geo]
    return "us-east-1", "N. Virginia has the lowest prices and broadest service availability."


def _rec_availability(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "availability")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    if s.value("environment") == "development":
        return "best_effort", "Development environments rarely justify paying for redundancy."
    if s.value("environment") == "production" and s.value("industry") in ("ecommerce", "finance", "healthcare"):
        return "high", "In your industry every minute of downtime is lost sales or delayed care."
    return (
        "tolerate_minutes",
        "A good balance for most small businesses; choose 'not acceptable' if every minute of downtime costs you customers.",
    )


def _rec_tls(s: InterviewState) -> tuple[str | None, str | None]:
    return "acm", "HTTPS protects your users' data and is free with AWS Certificate Manager."


def _rec_admin(s: InterviewState) -> tuple[str | None, str | None]:
    return "ssm", "Session Manager needs no open ports or SSH keys, and access is controlled with IAM."


def _rec_audit(s: InterviewState) -> tuple[str | None, str | None]:
    if s.value("environment") == "production" or s.value("data_sensitivity") in ("personal", "regulated"):
        return "yes", "You'll need it to investigate incidents involving customer data; the first trail is free."
    return "yes", "Costs almost nothing and answers “who changed what?”."


def _rec_budget(s: InterviewState) -> tuple[str | None, str | None]:
    from app.services.architect import minimum_viable_cost
    from app.services.compiler import compile_requirements

    try:
        draft = compile_requirements(s, require_complete=False)
    except Exception:  # noqa: BLE001 - a recommendation is optional; never block the interview on it
        return None, None
    mv = minimum_viable_cost(draft)
    if not mv:
        return None, None
    cost, name = mv
    suggestion = int(round(cost * 1.25 / 10.0) * 10)
    hint = _hint(s, "budget")
    if hint:
        return (
            hint.value,
            f"You mentioned {hint.evidence}. The cheapest option that meets your requirements is about ${cost:,.0f}/month ({name}).",
        )
    return str(
        suggestion
    ), f"The cheapest option meeting your requirements is about ${cost:,.0f}/month ({name}); this adds ~25% headroom for variable charges."


def _rec_industry(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "industry")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    return None, "Your industry shapes the defaults I suggest for data protection, compliance and log retention."


def _rec_geography(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "user_geography")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    return None, "Hosting close to your users lowers latency; I'll suggest a region from this."


def _rec_runtime(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "app_runtime")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    return None, "Pick the closest match; it sets the server size and the port the load balancer forwards to."


def _rec_pattern(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "traffic_pattern")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    if s.value("industry") in ("public_sector", "agency") or s.value("environment") in ("development", "staging"):
        return "business_hours", "Internal and pre-production systems are mostly used during working hours."
    return "steady", "The safest assumption if you are unsure; auto scaling still reacts to load either way."


def _rec_off_hours(s: InterviewState) -> tuple[str | None, str | None]:
    return (
        "yes",
        "Servers that nobody uses at night cost money. Scaling to zero from 19:00 to 07:00 and at weekends cuts compute cost by about 64%.",
    )


def _rec_db_size(s: InterviewState) -> tuple[str | None, str | None]:
    return "small", "Storage grows automatically up to five times the starting size, so starting small is safe."


def _rec_uploads(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "file_uploads")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    if s.value("industry") in ("ecommerce", "education", "healthcare"):
        return "yes", "Applications in your industry usually store files (product images, course material, documents)."
    return "no", "Only needed if users upload or download files; you can add it later."


def _min_backup_days(s: InterviewState) -> int:
    if s.value("compliance") in ("hipaa", "pci"):
        return 35
    if s.value("environment") == "production":
        return 7
    return 1


def _rec_recovery(s: InterviewState) -> tuple[str | None, str | None]:
    if s.value("compliance") in ("hipaa", "pci"):
        return "35", "Your compliance framework calls for the longest available point-in-time recovery window."
    if s.value("availability") == "high" or s.value("industry") in ("finance", "healthcare"):
        return "14", "Two weeks gives time to notice silent data corruption before the last good backup expires."
    if s.value("environment") == "production":
        return "7", "One week covers most accidental deletions; backups up to the database size are free."
    return "1", "Development data can usually be recreated."


def _min_log_days(s: InterviewState) -> int:
    return 365 if s.value("compliance") == "pci" else 1


def _rec_log_retention(s: InterviewState) -> tuple[str | None, str | None]:
    if s.value("compliance") == "pci":
        return "365", "PCI DSS requires at least twelve months of audit log history."
    if s.value("compliance") == "hipaa" or s.value("industry") == "healthcare":
        return "2192", "HIPAA requires six years of compliance documentation; many teams keep audit logs as long."
    if s.value("industry") in ("finance", "public_sector"):
        return "365", "Regulators in your industry commonly expect a year of logs."
    if s.value("environment") == "production":
        return "90", "Three months covers most incident investigations at low storage cost."
    return "30", "Short retention keeps storage cost down for non-production environments."


def _rec_ops_team(s: InterviewState) -> tuple[str | None, str | None]:
    h = _hint(s, "ops_team")
    if h:
        return h.value, f"Your description mentioned “{h.evidence}”."
    return None, "This changes how much automation I recommend (alerts, automatic failover)."


def _rec_alerting(s: InterviewState) -> tuple[str | None, str | None]:
    if s.value("environment") == "production" or s.value("ops_team") == "none":
        return "email", "Without alerts, the first sign of an outage is usually a customer complaint."
    return "none", "Alerts for a non-production environment are often noise; you can add them later."


_BASE_QUESTIONS: list[Question] = [
    Question(
        id="environment",
        prompt="Is this a development/test environment or a production service used by real customers?",
        help="Production environments get stronger protection: deletion protection on the database, longer backups and at least two servers. Development environments optimise for cost.",
        kind="choice",
        options=[
            Option(value="development", label="Development / testing", description="Internal use, can be rebuilt"),
            Option(value="staging", label="Staging", description="Pre-production copy"),
            Option(value="production", label="Production", description="Real customers rely on it"),
        ],
        recommend=_rec_env,
        affects=["availability", "cost", "security"],
        synonyms={
            "development": ["dev", "development", "test", "testing", "prototype", "poc", "sandbox"],
            "staging": ["staging", "stage", "pre-prod", "preprod", "uat"],
            "production": ["prod", "production", "live", "customers", "real users"],
        },
    ),
    Question(
        id="deployment_type",
        prompt="Is this a brand-new deployment, or do you already have this application running in AWS?",
        help="For an existing environment, Terraform must first 'import' the resources it should manage. Otherwise it would try to create duplicates. This MVP only creates new, separate environments.",
        kind="choice",
        options=[Option(value="new", label="New deployment"), Option(value="existing", label="Existing environment")],
        recommend=lambda s: ("new", "Nothing will be changed in any existing environment."),
        affects=["change safety"],
        synonyms={
            "new": ["new", "fresh", "greenfield", "from scratch", "nothing yet"],
            "existing": ["existing", "already", "migrate", "running"],
        },
    ),
    Question(
        id="existing_ack",
        prompt="Importing existing resources isn't supported yet. Should I design a separate new environment instead (your current resources won't be touched)?",
        help="Creating a separate environment lets you test the new design safely and migrate later. Your existing resources will not be read, modified or deleted.",
        kind="choice",
        options=[
            Option(value="separate", label="Yes, create a separate new environment"),
            Option(value="stop", label="No, I need to manage my existing resources"),
        ],
        applies=lambda s: s.value("deployment_type") == "existing",
        recommend=lambda s: ("separate", "Safe: nothing existing is changed."),
        affects=["change safety"],
        synonyms={"separate": ["yes", "separate", "new one", "ok", "sure"], "stop": ["no", "stop", "manage existing", "import"]},
    ),
    Question(
        id="needs_database",
        prompt="Does the application need a relational database (for example to store customer accounts or orders)?",
        help="A managed PostgreSQL database (Amazon RDS) handles backups, patching and encryption for you. It is placed in isolated subnets that the internet cannot reach.",
        kind="choice",
        options=[Option(value="yes", label="Yes, PostgreSQL"), Option(value="no", label="No database")],
        recommend=_rec_db,
        affects=["architecture", "cost", "security"],
        synonyms={
            "yes": ["yes", "postgres", "postgresql", "database", "db", "sql", "mysql"],
            "no": ["no", "none", "stateless", "no database"],
        },
    ),
    Question(
        id="traffic",
        prompt="Roughly how much traffic do you expect at launch?",
        help="This sizes servers and the database. Auto scaling adds servers when they get busy, so you don't have to be exact. 10 requests/second is roughly a few thousand active users per day.",
        kind="choice",
        options=[
            Option(value="low", label="Low", description="Up to ~10 requests/second"),
            Option(value="moderate", label="Moderate", description="~10–100 requests/second"),
            Option(value="high", label="High", description="~100–500 requests/second"),
        ],
        recommend=_rec_traffic,
        affects=["performance", "cost"],
        synonyms={
            "low": ["low", "small", "few", "hundreds", "light", "not much"],
            "moderate": ["moderate", "medium", "thousands", "growing"],
            "high": ["high", "heavy", "lots", "millions", "large"],
        },
    ),
    Question(
        id="data_sensitivity",
        prompt="What kind of data will the application store?",
        help="'Personal data' is anything that identifies a person: names, emails, addresses. 'Regulated' covers payment cards, health records or similar data with legal obligations. Sensitivity drives encryption, isolation and audit requirements.",
        kind="choice",
        options=[
            Option(value="public", label="Public information only"),
            Option(value="internal", label="Internal business data"),
            Option(value="personal", label="Customers' personal data"),
            Option(value="regulated", label="Regulated data (payments, health)"),
        ],
        recommend=_rec_sensitivity,
        affects=["security", "compliance"],
        synonyms={
            "public": ["public", "nothing sensitive", "open data"],
            "internal": ["internal", "business", "company"],
            "personal": ["personal", "pii", "customer data", "customer information", "emails", "names"],
            "regulated": ["regulated", "payment", "card", "health", "medical", "hipaa", "pci"],
        },
    ),
    Question(
        id="compliance",
        prompt="Do you have to meet a specific compliance framework?",
        help="Frameworks add specific controls (for example longer backups, audit trails or a web application firewall). The generated infrastructure supports these controls but cannot by itself make you compliant or certified.",
        kind="choice",
        options=[
            Option(value="none", label="None that I know of"),
            Option(value="gdpr", label="GDPR"),
            Option(value="hipaa", label="HIPAA"),
            Option(value="pci", label="PCI DSS"),
            Option(value="other", label="Other / not sure"),
        ],
        applies=lambda s: s.value("data_sensitivity") in ("personal", "regulated"),
        recommend=_rec_compliance,
        affects=["compliance", "security", "cost"],
        synonyms={
            "none": ["none", "no", "nothing"],
            "gdpr": ["gdpr", "europe privacy"],
            "hipaa": ["hipaa", "health"],
            "pci": ["pci", "card", "payments"],
            "other": ["other", "not sure", "soc"],
        },
    ),
    Question(
        id="data_residency",
        prompt="Must the data stay within a particular geography?",
        help="Data residency restricts which AWS regions can be used. The restriction is enforced by Terraform variable validation and a deployment-blocking policy.",
        kind="choice",
        options=[
            Option(value="none", label="No restriction"),
            Option(value="eu", label="Must stay in the EU"),
            Option(value="us", label="Must stay in the US"),
        ],
        recommend=_rec_residency,
        affects=["compliance", "region"],
        synonyms={
            "none": ["no", "none", "anywhere", "doesn't matter"],
            "eu": ["eu", "europe", "european"],
            "us": ["us", "usa", "united states", "america"],
        },
    ),
    Question(
        id="region",
        prompt="Which AWS region should host the application?",
        help="Pick the region closest to your customers. Prices differ slightly between regions.",
        kind="choice",
        options=[Option(value=r, label=f"{REGION_LABELS[r]} — {r}") for r in REGION_LABELS],
        dynamic_options=_region_options,
        recommend=_rec_region,
        affects=["latency", "cost", "compliance"],
        synonyms={
            "us-east-1": ["us-east-1", "virginia", "us east"],
            "us-west-2": ["us-west-2", "oregon", "us west"],
            "eu-west-1": ["eu-west-1", "ireland", "dublin"],
            "eu-central-1": ["eu-central-1", "frankfurt", "germany"],
        },
    ),
    Question(
        id="availability",
        prompt="Can the service tolerate brief interruptions?",
        help="An 'availability zone' is a separate data centre within a region. Surviving a zone outage requires a standby database in a second zone (Multi-AZ), which roughly doubles database cost.",
        kind="choice",
        options=[
            Option(value="best_effort", label="Yes, even hours of downtime is acceptable"),
            Option(value="tolerate_minutes", label="Short outages (minutes to an hour) are acceptable"),
            Option(value="high", label="No, it must keep running if a data centre fails"),
        ],
        recommend=_rec_availability,
        affects=["availability", "cost"],
        synonyms={
            "best_effort": ["hours", "doesn't matter", "best effort", "yes"],
            "tolerate_minutes": ["minutes", "short", "brief", "some"],
            "high": ["no", "never", "always", "24/7", "high availability", "must"],
        },
    ),
    Question(
        id="tls",
        prompt="Will users connect over HTTPS using a certificate for your domain?",
        help="HTTPS encrypts traffic between users and your application. AWS Certificate Manager issues public certificates for free; you need a domain you control to validate it.",
        kind="choice",
        options=[
            Option(value="acm", label="Yes, HTTPS with an ACM certificate"),
            Option(value="http_only", label="No, plain HTTP (internal demo only)"),
        ],
        recommend=_rec_tls,
        affects=["security"],
        synonyms={"acm": ["yes", "https", "tls", "ssl", "acm", "certificate"], "http_only": ["no", "http", "plain"]},
    ),
    Question(
        id="admin_access",
        prompt="How should your team access servers for maintenance?",
        help="Session Manager opens a shell through the AWS console or CLI without any inbound ports. SSH requires an open port, so it is only allowed from a specific network range you name.",
        kind="choice",
        options=[
            Option(value="ssm", label="AWS Systems Manager Session Manager (no open ports)"),
            Option(value="ssh", label="SSH from a specific office/VPN network"),
            Option(value="none", label="No server access needed"),
        ],
        recommend=_rec_admin,
        affects=["security"],
        synonyms={
            "ssm": ["ssm", "session manager", "systems manager", "recommended"],
            "ssh": ["ssh", "putty", "terminal"],
            "none": ["none", "no access", "never"],
        },
    ),
    Question(
        id="admin_cidr",
        prompt="Which network range should be allowed to use SSH? (CIDR notation, e.g. 203.0.113.0/24)",
        help="Use your office or VPN's public IP range. A /32 is a single address. 0.0.0.0/0 (the whole internet) is not allowed.",
        kind="text",
        applies=lambda s: s.value("admin_access") == "ssh",
        affects=["security"],
    ),
    Question(
        id="audit_logging",
        prompt="Do you need an audit trail of who changed what in your AWS account?",
        help="AWS CloudTrail records every API call (who, what, when, from where). The first trail is free; you pay only for log storage.",
        kind="choice",
        options=[Option(value="yes", label="Yes, record an audit trail"), Option(value="no", label="No")],
        applies=lambda s: s.value("compliance") not in ("hipaa", "pci"),
        recommend=_rec_audit,
        affects=["compliance", "security"],
        synonyms={"yes": ["yes", "audit", "sure", "please"], "no": ["no", "not needed"]},
    ),
    Question(
        id="budget",
        prompt="What monthly AWS budget should the architecture target (USD)?",
        help="I'll compare architecture options against this number. Estimates are approximate; variable charges like data transfer depend on usage. Security controls are never removed to meet a budget.",
        kind="number",
        unit="USD / month",
        recommend=_rec_budget,
        affects=["cost", "architecture"],
    ),
]

SECTIONS: list[tuple[str, str, str]] = [
    ("business", "Your business", "Who it is for and where your users are"),
    ("application", "Your application", "How it is built and how people use it"),
    ("data", "Data & compliance", "What you store and the rules that apply"),
    ("resilience", "Uptime & recovery", "How much downtime and data loss you can accept"),
    ("security", "Security & access", "How people and systems get in, and what is recorded"),
    ("operations", "Operations", "Who runs it and how they hear about problems"),
    ("budget", "Budget", "What it should cost each month"),
]

RUNTIME_PORTS = {"node": 3000, "python": 8000, "java": 8080, "dotnet": 5000, "go": 8080, "php": 8080, "ruby": 3000, "other": 8080}
MEMORY_HEAVY_RUNTIMES = {"java", "dotnet"}

NEW_QUESTIONS_BUSINESS = [
    Question(
        id="industry",
        section="business",
        prompt="Which best describes the business this application is for?",
        help="Different industries carry different expectations for data protection, uptime and record keeping. I use your answer to tailor the defaults I recommend; it never weakens a security control.",
        kind="choice",
        options=[
            Option(value="saas", label="Software / SaaS product", description="An app your customers sign in to"),
            Option(value="ecommerce", label="Online store / e-commerce", description="Catalogue, cart, orders"),
            Option(value="healthcare", label="Healthcare", description="Clinics, patients, health records"),
            Option(value="finance", label="Financial services", description="Payments, banking, insurance"),
            Option(value="education", label="Education", description="Schools, courses, students"),
            Option(value="public_sector", label="Government / public sector", description="Citizen or council services"),
            Option(value="agency", label="Agency building for a client", description="You deliver it for someone else"),
            Option(value="other", label="Something else"),
        ],
        recommend=_rec_industry,
        affects=["recommendations", "compliance", "retention"],
        synonyms={
            "saas": ["saas", "software", "platform", "subscription", "b2b"],
            "ecommerce": ["ecommerce", "e-commerce", "shop", "store", "retail", "webshop"],
            "healthcare": ["health", "healthcare", "clinic", "hospital", "medical", "patients"],
            "finance": ["finance", "financial", "bank", "banking", "fintech", "insurance"],
            "education": ["education", "school", "university", "courses", "students", "learning"],
            "public_sector": ["government", "public sector", "council", "municipal"],
            "agency": ["agency", "client", "consultancy"],
            "other": ["other", "something else"],
        },
    ),
    Question(
        id="user_geography",
        section="business",
        prompt="Where are most of the people who will use it?",
        help="Requests travel faster to a nearby region. This only shapes the region I suggest; any legal requirement about where data must live is asked separately.",
        kind="choice",
        options=[
            Option(value="north_america", label="North America"),
            Option(value="europe", label="Europe"),
            Option(value="middle_east_africa", label="Middle East & Africa"),
            Option(value="asia_pacific", label="Asia-Pacific"),
            Option(value="global", label="Spread around the world"),
        ],
        recommend=_rec_geography,
        affects=["region", "latency"],
        synonyms={
            "north_america": ["north america", "us", "usa", "america", "canada", "united states"],
            "europe": ["europe", "eu", "uk", "germany", "france", "ireland"],
            "middle_east_africa": ["middle east", "africa", "egypt", "uae", "dubai", "saudi", "gulf"],
            "asia_pacific": ["asia", "apac", "australia", "india", "singapore", "japan"],
            "global": ["global", "worldwide", "everywhere", "international"],
        },
    ),
]

NEW_QUESTIONS_APPLICATION_A = [
    Question(
        id="app_runtime",
        section="application",
        prompt="What is the application built with?",
        help="The runtime decides how much memory the servers need and which port the load balancer forwards traffic to. JVM and .NET applications get a larger instance size because they reserve more memory.",
        kind="choice",
        options=[
            Option(value="node", label="Node.js", description="Express, Next.js, NestJS"),
            Option(value="python", label="Python", description="Django, Flask, FastAPI"),
            Option(value="java", label="Java / Kotlin", description="Spring Boot, Quarkus"),
            Option(value="dotnet", label=".NET", description="ASP.NET Core on Linux"),
            Option(value="go", label="Go"),
            Option(value="php", label="PHP", description="Laravel, Symfony, WordPress"),
            Option(value="ruby", label="Ruby", description="Rails"),
            Option(value="other", label="Other / not decided yet"),
        ],
        recommend=_rec_runtime,
        affects=["server size", "cost"],
        synonyms={
            "node": ["node", "nodejs", "node.js", "express", "next.js", "nextjs", "javascript", "typescript", "nest"],
            "python": ["python", "django", "flask", "fastapi"],
            "java": ["java", "kotlin", "spring", "jvm", "quarkus"],
            "dotnet": [".net", "dotnet", "asp.net", "c#", "csharp"],
            "go": ["go", "golang"],
            "php": ["php", "laravel", "symfony", "wordpress"],
            "ruby": ["ruby", "rails"],
            "other": ["other", "not decided", "undecided"],
        },
    ),
]

NEW_QUESTIONS_APPLICATION_B = [
    Question(
        id="traffic_pattern",
        section="application",
        prompt="How does your traffic behave over a typical week?",
        help="Steady traffic needs a stable baseline. Sudden spikes need room to scale out quickly, so I allow twice as many servers and scale earlier (at 50% CPU instead of 60%). Business-hours traffic lets non-production servers switch off at night.",
        kind="choice",
        options=[
            Option(value="steady", label="Fairly steady, day and night"),
            Option(value="business_hours", label="Busy in working hours, quiet at night and weekends"),
            Option(value="spiky", label="Sudden spikes", description="Campaigns, launches, ticket sales, seasonal peaks"),
        ],
        recommend=_rec_pattern,
        affects=["scaling", "cost"],
        synonyms={
            "steady": ["steady", "constant", "24/7", "around the clock", "flat"],
            "business_hours": ["business hours", "office hours", "working hours", "daytime", "9 to 5", "weekdays"],
            "spiky": ["spiky", "spikes", "peaks", "bursts", "campaign", "black friday", "launch", "seasonal"],
        },
    ),
    Question(
        id="off_hours",
        section="application",
        prompt="Should the servers switch off outside business hours to save money?",
        help="Scheduled scaling sets the server count to zero at 19:00 and back at 07:00 on weekdays (in the region's time zone), and keeps them off at weekends. The database keeps running, so no data is lost; the application is simply unavailable overnight.",
        kind="choice",
        options=[
            Option(value="yes", label="Yes, switch off nights and weekends"),
            Option(value="no", label="No, keep them running"),
        ],
        applies=lambda s: s.value("environment") in ("development", "staging") and s.value("traffic_pattern") == "business_hours",
        recommend=_rec_off_hours,
        affects=["cost", "availability"],
        synonyms={"yes": ["yes", "switch off", "turn off", "save", "sure"], "no": ["no", "keep", "always on"]},
    ),
]

NEW_QUESTIONS_APPLICATION_C = [
    Question(
        id="db_size",
        section="application",
        prompt="How much data do you expect the database to hold after its first year?",
        help="This sets the starting disk size. Storage auto scaling grows it up to five times that size without downtime, so a rough estimate is fine. 1 GB holds roughly a million typical customer records.",
        kind="choice",
        options=[
            Option(value="small", label="Under 20 GB", description="Most new applications"),
            Option(value="medium", label="20–100 GB", description="Hundreds of thousands of customers or rich order history"),
            Option(value="large", label="100–500 GB", description="Large catalogues, analytics or event data"),
        ],
        applies=lambda s: s.value("needs_database") == "yes",
        recommend=_rec_db_size,
        affects=["cost", "database"],
        synonyms={
            "small": ["small", "little", "under 20", "few gb", "not much"],
            "medium": ["medium", "moderate", "20", "50", "100 gb"],
            "large": ["large", "big", "lots", "hundreds of gb", "500"],
        },
    ),
    Question(
        id="file_uploads",
        section="application",
        prompt="Will users upload or download files, such as images, documents or exports?",
        help="Files belong in object storage rather than on servers that get replaced. I'll add a private, encrypted, versioned S3 bucket that only the application's role can read and write; it is never publicly readable.",
        kind="choice",
        options=[
            Option(value="yes", label="Yes, store files in a private S3 bucket"),
            Option(value="no", label="No file storage needed"),
        ],
        recommend=_rec_uploads,
        affects=["architecture", "security", "cost"],
        synonyms={
            "yes": ["yes", "uploads", "upload", "images", "photos", "documents", "files", "attachments", "pdf"],
            "no": ["no", "none", "not needed"],
        },
    ),
]

NEW_QUESTIONS_RESILIENCE = [
    Question(
        id="recovery_window",
        section="resilience",
        prompt="If data is deleted or corrupted by mistake, how far back might you need to restore?",
        help="Amazon RDS keeps automated backups with point-in-time recovery to any second within this window. Longer windows protect against problems you notice late; backup storage up to the size of the database is free.",
        kind="choice",
        options=[
            Option(value="1", label="1 day"),
            Option(value="7", label="7 days"),
            Option(value="14", label="14 days"),
            Option(value="35", label="35 days (the maximum)"),
        ],
        applies=lambda s: s.value("needs_database") == "yes",
        recommend=_rec_recovery,
        affects=["recovery", "cost"],
        synonyms={
            "1": ["1 day", "one day", "a day", "yesterday"],
            "7": ["7", "week", "one week", "7 days"],
            "14": ["14", "two weeks", "fortnight", "14 days"],
            "35": ["35", "month", "maximum", "max", "as long as possible"],
        },
    ),
]

NEW_QUESTIONS_SECURITY = [
    Question(
        id="log_retention",
        section="security",
        prompt="How long must logs (access, network and audit logs) be kept?",
        help="Logs are evidence when you investigate an incident or answer an auditor. Older logs are deleted automatically after this period; longer retention costs a little more storage.",
        kind="choice",
        options=[
            Option(value="30", label="30 days"),
            Option(value="90", label="90 days"),
            Option(value="365", label="1 year"),
            Option(value="2192", label="6 years"),
        ],
        recommend=_rec_log_retention,
        affects=["compliance", "cost"],
        synonyms={
            "30": ["30", "month", "one month"],
            "90": ["90", "three months", "quarter"],
            "365": ["365", "year", "one year", "12 months"],
            "2192": ["6 years", "six years", "2192", "long"],
        },
    ),
]

NEW_QUESTIONS_OPERATIONS = [
    Question(
        id="ops_team",
        section="operations",
        prompt="Who will look after this infrastructure day to day?",
        help="Teams without a dedicated operations person benefit most from automation: alerts, automatic database failover and managed patching. This shapes what I recommend.",
        kind="choice",
        options=[
            Option(value="none", label="Nobody dedicated", description="Developers handle it alongside other work"),
            Option(value="some", label="A developer with some AWS experience"),
            Option(value="experienced", label="An experienced DevOps / cloud team"),
        ],
        recommend=_rec_ops_team,
        affects=["recommendations", "operations"],
        synonyms={
            "none": ["nobody", "no one", "none", "no ops", "no devops", "just developers", "me"],
            "some": ["some", "a developer", "a bit", "basic"],
            "experienced": ["experienced", "devops team", "sre", "cloud team", "platform team"],
        },
    ),
    Question(
        id="alerting",
        section="operations",
        prompt="Should someone be emailed when the application is unhealthy?",
        help="CloudWatch alarms watch for server errors, unhealthy servers and (if you have one) database CPU and free disk space, and send an email through an encrypted SNS topic. AWS asks the recipient to confirm the subscription once.",
        kind="choice",
        options=[
            Option(value="email", label="Yes, send email alerts"),
            Option(value="none", label="No alerts for now"),
        ],
        recommend=_rec_alerting,
        affects=["operations", "availability"],
        synonyms={"email": ["yes", "email", "alerts", "notify", "please"], "none": ["no", "none", "not now", "skip"]},
    ),
    Question(
        id="alert_email",
        section="operations",
        prompt="Which email address should receive the alerts?",
        help="Use a shared address such as a team mailbox, so alerts still arrive when someone is away. It is written into the Terraform configuration as a variable.",
        kind="text",
        applies=lambda s: s.value("alerting") == "email",
        affects=["operations"],
    ),
]

_SECTION_OF_BASE = {
    "environment": "business",
    "deployment_type": "business",
    "existing_ack": "business",
    "traffic": "application",
    "needs_database": "application",
    "data_sensitivity": "data",
    "compliance": "data",
    "data_residency": "data",
    "region": "data",
    "availability": "resilience",
    "tls": "security",
    "admin_access": "security",
    "admin_cidr": "security",
    "audit_logging": "security",
    "budget": "budget",
}
for _q in _BASE_QUESTIONS:
    _q.section = _SECTION_OF_BASE[_q.id]

_ALL = {
    q.id: q
    for q in [
        *_BASE_QUESTIONS,
        *NEW_QUESTIONS_BUSINESS,
        *NEW_QUESTIONS_APPLICATION_A,
        *NEW_QUESTIONS_APPLICATION_B,
        *NEW_QUESTIONS_APPLICATION_C,
        *NEW_QUESTIONS_RESILIENCE,
        *NEW_QUESTIONS_SECURITY,
        *NEW_QUESTIONS_OPERATIONS,
    ]
}
# Asking order: sections in sequence; dependent questions directly after the answer they depend on.
QUESTION_ORDER = [
    "industry",
    "user_geography",
    "environment",
    "deployment_type",
    "existing_ack",
    "app_runtime",
    "traffic",
    "traffic_pattern",
    "off_hours",
    "needs_database",
    "db_size",
    "file_uploads",
    "data_sensitivity",
    "compliance",
    "data_residency",
    "region",
    "availability",
    "recovery_window",
    "tls",
    "admin_access",
    "admin_cidr",
    "audit_logging",
    "log_retention",
    "ops_team",
    "alerting",
    "alert_email",
    "budget",
]
QUESTIONS: list[Question] = [_ALL[qid] for qid in QUESTION_ORDER]
QUESTION_INDEX = {q.id: q for q in QUESTIONS}

# ---------------------------------------------------------------------------
# Deterministic hint extraction and answer parsing
# ---------------------------------------------------------------------------

_HINT_RULES: list[tuple[str, str, str]] = [
    ("environment", "production", r"\b(production|live|real customers|my customers|our customers|customer-facing)\b"),
    ("environment", "staging", r"\b(staging|pre-?production|uat)\b"),
    ("environment", "development", r"\b(dev|development|testing|prototype|proof of concept|poc|sandbox)\b"),
    ("needs_database", "yes", r"\b(database|postgres(?:ql)?|mysql|store (?:customer|user|order)s?|records|accounts|orders)\b"),
    ("data_sensitivity", "regulated", r"\b(payments?|credit cards?|card data|health|medical|patients?)\b"),
    (
        "data_sensitivity",
        "personal",
        r"\b(customer information|customer data|personal (?:data|information)|pii|protect customer|user data)\b",
    ),
    ("compliance", "hipaa", r"\bhipaa\b"),
    ("compliance", "pci", r"\bpci\b"),
    ("compliance", "gdpr", r"\bgdpr\b"),
    ("data_residency", "eu", r"\b(eu|europe|european union|gdpr)\b"),
    ("traffic", "moderate", r"\b(increasing traffic|growing traffic|scale|scalable|spikes|grow)\b"),
    ("availability", "high", r"\b(high availability|highly available|no downtime|always (?:on|available)|24/7)\b"),
    ("cost", "minimise", r"\b(as little as possible|cheap|low[- ]cost|inexpensive|tight budget|cost-effective)\b"),
    ("industry", "ecommerce", r"\b(online (?:store|shop)|e-?commerce|webshop|marketplace|checkout|product catalog(?:ue)?)\b"),
    ("industry", "healthcare", r"\b(clinics?|hospitals?|patients?|healthcare|telehealth|medical practice)\b"),
    ("industry", "finance", r"\b(bank(?:ing)?|fintech|loans?|insurance|trading platform|wealth management)\b"),
    ("industry", "education", r"\b(schools?|students?|universit(?:y|ies)|e-?learning|online courses)\b"),
    ("industry", "public_sector", r"\b(government|municipal(?:ity)?|public sector|city council|citizens)\b"),
    ("industry", "saas", r"\b(saas|subscription software|b2b platform)\b"),
    ("industry", "agency", r"\b(for (?:a|our) client|client project|agency)\b"),
    ("user_geography", "europe", r"\b((?:users|customers) (?:in|across) (?:europe|the eu|the uk)|european (?:users|customers))\b"),
    (
        "user_geography",
        "north_america",
        r"\b((?:users|customers) in (?:the us|america|north america|canada)|(?:american|us|canadian) (?:users|customers))\b",
    ),
    ("user_geography", "middle_east_africa", r"\b(middle east|africa|egypt|uae|dubai|saudi|gulf region|gcc)\b"),
    ("user_geography", "asia_pacific", r"\b(asia|apac|australia|india|singapore|japan)\b"),
    ("user_geography", "global", r"\b(global(?:ly)?|worldwide|international(?:ly)?)\b"),
    ("app_runtime", "node", r"\b(node(?:\.js|js)?|express(?:\.js)?|next\.js|nestjs)\b"),
    ("app_runtime", "python", r"\b(python|django|flask|fastapi)\b"),
    ("app_runtime", "java", r"\b(java|spring boot|spring|kotlin)\b"),
    ("app_runtime", "dotnet", r"(\.net\b|\basp\.net\b|\bc#)"),
    ("app_runtime", "go", r"\b(golang|go service|written in go)\b"),
    ("app_runtime", "php", r"\b(php|laravel|symfony|wordpress)\b"),
    ("app_runtime", "ruby", r"\b(ruby|rails)\b"),
    ("traffic_pattern", "spiky", r"\b(spikes?|spiky|campaigns?|black friday|flash sales?|ticket sales|seasonal|product launch)\b"),
    ("traffic_pattern", "business_hours", r"\b(business hours|office hours|working hours|9 ?(?:-|to) ?5|internal staff|employees only)\b"),
    ("file_uploads", "yes", r"\b(uploads?|upload (?:files|images|documents)|images|photos|documents|attachments|pdfs?|invoices)\b"),
    (
        "ops_team",
        "none",
        r"\b(no (?:devops|ops|it|operations) (?:team|person|staff)|no dedicated (?:ops|devops|it)|just developers|small team)\b",
    ),
]


def extract_hints(text: str) -> list[Hint]:
    hints: list[Hint] = []
    low = text.lower()
    seen: set[str] = set()
    for key, value, pattern in _HINT_RULES:
        if key in seen:
            continue
        m = re.search(pattern, low)
        if m:
            hints.append(Hint(key=key, value=value, evidence=m.group(0), detected_by="deterministic"))
            seen.add(key)
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?(?:\s*(?:/|per|a)\s*month)?", low)
    if m:
        amount = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        hints.append(Hint(key="budget", value=str(int(amount)), evidence=m.group(0).strip(), detected_by="deterministic"))
    return hints


EXPLAIN_RE = re.compile(
    r"(^\s*(what|why|how|explain|huh|\?)|what does|what is|what's|don't understand|do not understand|not sure what|meaning of|\?\s*$)", re.I
)
ACCEPT_RE = re.compile(
    r"\b(you (choose|decide|pick)|whatever you (recommend|suggest)|use (the|your) recommend\w*|recommended|go with your|sounds good|default)\b",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
UNSURE_RE = re.compile(r"\b(i don'?t know|not sure|no idea|unsure)\b", re.I)


@dataclass
class Interpretation:
    kind: str  # answer | explain | unclear | accept_recommendation
    value: Any = None
    note: str = ""


def parse_number(text: str) -> float | None:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand)?", text.lower())
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    if m.group(2):
        val *= 1000
    return val


def deterministic_interpret(q: QuestionView, qdef: Question, text: str) -> Interpretation:
    t = text.strip()
    low = t.lower()
    if ACCEPT_RE.search(low):
        return Interpretation(kind="accept_recommendation")
    # Exact option value / label.
    for opt in q.options:
        if low in (opt.value.lower(), opt.label.lower()):
            return Interpretation(kind="answer", value=opt.value)
    if q.kind == "number":
        n = parse_number(low)
        if n is not None:
            return Interpretation(kind="answer", value=n)
    elif q.kind == "text":
        if q.id == "alert_email":
            m = EMAIL_RE.search(t)
            if m:
                return Interpretation(kind="answer", value=m.group(0))
        else:
            m = re.search(r"([0-9a-f:.]+/\d{1,3})", low)
            if m:
                return Interpretation(kind="answer", value=m.group(1))
    else:
        scores: dict[str, int] = {}
        for value, words in qdef.synonyms.items():
            for w in words:
                if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
                    scores[value] = scores.get(value, 0) + len(w)
        allowed = {o.value for o in q.options}
        scores = {k: v for k, v in scores.items() if k in allowed}
        if scores:
            if len(scores) == 1:
                return Interpretation(kind="answer", value=next(iter(scores)))
            # Several options matched: never guess between them.
            return Interpretation(kind="unclear", note=f"Your answer matched more than one option ({', '.join(sorted(scores))}).")
    if EXPLAIN_RE.search(t) or UNSURE_RE.search(low):
        return Interpretation(kind="explain")
    return Interpretation(kind="unclear")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def applicable(state: InterviewState) -> list[Question]:
    return [q for q in QUESTIONS if q.applies(state)]


def _display(q: QuestionView, value: Any) -> str:
    if q.kind == "number":
        return f"${float(value):,.0f} / month"
    if q.kind == "text":
        return str(value)
    opt = next((o for o in q.options if o.value == value), None)
    return opt.label if opt else str(value)


def _validate(state: InterviewState, qid: str, value: Any) -> tuple[Any, str | None]:
    """Return (normalised value, refusal reason). Refusals are never recorded as answers."""
    q = QUESTION_INDEX[qid]
    view = q.view(state)
    if q.kind == "choice":
        if value not in {o.value for o in view.options}:
            return None, f"'{value}' is not one of the available options."
        if qid == "tls" and value == "http_only":
            if state.value("data_sensitivity") != "public" or state.value("environment") != "development":
                return None, (
                    "Plain HTTP would send your users' data unencrypted. It's only allowed for a development environment that serves public information. "
                    "ACM certificates are free, so HTTPS adds no cost."
                )
        if qid == "recovery_window" and int(value) < _min_backup_days(state):
            minimum = _min_backup_days(state)
            why = (
                f"{str(state.value('compliance')).upper()} workloads need the full 35-day recovery window."
                if minimum == 35
                else "Production data needs at least 7 days of point-in-time recovery, so mistakes noticed after a weekend can still be undone."
            )
            return None, why + " Backup storage up to the size of your database is free."
        if qid == "log_retention" and int(value) < _min_log_days(state):
            return None, "PCI DSS requires at least one year of audit log history, so shorter retention isn't allowed for this project."
        if qid == "off_hours" and value == "yes" and state.value("availability") == "high":
            return (
                None,
                "Switching servers off at night contradicts your answer that the service must keep running. Change availability first.",
            )
        return value, None
    if q.kind == "number":
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None, "Please enter a number, for example 300."
        if n <= 0 or n > 1_000_000:
            return None, "Please enter a monthly amount between $1 and $1,000,000."
        return round(n, 2), None
    if qid == "alert_email":
        email = str(value).strip()
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            return None, "That doesn't look like an email address. Example: ops@yourcompany.com"
        return email, None
    if qid == "admin_cidr":
        try:
            net = ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError:
            return None, "That isn't valid CIDR notation. Example: 203.0.113.0/24 (or 203.0.113.10/32 for one address)."
        if net.prefixlen < (16 if net.version == 4 else 48):
            return (
                None,
                f"{net} is too broad: it would expose SSH to a very large part of the internet. Use your office or VPN range (/16 or narrower).",
            )
        internal = [
            ipaddress.ip_network(n)
            for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "fc00::/7", "fe80::/10")
        ]
        if any(net.version == i.version and net.subnet_of(i) for i in internal):  # type: ignore[arg-type]
            return (
                None,
                f"{net} is a private range; SSH from the internet arrives from your public IP. Use your public office/VPN range, or choose Session Manager.",
            )
        return str(net), None
    return value, None


def evaluate_conflicts(state: InterviewState) -> list[Conflict]:
    a = state.value
    out: list[Conflict] = []
    if a("existing_ack") == "stop":
        out.append(
            Conflict(
                id="CF-EXISTING",
                severity="blocking",
                message="Managing existing infrastructure requires importing it into Terraform state, which this MVP does not support. Nothing will be generated for your existing environment.",
                involved=["deployment_type", "existing_ack"],
                suggestions=[
                    "Choose 'create a separate new environment'",
                    "Import existing resources manually with `terraform import`, outside this tool",
                ],
            )
        )
    if a("data_residency") == "eu" and a("region") and a("region") not in EU:
        out.append(
            Conflict(
                id="CF-RESIDENCY",
                severity="blocking",
                message=f"Data must stay in the EU, but {a('region')} is not an EU region.",
                involved=["data_residency", "region"],
                suggestions=["Choose eu-west-1 or eu-central-1"],
            )
        )
    if a("data_residency") == "us" and a("region") and a("region") not in US:
        out.append(
            Conflict(
                id="CF-RESIDENCY",
                severity="blocking",
                message=f"Data must stay in the US, but {a('region')} is not a US region.",
                involved=["data_residency", "region"],
                suggestions=["Choose us-east-1 or us-west-2"],
            )
        )
    if a("data_sensitivity") == "regulated" and a("compliance") == "none":
        out.append(
            Conflict(
                id="CF-REGULATED",
                severity="warning",
                message="You store regulated data (payments or health) but selected no compliance framework. Please double-check: frameworks like PCI DSS or HIPAA usually apply.",
                involved=["data_sensitivity", "compliance"],
                suggestions=[
                    "Select the framework that applies",
                    "Keep 'none' if your provider handles the regulated data (e.g. a payment processor)",
                ],
            )
        )
    if a("environment") == "development" and a("availability") == "high":
        out.append(
            Conflict(
                id="CF-DEV-HA",
                severity="warning",
                message="High availability for a development environment roughly doubles database cost. That's unusual — confirm it's intended.",
                involved=["environment", "availability"],
                suggestions=["Choose 'short outages are acceptable' for development"],
            )
        )
    if a("environment") == "production" and a("alerting") == "none":
        out.append(
            Conflict(
                id="CF-NO-ALERTS",
                severity="warning",
                message="Nobody will be notified if the production service becomes unhealthy; customers are likely to notice first.",
                involved=["alerting", "environment"],
                suggestions=["Enable email alerts (about $2/month)", "Keep 'no alerts' if you already monitor the service another way"],
            )
        )
    if a("budget") is not None:
        from app.services.architect import minimum_viable_cost
        from app.services.compiler import compile_requirements

        draft = compile_requirements(state, require_complete=False)
        mv = minimum_viable_cost(draft)
        if mv and float(a("budget")) < mv[0]:
            cost, name = mv
            suggestions = [f"Raise the budget to at least ${cost:,.0f}/month (the {name} option)"]
            if a("availability") == "high":
                relaxed = state.model_copy(deep=True)
                relaxed.answers["availability"] = relaxed.answers["availability"].model_copy(update={"value": "tolerate_minutes"})
                mv2 = minimum_viable_cost(compile_requirements(relaxed, require_complete=False))
                if mv2:
                    suggestions.append(f"Accept short outages (single-AZ database), which lowers the minimum to about ${mv2[0]:,.0f}/month")
            if a("environment") == "production":
                suggestions.append("Use a development environment for now (fewer servers, shorter backups)")
            suggestions.append("Security controls (encryption, private database, logging) will not be removed to meet the budget.")
            out.append(
                Conflict(
                    id="CF-BUDGET",
                    severity="blocking",
                    message=f"A ${float(a('budget')):,.0f}/month budget can't cover the cheapest architecture that meets your requirements (about ${cost:,.0f}/month).",
                    involved=["budget", "availability", "environment"],
                    suggestions=suggestions,
                )
            )
    return out


def _say(state: InterviewState, text: str, kind: str = "message", qid: str | None = None) -> None:
    state.transcript.append(TranscriptEntry(role="assistant", text=text, at=now(), question_id=qid, kind=kind))  # type: ignore[arg-type]


def _advance(state: InterviewState) -> None:
    """Prune answers to questions that no longer apply, re-check conflicts,
    and pick the next question (or finish)."""
    app_ids = {q.id for q in applicable(state)}
    for qid in list(state.answers):
        if qid not in app_ids:
            del state.answers[qid]
            _say(state, f"Your earlier answer to '{qid}' no longer applies after this change and was removed.", "warning")
    previous = {c.id for c in state.conflicts}
    state.conflicts = evaluate_conflicts(state)
    for c in state.conflicts:
        if c.id not in previous:
            _say(
                state,
                ("Conflict: " if c.severity == "blocking" else "Please check: ")
                + c.message
                + (" Options: " + " · ".join(c.suggestions) if c.suggestions else ""),
                "warning",
            )
    nxt = next((q for q in applicable(state) if q.id not in state.answers), None)
    blocking = [c for c in state.conflicts if c.severity == "blocking"]
    if nxt:
        state.current_question = nxt.id
        state.complete = False
        view = nxt.view(state)
        if not state.transcript or state.transcript[-1].question_id != nxt.id or state.transcript[-1].kind != "question":
            _say(state, view.prompt, "question", nxt.id)
    elif blocking:
        state.current_question = blocking[0].involved[0]
        state.complete = False
    else:
        state.current_question = None
        if not state.complete:
            state.complete = True
            _say(
                state,
                "I have everything I need. Review the confirmed requirements and assumptions, then compile the requirements specification.",
            )


def start(initial_request: str, hints: list[Hint], engine: str) -> InterviewState:
    state = InterviewState(initial_request=initial_request, hints=hints, engine=engine)  # type: ignore[arg-type]
    state.transcript.append(TranscriptEntry(role="user", text=initial_request, at=now()))
    if hints:
        detected = "; ".join(f"{h.key.replace('_', ' ')} → {h.value} (from “{h.evidence}”)" for h in hints)
        _say(state, f"From your description I noticed: {detected}. I'll use these only as suggestions — please confirm each one.")
    _say(state, "I'll ask a few questions that change the architecture, security or cost. Ask “what does that mean?” at any time.")
    _advance(state)
    return state


def record_answer(state: InterviewState, qid: str, value: Any, origin: str, raw_text: str | None, interpreted_by: str) -> str | None:
    """Validate and store an answer. Returns a refusal message if rejected."""
    q = QUESTION_INDEX.get(qid)
    if q is None or qid not in {x.id for x in applicable(state)}:
        return "That question doesn't apply to this project."
    norm, refusal = _validate(state, qid, value)
    if refusal:
        state.rejected.append(RejectedSuggestion(question_id=qid, value=value, reason=refusal, rejected_by="system", at=now()))
        _say(state, refusal, "warning", qid)
        return refusal
    view = q.view(state)
    if view.recommended is not None and str(norm) != str(view.recommended) and q.kind == "choice":
        state.rejected.append(
            RejectedSuggestion(
                question_id=qid,
                value=view.recommended,
                reason=f"User chose '{_display(view, norm)}' instead of the recommended '{_display(view, view.recommended)}'.",
                rejected_by="user",
                at=now(),
            )
        )
    revising = qid in state.answers
    state.answers[qid] = Answer(
        question_id=qid,
        value=norm,
        display=_display(view, norm),
        origin=origin,  # type: ignore[arg-type]  # validated by pydantic at runtime
        answered_at=now(),  # type: ignore[arg-type]
        raw_text=raw_text,
        interpreted_by=interpreted_by,  # type: ignore[arg-type]  # validated by pydantic at runtime
    )  # type: ignore[arg-type]
    if raw_text is None:
        state.transcript.append(TranscriptEntry(role="user", text=_display(view, norm), at=now(), question_id=qid))
    if revising:
        _say(state, f"Updated '{q.prompt}' to {_display(view, norm)}. Dependent questions and checks were re-evaluated.")
    _advance(state)
    return None


def explain(state: InterviewState, qid: str) -> None:
    q = QUESTION_INDEX[qid]
    view = q.view(state)
    text = view.help
    if view.recommended:
        text += f" My recommendation: {_display(view, view.recommended)} — {view.recommendation_reason}"
    _say(state, text, "explanation", qid)


def view(state: InterviewState, engine_label: str) -> InterviewView:
    apps = applicable(state)
    answered = sum(1 for q in apps if q.id in state.answers)
    current = (
        QUESTION_INDEX[state.current_question].view(state) if state.current_question and state.current_question in QUESTION_INDEX else None
    )
    sections = []
    for sid, label, description in SECTIONS:
        qs = [q for q in apps if q.section == sid]
        if not qs:
            continue
        sections.append(
            SectionProgress(
                id=sid,
                label=label,
                description=description,
                answered=sum(1 for q in qs if q.id in state.answers),
                total=len(qs),
                current=current is not None and current.section == sid,
            )
        )
    return InterviewView(
        state=state,
        question=current,
        progress={"answered": answered, "total": len(apps)},
        applicable_questions=[q.id for q in apps],
        engine_label=engine_label,
        sections=sections,
        question_sections={q.id: q.section for q in apps},
    )
