"""
CSRF coverage test — every mutating endpoint must reject requests
without the X-CSRF-Token header with HTTP 403.

T1 from launch-readiness QA pass.

The test enumerates all POST/PUT/PATCH/DELETE routes registered on the
FastAPI app and fires each one without the CSRF header (but with a valid
session cookie). Only /auth/login is explicitly exempt.
"""
from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient


# ── Endpoints explicitly exempt from CSRF (unauthenticated bootstrap) ─────────
_CSRF_EXEMPT = {
    "/api/v1/auth/login",  # No session exists yet — CSRF token hasn't been issued
}

# ── Endpoints that require a path param we can't easily satisfy ───────────────
# These still get the test but with a sentinel UUID that should return 404 not 403.
# A 404 proves auth was checked (session OK) but CSRF was also checked (403 would
# appear before route matching completes only if middleware is involved, but here
# CSRF is a Depends() so it fires after path matching). We verify the response is
# NOT 403 (CSRF passed unexpectedly) — actually we want 403 from CSRF before 404.
# The dependency fires in order: require_csrf → get_current_user → handler.
# So we expect 403 if CSRF is missing regardless of whether the resource exists.

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _collect_mutating_routes(app) -> list[tuple[str, str]]:
    """
    Walk FastAPI app routes and return (method, path) pairs for all
    mutating routes that are not in the CSRF-exempt list.
    """
    from fastapi.routing import APIRoute
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or []:
            if method.upper() not in _MUTATING_METHODS:
                continue
            path = route.path
            if path in _CSRF_EXEMPT:
                continue
            routes.append((method.upper(), path))
    return routes


def _fill_path_params(path: str) -> str:
    """Replace {param} placeholders with a sentinel UUID."""
    import re
    sentinel = str(uuid.uuid4())
    return re.sub(r"\{[^}]+\}", sentinel, path)


@pytest.mark.parametrize("method,path", _collect_mutating_routes(
    __import__("app.main", fromlist=["create_app"]).create_app()
))
def test_csrf_required_on_mutating_endpoint(
    method: str,
    path: str,
    logged_in_admin: TestClient,
):
    """
    Any mutating endpoint called WITHOUT the X-CSRF-Token header must return
    HTTP 403. A 422 (validation error on path/body) or 404 (resource not found)
    are also acceptable — they mean the request got past CSRF (bad) only if
    the status is not 403.

    We remove the CSRF header from the client for this test.
    """
    url = _fill_path_params(path)

    # Build a client with session cookie but NO CSRF header
    from fastapi.testclient import TestClient as _TC
    app = logged_in_admin.app
    no_csrf_client = _TC(app, raise_server_exceptions=False)
    # Copy the session cookie from the logged-in client
    for cookie in logged_in_admin.cookies.jar:
        no_csrf_client.cookies.set(cookie.name, cookie.value)
    # Explicitly do NOT set X-CSRF-Token

    kwargs: dict = {"url": url}

    method_fn = getattr(no_csrf_client, method.lower())
    resp = method_fn(**kwargs)

    assert resp.status_code == 403, (
        f"{method} {path} → expected 403 (CSRF rejected) without X-CSRF-Token header, "
        f"got {resp.status_code}. Response: {resp.text[:200]}"
    )
