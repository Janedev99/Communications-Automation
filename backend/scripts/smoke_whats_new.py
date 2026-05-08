"""Smoke test for the "What's New" modal feature backend (Phases 1-3).

Walks through the full manual workflow against a running backend:
  1. Login as admin
  2. Verify admin profile shape (hide_releases_forever field)
  3. Create a transient staff user so the staff-side checks have someone to be
  4. List releases (initial state)
  5. Create a draft release with generated_from=manual_only
  6. Edit the draft (PATCH)
  7. Publish it
  8. Confirm published immutability (409 on PATCH and DELETE)
  9. Login as staff (separate session)
 10. Verify staff /auth/me has hide_releases_forever=False
 11. GET /releases/latest-unread → expects the published release
 12. Dismiss with dont_show_again=False (session-only) → still returns next call
 13. Dismiss with dont_show_again=True → next call returns null
 14. PATCH /auth/me/preferences hide_releases_forever=True
 15. Verify GET /auth/me reflects new value
 16. Admin creates a SECOND release to test hide-forever still hides it
 17. Toggle hide_releases_forever back to False → second release returns
 18. Cleanup: delete the staff user and any leftover drafts (published rows are immutable, left as-is)

Usage:
    cd backend
    # Start the backend in another terminal:
    #   uvicorn app.main:app --reload
    # Then in this terminal:
    python scripts/smoke_whats_new.py

Environment variables (all optional, with sensible defaults):
    BACKEND_URL       default: http://localhost:8000
    ADMIN_EMAIL       default: jane@schilcpa.com   (matches seed_admin.py)
    ADMIN_PASSWORD    required (read from .env via your shell, or supply inline)
    SMOKE_STAFF_EMAIL default: smoke-staff@example.com (created + deleted by this script)
    SMOKE_STAFF_PASS  default: SmokeStaff123!

Exit code: 0 if every step lands the expected outcome, 1 otherwise.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import httpx


BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "jane@schilcpa.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
STAFF_EMAIL = os.environ.get(
    "SMOKE_STAFF_EMAIL", f"smoke-staff-{uuid.uuid4().hex[:8]}@example.com",
)
STAFF_PASSWORD = os.environ.get("SMOKE_STAFF_PASS", "SmokeStaff123!")

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"

step_n = 0
failures: list[str] = []


def log_step(label: str) -> None:
    global step_n
    step_n += 1
    print(f"\n{YELLOW}[{step_n:02d}] {label}{RESET}")


def expect(actual: Any, expected: Any, what: str) -> bool:
    ok = actual == expected
    icon = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"     {icon} {what}: expected {expected!r}, got {actual!r}")
    if not ok:
        failures.append(f"step {step_n} ({what})")
    return ok


def expect_in(actual: Any, expected_set: set, what: str) -> bool:
    ok = actual in expected_set
    icon = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"     {icon} {what}: expected one of {expected_set!r}, got {actual!r}")
    if not ok:
        failures.append(f"step {step_n} ({what})")
    return ok


def expect_truthy(actual: Any, what: str) -> bool:
    ok = bool(actual)
    icon = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"     {icon} {what}: got {actual!r}")
    if not ok:
        failures.append(f"step {step_n} ({what})")
    return ok


def make_client() -> httpx.Client:
    """Return a fresh httpx client targeting the backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=10.0)


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    """POST /auth/login, return the headers needed for subsequent CSRF-guarded calls.

    Session token lives in a cookie set by the server; httpx.Client carries cookies
    across requests on the same client, so we only need to manually thread the
    csrf_token cookie's value into the X-CSRF-Token header for mutating verbs."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if res.status_code != 200:
        raise RuntimeError(
            f"Login failed for {email}: HTTP {res.status_code} {res.text}"
        )
    csrf = client.cookies.get("csrf_token")
    if not csrf:
        raise RuntimeError(
            f"Login succeeded but csrf_token cookie not set. "
            f"Cookies seen: {list(client.cookies.keys())}",
        )
    return {"X-CSRF-Token": csrf}


def main() -> int:
    if not ADMIN_PASSWORD:
        print(
            f"{RED}ADMIN_PASSWORD not set. Source backend/.env first or "
            f"pass it inline:{RESET}\n"
            f'  $env:ADMIN_PASSWORD="..." ; python scripts/smoke_whats_new.py'
        )
        return 1

    print(f"{DIM}Backend URL  : {BACKEND_URL}{RESET}")
    print(f"{DIM}Admin email  : {ADMIN_EMAIL}{RESET}")
    print(f"{DIM}Staff email  : {STAFF_EMAIL} (transient){RESET}")

    admin_client = make_client()
    staff_client = make_client()

    # ── 1. Login admin ───────────────────────────────────────────────────────
    log_step("Login as admin")
    admin_headers = login(admin_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"     {GREEN}OK{RESET} Admin session established")

    # ── 2. Admin /auth/me shape ───────────────────────────────────────────────
    log_step("GET /auth/me as admin — confirm hide_releases_forever field")
    res = admin_client.get("/api/v1/auth/me")
    expect(res.status_code, 200, "status")
    me = res.json()
    expect(me.get("role"), "admin", "role")
    expect_truthy("hide_releases_forever" in me, "hide_releases_forever in body")

    # ── 3. Create a transient staff user (admin endpoint) ─────────────────────
    log_step("Create transient staff user")
    res = admin_client.post(
        "/api/v1/auth/users",
        json={
            "email": STAFF_EMAIL,
            "name": "Smoke Staff",
            "password": STAFF_PASSWORD,
            "role": "staff",
        },
        headers=admin_headers,
    )
    if res.status_code in (200, 201):
        staff_id = res.json().get("id")
        print(f"     {GREEN}OK{RESET} Staff user created (id={staff_id})")
    elif res.status_code == 409:
        # User may already exist from a prior smoke run; that's fine.
        print(f"     {YELLOW}NOTE{RESET} Staff user already exists; reusing")
        staff_id = None
    else:
        print(f"     {RED}FAIL{RESET} HTTP {res.status_code}: {res.text}")
        failures.append("step 3 (create staff)")
        return 1

    # ── 4. List releases — initial state ──────────────────────────────────────
    log_step("GET /admin/releases — initial state")
    res = admin_client.get("/api/v1/admin/releases", headers=admin_headers)
    expect(res.status_code, 200, "status")
    initial_releases = res.json()
    print(f"     {DIM}({len(initial_releases)} existing rows in DB){RESET}")

    # ── 5. Create a draft (manual_only) ───────────────────────────────────────
    log_step("POST /admin/releases — create draft 1 (manual_only)")
    res = admin_client.post(
        "/api/v1/admin/releases",
        json={
            "title": "Smoke draft 1",
            "body": "## What changed\n- smoke-test draft body 1",
            "generated_from": "manual_only",
        },
        headers=admin_headers,
    )
    expect(res.status_code, 201, "status")
    draft1 = res.json()
    expect(draft1["status"], "draft", "draft.status")
    expect(draft1["generated_from"], "manual_only", "draft.generated_from")
    expect_truthy(draft1.get("created_by"), "created_by populated")
    draft1_id = draft1["id"]

    # ── 6. Edit the draft (PATCH) ────────────────────────────────────────────
    log_step("PATCH /admin/releases/{id} — edit draft title")
    res = admin_client.patch(
        f"/api/v1/admin/releases/{draft1_id}",
        json={"title": "Smoke draft 1 (edited)"},
        headers=admin_headers,
    )
    expect(res.status_code, 200, "status")
    expect(res.json()["title"], "Smoke draft 1 (edited)", "title updated")

    # ── 7. Publish draft 1 ────────────────────────────────────────────────────
    log_step("POST /admin/releases/{id}/publish — publish draft 1")
    res = admin_client.post(
        f"/api/v1/admin/releases/{draft1_id}/publish",
        headers=admin_headers,
    )
    expect(res.status_code, 200, "status")
    published1 = res.json()
    expect(published1["status"], "published", "status flipped")
    expect_truthy(published1.get("published_at"), "published_at set")

    # ── 8. Confirm published immutability ─────────────────────────────────────
    log_step("PATCH on published release — expect 409")
    res = admin_client.patch(
        f"/api/v1/admin/releases/{draft1_id}",
        json={"title": "should not stick"},
        headers=admin_headers,
    )
    expect(res.status_code, 409, "patch published returns 409")

    log_step("DELETE on published release — expect 409")
    res = admin_client.delete(
        f"/api/v1/admin/releases/{draft1_id}",
        headers=admin_headers,
    )
    expect(res.status_code, 409, "delete published returns 409")

    log_step("POST publish on already-published — expect 409")
    res = admin_client.post(
        f"/api/v1/admin/releases/{draft1_id}/publish",
        headers=admin_headers,
    )
    expect(res.status_code, 409, "republish returns 409")

    # ── 9. Login staff ────────────────────────────────────────────────────────
    log_step("Login as staff (transient user)")
    staff_headers = login(staff_client, STAFF_EMAIL, STAFF_PASSWORD)
    print(f"     {GREEN}OK{RESET} Staff session established")

    # ── 10. Staff /auth/me shape ──────────────────────────────────────────────
    log_step("GET /auth/me as staff")
    res = staff_client.get("/api/v1/auth/me")
    expect(res.status_code, 200, "status")
    staff_me = res.json()
    expect(staff_me["role"], "staff", "role")
    expect(staff_me["hide_releases_forever"], False, "hide_releases_forever False")

    # ── 11. latest-unread should return the published release ────────────────
    log_step("GET /releases/latest-unread — expect the published release")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    body = res.json()
    expect_truthy(body, "body non-null")
    if body:
        expect(body["id"], draft1_id, "id matches published release")

    # ── 12. Dismiss with dont_show_again=False (session-only) ────────────────
    log_step("PUT /releases/{id}/dismissal — dont_show_again=False")
    res = staff_client.put(
        f"/api/v1/releases/{draft1_id}/dismissal",
        json={"dont_show_again": False},
        headers=staff_headers,
    )
    expect(res.status_code, 204, "status")

    # ── 13. latest-unread still returns (session-only dismissal) ─────────────
    log_step("GET /releases/latest-unread — session-only dismissal still returns")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    expect_truthy(res.json(), "still returns release (session-only)")

    # ── 14. Dismiss with dont_show_again=True ────────────────────────────────
    log_step("PUT /releases/{id}/dismissal — dont_show_again=True")
    res = staff_client.put(
        f"/api/v1/releases/{draft1_id}/dismissal",
        json={"dont_show_again": True},
        headers=staff_headers,
    )
    expect(res.status_code, 204, "status")

    # ── 15. latest-unread now returns null ───────────────────────────────────
    log_step("GET /releases/latest-unread — expect null after permanent dismissal")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    expect(res.json(), None, "body is null")

    # ── 16. Toggle hide_releases_forever=True ────────────────────────────────
    log_step("PATCH /auth/me/preferences — hide_releases_forever=True")
    res = staff_client.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": True},
        headers=staff_headers,
    )
    expect(res.status_code, 200, "status")
    expect(res.json()["hide_releases_forever"], True, "field updated in response")

    # ── 17. Verify GET /auth/me reflects toggled state ────────────────────────
    log_step("GET /auth/me — verify hide_releases_forever=True persisted")
    res = staff_client.get("/api/v1/auth/me")
    expect(res.json()["hide_releases_forever"], True, "field persisted")

    # ── 18. Admin creates draft 2 + publishes — staff with hide-forever should still see null
    log_step("POST /admin/releases — create + publish draft 2")
    res = admin_client.post(
        "/api/v1/admin/releases",
        json={
            "title": "Smoke draft 2",
            "body": "## Second release\nshould be hidden by hide-forever",
            "generated_from": "manual_only",
        },
        headers=admin_headers,
    )
    expect(res.status_code, 201, "create status")
    draft2_id = res.json()["id"]

    res = admin_client.post(
        f"/api/v1/admin/releases/{draft2_id}/publish",
        headers=admin_headers,
    )
    expect(res.status_code, 200, "publish status")

    log_step("GET /releases/latest-unread (staff with hide-forever) — expect null")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.json(), None, "still null with hide_releases_forever=True")

    # ── 19. Toggle hide-forever back off — release 2 should return ────────────
    log_step("PATCH /auth/me/preferences — hide_releases_forever=False")
    res = staff_client.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": False},
        headers=staff_headers,
    )
    expect(res.status_code, 200, "status")

    log_step("GET /releases/latest-unread — expect draft 2 to appear now")
    res = staff_client.get("/api/v1/releases/latest-unread")
    body = res.json()
    expect_truthy(body, "body non-null")
    if body:
        expect(body["id"], draft2_id, "returns draft 2 (latest published the user hasn't permanently dismissed)")

    # ── 20. Auth boundary checks ─────────────────────────────────────────────
    log_step("Anonymous client — GET /releases/latest-unread expects 401")
    anon = make_client()
    res = anon.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 401, "status")

    log_step("Staff hitting admin endpoint — expect 403")
    res = staff_client.get("/api/v1/admin/releases", headers=staff_headers)
    expect(res.status_code, 403, "status")

    # ── 21. Cleanup: dismiss draft 2 permanently for staff so reruns are clean,
    #         then leave the published rows in place (immutable by design). The
    #         staff user is left for the user to delete via admin UI if desired.
    log_step("Cleanup — staff permanently dismisses draft 2")
    staff_client.put(
        f"/api/v1/releases/{draft2_id}/dismissal",
        json={"dont_show_again": True},
        headers=staff_headers,
    )

    print()
    if failures:
        print(f"{RED}━━ SMOKE FAILED ━━{RESET}")
        print(f"{RED}{len(failures)} step(s) failed:{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"{GREEN}━━ SMOKE PASSED ━━{RESET}")
    print(
        f"{DIM}Note: 2 published releases were created during this run and remain in the DB"
        f" (immutable). The transient staff user '{STAFF_EMAIL}' also remains;"
        f" delete via the admin UI / SQL if desired.{RESET}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
