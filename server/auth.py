"""Session handling and the request-level guards that use it.

The backend is FastAPI, but the account model is the same one the reference
application uses, so the pieces line up:

* the browser holds one opaque token in an ``HttpOnly`` cookie; the database only
  ever stores that token's SHA-256 digest;
* a request is attributed to a user by looking the cookie up, and nothing is
  trusted from the request body;
* when the operator turns login off for a private single-user install, every
  request is simply attributed to the default admin, so drafts and exports still
  have an owner.

Two guards from the reference are worth keeping even in a small deployment:

* ``X-QB-Expected-User-Id`` -- all tabs in one browser profile share one cookie,
  so a tab that still thinks it is signed in as somebody else must be stopped
  *before* it writes;
* a small in-memory sign-in throttle, so the login endpoint cannot be used to
  grind through passwords.
"""

from __future__ import annotations

import os
import time
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response

from server import appdb  # noqa: E402

SESSION_COOKIE_NAME = "qb_session"
EXPECTED_USER_HEADER = "X-QB-Expected-User-Id"
SESSION_MAX_AGE = appdb.SESSION_TTL_SECONDS

# Paths that must stay reachable without a session: the SPA itself, the health
# probe, and the sign-in endpoints.  Everything else under /api needs an account.
PUBLIC_API_PATHS = frozenset({"/api/session", "/api/health", "/api/logout"})


def app_db_path() -> Path:
    configured = os.environ.get("QB_APP_DB", "").strip()
    return Path(configured) if configured else appdb.DEFAULT_APP_DB


def login_required() -> bool:
    """Login is enforced by default; set QB_REQUIRE_LOGIN=0 for a private install."""
    raw = os.environ.get("QB_REQUIRE_LOGIN", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def secure_cookies() -> bool:
    raw = os.environ.get("QB_SECURE_COOKIES", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def session_cookie_header(token: str) -> tuple[str, str]:
    flags = f"Path=/; Max-Age={SESSION_MAX_AGE}; HttpOnly; SameSite=Lax"
    if secure_cookies():
        flags += "; Secure"
    return "Set-Cookie", f"{SESSION_COOKIE_NAME}={token}; {flags}"


def clear_session_cookie_header() -> tuple[str, str]:
    flags = "Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
    if secure_cookies():
        flags += "; Secure"
    return "Set-Cookie", f"{SESSION_COOKIE_NAME}=; {flags}"


def cookie_value(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def user_for_request(request: Request) -> dict[str, Any] | None:
    """The signed-in user, or None when nobody is signed in."""
    return appdb.user_for_session_token(app_db_path(), cookie_value(request))


def acting_user(request: Request) -> dict[str, Any]:
    """Who this request runs as.

    With login enforced this is the session user; with login disabled it is the
    default admin, which keeps ownership meaningful on a one-person install.
    """
    user = user_for_request(request)
    if user is not None:
        return user
    if login_required():
        raise HTTPException(401, "Login required")
    with appdb.connect(app_db_path()) as conn:
        row = conn.execute(
            """
            SELECT u.*, o.code AS organization_code
            FROM users u
            LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE u.role = 'admin' AND u.active = 1
            ORDER BY u.id LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Login required")
    return appdb.user_payload(row)


def guard_expected_user(request: Request, user: dict[str, Any]) -> None:
    """Reject a tab that is still showing a different account."""
    expected = str(request.headers.get(EXPECTED_USER_HEADER) or "").strip()
    if expected and expected != str(user["id"]):
        raise HTTPException(
            409,
            {"error": "This browser tab is signed in as another account. "
                      "Reload the tab, or use a separate browser profile to keep "
                      "two accounts open.",
             "code": "session_user_mismatch"},
        )


def current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: the acting user, plus the stale-tab guard."""
    user = acting_user(request)
    guard_expected_user(request, user)
    return user


def admin_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def json_response(payload: Any, *, status: int = 200,
                  headers: list[tuple[str, str]] | None = None) -> Response:
    import json

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response = Response(content=body, status_code=status,
                        media_type="application/json")
    for name, value in headers or ():
        response.headers.append(name, value)
    return response


# --------------------------------------------------------------------------------------
# sign-in throttle
# --------------------------------------------------------------------------------------

class LoginAttemptLimiter:
    """Very small sliding-window throttle, keyed per (ip, username) and per ip."""

    def __init__(self, *, window_seconds: int = 900, limit: int = 20) -> None:
        self.window_seconds = window_seconds
        self.limit = limit
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._attempts.get(key, [])
                      if now - t < self.window_seconds]
            self._attempts[key] = recent
            return len(recent) >= self.limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._attempts[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


LOGIN_ATTEMPT_LIMITER = LoginAttemptLimiter()
LOGIN_IP_LIMITER = LoginAttemptLimiter(limit=60)
