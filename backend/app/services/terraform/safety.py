"""Execution-safety gate for Terraform configurations.

Runs BEFORE ``terraform init``/``plan``. Terraform itself can execute code or
read host files while planning (``external`` data sources run programs,
``file()`` reads the server's filesystem into plan output, backends redirect
state), so configurations — generated or edited — must not contain those
constructs. This is a deliberately conservative lexical pre-filter — comments
and string literals are NOT stripped, because naive stripping can be bypassed
(e.g. ``{ a = "https://x", b = file("/etc/passwd") }``); a forbidden word in a
comment is therefore also rejected. It is paired with a
provider allow-list checked after ``init``. It complements, and does not
replace, the plan-based policy engine.
"""

from __future__ import annotations

import re

ALLOWED_PROVIDERS = {"registry.terraform.io/hashicorp/aws"}

FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bprovisioner\s+\""), "provisioner blocks (execute commands during apply)"),
    (
        re.compile(r"\bdata\s+\"(external|http|local_file|local_sensitive_file)\""),
        "data sources that run programs, make HTTP requests or read local files",
    ),
    (re.compile(r"\b(backend|cloud)\s*(\"[^\"]*\"\s*)?\{"), "backend / cloud blocks (state location is managed by the application)"),
    (re.compile(r"\bmodule\s+\""), "module blocks (remote code is not allowed in this MVP)"),
    (
        re.compile(
            r"\b(file|fileset|filebase64|filesha1|filesha256|filesha512|filemd5|filebase64sha256|filebase64sha512|templatefile|fileexists|pathexpand|abspath)\s*\("
        ),
        "functions that read the server's filesystem",
    ),
    (
        re.compile(r"\bresource\s+\"(null_resource|terraform_data|local_file|local_sensitive_file)\""),
        "resources that exist to run local actions or write local files",
    ),
]


def precheck(files: dict[str, str]) -> list[str]:
    """Return human-readable violations (empty list = allowed)."""
    problems: list[str] = []
    for name in sorted(files):
        if not name.endswith(".tf"):
            continue
        text = files[name]
        for pattern, why in FORBIDDEN:
            m = pattern.search(text)
            if m:
                line = text[: m.start()].count("\n") + 1
                problems.append(f"{name}:{line}: '{m.group(0).strip()}' — {why}")
    return problems


def provider_violations(providers_output: str) -> list[str]:
    """Parse ``terraform providers`` output and return disallowed providers."""
    found = set(re.findall(r"provider\[([^\]]+)\]", providers_output))
    return sorted(p for p in found if p not in ALLOWED_PROVIDERS)
