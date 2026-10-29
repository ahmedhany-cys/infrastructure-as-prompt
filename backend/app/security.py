"""Workspace sessions, CSRF protection and rate limiting.

MVP scope: each browser gets an anonymous workspace session (signed, HttpOnly,
SameSite=Lax cookie). Projects are isolated per session; other sessions get
404. State-changing requests require an ``X-CSRF-Token`` header derived from
the session (double-submit with a server-side HMAC). Multi-user accounts and
SSO are on the roadmap.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Project, WorkspaceSession

SESSION_COOKIE = "iap_session"
CSRF_COOKIE = "iap_csrf"
CSRF_HEADER = "x-csrf-token"


def _sign(value: str, purpose: str) -> str:
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def make_cookie_value(session_id: str) -> str:
    return f"{session_id}.{_sign(session_id, 'session')}"


def parse_cookie_value(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    sid, sig = value.rsplit(".", 1)
    return sid if hmac.compare_digest(sig, _sign(sid, "session")) else None


def csrf_token(session_id: str) -> str:
    return _sign(session_id, "csrf")


def set_session_cookies(response: Response, session_id: str) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(
        SESSION_COOKIE, make_cookie_value(session_id), httponly=True, samesite="lax", secure=secure, max_age=60 * 60 * 24 * 30, path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token(session_id), httponly=False, samesite="lax", secure=secure, max_age=60 * 60 * 24 * 30, path="/"
    )


def current_session(request: Request, db: Session = Depends(get_db)) -> WorkspaceSession:
    sid = parse_cookie_value(request.cookies.get(SESSION_COOKIE))
    if not sid:
        raise HTTPException(status_code=401, detail="No workspace session. Call POST /api/session first.")
    ws = db.get(WorkspaceSession, sid)
    if ws is None:
        raise HTTPException(status_code=401, detail="Workspace session not found.")
    ws.last_seen_at = datetime.now(UTC)
    db.commit()
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        token = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(token, csrf_token(sid)):
            raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")
    return ws


def owned_project(project_id: str, ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != ws.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, bucket: str, per_minute: int) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[(key, bucket)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {bucket}; try again in a minute.")
            q.append(now)


limiter = RateLimiter()
