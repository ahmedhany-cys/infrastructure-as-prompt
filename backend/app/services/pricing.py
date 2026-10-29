"""Budget-aware cost model.

Prices are a static, curated table of AWS public on-demand list prices
(us-east-1, Linux, USD). They are NOT fetched live, so every estimate is
labelled approximate. Regional prices are approximated with multipliers. The
``PricingSource`` protocol exists so a live integration (AWS Price List Query
API) can replace the static table without touching the cost model.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.architecture import ArchitectureParams, CostEstimate, CostLine

HOURS_PER_MONTH = 730

PRICING_SOURCE = (
    "Static table of AWS public on-demand list prices (us-east-1, Linux), curated by the project maintainers; not retrieved live"
)
PRICING_AS_OF = "price table v1 — compiled from AWS published rates as of 2025; verify with the AWS Pricing Calculator"


class PricingSource(Protocol):
    def hourly(self, key: str, region: str) -> float: ...
    def monthly(self, key: str, region: str) -> float: ...


# Hourly prices (USD) in us-east-1.
_HOURLY = {
    "ec2:t4g.micro": 0.0084,
    "ec2:t4g.small": 0.0168,
    "ec2:t4g.medium": 0.0336,
    "ec2:t4g.large": 0.0672,
    "ec2:t4g.xlarge": 0.1344,
    "rds:db.t4g.micro": 0.016,
    "rds:db.t4g.small": 0.032,
    "rds:db.t4g.medium": 0.065,
    "rds:db.t4g.large": 0.129,
    "alb:hour": 0.0225,
    "alb:lcu": 0.008,
    "nat:hour": 0.045,
    "ipv4:public": 0.005,
}
# Monthly / per-unit prices (USD) in us-east-1.
_UNIT = {
    "rds:gp3_gb_month": 0.115,
    "ebs:gp3_gb_month": 0.08,
    "nat:gb_processed": 0.045,
    "transfer:out_gb": 0.09,
    "s3:standard_gb_month": 0.023,
    "logs:vended_s3_gb": 0.25,
    "logs:cw_ingest_gb": 0.50,
    "secrets:secret_month": 0.40,
    "waf:acl_month": 5.0,
    "waf:rule_month": 1.0,
    "waf:million_requests": 0.60,
    "kms:key_month": 1.0,
    "cloudwatch:alarm_month": 0.10,
}
# Business-hours schedule: 12 hours a day, 5 days a week.
BUSINESS_HOURS_FRACTION = (12 * 5) / (24 * 7)
# Approximate regional multipliers relative to us-east-1.
_REGION_MULTIPLIER = {
    "us-east-1": 1.0,
    "us-east-2": 1.0,
    "us-west-2": 1.0,
    "eu-west-1": 1.08,
    "eu-central-1": 1.16,
    "eu-west-2": 1.12,
    "ap-southeast-1": 1.2,
}


class StaticPricing:
    def multiplier(self, region: str) -> float:
        return _REGION_MULTIPLIER.get(region, 1.2)

    def hourly(self, key: str, region: str) -> float:
        return _HOURLY[key] * self.multiplier(region)

    def monthly(self, key: str, region: str) -> float:
        return _UNIT[key] * self.multiplier(region)


# Usage assumptions per traffic profile (monthly).
TRAFFIC_PROFILES: dict[str, dict[str, Any]] = {
    "low": {
        "label": "up to ~10 requests/second",
        "lcu": 1,
        "nat_gb": 10,
        "out_gb": 20,
        "flow_gb": 1,
        "log_gb": 5,
        "req_m": 1,
        "files_gb": 10,
    },
    "moderate": {
        "label": "~10–100 requests/second",
        "lcu": 3,
        "nat_gb": 50,
        "out_gb": 150,
        "flow_gb": 5,
        "log_gb": 20,
        "req_m": 10,
        "files_gb": 50,
    },
    "high": {
        "label": "~100–500 requests/second",
        "lcu": 10,
        "nat_gb": 200,
        "out_gb": 800,
        "flow_gb": 20,
        "log_gb": 80,
        "req_m": 50,
        "files_gb": 200,
    },
}


def estimate(params: ArchitectureParams, traffic: str, budget: float | None, pricing: StaticPricing | None = None) -> CostEstimate:
    p = pricing or StaticPricing()
    r = params.region
    prof = TRAFFIC_PROFILES.get(traffic, TRAFFIC_PROFILES["low"])
    lines: list[CostLine] = []

    def add(component: str, item: str, qty: float, unit: str, unit_price: float, variable: bool = False, note: str = "") -> None:
        lines.append(
            CostLine(
                component=component,
                item=item,
                quantity=round(qty, 2),
                unit=unit,
                unit_price_usd=round(unit_price, 5),
                monthly_usd=round(qty * unit_price, 2),
                variable=variable,
                note=note,
            )
        )

    inst_hourly = p.hourly(f"ec2:{params.instance_type}", r)
    run_fraction = BUSINESS_HOURS_FRACTION if params.scheduled_scaling else 1.0
    add(
        "Application servers",
        f"EC2 {params.instance_type} × {params.asg_desired} ({'business hours only' if params.scheduled_scaling else 'baseline'})",
        params.asg_desired * HOURS_PER_MONTH * run_fraction,
        "instance-hours",
        inst_hourly,
        note=f"Auto scaling may add up to {params.asg_max - params.asg_desired} more instances under load."
        + (" Servers are scaled to zero nights and weekends (~36% of the month running)." if params.scheduled_scaling else ""),
    )
    add(
        "Application servers",
        "EBS gp3 root volumes (16 GB each)",
        params.asg_desired * 16 * run_fraction,
        "GB-month",
        p.monthly("ebs:gp3_gb_month", r),
        note="Volumes are deleted with their instances, so they are billed only while servers run." if params.scheduled_scaling else "",
    )

    add("Load balancer", "Application Load Balancer", HOURS_PER_MONTH, "hours", p.hourly("alb:hour", r))
    add(
        "Load balancer",
        f"ALB capacity units (~{prof['lcu']} LCU average)",
        prof["lcu"] * HOURS_PER_MONTH,
        "LCU-hours",
        p.hourly("alb:lcu", r),
        variable=True,
        note="Depends on connections, requests and bytes processed.",
    )

    public_ips = len(params.availability_zones)  # ALB node per AZ
    if not params.app_subnets_private:
        public_ips += params.asg_desired  # (business-hours schedules reduce this slightly; not modelled)
    public_ips += params.nat_gateways
    add(
        "Networking",
        f"Public IPv4 addresses ({public_ips})",
        public_ips * HOURS_PER_MONTH,
        "address-hours",
        p.hourly("ipv4:public", r),
        note="AWS charges for every public IPv4 address, including those used by load balancers and NAT gateways.",
    )

    if params.nat_gateways:
        add("Networking", f"NAT gateway × {params.nat_gateways}", params.nat_gateways * HOURS_PER_MONTH, "hours", p.hourly("nat:hour", r))
        add(
            "Networking",
            f"NAT data processing (~{prof['nat_gb']} GB)",
            prof["nat_gb"],
            "GB",
            p.monthly("nat:gb_processed", r),
            variable=True,
        )

    out_gb = prof["out_gb"]
    billable_out = max(0.0, out_gb - 100)
    add(
        "Data transfer",
        f"Internet egress (~{out_gb} GB, first 100 GB/month free tier)",
        billable_out,
        "GB",
        p.monthly("transfer:out_gb", r),
        variable=True,
        note="The 100 GB monthly free egress allowance is shared across the AWS account.",
    )

    if params.db_enabled:
        az_factor = 2 if params.db_multi_az else 1
        add(
            "Database",
            f"RDS PostgreSQL {params.db_instance_class}{' Multi-AZ' if params.db_multi_az else ''}",
            HOURS_PER_MONTH * az_factor,
            "instance-hours",
            p.hourly(f"rds:{params.db_instance_class}", r),
        )
        add(
            "Database",
            f"RDS gp3 storage ({params.db_storage_gb} GB{' ×2 Multi-AZ' if params.db_multi_az else ''})",
            params.db_storage_gb * az_factor,
            "GB-month",
            p.monthly("rds:gp3_gb_month", r),
        )
        add("Database", "Secrets Manager secret (RDS-managed master password)", 1, "secret-month", p.monthly("secrets:secret_month", r))

    if params.flow_logs:
        add(
            "Logging",
            f"VPC flow logs delivered to S3 (~{prof['flow_gb']} GB)",
            prof["flow_gb"],
            "GB",
            p.monthly("logs:vended_s3_gb", r),
            variable=True,
        )
    retained_gb = prof["log_gb"] * max(1.0, params.log_retention_days / 30)
    add(
        "Logging",
        f"S3 log storage (~{retained_gb:,.0f} GB retained for {params.log_retention_days} days)",
        retained_gb,
        "GB-month",
        p.monthly("s3:standard_gb_month", r),
        variable=True,
        note=f"About {prof['log_gb']} GB of new logs per month, expired after {params.log_retention_days} days (steady state).",
    )
    if params.db_enabled:
        add(
            "Logging",
            "CloudWatch Logs ingestion for exported PostgreSQL logs (~2 GB)",
            2,
            "GB",
            p.monthly("logs:cw_ingest_gb", r),
            variable=True,
        )
    if params.uploads_bucket:
        add(
            "File storage",
            f"S3 uploads bucket (~{prof['files_gb']} GB stored)",
            prof["files_gb"],
            "GB-month",
            p.monthly("s3:standard_gb_month", r),
            variable=True,
            note="Depends on how many files users store; request charges are not included.",
        )
    if params.alerts:
        alarms = 4 if params.db_enabled else 2
        add("Monitoring", f"CloudWatch alarms ({alarms})", alarms, "alarm-month", p.monthly("cloudwatch:alarm_month", r))
        add("Monitoring", "KMS key for the encrypted alert topic", 1, "key-month", p.monthly("kms:key_month", r))
        add("Monitoring", "SNS email notifications", 1, "topic", 0.0, note="The first 1,000 email notifications each month are free.")
    if params.cloudtrail:
        add(
            "Audit",
            "CloudTrail management events (first trail copy)",
            1,
            "trail",
            0.0,
            note="The first copy of management events is free; storage is counted under S3.",
        )
    if params.waf:
        add("Web application firewall", "AWS WAF web ACL", 1, "ACL-month", p.monthly("waf:acl_month", r))
        add("Web application firewall", "AWS WAF managed rule groups (3)", 3, "rule-month", p.monthly("waf:rule_month", r))
        add(
            "Web application firewall",
            f"AWS WAF requests (~{prof['req_m']}M)",
            prof["req_m"],
            "million requests",
            p.monthly("waf:million_requests", r),
            variable=True,
        )

    total = round(sum(line.monthly_usd for line in lines), 2)
    variable = round(sum(line.monthly_usd for line in lines if line.variable), 2)
    by_component: dict[str, float] = {}
    for line in lines:
        by_component[line.component] = by_component.get(line.component, 0) + line.monthly_usd
    top = sorted(by_component.items(), key=lambda kv: kv[1], reverse=True)[:3]

    within: bool | None = None
    note = ""
    if budget is not None:
        within = total <= budget
        if within:
            headroom = budget - total
            note = f"Estimated ${total:,.0f}/month against a ${budget:,.0f} budget (${headroom:,.0f} headroom). Variable charges can exceed this estimate."
        else:
            note = f"Estimated ${total:,.0f}/month exceeds the ${budget:,.0f} budget by ${total - budget:,.0f}."

    return CostEstimate(
        total_monthly_usd=total,
        fixed_monthly_usd=round(total - variable, 2),
        variable_monthly_usd=variable,
        lines=lines,
        assumptions=[
            f"On-demand pricing in {r}; 730 hours per month; no Savings Plans, Reserved Instances or free-tier credits applied (except the 100 GB egress allowance).",
            f"Traffic profile '{traffic}': {prof['label']}.",
            f"Auto scaling runs at its desired capacity of {params.asg_desired} instance(s) on average"
            + (", 12 hours a day on weekdays." if params.scheduled_scaling else "."),
            "AWS-managed KMS keys are used for encryption"
            + (
                " (plus one customer-managed key for the alert topic, included above)."
                if params.alerts
                else ", so no per-key KMS charge is included."
            ),
            "Taxes, support plans, domain registration and ACM certificates (free for public certificates) are not included.",
        ],
        variable_charges=[
            "Data transfer out to the internet",
            "Load balancer capacity units (LCUs)",
            "NAT gateway data processing" if params.nat_gateways else "Instance egress through public IPs (charged as data transfer)",
            "Log volume (flow logs, access logs, CloudWatch Logs)",
            "Additional instances launched by auto scaling",
        ],
        top_drivers=[f"{name}: ${amount:,.0f}/month" for name, amount in top],
        pricing_source=PRICING_SOURCE,
        pricing_as_of=PRICING_AS_OF,
        approximate=True,
        budget_usd=budget,
        within_budget=within,
        budget_note=note,
    )
