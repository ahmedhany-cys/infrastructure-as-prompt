"""Architecture specification. The diagram, the cost model and the Terraform
generator all read from this one structure so they cannot drift apart."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OptionId = Literal["lean", "balanced", "resilient"]


class ArchitectureParams(BaseModel):
    region: str
    availability_zones: list[str]
    environment: Literal["development", "staging", "production"]
    app_port: int = 8080
    app_subnets_private: bool
    nat_gateways: int = Field(ge=0, le=3)
    instance_type: str
    instance_arch: Literal["arm64", "x86_64"] = "arm64"
    asg_min: int = Field(ge=1)
    asg_max: int = Field(ge=1)
    asg_desired: int = Field(ge=1)
    db_enabled: bool
    db_engine_version: str = "16"
    db_instance_class: str = "db.t4g.micro"
    db_multi_az: bool = False
    db_storage_gb: int = 20
    backup_retention_days: int = 7
    deletion_protection: bool = False
    waf: bool = False
    cloudtrail: bool = True
    flow_logs: bool = True
    alb_access_logs: bool = True
    log_retention_days: int = 30
    https: bool = True
    admin_access: Literal["ssm", "ssh"] = "ssm"
    admin_cidr: str | None = None
    allowed_regions: list[str] = Field(default_factory=list)
    # Customer-tailored settings
    app_runtime: str = "other"
    scale_out_cpu: int = 60
    scheduled_scaling: bool = False
    schedule_timezone: str = "UTC"
    uploads_bucket: bool = False
    alerts: bool = False
    alert_email: str | None = None


class Component(BaseModel):
    id: str
    kind: str
    label: str
    parent: str | None = None
    tier: Literal["edge", "public", "private_app", "private_data", "regional", "account"] = "regional"
    details: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    requirements: list[str] = Field(default_factory=list)
    terraform_addresses: list[str] = Field(default_factory=list)
    security_boundary: str | None = None


class Connection(BaseModel):
    id: str
    source: str
    target: str
    label: str
    kind: Literal["traffic", "data", "logs", "admin", "egress"] = "traffic"


class Decision(BaseModel):
    id: str
    title: str
    choice: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)


class CostLine(BaseModel):
    component: str
    item: str
    quantity: float
    unit: str
    unit_price_usd: float
    monthly_usd: float
    variable: bool = False
    note: str = ""


class CostEstimate(BaseModel):
    total_monthly_usd: float
    fixed_monthly_usd: float
    variable_monthly_usd: float
    lines: list[CostLine]
    assumptions: list[str]
    variable_charges: list[str]
    top_drivers: list[str]
    pricing_source: str
    pricing_as_of: str
    approximate: bool = True
    budget_usd: float | None = None
    within_budget: bool | None = None
    budget_note: str = ""


class TradeoffScore(BaseModel):
    score: int = Field(ge=1, le=5)
    note: str


class ArchitectureOption(BaseModel):
    id: OptionId
    name: str
    summary: str
    params: ArchitectureParams
    components: list[Component]
    connections: list[Connection]
    decisions: list[Decision]
    cost: CostEstimate
    tradeoffs: dict[str, TradeoffScore]
    satisfies: list[str] = Field(default_factory=list)  # requirement ids
    violates: list[str] = Field(default_factory=list)


class ExcludedOption(BaseModel):
    id: OptionId
    name: str
    reason: str


class ArchitectureSpec(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime
    requirements_revision: int
    recommended: OptionId
    selected: OptionId | None = None
    options: list[ArchitectureOption]
    excluded: list[ExcludedOption] = Field(default_factory=list)

    def option(self, option_id: str | None) -> ArchitectureOption | None:
        return next((o for o in self.options if o.id == option_id), None)
