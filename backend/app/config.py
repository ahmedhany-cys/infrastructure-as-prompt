"""Application configuration.

All settings are read from environment variables (prefix ``IAP_``) or a local
``.env`` file. Secrets never have defaults that would work in production and are
never sent to the frontend.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IAP_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    # Used to sign session cookies and CSRF tokens. The development default is
    # intentionally obvious; startup refuses to run in production with it.
    secret_key: SecretStr = SecretStr("dev-only-insecure-secret-change-me")
    database_url: str = f"sqlite:///{BACKEND_DIR / 'var' / 'iap.db'}"
    data_dir: Path = BACKEND_DIR / "var"
    cookie_secure: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- AI provider -------------------------------------------------------
    # "demo" uses the deterministic interview engine and never calls a model.
    ai_provider: Literal["demo", "anthropic"] = "demo"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    ai_timeout_seconds: float = 30.0

    # --- Tooling -------------------------------------------------------------
    terraform_bin: str = "terraform"
    plugin_cache_path: Path | None = None  # shared provider cache (defaults to <data_dir>/plugin-cache)
    checkov_cmd: str = ""  # e.g. "/path/to/venv/bin/python -m checkov.main"
    trivy_bin: str = "trivy"
    tool_timeout_seconds: int = 300
    tool_output_limit_bytes: int = 400_000

    # --- Deployment safety --------------------------------------------------
    # Real AWS deployment is disabled unless an operator explicitly enables it
    # on the server. The UI can never turn this on.
    allow_real_deploy: bool = False
    aws_profile: str | None = None
    aws_expected_account_id: str | None = None
    aws_allowed_regions: list[str] = Field(default_factory=lambda: ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1"])

    # --- Rate limits (per session, per minute) ------------------------------
    rate_limit_pipeline_per_minute: int = 6
    rate_limit_interview_per_minute: int = 60

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def plugin_cache_dir(self) -> Path:
        return self.plugin_cache_path or (self.data_dir / "plugin-cache")

    def terraform_path(self) -> str | None:
        return shutil.which(self.terraform_bin)

    def trivy_path(self) -> str | None:
        return shutil.which(self.trivy_bin)

    def checkov_argv(self) -> list[str] | None:
        if self.checkov_cmd:
            import shlex

            argv = shlex.split(self.checkov_cmd)
            if argv and (Path(argv[0]).exists() or shutil.which(argv[0])):
                return argv
            return None
        default = REPO_DIR / ".tools" / "checkov-venv" / "bin" / "python"
        if default.exists():
            return [str(default), "-m", "checkov.main"]
        found = shutil.which("checkov")
        return [found] if found else None

    def ai_live(self) -> bool:
        return self.ai_provider == "anthropic" and self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and "dev-only" in settings.secret_key.get_secret_value():
        raise RuntimeError("IAP_SECRET_KEY must be set to a strong random value in production")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    settings.plugin_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
