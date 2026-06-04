"""
Demo seed script — populates the database with realistic test data for a
tax/accounting firm (Schiller CPA, jane@schilcpa.com).

Idempotent: checks for a sentinel knowledge entry before inserting anything.

Usage:
    cd backend
    source venv/Scripts/activate   # (or venv/bin/activate on Mac/Linux)
    python scripts/seed_demo.py
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
from app.models.user import User, UserRole
from app.services.auth import create_user, get_user_by_email


# ── Helpers ───────────────────────────────────────────────────────────────────

def uid() -> uuid.UUID:
    return uuid.uuid4()


def utc(*args) -> datetime:
    """Return a timezone-aware UTC datetime.  Pass (year, month, day, hour, minute)."""
    return datetime(*args, tzinfo=timezone.utc)


def days_ago(n: int, hour: int = 9, minute: int = 0) -> datetime:
    base = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base - timedelta(days=n)


def hours_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=n)


SENTINEL_TITLE = "__demo_seed_v1__"  # checked to make the script idempotent


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    db = SessionLocal()
    try:
        # ── Idempotency guard ──────────────────────────────────────────────────
        sentinel = db.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.title == SENTINEL_TITLE)
        ).scalar_one_or_none()
        if sentinel is not None:
            print("Demo data already exists. Nothing to do.")
            return

        print("Seeding demo data for Schiller CPA …")

        # ── 1. Staff users ─────────────────────────────────────────────────────
        jane = get_user_by_email(db, "jane@schilcpa.com")
        if jane is None:
            print("  WARNING: Jane's admin account not found. Run seed_admin.py first.")
            print("  Creating a stand-in Jane account for demo purposes …")
            jane = create_user(
                db,
                email="jane@schilcpa.com",
                name="Jane Schiller",
                password="change-me-before-deploying",
                role=UserRole.admin,
            )

        maria = get_user_by_email(db, "maria@schilcpa.com")
        if maria is None:
            maria = create_user(
                db,
                email="maria@schilcpa.com",
                name="Maria Rodriguez",
                password="Staff@2026!",
                role=UserRole.staff,
            )
            print(f"  Created staff user: {maria.email}")
        else:
            print(f"  Staff user already exists: {maria.email}")

        david = get_user_by_email(db, "david@schilcpa.com")
        if david is None:
            david = create_user(
                db,
                email="david@schilcpa.com",
                name="David Chen",
                password="Staff@2026!",
                role=UserRole.staff,
            )
            print(f"  Created staff user: {david.email}")
        else:
            print(f"  Staff user already exists: {david.email}")

        db.flush()

        # ── 2. Knowledge base entries ──────────────────────────────────────────
        print("  Creating knowledge base entries …")

        kb_entries = [
            KnowledgeEntry(
                id=uid(),
                title="Tax Season Extended Hours — 2026",
                content=(
                    "During tax season (January 15 – April 15), Schiller CPA operates on "
                    "extended hours: Monday through Friday 8:00 AM – 7:00 PM, and Saturday "
                    "9:00 AM – 2:00 PM. After April 15, we return to standard hours: "
                    "Monday–Friday 9:00 AM – 5:00 PM. Clients should schedule appointments "
                    "at least 48 hours in advance via our online booking portal."
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane.id,
                tags=["hours", "tax-season", "appointments"],
                usage_count=12,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Individual Return — Required Document Checklist",
                content=(
                    "To prepare your individual federal and state income tax return, please "
                    "provide the following documents:\n\n"
                    "INCOME:\n"
                    "• W-2 forms from all employers\n"
                    "• 1099-NEC / 1099-MISC for freelance or contract income\n"
                    "• 1099-INT and 1099-DIV from banks and brokerages\n"
                    "• 1099-B for investment sales (or brokerage year-end statement)\n"
                    "• SSA-1099 if you received Social Security benefits\n"
                    "• K-1 from any partnerships, S-corps, or trusts\n\n"
                    "DEDUCTIONS & CREDITS:\n"
                    "• Mortgage interest statement (Form 1098)\n"
                    "• Property tax records\n"
                    "• Charitable donation receipts (cash and non-cash)\n"
                    "• Child/dependent care provider name, address, and EIN\n"
                    "• Tuition statements (Form 1098-T)\n"
                    "• Health insurance premiums (if self-employed)\n"
                    "• Business expense records if self-employed (Schedule C)\n\n"
                    "OTHER:\n"
                    "• Prior-year tax return (first-time clients)\n"
                    "• Copy of any IRS or state notices received during the year\n"
                    "• Bank routing and account number for direct deposit of refund"
                ),
                category="process",
                entry_type="policy",
                is_active=True,
                created_by_id=jane.id,
                tags=["documents", "checklist", "individual-return", "W-2"],
                usage_count=31,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Filing Extension — Process and Limitations",
                content=(
                    "We can file IRS Form 4868 on your behalf to grant an automatic 6-month "
                    "extension of time to FILE your return (new deadline: October 15). "
                    "IMPORTANT: an extension of time to file is NOT an extension of time to PAY. "
                    "Any taxes owed are still due by April 15. Failure to pay by April 15 may "
                    "result in interest and late-payment penalties.\n\n"
                    "To request an extension:\n"
                    "1. Contact our office by April 10 at the latest.\n"
                    "2. Provide your best estimate of taxes owed.\n"
                    "3. We will file Form 4868 electronically before the April 15 deadline.\n"
                    "4. You will receive an email confirmation once the extension is accepted.\n\n"
                    "State extensions: most states automatically accept the federal extension; "
                    "however, a few require a separate state form. We will advise you based on "
                    "your state of residence."
                ),
                category="process",
                entry_type="policy",
                is_active=True,
                created_by_id=jane.id,
                tags=["extension", "Form-4868", "deadline", "April-15"],
                usage_count=18,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Standard Email Disclaimer",
                content=(
                    "This communication is from Schiller CPA and is intended solely for the "
                    "use of the individual(s) named above. It may contain information that is "
                    "privileged, confidential, or otherwise protected from disclosure. If you "
                    "are not the intended recipient, please notify us immediately by reply email "
                    "and permanently delete this message. Tax advice contained in this "
                    "communication is not intended or written to be used, and cannot be used, "
                    "to avoid penalties under the Internal Revenue Code."
                ),
                category="compliance",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane.id,
                tags=["disclaimer", "legal", "compliance"],
                usage_count=89,
            ),
            KnowledgeEntry(
                id=uid(),
                title="New Client Welcome Template",
                content=(
                    "Welcome to Schiller CPA! We're delighted to have you as a client and look "
                    "forward to helping you navigate your tax and accounting needs.\n\n"
                    "Here's what to expect as we get started:\n\n"
                    "1. ENGAGEMENT LETTER: You'll receive a client engagement letter within "
                    "1–2 business days. Please review, sign, and return it at your earliest "
                    "convenience.\n"
                    "2. SECURE CLIENT PORTAL: We'll send you login credentials for our secure "
                    "document portal. All sensitive documents should be shared exclusively "
                    "through this portal — never as unencrypted email attachments.\n"
                    "3. INITIAL CONSULTATION: We'd like to schedule a 30-minute onboarding "
                    "call to discuss your financial situation and goals. You can book directly "
                    "using the link on our website.\n\n"
                    "Our office hours during tax season are Monday–Friday 8 AM–7 PM and "
                    "Saturday 9 AM–2 PM. For general inquiries, please allow 1 business day "
                    "for a response.\n\n"
                    "We're here to make taxes as painless as possible!"
                ),
                category="onboarding",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane.id,
                tags=["new-client", "welcome", "onboarding", "template"],
                usage_count=7,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Fee Schedule — Individual Tax Returns (2026)",
                content=(
                    "Our base fees for individual tax preparation are as follows. Final fees "
                    "may vary based on the complexity of your return.\n\n"
                    "Form 1040 (basic, W-2 income only): $350\n"
                    "Form 1040 + Schedule A (itemized deductions): $425\n"
                    "Form 1040 + Schedule C (self-employment): starting at $495\n"
                    "Form 1040 + Schedule D (capital gains/losses): add $75\n"
                    "Form 1040 + Schedule E (rental income or K-1): add $100 per property/entity\n"
                    "State return (per state): $95\n"
                    "Amendment (Form 1040-X): starting at $200\n\n"
                    "ESTIMATED TAX PLANNING: $150/session\n"
                    "AUDIT REPRESENTATION: quoted separately based on scope\n\n"
                    "Payment is due upon delivery of the completed return. We accept check, "
                    "ACH transfer, and all major credit cards. A 50% deposit may be required "
                    "for new clients or complex returns."
                ),
                category="billing",
                entry_type="policy",
                is_active=True,
                created_by_id=jane.id,
                tags=["fees", "pricing", "billing", "1040"],
                usage_count=14,
            ),
            # Sentinel entry — must be last
            KnowledgeEntry(
                id=uid(),
                title=SENTINEL_TITLE,
                content="Internal marker. Do not delete.",
                category="internal",
                entry_type="snippet",
                is_active=False,
                created_by_id=jane.id,
            ),
        ]

        for entry in kb_entries:
            db.add(entry)
        db.flush()
        print(f"  Created {len(kb_entries) - 1} knowledge base entries.")

        # ── 3. Email threads, messages, drafts, and escalations ────────────────
        print("  Creating email threads …")

        threads_created = 0

        # ── Thread 1: Status update — "Where's my tax return?" (SENT) ─────────
        t1_id = uid()
        t1 = EmailThread(
            id=t1_id,
            subject="Status update on my 2025 tax return?",
            client_email="robert.harmon@gmail.com",
            client_name="Robert Harmon",
            status=EmailStatus.sent,
            category=EmailCategory.status_update,
            category_confidence=0.97,
            ai_summary=(
                "Client Robert Harmon is asking about the status of his 2025 individual "
                "tax return, which he submitted documents for on March 3rd. He is expecting "
                "a refund and wants to know when to expect the return to be filed."
            ),
            suggested_reply_tone="professional",
            provider_thread_id="AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0AAv7bPqhM8UKhkS1",
            created_at=days_ago(5),
            updated_at=days_ago(3),
        )
        db.add(t1)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t1_id,
            message_id_header="<20260322.0843.robert.harmon@gmail.com>",
            sender="robert.harmon@gmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(5, hour=8, minute=43),
            is_processed=True,
            body_text=(
                "Hi Jane,\n\n"
                "I wanted to follow up on my tax return for 2025. I dropped off all my "
                "documents on March 3rd and haven't heard anything since. I'm expecting "
                "a decent refund this year and was hoping to use it for home repairs.\n\n"
                "Could you let me know where things stand and when I can expect the return "
                "to be filed? I'd appreciate any update you can give me.\n\n"
                "Thanks,\n"
                "Robert Harmon"
            ),
            raw_headers={"From": "robert.harmon@gmail.com", "To": "jane@schilcpa.com",
                         "Subject": "Status update on my 2025 tax return?"},
        ))

        # Approved draft (already sent)
        t1_draft = DraftResponse(
            id=uid(),
            thread_id=t1_id,
            status=DraftStatus.sent,
            reviewed_by_id=maria.id,
            created_at=days_ago(5, hour=10, minute=15),
            reviewed_at=days_ago(3, hour=14, minute=30),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=812,
            ai_completion_tokens=247,
            body_text=(
                "Dear Robert,\n\n"
                "Thank you for reaching out. I'm happy to report that your 2025 return is "
                "currently in final review and is on track to be filed by March 28th. We "
                "received all of your documents and everything looks complete.\n\n"
                "Based on our preliminary calculations, you are looking at a refund. I'll "
                "send you the completed return for your review and signature before we file. "
                "You should receive that within the next 1–2 business days.\n\n"
                "Please don't hesitate to reach out if you have any questions in the meantime.\n\n"
                "Warm regards,\n"
                "Maria Rodriguez\n"
                "Schiller CPA | (312) 555-0192"
            ),
            original_body_text=(
                "Dear Robert,\n\n"
                "Thank you for reaching out. Your 2025 tax return is currently in final "
                "review. We received all your documents and anticipate filing by March 28th. "
                "You will receive a copy for signature before we file.\n\n"
                "Best regards,\n"
                "Schiller CPA"
            ),
        )
        db.add(t1_draft)

        # Outbound reply (the sent message)
        db.add(EmailMessage(
            id=uid(),
            thread_id=t1_id,
            message_id_header="<20260324.1430.schilcpa.maria@schilcpa.com>",
            sender="jane@schilcpa.com",
            recipient="robert.harmon@gmail.com",
            direction=MessageDirection.outbound,
            received_at=days_ago(3, hour=14, minute=30),
            is_processed=True,
            body_text=t1_draft.body_text,
        ))
        threads_created += 1

        # ── Thread 2: Document request — what docs do I need? (DRAFT READY) ───
        t2_id = uid()
        t2 = EmailThread(
            id=t2_id,
            subject="What documents do I need to bring in?",
            client_email="patricia.nguyen@outlook.com",
            client_name="Patricia Nguyen",
            status=EmailStatus.draft_ready,
            category=EmailCategory.document_request,
            category_confidence=0.94,
            ai_summary=(
                "First-time client Patricia Nguyen is asking what documents she needs to "
                "gather for her individual tax return. She mentions she had freelance income "
                "this year in addition to her W-2 from her primary employer."
            ),
            suggested_reply_tone="professional",
            created_at=days_ago(2),
            updated_at=days_ago(2, hour=11, minute=0),
        )
        db.add(t2)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t2_id,
            message_id_header="<20260325.0917.patricia.nguyen@outlook.com>",
            sender="patricia.nguyen@outlook.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(2, hour=9, minute=17),
            is_processed=True,
            body_text=(
                "Hello,\n\n"
                "I'm a new client — I just signed the engagement letter last week. I'm "
                "preparing to come in and wanted to know exactly what documents I should "
                "bring or upload to the portal.\n\n"
                "I have a regular W-2 from my job at the hospital, but I also did some "
                "freelance graphic design work this year and I'm not sure what I need for "
                "that part. I made about $8,000 from the freelance work.\n\n"
                "Thank you!\n"
                "Patricia Nguyen"
            ),
            raw_headers={"From": "patricia.nguyen@outlook.com", "To": "jane@schilcpa.com"},
        ))

        db.add(DraftResponse(
            id=uid(),
            thread_id=t2_id,
            status=DraftStatus.pending,
            created_at=days_ago(2, hour=9, minute=45),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=1124,
            ai_completion_tokens=389,
            body_text=(
                "Dear Patricia,\n\n"
                "Welcome to Schiller CPA — we're so glad to have you! Great question; "
                "being prepared makes the process much smoother.\n\n"
                "For your situation, please gather the following:\n\n"
                "INCOME DOCUMENTS:\n"
                "• W-2 from your hospital employer\n"
                "• 1099-NEC from each client who paid you $600 or more for freelance work "
                "(clients who paid less may not send one, but you still owe tax on that income)\n"
                "• Records of all freelance income received, even if no 1099 was issued\n\n"
                "FREELANCE BUSINESS EXPENSES (these reduce your taxable freelance income):\n"
                "• Software subscriptions (Adobe Creative Cloud, etc.)\n"
                "• Equipment purchases (cameras, tablets, monitors)\n"
                "• Home office expenses if you have a dedicated workspace\n"
                "• Business mileage log (if you drove to client sites)\n"
                "• Professional development / courses\n\n"
                "STANDARD ITEMS:\n"
                "• Prior-year tax return (helps us verify carryovers and filing history)\n"
                "• Bank account info for direct deposit of any refund\n\n"
                "Please upload everything to your client portal when ready. If you have any "
                "questions about what qualifies as a deductible expense, we're happy to chat "
                "briefly before your appointment.\n\n"
                "Looking forward to working with you!\n\n"
                "Warm regards,\n"
                "Schiller CPA"
            ),
        ))
        threads_created += 1

        # ── Thread 3: Appointment scheduling (CATEGORIZED) ────────────────────
        t3_id = uid()
        t3 = EmailThread(
            id=t3_id,
            subject="Scheduling a meeting to discuss my taxes",
            client_email="michael.burton@burtonroofing.com",
            client_name="Michael Burton",
            status=EmailStatus.categorized,
            category=EmailCategory.appointment,
            category_confidence=0.91,
            ai_summary=(
                "Business client Michael Burton (Burton Roofing) wants to schedule an "
                "in-person appointment to discuss his business taxes and potential quarterly "
                "estimated tax payments for 2026."
            ),
            suggested_reply_tone="professional",
            created_at=days_ago(1),
            updated_at=days_ago(1, hour=10, minute=5),
        )
        db.add(t3)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t3_id,
            message_id_header="<20260326.0952.m.burton@burtonroofing.com>",
            sender="michael.burton@burtonroofing.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(1, hour=9, minute=52),
            is_processed=True,
            body_text=(
                "Jane,\n\n"
                "Hope you're doing well during this busy season. I'd like to come in for a "
                "meeting before the April 15th deadline to go over my business taxes and also "
                "talk about setting up quarterly estimated payments for next year — I got "
                "hit with an underpayment penalty this year and want to avoid that.\n\n"
                "What does your availability look like the week of April 7th? Morning or "
                "early afternoon works best for me.\n\n"
                "Thanks,\n"
                "Michael Burton\n"
                "Burton Roofing LLC"
            ),
            raw_headers={"From": "michael.burton@burtonroofing.com", "To": "jane@schilcpa.com"},
        ))
        threads_created += 1

        # ── Thread 4: IRS Audit Notice (ESCALATED — critical) ─────────────────
        t4_id = uid()
        t4 = EmailThread(
            id=t4_id,
            subject="Received an IRS audit letter — very concerned",
            client_email="linda.castellano@yahoo.com",
            client_name="Linda Castellano",
            status=EmailStatus.escalated,
            category=EmailCategory.urgent,
            category_confidence=0.99,
            ai_summary=(
                "Client Linda Castellano received an IRS CP2000 notice proposing changes to "
                "her 2023 tax return, adding approximately $4,200 in additional tax due to "
                "unreported 1099-B income. The letter is dated March 15 and requests a "
                "response within 60 days. Client is distressed and needs immediate guidance."
            ),
            suggested_reply_tone="empathetic",
            created_at=days_ago(3),
            updated_at=days_ago(3, hour=9, minute=30),
        )
        db.add(t4)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t4_id,
            message_id_header="<20260324.0811.linda.castellano@yahoo.com>",
            sender="linda.castellano@yahoo.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(3, hour=8, minute=11),
            is_processed=True,
            body_text=(
                "Jane,\n\n"
                "I'm really panicking right now. I just received a letter from the IRS "
                "that says I owe an additional $4,200 on my 2023 taxes! The letter is a "
                "CP2000 notice and it looks very official. They are saying I had unreported "
                "income from stock sales.\n\n"
                "I don't understand — you filed my return and everything seemed fine. The "
                "letter says I have 60 days to respond but I don't know what to do. Can "
                "you help me? I can scan and send you the letter.\n\n"
                "I'm really worried about this. Please call me as soon as you can.\n\n"
                "Linda Castellano\n"
                "(312) 555-0847"
            ),
            raw_headers={"From": "linda.castellano@yahoo.com", "To": "jane@schilcpa.com"},
        ))

        esc4 = Escalation(
            id=uid(),
            thread_id=t4_id,
            reason=(
                "Client received IRS CP2000 notice proposing $4,200 in additional tax for "
                "unreported 1099-B income on 2023 return. Client is distressed and requesting "
                "urgent callback. Requires Jane's review of the original return and direct "
                "response to client. Potential audit representation engagement."
            ),
            severity=EscalationSeverity.critical,
            status=EscalationStatus.acknowledged,
            assigned_to_id=jane.id,
            created_at=days_ago(3, hour=8, minute=30),
        )
        db.add(esc4)
        threads_created += 1

        # ── Thread 5: Billing complaint (ESCALATED — high) ────────────────────
        t5_id = uid()
        t5 = EmailThread(
            id=t5_id,
            subject="Question about my invoice — seems too high",
            client_email="george.patel@patelhvac.net",
            client_name="George Patel",
            status=EmailStatus.escalated,
            category=EmailCategory.complaint,
            category_confidence=0.88,
            ai_summary=(
                "Client George Patel is disputing his invoice of $1,485 for his business "
                "tax return, saying it is higher than last year and was not quoted in advance. "
                "He is threatening to take his business elsewhere if the issue is not resolved. "
                "Requires Jane's personal attention."
            ),
            suggested_reply_tone="empathetic",
            created_at=days_ago(4),
            updated_at=days_ago(4, hour=14, minute=0),
        )
        db.add(t5)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t5_id,
            message_id_header="<20260323.1347.george.patel@patelhvac.net>",
            sender="george.patel@patelhvac.net",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(4, hour=13, minute=47),
            is_processed=True,
            body_text=(
                "Jane,\n\n"
                "I just received my invoice for $1,485 and I have to say I'm not happy. "
                "Last year it was $975 and nobody told me it was going to go up this much. "
                "That is a 52% increase and I was not given any warning.\n\n"
                "I understand costs go up but a heads-up would have been appreciated. I run "
                "a small business and this kind of surprise is not acceptable. If Schiller "
                "CPA cannot be more transparent about pricing, I may need to look for "
                "another accountant.\n\n"
                "I would like someone to call me and explain this before I pay anything.\n\n"
                "George Patel\n"
                "Patel HVAC Services"
            ),
            raw_headers={"From": "george.patel@patelhvac.net", "To": "jane@schilcpa.com"},
        ))

        esc5 = Escalation(
            id=uid(),
            thread_id=t5_id,
            reason=(
                "Client George Patel is disputing a 52% fee increase on his invoice ($975 → "
                "$1,485) and threatening to leave the firm. Requires Jane to review the billing "
                "history, explain the increase (likely additional Schedule E rental income this "
                "year), and personally reach out to retain the client relationship."
            ),
            severity=EscalationSeverity.high,
            status=EscalationStatus.pending,
            assigned_to_id=jane.id,
            created_at=days_ago(4, hour=14, minute=0),
        )
        db.add(esc5)
        threads_created += 1

        # ── Thread 6: New client onboarding inquiry (DRAFT READY) ─────────────
        t6_id = uid()
        t6 = EmailThread(
            id=t6_id,
            subject="Inquiry about becoming a new client",
            client_email="sarah.vantassel@gmail.com",
            client_name="Sarah Van Tassel",
            status=EmailStatus.draft_ready,
            category=EmailCategory.general_inquiry,
            category_confidence=0.85,
            ai_summary=(
                "Prospective client Sarah Van Tassel is inquiring about switching to Schiller "
                "CPA from her previous accountant. She is self-employed (freelance writer) and "
                "owns a rental property. She wants to know about services and pricing."
            ),
            suggested_reply_tone="professional",
            created_at=hours_ago(6),
            updated_at=hours_ago(5),
        )
        db.add(t6)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t6_id,
            message_id_header="<20260327.0914.sarah.vantassel@gmail.com>",
            sender="sarah.vantassel@gmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=hours_ago(6),
            is_processed=True,
            body_text=(
                "Hello,\n\n"
                "I found Schiller CPA through a referral from my neighbor (Robert Harmon) "
                "and I'm looking to switch accountants for the 2025 tax year if it's not "
                "too late.\n\n"
                "My situation: I'm a freelance writer (1099 income, roughly $65,000/year), "
                "I also have a rental property in Oak Park that I've had since 2019, and my "
                "husband has a regular W-2 job. We file jointly.\n\n"
                "Can you tell me more about your services and what the fee would be for "
                "our situation? I'd love to schedule a consultation if there's still time "
                "before the deadline.\n\n"
                "Thank you!\n"
                "Sarah Van Tassel"
            ),
            raw_headers={"From": "sarah.vantassel@gmail.com", "To": "jane@schilcpa.com"},
        ))

        db.add(DraftResponse(
            id=uid(),
            thread_id=t6_id,
            status=DraftStatus.pending,
            created_at=hours_ago(5),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=987,
            ai_completion_tokens=412,
            body_text=(
                "Dear Sarah,\n\n"
                "What a lovely way to find us — thank you to Robert for the kind referral! "
                "We'd be delighted to work with you, and yes, there's still time to get your "
                "2025 return filed before April 15th.\n\n"
                "Your situation is one we handle frequently and enjoy: a married couple filing "
                "jointly with a mix of freelance income, a rental property, and W-2 income. "
                "Here's a rough overview of what to expect:\n\n"
                "SERVICES FOR YOUR SITUATION:\n"
                "• Joint Form 1040 with Schedule C (freelance writing business)\n"
                "• Schedule E (rental property — income, depreciation, expenses)\n"
                "• Your state return\n"
                "• Year-round support for questions between filings\n\n"
                "ESTIMATED FEE: $695–$795 depending on the complexity of the rental "
                "property and business expenses. We'll give you a firm quote after a brief "
                "15-minute intake call.\n\n"
                "NEXT STEPS: I'd suggest scheduling a free 15-minute consultation via the "
                "link on our website. We can confirm scope, get you onboarded, and get your "
                "documents collected — all before the deadline.\n\n"
                "Looking forward to meeting you!\n\n"
                "Warm regards,\n"
                "Schiller CPA"
            ),
        ))
        threads_created += 1

        # ── Thread 7: Deduction clarification (PENDING REVIEW) ────────────────
        t7_id = uid()
        t7 = EmailThread(
            id=t7_id,
            subject="Question about home office deduction",
            client_email="kevin.omalley@omalleyconsulting.com",
            client_name="Kevin O'Malley",
            status=EmailStatus.pending_review,
            category=EmailCategory.clarification,
            category_confidence=0.92,
            ai_summary=(
                "Client Kevin O'Malley is asking whether his co-working space membership "
                "and home office qualify for deductions, given that he works from home three "
                "days a week and uses a co-working space two days. He is confused about the "
                "rules around exclusive use."
            ),
            suggested_reply_tone="direct",
            created_at=days_ago(2),
            updated_at=days_ago(1, hour=16, minute=20),
        )
        db.add(t7)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t7_id,
            message_id_header="<20260325.1102.k.omalley@omalleyconsulting.com>",
            sender="kevin.omalley@omalleyconsulting.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(2, hour=11, minute=2),
            is_processed=True,
            body_text=(
                "Hi Maria,\n\n"
                "Hope you're surviving tax season! I had a question about deductions that "
                "I've been going back and forth on.\n\n"
                "I work from home Monday, Wednesday, Friday, and then I go to a WeWork "
                "space Tuesday and Thursday. My home office is a dedicated room that I only "
                "use for work. Can I deduct both the co-working membership AND the home office? "
                "I wasn't sure if using the WeWork space affects my ability to claim the "
                "home office since I'm not there every day.\n\n"
                "The room at home is about 150 sq ft out of a 1,500 sq ft house if that "
                "helps with calculations.\n\n"
                "Thanks!\n"
                "Kevin"
            ),
            raw_headers={"From": "kevin.omalley@omalleyconsulting.com", "To": "jane@schilcpa.com"},
        ))

        # Staff-edited draft (pending review)
        db.add(DraftResponse(
            id=uid(),
            thread_id=t7_id,
            status=DraftStatus.edited,
            reviewed_by_id=david.id,
            created_at=days_ago(2, hour=11, minute=30),
            reviewed_at=days_ago(1, hour=16, minute=20),
            version=2,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=1043,
            ai_completion_tokens=356,
            body_text=(
                "Hi Kevin,\n\n"
                "Great question — this comes up a lot with remote workers, and the good "
                "news is you can likely deduct both.\n\n"
                "HOME OFFICE (Schedule C): Since you use that room exclusively and regularly "
                "for business, you qualify for the home office deduction. The fact that you "
                "also work elsewhere doesn't disqualify your home office — as long as the "
                "home office is your principal place of business for administrative work. "
                "For a 150/1,500 sq ft space, that's a 10% allocation, which you can apply "
                "to rent/mortgage interest, utilities, and insurance.\n\n"
                "CO-WORKING SPACE: Your WeWork membership is a fully deductible business "
                "expense on Schedule C — no limitations, since it's a direct cost of doing "
                "business.\n\n"
                "SIMPLIFIED METHOD OPTION: You can also use the IRS Simplified Method "
                "($5/sq ft × 150 sq ft = $750/year) instead of calculating actual expenses. "
                "We'll figure out which gives you the better deduction.\n\n"
                "We'll work through the exact numbers when we have your full return "
                "in front of us. Let us know if you have any other questions!\n\n"
                "Best,\n"
                "David Chen\n"
                "Schiller CPA"
            ),
            original_body_text=(
                "Hi Kevin,\n\n"
                "You can deduct both your home office and co-working space. The home office "
                "deduction requires exclusive and regular use for business. Since your room "
                "meets this test, the 10% allocation applies. The WeWork is a direct business "
                "expense. We'll calculate which method works best at filing time.\n\n"
                "Best,\nSchiller CPA"
            ),
        ))
        threads_created += 1

        # ── Thread 8: W-2 follow-up, outbound (SENT) ──────────────────────────
        t8_id = uid()
        t8 = EmailThread(
            id=t8_id,
            subject="Following up: missing W-2 from Apex Retail",
            client_email="diane.moreau@gmail.com",
            client_name="Diane Moreau",
            status=EmailStatus.sent,
            category=EmailCategory.document_request,
            category_confidence=0.90,
            ai_summary=(
                "Schiller CPA is following up with client Diane Moreau regarding a missing "
                "W-2 from her part-time employer Apex Retail. Without it, her return cannot "
                "be completed. Staff sent an initial follow-up; no response yet."
            ),
            suggested_reply_tone="professional",
            created_at=days_ago(6),
            updated_at=days_ago(4, hour=10, minute=0),
        )
        db.add(t8)

        # Original inbound message (Diane sent documents, but W-2 was missing)
        db.add(EmailMessage(
            id=uid(),
            thread_id=t8_id,
            message_id_header="<20260321.1523.diane.moreau@gmail.com>",
            sender="diane.moreau@gmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(6, hour=15, minute=23),
            is_processed=True,
            body_text=(
                "Hi,\n\n"
                "I uploaded all my documents to the portal — W-2 from my main job at "
                "Northwestern Memorial, my 1099-INT from Chase, and my mortgage statement. "
                "I think that's everything!\n\n"
                "Let me know if you need anything else.\n\n"
                "Diane"
            ),
            raw_headers={"From": "diane.moreau@gmail.com", "To": "jane@schilcpa.com"},
        ))

        # Outbound follow-up from firm
        db.add(EmailMessage(
            id=uid(),
            thread_id=t8_id,
            message_id_header="<20260323.1000.schilcpa.david@schilcpa.com>",
            sender="jane@schilcpa.com",
            recipient="diane.moreau@gmail.com",
            direction=MessageDirection.outbound,
            received_at=days_ago(4, hour=10, minute=0),
            is_processed=True,
            body_text=(
                "Hi Diane,\n\n"
                "Thank you for uploading your documents! We've reviewed what you sent and "
                "we have everything we need, with one exception: our records show you worked "
                "part-time at Apex Retail during 2025, but we don't see a W-2 from them in "
                "your portal.\n\n"
                "Could you check whether you received a W-2 from Apex Retail, either by "
                "mail or through their employee portal? Employers are required to issue W-2s "
                "by January 31st, so it should be available.\n\n"
                "We can't complete your return until we have all income documents, so "
                "please send that over as soon as possible so we can stay on track for "
                "filing before April 15th.\n\n"
                "Thank you!\n\n"
                "David Chen\n"
                "Schiller CPA | (312) 555-0192"
            ),
        ))

        db.add(DraftResponse(
            id=uid(),
            thread_id=t8_id,
            status=DraftStatus.sent,
            reviewed_by_id=david.id,
            created_at=days_ago(4, hour=9, minute=30),
            reviewed_at=days_ago(4, hour=9, minute=55),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=623,
            ai_completion_tokens=198,
            body_text=(
                "Hi Diane,\n\n"
                "Thank you for uploading your documents! We've reviewed what you sent and "
                "we have everything we need, with one exception: our records show you worked "
                "part-time at Apex Retail during 2025, but we don't see a W-2 from them in "
                "your portal.\n\n"
                "Could you check whether you received a W-2 from Apex Retail, either by "
                "mail or through their employee portal? Employers are required to issue W-2s "
                "by January 31st, so it should be available.\n\n"
                "We can't complete your return until we have all income documents, so "
                "please send that over as soon as possible so we can stay on track for "
                "filing before April 15th.\n\n"
                "Thank you!\n\n"
                "David Chen\n"
                "Schiller CPA | (312) 555-0192"
            ),
        ))
        threads_created += 1

        # ── Thread 9: Extension request (CATEGORIZED) ─────────────────────────
        t9_id = uid()
        t9 = EmailThread(
            id=t9_id,
            subject="Need to file for an extension",
            client_email="tony.ferreira@ferreiralaw.com",
            client_name="Tony Ferreira",
            status=EmailStatus.categorized,
            category=EmailCategory.general_inquiry,
            category_confidence=0.93,
            ai_summary=(
                "Client Tony Ferreira (attorney) is requesting a filing extension because "
                "he is waiting on K-1 forms from two partnerships and will not have all "
                "his documents before April 15th. He wants to confirm the process and "
                "understand if he needs to make an estimated payment."
            ),
            suggested_reply_tone="professional",
            created_at=hours_ago(3),
            updated_at=hours_ago(3),
        )
        db.add(t9)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t9_id,
            message_id_header="<20260327.1244.tony.ferreira@ferreiralaw.com>",
            sender="tony.ferreira@ferreiralaw.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=hours_ago(3),
            is_processed=True,
            body_text=(
                "Jane,\n\n"
                "I'm writing because I'm going to need an extension this year. I'm a partner "
                "in two small LLCs and neither of them has issued their K-1s yet — apparently "
                "those partnerships are also extending. Without those K-1s, my return is "
                "incomplete.\n\n"
                "Can you file the extension on my behalf? I also want to make sure I don't "
                "get penalized. Do I need to send in a payment with the extension, and if so, "
                "how do I figure out how much?\n\n"
                "Thanks,\n"
                "Tony Ferreira"
            ),
            raw_headers={"From": "tony.ferreira@ferreiralaw.com", "To": "jane@schilcpa.com"},
        ))
        threads_created += 1

        # ── Thread 10: General pricing inquiry (NEW) ───────────────────────────
        t10_id = uid()
        t10 = EmailThread(
            id=t10_id,
            subject="Pricing inquiry — individual tax return",
            client_email="anonymous.inquiry@hotmail.com",
            client_name=None,
            status=EmailStatus.new,
            category=EmailCategory.uncategorized,
            category_confidence=None,
            ai_summary=None,
            suggested_reply_tone="professional",
            created_at=hours_ago(1),
            updated_at=hours_ago(1),
        )
        db.add(t10)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t10_id,
            message_id_header="<20260327.1501.inquiry@hotmail.com>",
            sender="anonymous.inquiry@hotmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=hours_ago(1),
            is_processed=False,
            body_text=(
                "Hello,\n\n"
                "I'm looking for a CPA to do my individual taxes this year. Can you tell me "
                "how much you charge? I have a fairly simple return — just W-2 income and "
                "a mortgage.\n\n"
                "Thank you"
            ),
            raw_headers={"From": "anonymous.inquiry@hotmail.com", "To": "jane@schilcpa.com"},
        ))
        threads_created += 1

        # ── Thread 11: Urgent estimated taxes deadline (ESCALATED — medium) ────
        t11_id = uid()
        t11 = EmailThread(
            id=t11_id,
            subject="Estimated tax payment due — need help calculating Q1",
            client_email="rebecca.shaw@shawdesignstudio.com",
            client_name="Rebecca Shaw",
            status=EmailStatus.escalated,
            category=EmailCategory.urgent,
            category_confidence=0.96,
            ai_summary=(
                "Self-employed client Rebecca Shaw realizes her Q1 2026 estimated tax "
                "payment is due April 15th and she has no idea what to pay. She had a "
                "significantly higher income in 2025 than 2024 and is worried about "
                "underpayment penalties. Needs urgent attention due to the upcoming deadline."
            ),
            suggested_reply_tone="empathetic",
            created_at=hours_ago(4),
            updated_at=hours_ago(4),
        )
        db.add(t11)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t11_id,
            message_id_header="<20260327.1118.rebecca.shaw@shawdesignstudio.com>",
            sender="rebecca.shaw@shawdesignstudio.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=hours_ago(4),
            is_processed=True,
            body_text=(
                "Hi Jane,\n\n"
                "I just realized — my Q1 estimated tax payment for 2026 is due April 15th "
                "and I have no idea what to send. I'm self-employed and my income was much "
                "higher in 2025 than in 2024 (roughly double). I don't want to underpay "
                "and get hit with penalties.\n\n"
                "Can you help me figure out what I should be paying? I know you're busy "
                "but this feels urgent. I have my 2024 return for reference.\n\n"
                "Thank you,\n"
                "Rebecca Shaw\n"
                "Shaw Design Studio"
            ),
            raw_headers={"From": "rebecca.shaw@shawdesignstudio.com", "To": "jane@schilcpa.com"},
        ))

        esc11 = Escalation(
            id=uid(),
            thread_id=t11_id,
            reason=(
                "Self-employed client Rebecca Shaw needs Q1 2026 estimated tax calculation "
                "before April 15th deadline (19 days away). Her income doubled in 2025. "
                "This requires Jane or senior staff to pull her 2025 return, calculate safe "
                "harbor amounts, and respond with a payment voucher. Time-sensitive."
            ),
            severity=EscalationSeverity.medium,
            status=EscalationStatus.pending,
            assigned_to_id=maria.id,
            created_at=hours_ago(4),
        )
        db.add(esc11)
        threads_created += 1

        # ── Thread 12: Thank you / closed ─────────────────────────────────────
        t12_id = uid()
        t12 = EmailThread(
            id=t12_id,
            subject="Thank you for another great year!",
            client_email="carol.bishop@gmail.com",
            client_name="Carol Bishop",
            status=EmailStatus.closed,
            category=EmailCategory.general_inquiry,
            category_confidence=0.78,
            ai_summary=(
                "Long-time client Carol Bishop sent a thank-you email after receiving her "
                "completed 2025 tax return. She is pleased with the service and mentioned "
                "she referred two friends to the firm."
            ),
            suggested_reply_tone="empathetic",
            created_at=days_ago(7),
            updated_at=days_ago(6, hour=11, minute=0),
        )
        db.add(t12)

        db.add(EmailMessage(
            id=uid(),
            thread_id=t12_id,
            message_id_header="<20260320.1634.carol.bishop@gmail.com>",
            sender="carol.bishop@gmail.com",
            recipient="jane@schilcpa.com",
            direction=MessageDirection.inbound,
            received_at=days_ago(7, hour=16, minute=34),
            is_processed=True,
            body_text=(
                "Dear Jane and team,\n\n"
                "I just wanted to say thank you for another wonderful year. You've been "
                "doing my taxes for seven years now and I always feel so taken care of. "
                "The fact that you caught that IRA deduction I had missed — that alone "
                "saved me almost $600!\n\n"
                "I've already referred two friends who were looking for a new accountant: "
                "Sarah Van Tassel and James Okonkwo. I hope they reach out.\n\n"
                "See you next year (or sooner if I have questions).\n\n"
                "With gratitude,\n"
                "Carol Bishop"
            ),
            raw_headers={"From": "carol.bishop@gmail.com", "To": "jane@schilcpa.com"},
        ))

        # Warm reply that was sent
        db.add(EmailMessage(
            id=uid(),
            thread_id=t12_id,
            message_id_header="<20260321.1100.schilcpa.jane@schilcpa.com>",
            sender="jane@schilcpa.com",
            recipient="carol.bishop@gmail.com",
            direction=MessageDirection.outbound,
            received_at=days_ago(6, hour=11, minute=0),
            is_processed=True,
            body_text=(
                "Dear Carol,\n\n"
                "This truly made our day! Thank you so much for your kind words — it means "
                "the world to us to hear that our work makes a real difference.\n\n"
                "Seven years together and counting! We love having you as a client and we're "
                "so glad we caught that IRA deduction for you.\n\n"
                "And thank you for the referrals — that is the highest compliment we can "
                "receive. We'll make sure Sarah and James are well taken care of.\n\n"
                "Here's to many more years of working together. Don't hesitate to reach "
                "out if anything comes up!\n\n"
                "Warmly,\n"
                "Jane Schiller\n"
                "Schiller CPA"
            ),
        ))

        db.add(DraftResponse(
            id=uid(),
            thread_id=t12_id,
            status=DraftStatus.sent,
            reviewed_by_id=jane.id,
            created_at=days_ago(6, hour=10, minute=40),
            reviewed_at=days_ago(6, hour=10, minute=58),
            version=1,
            ai_model="claude-sonnet-4-5",
            ai_prompt_tokens=534,
            ai_completion_tokens=189,
            body_text=(
                "Dear Carol,\n\n"
                "This truly made our day! Thank you so much for your kind words — it means "
                "the world to us to hear that our work makes a real difference.\n\n"
                "Seven years together and counting! We love having you as a client and we're "
                "so glad we caught that IRA deduction for you.\n\n"
                "And thank you for the referrals — that is the highest compliment we can "
                "receive. We'll make sure Sarah and James are well taken care of.\n\n"
                "Here's to many more years of working together. Don't hesitate to reach "
                "out if anything comes up!\n\n"
                "Warmly,\n"
                "Jane Schiller\n"
                "Schiller CPA"
            ),
        ))
        threads_created += 1

        # ── Commit everything ──────────────────────────────────────────────────
        db.commit()

        print(f"  Created {threads_created} email threads with messages, drafts, and escalations.")
        print()
        print("Demo seed complete.")
        print()
        print("Summary:")
        print("  Staff users:        Maria Rodriguez, David Chen")
        print("  Email threads:      12 (new / categorized / draft_ready / pending_review / sent / escalated / closed)")
        print("  Drafts:             7  (pending / edited / sent)")
        print("  Escalations:        3  (critical / high / medium)")
        print("  Knowledge entries:  6")
        print()
        print("Login credentials for demo staff:")
        print("  jane@schilcpa.com  — (from seed_admin.py / .env ADMIN_PASSWORD)")
        print("  maria@schilcpa.com — Staff@2026!")
        print("  david@schilcpa.com — Staff@2026!")

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
