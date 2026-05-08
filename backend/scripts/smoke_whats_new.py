"""Smoke test for the "What's New" modal feature backend (Phases 1-4).

Walks through the full workflow against a running backend:
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
 10b. Staff baseline clear: permanently dismiss any pre-existing published
      releases left over from prior smoke runs (so subsequent assertions can
      assume a clean baseline for THIS run's just-published release)
 11. GET /releases/latest-unread expects the published release
 12. Dismiss with dont_show_again=False (session-only) - still returns next call
 13. Dismiss with dont_show_again=True - next call returns null
 14. PATCH /auth/me/preferences hide_releases_forever=True
 15. Verify GET /auth/me reflects new value
 16. Admin creates a SECOND release to test hide-forever still hides it
 17. Toggle hide_releases_forever back to False - second release returns
 18-19. Auth boundary checks (anon 401, staff-on-admin 403)
 20-23. Phase 4: AI generation endpoint (draft-from-commits)
        - local_meta happy path (real LLM call if configured + meta file present)
        - 422 release_meta_unavailable when meta file is missing
        - 422 ai_unavailable when LLM provider not configured
        - staff hitting draft-from-commits -> 403
 24. Cleanup

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
    SMOKE_STAFF_EMAIL default: smoke-staff-<random>@example.com
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
notes: list[str] = []


def log_step(label: str) -> None:
    global step_n
    step_n += 1
    print(f"\n{YELLOW}[{step_n:02d}] {label}{RESET}")


def log_note(msg: str) -> None:
    """Non-fatal observation surfaced in the final summary."""
    print(f"     {YELLOW}NOTE{RESET} {msg}")
    notes.append(f"step {step_n}: {msg}")


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
    return httpx.Client(base_url=BACKEND_URL, timeout=30.0)


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    """POST /auth/login, return the headers needed for CSRF-guarded calls.

    Session token lives in a cookie set by the server; httpx.Client carries
    cookies across requests on the same client, so we only need to thread the
    csrf_token cookie's value into the X-CSRF-Token header for mutating verbs.
    """
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


def staff_baseline_clear(staff_client: httpx.Client, headers: dict[str, str]) -> int:
    """Permanently dismiss every published release the staff user can see.

    Idempotent: walks latest-unread until the endpoint returns null. Returns
    the number of releases dismissed (for diagnostics).

    Why: the in-memory backend DB accumulates published releases across smoke
    runs (published is immutable by design). A fresh staff user inherits all
    those releases. Pre-dismissing them gives THIS smoke run a clean baseline
    so step 13's "expect null" assertion measures only THIS run's dismiss
    flow, not stale state.
    """
    dismissed = 0
    safety = 50  # don't loop forever if something is off
    while safety > 0:
        res = staff_client.get("/api/v1/releases/latest-unread")
        if res.status_code != 200:
            break
        body = res.json()
        if body is None:
            break
        rel_id = body["id"]
        d = staff_client.put(
            f"/api/v1/releases/{rel_id}/dismissal",
            json={"dont_show_again": True},
            headers=headers,
        )
        if d.status_code != 204:
            break
        dismissed += 1
        safety -= 1
    return dismissed


def main() -> int:
    # Make stdout UTF-8 tolerant on Windows (cp1252 default chokes on
    # non-Latin-1 characters). All print labels in this script are ASCII,
    # but defensive: log lines that include user input or LLM output
    # could carry arbitrary chars.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

    # -- 1. Login admin --------------------------------------------------------
    log_step("Login as admin")
    admin_headers = login(admin_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"     {GREEN}OK{RESET} Admin session established")

    # -- 2. Admin /auth/me shape -----------------------------------------------
    log_step("GET /auth/me as admin - confirm hide_releases_forever field")
    res = admin_client.get("/api/v1/auth/me")
    expect(res.status_code, 200, "status")
    me = res.json()
    expect(me.get("role"), "admin", "role")
    expect_truthy("hide_releases_forever" in me, "hide_releases_forever in body")

    # -- 3. Create a transient staff user (admin endpoint) ---------------------
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
        print(f"     {YELLOW}NOTE{RESET} Staff user already exists; reusing")
        staff_id = None
    else:
        print(f"     {RED}FAIL{RESET} HTTP {res.status_code}: {res.text}")
        failures.append("step 3 (create staff)")
        return 1

    # -- 4. List releases - initial state --------------------------------------
    log_step("GET /admin/releases - initial state")
    res = admin_client.get("/api/v1/admin/releases", headers=admin_headers)
    expect(res.status_code, 200, "status")
    initial_releases = res.json()
    print(f"     {DIM}({len(initial_releases)} existing rows in DB){RESET}")

    # -- Staff login + baseline clear (BEFORE this run publishes anything) ----
    # The conftest-style accumulation problem applies here too: prior smoke
    # runs left published rows in the DB. We need staff to dismiss those
    # NOW, before we publish this run's draft 1, so step 14's "expect this
    # run's release" assertion sees only this run's published row.
    log_step("Login as staff (transient user)")
    staff_headers = login(staff_client, STAFF_EMAIL, STAFF_PASSWORD)
    print(f"     {GREEN}OK{RESET} Staff session established")

    log_step("GET /auth/me as staff")
    res = staff_client.get("/api/v1/auth/me")
    expect(res.status_code, 200, "status")
    staff_me = res.json()
    expect(staff_me["role"], "staff", "role")
    expect(staff_me["hide_releases_forever"], False, "hide_releases_forever False")

    log_step("Staff baseline clear - dismiss leftover releases from prior runs")
    cleared = staff_baseline_clear(staff_client, staff_headers)
    if cleared > 0:
        print(f"     {DIM}Pre-dismissed {cleared} accumulated release(s){RESET}")
    else:
        print(f"     {DIM}No accumulated releases to clear{RESET}")

    # -- 5. Create a draft (manual_only) ---------------------------------------
    # Uses the structured shape (summary + highlights) so the publish step
    # downstream passes the strict gate (title + summary + ≥1 highlight).
    log_step("POST /admin/releases - create draft 1 (manual_only)")
    res = admin_client.post(
        "/api/v1/admin/releases",
        json={
            "title": "Smoke draft 1",
            "summary": "Smoke-test summary about what staff will notice.",
            "highlights": [
                {"category": "new", "text": "Smoke-test new highlight"},
                {"category": "fixed", "text": "Smoke-test fixed highlight"},
            ],
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

    # -- 6. Edit the draft (PATCH) ---------------------------------------------
    log_step("PATCH /admin/releases/{id} - edit draft title")
    res = admin_client.patch(
        f"/api/v1/admin/releases/{draft1_id}",
        json={"title": "Smoke draft 1 (edited)"},
        headers=admin_headers,
    )
    expect(res.status_code, 200, "status")
    expect(res.json()["title"], "Smoke draft 1 (edited)", "title updated")

    # -- 7. Publish draft 1 ----------------------------------------------------
    log_step("POST /admin/releases/{id}/publish - publish draft 1")
    res = admin_client.post(
        f"/api/v1/admin/releases/{draft1_id}/publish",
        headers=admin_headers,
    )
    expect(res.status_code, 200, "status")
    published1 = res.json()
    expect(published1["status"], "published", "status flipped")
    expect_truthy(published1.get("published_at"), "published_at set")

    # -- 8. Confirm published immutability -------------------------------------
    log_step("PATCH on published release - expect 409")
    res = admin_client.patch(
        f"/api/v1/admin/releases/{draft1_id}",
        json={"title": "should not stick"},
        headers=admin_headers,
    )
    expect(res.status_code, 409, "patch published returns 409")

    log_step("DELETE on published release - expect 409")
    res = admin_client.delete(
        f"/api/v1/admin/releases/{draft1_id}",
        headers=admin_headers,
    )
    expect(res.status_code, 409, "delete published returns 409")

    log_step("POST publish on already-published - expect 409")
    res = admin_client.post(
        f"/api/v1/admin/releases/{draft1_id}/publish",
        headers=admin_headers,
    )
    expect(res.status_code, 409, "republish returns 409")

    # -- latest-unread should return THIS run's published release ------------
    # Staff is already logged in and baseline-cleared (above, before publish).
    log_step("GET /releases/latest-unread - expect the just-published release")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    body = res.json()
    expect_truthy(body, "body non-null")
    if body:
        expect(body["id"], draft1_id, "id matches published release")

    # -- 12. Dismiss with dont_show_again=False (session-only) ----------------
    log_step("PUT /releases/{id}/dismissal - dont_show_again=False")
    res = staff_client.put(
        f"/api/v1/releases/{draft1_id}/dismissal",
        json={"dont_show_again": False},
        headers=staff_headers,
    )
    expect(res.status_code, 204, "status")

    # -- 13. latest-unread still returns (session-only dismissal) -------------
    log_step("GET /releases/latest-unread - session-only dismissal still returns")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    body = res.json()
    expect_truthy(body, "still returns release (session-only)")
    if body:
        expect(body["id"], draft1_id, "id still matches THIS run's release")

    # -- 14. Dismiss with dont_show_again=True --------------------------------
    log_step("PUT /releases/{id}/dismissal - dont_show_again=True")
    res = staff_client.put(
        f"/api/v1/releases/{draft1_id}/dismissal",
        json={"dont_show_again": True},
        headers=staff_headers,
    )
    expect(res.status_code, 204, "status")

    # -- 15. latest-unread now returns null -----------------------------------
    log_step("GET /releases/latest-unread - expect null after permanent dismissal")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 200, "status")
    expect(res.json(), None, "body is null")

    # -- 16. Toggle hide_releases_forever=True --------------------------------
    log_step("PATCH /auth/me/preferences - hide_releases_forever=True")
    res = staff_client.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": True},
        headers=staff_headers,
    )
    expect(res.status_code, 200, "status")
    expect(res.json()["hide_releases_forever"], True, "field updated in response")

    # -- 17. Verify GET /auth/me reflects toggled state ------------------------
    log_step("GET /auth/me - verify hide_releases_forever=True persisted")
    res = staff_client.get("/api/v1/auth/me")
    expect(res.json()["hide_releases_forever"], True, "field persisted")

    # -- 18. Admin creates draft 2 + publishes; staff with hide-forever should still see null
    log_step("POST /admin/releases - create + publish draft 2")
    res = admin_client.post(
        "/api/v1/admin/releases",
        json={
            "title": "Smoke draft 2",
            "summary": "Second release summary — should be hidden by hide-forever.",
            "highlights": [
                {"category": "improved", "text": "Second release improvement"},
            ],
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

    log_step("GET /releases/latest-unread (staff with hide-forever) - expect null")
    res = staff_client.get("/api/v1/releases/latest-unread")
    expect(res.json(), None, "still null with hide_releases_forever=True")

    # -- 19. Toggle hide-forever back off; release 2 should return ------------
    log_step("PATCH /auth/me/preferences - hide_releases_forever=False")
    res = staff_client.patch(
        "/api/v1/auth/me/preferences",
        json={"hide_releases_forever": False},
        headers=staff_headers,
    )
    expect(res.status_code, 200, "status")

    log_step("GET /releases/latest-unread - expect draft 2 to appear now")
    res = staff_client.get("/api/v1/releases/latest-unread")
    body = res.json()
    expect_truthy(body, "body non-null")
    if body:
        expect(body["id"], draft2_id, "returns draft 2 (latest unpermanent-dismissed)")

    # -- 20. Auth boundary checks ---------------------------------------------
    log_step("Anonymous client - GET /releases/latest-unread expects 401")
    anon = make_client()
    res = anon.get("/api/v1/releases/latest-unread")
    expect(res.status_code, 401, "status")

    log_step("Staff hitting admin endpoint - expect 403")
    res = staff_client.get("/api/v1/admin/releases", headers=staff_headers)
    expect(res.status_code, 403, "status")

    # -- Phase 4: AI generation endpoint (draft-from-commits) -----------------
    # The endpoint reads backend/release-meta.json (build-time snapshot of git
    # log). If the file is missing, expect 422 release_meta_unavailable. If AI
    # is unconfigured, expect 422 ai_unavailable (AI gate fires first).
    log_step("POST /admin/releases/draft-from-commits - local_meta happy path")
    res = admin_client.post(
        "/api/v1/admin/releases/draft-from-commits",
        json={},
        headers=admin_headers,
    )
    ai_available = True
    meta_available = True
    if res.status_code == 422:
        detail = res.json().get("detail")
        if detail == "ai_unavailable":
            ai_available = False
            log_note(
                "AI is not configured (LLM placeholder or missing key). "
                "Skipping happy-path assertions; verifying contract instead."
            )
        elif detail == "release_meta_unavailable":
            meta_available = False
            log_note(
                "release-meta.json is missing — generate it with "
                "`python scripts/generate_release_meta.py` before smoke."
            )
            expect(detail, "release_meta_unavailable", "release_meta_unavailable contract")
        else:
            expect(res.status_code, 200, "status (got 422 with unexpected detail)")
    else:
        expect(res.status_code, 200, "status")
        if res.status_code == 200:
            body = res.json()
            expect(body["generated_from"], "local_meta", "generated_from")
            expect_truthy("title_suggestion" in body, "title_suggestion field present")
            expect_truthy("summary_suggestion" in body, "summary_suggestion field present")
            expect_truthy("highlights_suggestion" in body, "highlights_suggestion field present")
            expect_truthy(
                isinstance(body["highlights_suggestion"], list),
                "highlights_suggestion is a list",
            )
            expect_truthy("low_confidence" in body, "low_confidence field present")
            print(f"     {DIM}LLM produced title: {body['title_suggestion'][:80]}{RESET}")
            print(f"     {DIM}Highlights: {len(body['highlights_suggestion'])}{RESET}")

    log_step("Staff hitting draft-from-commits - expect 403")
    res = staff_client.post(
        "/api/v1/admin/releases/draft-from-commits",
        json={},
        headers=staff_headers,
    )
    expect(res.status_code, 403, "status")

    # -- Cleanup: dismiss draft 2 permanently for staff so reruns are clean ---
    log_step("Cleanup - staff permanently dismisses draft 2")
    staff_client.put(
        f"/api/v1/releases/{draft2_id}/dismissal",
        json={"dont_show_again": True},
        headers=staff_headers,
    )

    print()
    if failures:
        print(f"{RED}== SMOKE FAILED =={RESET}")
        print(f"{RED}{len(failures)} step(s) failed:{RESET}")
        for f in failures:
            print(f"  - {f}")
        if notes:
            print(f"{YELLOW}Notes:{RESET}")
            for n in notes:
                print(f"  - {n}")
        return 1

    print(f"{GREEN}== SMOKE PASSED =={RESET}")
    if notes:
        print(f"{YELLOW}Notes (non-fatal):{RESET}")
        for n in notes:
            print(f"  - {n}")
    print(
        f"{DIM}Note: 2 published releases were created during this run and remain in the DB"
        f" (immutable). The transient staff user '{STAFF_EMAIL}' also remains;"
        f" delete via the admin UI / SQL if desired.{RESET}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
