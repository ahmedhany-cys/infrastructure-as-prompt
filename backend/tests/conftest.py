import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="iap-test-"))
_SHARED_CACHE = Path(__file__).resolve().parent.parent / "var" / "plugin-cache"
_SHARED_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.update(
    {
        "IAP_ENVIRONMENT": "test",
        "IAP_DATA_DIR": str(_TMP),
        "IAP_DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "IAP_PLUGIN_CACHE_PATH": str(_SHARED_CACHE),
        "IAP_SECRET_KEY": "test-secret-key-not-for-production",
        "IAP_AI_PROVIDER": "demo",
        "IAP_ALLOW_REAL_DEPLOY": "false",
        "IAP_RATE_LIMIT_PIPELINE_PER_MINUTE": "200",
    }
)
for key in list(os.environ):
    if key.startswith("IAP_ANTHROPIC"):
        del os.environ[key]

FIXTURES = Path(__file__).parent / "fixtures"


def terraform_available() -> bool:
    return shutil.which("terraform") is not None


requires_terraform = pytest.mark.skipif(not terraform_available(), reason="terraform binary not installed")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def new_session(client):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    token = c.post("/api/session").json()["csrf_token"]
    c.headers["x-csrf-token"] = token
    return c


@pytest.fixture
def api(client):
    return new_session(client)
