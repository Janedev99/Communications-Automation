"""
Demo seed — adds one PII-handling example thread to the database.

This is a *supplemental* seed script that runs alongside seed_demo.py
without bumping its sentinel. It demonstrates the firm's compliance/PII
detection story for client demos:

  Client unknowingly emails sensitive PII (SSN + bank routing/account)
  in plaintext. The AI flags this, recommends moving the conversation
  to the secure portal, and escalates to the firm owner so the data
  can be redacted from logs and the client gently redirected.

PII values used in the demo body are deliberately invalid:
  - SSN 123-45-6789  is the canonical "never issued" placeholder
  - Routing 110000000 fails the ABA checksum and is rejected by banks
  - Account number is plain decimal padding, not tied to any real bank

Idempotent: checks for its own sentinel KnowledgeEntry before inserting.

Usage (from backend/, with venv active and DATABASE_URL pointed at target):
    python scripts/seed_pii_example.py
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow importing from app/ when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from sqlalchemy import select

from app.database import SessionLocal
from app.models.email import (
    DraftResponse,
    DraftStatus,
    EmailCategory,
    EmailMessage,
    EmailStatus,
    EmailThread,
    KnowledgeEntry,
    MessageDirection,
)
from app.models.escalation import Escalation, EscalationSeverity, EscalationStatus
from app.services.auth import get_user_by_email


SENTINEL_TITLE = "__demo_seed_pii_v1__"  # idempotency marker


def uid() -> uuid.UUID:
    return uuid.uuid4()


def hours_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=n)


def main() -> None:
    db = SessionLocal()
    try:
        sentinel = db.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.title == SENTINEL_TITLE)
        ).scalar_one_or_none()
        if sentinel is not None:
            print("PII demo example already exists. Nothing to do.")
            return

        # The thread is escalated to Jane — she must exist as the owner-admin
        # for the assignment to be meaningful. seed_demo.py creates her if
        # the regular admin seed didn't.
        jane = get_user_by_email(db, "jane@schilcpa.com")
        if jane is None:
            print(
                "ERROR: jane@schilcpa.com not found. Run seed_demo.py first "
                "so the firm-owner account exists, then re-run this script."
            )
            sys.exit(1)

        print("Seeding PII demo example for Schiller CPA …")

        # ── PII thread: client emails SSN + bank info in plaintext ────────────
        thread_id = uid()
        thread = EmailThread(
            id=thread_id,
            subject="Account info for direct deposit of my refund",
            client_email="marcus.webb@gmail.com",
            client_name="Marcus Webb",
            status=EmailStatus.escalated,
            category=EmailCategory.urgent,
            category_confidence=0.96,
            ai_summary=(
                "Client Marcus Webb has emailed his full Social Security number "
                "and bank routing/account numbers in plaintext to set up direct "
                "deposit for his tax refund. This is a compliance/PII incident: "
                "financial identifiers must never travel by unencrypted email per "
                "firm policy. The conversation should be moved to the secure "
                "portal, and the email + any logs containing it should be flagged "
                "for redaction."
            ),
            suggested_reply_tone="empathetic",
            created_at=hours_ago(2),
            updated_at=hours_ago(2),
        )
        db.add(thread)

        db.add(EmailMessage(
            id=uid(),
            thread_id=thread_id,
            message_id_header="<20260507.1042.marcus.webb@gmail.com>",
            sender="marcus.webb@gmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=hours_ago(2),
            is_processed=True,
            body_text=(
                "Hi Jane,\n\n"
                "For my tax refund this year, can you set up direct deposit? "
                "Here are my account details:\n\n"
                "Routing number: 110000000\n"
                "Account number: 1234567890123\n"
                "SSN for verification: 123-45-6789\n\n"
                "Just so you have everything you need. Let me know if you need "
                "anything else.\n\n"
                "Thanks,\n"
                "Marcus Webb"
            ),
            raw_headers={
                "From": "marcus.webb@gmail.com",
                "To": "jane@schilcpa.com",
                "Subject": "Account info for direct deposit of my refund",
            },
        ))

        # AI-drafted reply: empathetic, doesn't shame, redirects to secure portal,
        # asks the client to send the info via that channel instead. Critically
        # avoids quoting back the PII the client just sent.
        db.add(DraftResponse(
            id=uid(),
            thread_id=thread_id,
            status=DraftStatus.pending,
            created_at=hours_ago(2),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=872,
            ai_completion_tokens=312,
            body_text=(
                "Dear Marcus,\n\n"
                "Thanks so much for getting your refund deposit info to us. "
                "Quick note before we proceed: we keep all banking and "
                "Social-Security details out of regular email for your "
                "protection — even our own. Sensitive financial information "
                "should always go through our secure client portal, where it's "
                "encrypted end-to-end.\n\n"
                "Could you re-send that information via the portal? Here's the "
                "link to the relevant form: [secure portal — Direct Deposit "
                "Setup]. It takes about 30 seconds and we'll have your refund "
                "routing set up the same day.\n\n"
                "We'll also redact the details you sent earlier from our "
                "internal records, so there's no lingering copy of those "
                "numbers in our regular email system.\n\n"
                "Thanks for your patience — it's just for your safety.\n\n"
                "Warm regards,\n"
                "Schiller CPA"
            ),
        ))

        # Escalation: Jane needs to (a) review the response before send, and
        # (b) initiate the redaction workflow with IT.
        db.add(Escalation(
            id=uid(),
            thread_id=thread_id,
            reason=(
                "PII compliance incident. Client Marcus Webb included unredacted "
                "Social Security number and bank routing/account numbers in a "
                "plaintext email. Firm policy requires that any conversation "
                "involving these identifiers be moved to the secure portal "
                "immediately. Required actions: (1) approve the AI's empathetic "
                "redirect-to-portal reply before send, (2) flag the inbound "
                "email for redaction from email logs and any backup retention, "
                "(3) confirm via secure portal once new direct-deposit details "
                "arrive, (4) record the incident in the firm's PII-exposure "
                "log for the quarterly compliance review."
            ),
            severity=EscalationSeverity.high,
            status=EscalationStatus.pending,
            assigned_to_id=jane.id,
            created_at=hours_ago(2),
        ))

        # Sentinel — last so partial failures don't trip false-positive idempotency
        db.add(KnowledgeEntry(
            id=uid(),
            title=SENTINEL_TITLE,
            content="Internal marker for seed_pii_example.py. Do not delete.",
            category="internal",
            entry_type="snippet",
            is_active=False,
            created_by_id=jane.id,
        ))

        db.commit()

        print()
        print("PII demo example seeded.")
        print()
        print("Summary:")
        print("  Thread:     'Account info for direct deposit of my refund'")
        print("  Client:     Marcus Webb <marcus.webb@gmail.com>")
        print("  Status:     escalated (urgent)")
        print("  Severity:   high")
        print("  Escalated:  jane@schilcpa.com")
        print()
        print(
            "Demo angle: AI flags PII in inbound email, drafts an empathetic "
            "redirect-to-secure-portal reply, and escalates for redaction "
            "workflow. Login as Jane to see it on the dashboard."
        )

    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
