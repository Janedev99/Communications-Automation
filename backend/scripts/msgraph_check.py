"""
MSGraph verification: non-destructive check of the M365 app registration.

Exercises the same code path as production (``MSGraphProvider.connect``) to
prove that the four ``MSGRAPH_*`` env vars in ``.env`` are correct, then
performs one read-only probe of the configured mailbox to confirm
admin-consented Mail.Read application permission is actually in effect.

Safety guarantees:

    1. Read-only. No POST, no PATCH, no DELETE. The only Graph call is
       GET /users/{mailbox}/mailFolders/Inbox — returns folder metadata
       only (id, displayName, unreadItemCount). Message contents are
       never fetched.
    2. The client secret is never printed. Only the public identifiers
       (tenant, client, mailbox) appear in output.
    3. Exit code reflects status so this can be wired into CI later:
            0 — token acquired AND inbox folder accessible (fully healthy)
            1 — token acquired but mailbox probe failed (admin consent
                missing, wrong mailbox UPN, or scope not granted)
            2 — token acquisition failed (bad tenant/client/secret, or
                tenant doesn't exist)
            3 — config error (env vars missing)

Usage:

    cd backend
    python scripts/msgraph_check.py                # default: read-path check
    python scripts/msgraph_check.py --check-send   # send-path check (no email sent)

``--check-send`` swaps the inbox round-trip for a local decode of the
access token's ``roles`` claim, which lists every Application permission
that admin consent has granted to this app registration. It exits 0 only
if ``Mail.Send`` appears in that list. No /sendMail call is made — no
email is dispatched. Use this after asking the tenant admin to grant
Mail.Send to confirm the change took effect before clicking Send in the
deployed app.

Output is concise; pass ``--verbose`` to also print the raw token response
metadata (token_type, expires_in, scope claim — never the access_token).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Final

# Allow importing from app/ when run from backend/.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent.parent / ".env")

import certifi  # noqa: E402
import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.email_provider import MSGraphProvider  # noqa: E402

# Windows: Python's default cert store often misses the Microsoft chain.
# Force httpx to use certifi's CA bundle. On Linux/Railway this is the same
# default httpx already picks, so no production divergence.
_HTTP_VERIFY = certifi.where()

GRAPH_BASE: Final = "https://graph.microsoft.com/v1.0"


def _exit(code: int, msg: str) -> None:
    print(msg)
    sys.exit(code)


def _decode_token_roles(access_token: str) -> list[str]:
    """
    Decode the JWT access token locally and return its ``roles`` claim.

    The middle segment of a JWT is base64url-encoded JSON. We never verify
    the signature here — we are reading roles for an *informational* probe,
    not authorizing anything. The token was just issued by Microsoft on the
    line above; trusting it for display purposes is fine.

    Returns an empty list if the ``roles`` claim is absent (which itself is
    the answer — no application roles granted).
    """
    segments = access_token.split(".")
    if len(segments) != 3:
        raise ValueError(f"expected 3 JWT segments, got {len(segments)}")
    payload_b64 = segments[1]
    # base64url uses no padding; restore it for stdlib base64.
    padding = "=" * (-len(payload_b64) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
    claims = json.loads(payload_bytes.decode("utf-8"))
    roles = claims.get("roles", [])
    if not isinstance(roles, list):
        raise ValueError(f"unexpected 'roles' claim type: {type(roles).__name__}")
    return [str(r) for r in roles]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true",
                        help="print non-secret token metadata")
    parser.add_argument("--check-send", action="store_true",
                        help="decode the token's roles claim and require Mail.Send "
                             "(no Graph write, no email sent)")
    args = parser.parse_args()

    settings = get_settings()

    missing = [
        name for name, val in [
            ("MSGRAPH_TENANT_ID", settings.msgraph_tenant_id),
            ("MSGRAPH_CLIENT_ID", settings.msgraph_client_id),
            ("MSGRAPH_CLIENT_SECRET", settings.msgraph_client_secret),
            ("MSGRAPH_MAILBOX", settings.msgraph_mailbox),
        ] if not val
    ]
    if missing:
        _exit(3, f"config error: missing {', '.join(missing)} in .env")

    print(f"Tenant:  {settings.msgraph_tenant_id}")
    print(f"Client:  {settings.msgraph_client_id}")
    print(f"Mailbox: {settings.msgraph_mailbox}")
    print("Secret:  (hidden)")
    print()

    provider = MSGraphProvider(settings)
    # Swap in a verify-explicit client so local Windows SSL store doesn't bite.
    provider._client = httpx.Client(timeout=30, verify=_HTTP_VERIFY)

    # Step 1 — token acquisition via the production code path.
    print("[1/2] Acquiring access token from Microsoft OAuth endpoint...")
    try:
        provider.connect()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        _exit(2, f"token request failed: HTTP {exc.response.status_code}\n{body}")
    except Exception as exc:  # noqa: BLE001
        _exit(2, f"token request failed: {type(exc).__name__}: {exc}")
    print("      OK — token acquired.\n")

    # Step 2 — branch on probe mode.
    if args.check_send:
        # Send-path check: decode roles locally. No Graph call.
        print("[2/2] Decoding token roles claim (local, no Graph call)...")
        try:
            roles = _decode_token_roles(provider._access_token or "")
        except Exception as exc:  # noqa: BLE001
            _exit(1, f"could not decode token roles: {type(exc).__name__}: {exc}")

        if not roles:
            _exit(1,
                "      FAIL — token carries no 'roles' claim.\n"
                "      This means the app registration has zero Application "
                "permissions granted with admin consent.\n"
                "      hint: Azure portal → App registrations → Mailbox API → "
                "API permissions → grant Mail.Send (Application) and click "
                "'Grant admin consent'.")

        print(f"      Granted Application roles ({len(roles)}):")
        for r in sorted(roles):
            marker = "  <-- send-path requires this" if r == "Mail.Send" else ""
            print(f"        • {r}{marker}")
        print()

        if "Mail.Send" in roles:
            print("PASS — Mail.Send is granted. The deployed app should be able to send.")
            print("If sending still fails, restart Railway to drop the cached token "
                  "(it was issued before the grant landed).")
            sys.exit(0)
        else:
            _exit(1,
                "FAIL — Mail.Send is NOT in the granted roles list.\n"
                "This is the most likely cause of 'failed to send' in the "
                "deployed app.\n"
                "Fix: Azure portal → App registrations → Mailbox API "
                "→ API permissions → Add a permission → Microsoft Graph "
                "→ Application permissions → Mail.Send → Add → Grant admin "
                "consent. Then restart Railway and retry.")

    # Default: read-only mailbox probe. No message content fetched.
    print(f"[2/2] Probing inbox folder for {settings.msgraph_mailbox}...")
    url = f"{GRAPH_BASE}/users/{settings.msgraph_mailbox}/mailFolders/Inbox"
    try:
        resp = httpx.get(url, headers=provider._headers(), timeout=30, verify=_HTTP_VERIFY)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        hint = ""
        if exc.response.status_code == 403:
            hint = ("\nhint: HTTP 403 typically means admin consent is missing "
                    "for Mail.Read application permission, or the app is not "
                    "permitted to access this mailbox.")
        elif exc.response.status_code == 404:
            hint = ("\nhint: HTTP 404 typically means the MSGRAPH_MAILBOX UPN "
                    "doesn't exist in this tenant. Confirm jane@schilcpa.com "
                    "is the correct UPN (not an alias).")
        _exit(1, f"mailbox probe failed: HTTP {exc.response.status_code}\n{body}{hint}")
    except Exception as exc:  # noqa: BLE001
        _exit(1, f"mailbox probe failed: {type(exc).__name__}: {exc}")

    folder = resp.json()
    print(f"      OK — inbox reachable.")
    print(f"      Folder id:          {folder.get('id', '')[:24]}...")
    print(f"      Display name:       {folder.get('displayName')}")
    print(f"      Unread item count:  {folder.get('unreadItemCount')}")
    print(f"      Total item count:   {folder.get('totalItemCount')}")
    print()
    print("All checks passed. M365 integration is ready to activate.")
    print("Next step (when ready): set EMAIL_PROVIDER=msgraph in .env.")


if __name__ == "__main__":
    main()
