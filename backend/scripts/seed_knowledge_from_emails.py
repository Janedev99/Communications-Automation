"""
Seed knowledge base from Jane's REAL email patterns.

Analyzes Jane Schilmoeller's 29 curated emails and creates KnowledgeEntry
records that capture her authentic voice, communication style, and response
patterns across all email categories.

Idempotent: checks for a sentinel entry before inserting anything.

Usage:
    cd backend
    source venv/Scripts/activate   # (or venv/bin/activate on Mac/Linux)
    python scripts/seed_knowledge_from_emails.py
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow importing from app/ when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from sqlalchemy import select

from app.database import SessionLocal
from app.models.email import KnowledgeEntry
from app.models.user import User
from app.services.auth import get_user_by_email


# ── Helpers ──────────────────────────────────────────────────────────────────

def uid() -> uuid.UUID:
    return uuid.uuid4()


SENTINEL_TITLE = "__jane_email_seed_v1__"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    db = SessionLocal()
    try:
        # ── Idempotency guard ─────────────────────────────────────────────
        sentinel = db.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.title == SENTINEL_TITLE)
        ).scalar_one_or_none()
        if sentinel is not None:
            print("Jane's email-based knowledge entries already exist. Nothing to do.")
            return

        print("Seeding knowledge base from Jane's real email patterns ...")

        # ── Resolve Jane's user ID ────────────────────────────────────────
        jane = get_user_by_email(db, "jane@schilcpa.com")
        jane_id = jane.id if jane else None
        if jane is None:
            print("  WARNING: Jane's account not found. Entries will have no created_by.")

        # ── POLICIES ──────────────────────────────────────────────────────
        print("  Creating policy entries ...")

        policies = [
            KnowledgeEntry(
                id=uid(),
                title="Jane's Communication Style - Core Principles",
                content=(
                    "Jane's emails follow a consistent warm-but-professional tone. Key rules:\n\n"
                    "1. ALWAYS open with a personal touch - comment on the client's life, travel, "
                    "retirement, projects, or family before diving into business.\n"
                    "2. Use 'Good morning,' or 'Hi [Name] -' as greetings. Never 'Dear' for "
                    "existing clients.\n"
                    "3. Close with 'Thanks and have a great day,' or 'Thanks and have a wonderful "
                    "day,' followed by 'Jane' on a separate line.\n"
                    "4. Use numbered lists for action items and questions. Use bullet points (*) "
                    "for sub-items under numbered items.\n"
                    "5. Always offer to answer questions: 'Please let me know if you have any "
                    "questions.' or 'Please reach out with any questions.'\n"
                    "6. When delegating to staff, explicitly name them and explain their role: "
                    "'Sandra (cc'd above) will send you a separate email when...'\n"
                    "7. Acknowledge the client's situation before providing guidance.\n"
                    "8. Keep technical explanations clear but not condescending - assume smart "
                    "clients who are not tax experts.\n"
                    "9. When things are busy, be honest: 'things are quite busy at the office "
                    "these days' rather than making excuses.\n"
                    "10. Compliment staff work when forwarding internally: 'You did a great job "
                    "on these two returns!'"
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["communication-style", "tone", "voice", "jane-patterns"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Email Structure Rules",
                content=(
                    "Jane's emails follow a consistent structure:\n\n"
                    "GREETING: 'Good morning,' (most common) | 'Hi [Name],' | 'Hi [Name] -' "
                    "(with dash for internal/familiar contacts)\n\n"
                    "PERSONAL TOUCH (for client-facing emails): One sentence acknowledging the "
                    "client's life - travel plans, retirement, health, family events. Examples:\n"
                    "- 'Your travel plans sound fabulous! I've eyed those European river cruises "
                    "- let me know how wonderful it is!'\n"
                    "- 'I hope you are doing well these days!'\n"
                    "- 'I hope things are going well with you these days!'\n"
                    "- 'Congratulations Steve! How are you adjusting to putting your feet up and "
                    "relaxing?'\n\n"
                    "BODY: Clear, organized content. Numbered lists for questions or action items. "
                    "Bullet points for supporting details under numbered items.\n\n"
                    "CLOSE: 'Thanks and have a great day,' | 'Have a great day,' | "
                    "'Thanks and have a wonderful day,' | 'Thanks,' | 'Thanks!'\n\n"
                    "SIGNATURE: 'Jane' on its own line. Full signature block for first emails in "
                    "a thread. Shorter 'Jane' for replies.\n\n"
                    "STAFF DELEGATION: When cc'ing staff, always explain who they are: "
                    "'Sandra Rivera (cc'd above) will upload the returns to our portal...'"
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["email-structure", "formatting", "jane-patterns"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Numbered List and Action Item Style",
                content=(
                    "Jane uses a very specific format for numbered lists and action items:\n\n"
                    "FOR QUESTIONS TO CLIENTS (clarification):\n"
                    "Numbered items (1, 2, 3...) each as a distinct question. Sub-items use "
                    "letters (a, b, c) or bullets. Always ends the question directly - no "
                    "unnecessary filler. Example pattern:\n"
                    "1. We understand [fact]. Correct?\n"
                    "2. Should we [action] or [alternative]?\n"
                    "3. For [topic], please provide:\n"
                    "   a. [specific item]\n"
                    "   b. [specific item]\n\n"
                    "FOR INSTRUCTIONS TO STAFF:\n"
                    "Numbered items are directives, concise and clear. Example pattern:\n"
                    "1. Prep 2025 [Entity] for PDF delivery on portal.\n"
                    "2. Federal and [State].\n"
                    "3. Attach Federal extension.\n"
                    "4. Prep T ltr and filing instructions.\n"
                    "5. Send to [Client] for approval.\n\n"
                    "FOR TAX GUIDANCE TO CLIENTS:\n"
                    "Numbered or bulleted points explaining tax concepts. Uses plain language "
                    "with occasional technical terms. Always frames the net benefit. Example:\n"
                    "* Your 2026 charitable donation will be the Fair Market Value on the "
                    "donation date.\n"
                    "* A formal appraisal will be needed (IRS requirement when property > $5k).\n"
                    "* The deduction will be limited to 50% of AGI. If limited, the excess "
                    "carries over - so it is not lost."
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["formatting", "numbered-lists", "action-items", "jane-patterns"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Client Communication Delegation Policy",
                content=(
                    "When involving staff members in client communications, Jane follows these "
                    "patterns:\n\n"
                    "1. Always name the staff member explicitly: 'Sandra Rivera (cc'd above)' "
                    "or 'Simmi (cc'd above)'\n"
                    "2. Explain what the staff member will do: 'Sandra will upload the returns "
                    "to our portal for your review and approval. She will send you a separate "
                    "email when it has been uploaded.'\n"
                    "3. Ask clients to cc staff on future emails: 'Please cc Sandra (cc'd above) "
                    "on all emails so we don't miss anything on our end.'\n"
                    "4. When redirecting to staff: '[Staff member] is the best person to receive "
                    "the secure links.' or 'Sandra Rivera may be able to help you and can be "
                    "reached at our office number (below), Extension 3.'\n"
                    "5. Keep ownership clear: 'Sandra is on top of gathering your information, "
                    "so please continue to communicate with her on that project. I will be very "
                    "involved in the estimate calculations after most of your information is "
                    "received.'"
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["delegation", "staff", "communication-policy", "jane-patterns"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Approach to Tax Explanations",
                content=(
                    "When explaining tax concepts, Jane follows these principles:\n\n"
                    "1. Lead with the conclusion/benefit first, then explain the mechanics.\n"
                    "   Example: 'Appreciated stock is definitely the way to go. The deduction "
                    "will be the Fair Market Value, and the gain does not have to be recognized.'\n\n"
                    "2. Use simple analogies: '(similar to appreciated stock)'\n\n"
                    "3. Always note when something is an IRS requirement vs. optional: "
                    "'A formal appraisal will be needed to establish the deduction (IRS "
                    "requirement when property greater than $5k is donated).'\n\n"
                    "4. Reassure when a limitation exists: 'If limited, the excess carries over "
                    "to future years - so it is not lost.'\n\n"
                    "5. Offer forward planning: 'Depending on your planned charitable giving, "
                    "it might make sense to group contributions into one year and then take "
                    "advantage of the standard deduction in the next year. If helpful, we can "
                    "help with planning when you are ready.'\n\n"
                    "6. Use 'Make sense?' as an informal check-in after complex explanations.\n\n"
                    "7. Show the math when it helps: 'Credit: ($6,402) reduction of tax. "
                    "Deduction add back: $6,402 * 30% tax rate = $1,920. So, the net reduction "
                    "of tax is ($4,482).'"
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["tax-explanations", "client-education", "jane-patterns"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Approach to New/Potential Client Inquiries",
                content=(
                    "When responding to potential client referrals, Jane's approach:\n\n"
                    "1. Express genuine appreciation: 'Great to hear from you!'\n"
                    "2. Clearly state the firm's ideal client profile: 'The best fit for us is "
                    "when they have complex tax issues (K-1s, multiple accounts, business "
                    "owners, etc.) This is when we can bring value to the table.'\n"
                    "3. Be upfront about timing constraints: 'For 2025 returns, we would need "
                    "to file an extension and work through details after April 15th.'\n"
                    "4. Check if it works for the referrer: 'Not sure if that would work for "
                    "them? If so, we'd gladly talk to them!'\n"
                    "5. Thank them for the referral: 'Thanks for thinking of us,'\n\n"
                    "Key: Jane is honest about fit and timing rather than accepting everyone. "
                    "She positions limitations as practical realities, not rejections."
                ),
                category="policy",
                entry_type="policy",
                is_active=True,
                created_by_id=jane_id,
                tags=["new-clients", "referrals", "intake", "jane-patterns"],
                usage_count=0,
            ),
        ]

        # ── SNIPPETS ──────────────────────────────────────────────────────
        print("  Creating snippet entries ...")

        snippets = [
            KnowledgeEntry(
                id=uid(),
                title="Jane's Greeting - Good Morning",
                content="Good morning,",
                category="greeting",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["greeting", "opening", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Greeting - Hi Name",
                content="Hi [Client Name],",
                category="greeting",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["greeting", "opening", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Greeting - Hi Name with Dash",
                content="Hi [Client Name] -",
                category="greeting",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["greeting", "opening", "jane-voice", "informal"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Sign-Off - Thanks and Great Day",
                content="Thanks and have a great day,\n\nJane",
                category="sign-off",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["sign-off", "closing", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Sign-Off - Thanks and Wonderful Day",
                content="Thanks and have a wonderful day,\n\nJane",
                category="sign-off",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["sign-off", "closing", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Sign-Off - Have a Great Day",
                content="Have a great day,\n\nJane",
                category="sign-off",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["sign-off", "closing", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Sign-Off - Short Thanks",
                content="Thanks!\n\nJane",
                category="sign-off",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["sign-off", "closing", "jane-voice", "brief"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Sign-Off - Thanks Only",
                content="Thanks,\n\nJane",
                category="sign-off",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["sign-off", "closing", "jane-voice", "brief"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Personal Touch - Hope Doing Well",
                content=(
                    "Personal warmth phrases Jane uses at the start of emails:\n"
                    "- 'I hope you are doing well these days!'\n"
                    "- 'I hope things are going well with you these days!'\n"
                    "- 'I hope you are doing well these days.'\n"
                    "Use these when you don't have specific knowledge of the client's "
                    "recent activities."
                ),
                category="personal-touch",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["personal-touch", "warmth", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Personal Touch - Commenting on Client Activities",
                content=(
                    "When Jane knows about a client's activities, she comments specifically:\n"
                    "- 'Your travel plans sound fabulous! I've eyed those European river "
                    "cruises - let me know how wonderful it is!'\n"
                    "- 'Congratulations Steve! How are you adjusting to putting your feet up "
                    "and relaxing? I suspect you'll find many meaningful projects to embrace!'\n"
                    "- 'This chapel will be so lovely. Please send us pictures as the project "
                    "develops!'\n"
                    "- 'Thanks for your thorough note.'\n\n"
                    "Key pattern: Show genuine interest, ask follow-up questions, express "
                    "excitement about their life events."
                ),
                category="personal-touch",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["personal-touch", "client-engagement", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's CC Staff Instruction Phrase",
                content=(
                    "Phrases Jane uses when asking clients to include staff:\n"
                    "- 'Please cc Sandra (cc'd above) on all emails so we don't miss anything "
                    "on our end.'\n"
                    "- '(Please cc Sandra Rivera - cc'd above - on all emails so we don't "
                    "overlook anything.)'\n"
                    "- 'Please cc Simmi on emails so we don't miss anything on our end.'"
                ),
                category="delegation",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["delegation", "staff-cc", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Portal Upload Notification Phrase",
                content=(
                    "Standard phrases Jane uses when notifying clients about portal uploads:\n"
                    "- 'Tomorrow, Sandra Rivera will upload the returns to our portal for your "
                    "review and approval. She will send you a separate email when it has been "
                    "uploaded.'\n"
                    "- 'Sandra (cc'd above) will send you a separate email when your return "
                    "has been uploaded.'\n"
                    "- 'Later today, Sandra will upload the returns to our portal for your "
                    "review and approval. She'll send you a separate email when your return "
                    "has been uploaded.'\n"
                    "- 'Sandra will upload the returns to our portal for your review and "
                    "approval. She'll send you a separate email when your return has been "
                    "uploaded.'"
                ),
                category="process",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["portal", "upload", "notification", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Reassurance Phrases",
                content=(
                    "Phrases Jane uses to reassure clients about common concerns:\n"
                    "- 'Late K-1s are a common event, so we are on top of it.'\n"
                    "- 'If limited, the excess carries over to future years - so it is not "
                    "lost.'\n"
                    "- 'If limited, the excess carries over - so it is not lost.'\n"
                    "- 'Unfortunately this is likely to take 3-6 months to resolve. The IRS "
                    "is VERY short handed these days, so anything that requires a \"real "
                    "person\" is very slow.'\n"
                    "- 'There should not be penalties or interest related to this return.'\n"
                    "- 'Please continue to forward to me any notices you receive.'"
                ),
                category="reassurance",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["reassurance", "client-comfort", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Question Follow-Up Phrases",
                content=(
                    "Phrases Jane uses to invite questions:\n"
                    "- 'Please let me know if you have any questions.'\n"
                    "- 'Please reach out with any questions.'\n"
                    "- 'If you have any questions, please let me know.'\n"
                    "- 'Please let us know if you need anything from us.'\n"
                    "- 'Make sense?' (after complex tax explanations)\n"
                    "- 'If you need anything from us, please let us know.'"
                ),
                category="closing",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["questions", "follow-up", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Jane's Staff Compliment Phrases",
                content=(
                    "When providing internal feedback, Jane uses warm, specific compliments:\n"
                    "- 'You did a great job on these two returns!'\n"
                    "- 'Angel Island looks great!'\n"
                    "- 'Looks great! Let's go!'\n"
                    "- 'I want to walk through them with you tomorrow so you understand "
                    "the changes I made.' (constructive, not critical)\n\n"
                    "Pattern: Compliment first, then discuss changes needed."
                ),
                category="internal",
                entry_type="snippet",
                is_active=True,
                created_by_id=jane_id,
                tags=["internal", "staff-feedback", "jane-voice"],
                usage_count=0,
            ),
        ]

        # ── RESPONSE TEMPLATES ────────────────────────────────────────────
        print("  Creating response template entries ...")

        templates = [
            KnowledgeEntry(
                id=uid(),
                title="Template: Tax Return Status Update",
                content=(
                    "CATEGORY: status_update\n"
                    "USE WHEN: Client asks about the status of their tax return.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "[Personal touch - comment on their life/recent news if known, "
                    "otherwise use 'I hope you are doing well these days!']\n\n"
                    "We've finished the [Year] [Entity Name] [Federal and/or State] "
                    "Returns. A few comments:\n\n"
                    "* [Include any reconciliation notes or adjusting entries]\n"
                    "* [Include any items requiring client action]\n"
                    "* [Timeline], Sandra Rivera (cc'd above) will upload the returns "
                    "to our portal for your review and approval. She'll send you a "
                    "separate email when your return has been uploaded.\n\n"
                    "[If personal return is also relevant:]\n"
                    "Personal return:\n"
                    "* Are you aware of any open items on your personal return?\n\n"
                    "Please reach out with any questions.\n\n"
                    "Thanks and have a great day!\n\n"
                    "Jane"
                ),
                category="status_update",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "status-update", "return-delivery", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Document Request to Client",
                content=(
                    "CATEGORY: document_request\n"
                    "USE WHEN: We need tax documents or information from a client.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "[Personal touch]\n\n"
                    "We are working on [your/Entity Name's] [Year] tax [return/estimates/"
                    "extension]. Could you please send over [the following / answers to "
                    "these questions]:\n\n"
                    "1. [Specific document or question]\n"
                    "2. [Specific document or question]\n"
                    "3. [Specific document or question]\n"
                    "   a. [Sub-item if needed]\n"
                    "   b. [Sub-item if needed]\n\n"
                    "[If staff should be contacted:]\n"
                    "Please cc Sandra (cc'd above) on all emails so we don't miss "
                    "anything on our end.\n\n"
                    "Thanks and have a great day,\n\n"
                    "Jane"
                ),
                category="document_request",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "document-request", "info-gathering", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Document Request to Third Party (Financial Advisor/Broker)",
                content=(
                    "CATEGORY: document_request\n"
                    "USE WHEN: Requesting tax documents from a client's financial advisor, "
                    "broker, or other third party.\n\n"
                    "---\n\n"
                    "Hi [Contact Name],\n\n"
                    "(Please cc Sandra Rivera - cc'd above - on all emails so we don't "
                    "overlook anything.)\n\n"
                    "I hope you are doing well these days.\n\n"
                    "We are working on [Client Name]'s [Year] tax [return/estimates]. "
                    "Could you please send over [Client Name]'s [Year] tax documents "
                    "[for account(s) XXX XXXX] including:\n\n"
                    "* [Year] Form 1099\n"
                    "* [Year] Tax Worksheets\n"
                    "* 12/31/[YY] Annual Statement showing balance in the accounts\n"
                    "* [Any specific reports needed]\n"
                    "* A list of tax payments paid from these accounts, if any.\n"
                    "* If there are any new [Year] accounts, please send these documents "
                    "for the new accounts as well.\n\n"
                    "Thanks and have a great day,\n\n"
                    "Jane"
                ),
                category="document_request",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "document-request", "third-party", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Clarification Questions (Wrap-Up Questions)",
                content=(
                    "CATEGORY: clarification\n"
                    "USE WHEN: We need to verify information or ask clarifying questions "
                    "before finalizing a return.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "As we wrap up your [Year] tax return, a few questions:\n\n"
                    "1. We understand [fact/assumption]. Correct?\n\n"
                    "2. We understand [fact/assumption]. Correct?\n\n"
                    "3. [Specific question about address, entity, filing detail]?\n\n"
                    "4. [Question about preferences or options]:\n"
                    "   * [Option A]\n"
                    "   * [Option B]\n"
                    "   * [Option C]\n\n"
                    "Thanks and have a great day,\n\n"
                    "Jane"
                ),
                category="clarification",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "clarification", "wrap-up", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Extension and Estimated Tax Payments",
                content=(
                    "CATEGORY: status_update\n"
                    "USE WHEN: Communicating extension filing status and estimated tax "
                    "payment schedule to a client.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "To access your [Year] EFTPS estimated payment instructions, please "
                    "visit https://schilcpa.firmportal.com/login and log into our portal.\n\n"
                    "We have completed the [Year] Federal Tax Return Extension for "
                    "[Entity/Trust Name].\n\n"
                    "A few questions:\n\n"
                    "1. We understand these [Year] Estimated Tax Payments were all paid:\n"
                    "   * [Date]: $[Amount]\n"
                    "   * [Date]: $[Amount]\n\n"
                    "   * Can you please confirm these were all paid?\n\n"
                    "2. [Any additional verification questions]\n\n"
                    "3. OPEN:\n"
                    "   * [List any outstanding K-1s or documents not yet received]\n\n"
                    "Here is the status:\n\n"
                    "* [Year] Federal Tax Return Extension:\n"
                    "  * We recommend a payment with your extension of [AMOUNT/NONE].\n"
                    "  * [Note any overpayment to be applied forward]\n"
                    "  * We have e-filed your extension from our office to assure timely "
                    "filing.\n\n"
                    "* [Next Year] Estimated Tax Payments:\n"
                    "  * We have computed the [Year] Estimated Tax Payments using the "
                    "\"Safe Estimate\" (110% of your [Prior Year] taxes).\n"
                    "  * If your income changes materially, please reach out and we can "
                    "compute an \"actual\" estimate.\n"
                    "  * Your recommended Estimated Tax Payments are:\n"
                    "    * [Date]  $[Amount]\n"
                    "    * [Date]  $[Amount]\n\n"
                    "If you have any questions, please let me know.\n\n"
                    "Thanks and have a wonderful day,\n\n"
                    "Jane"
                ),
                category="status_update",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "extension", "estimated-payments", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Tax Guidance Response (Charitable Donations)",
                content=(
                    "CATEGORY: general_inquiry\n"
                    "USE WHEN: Client asks about charitable donations, appreciated stock, "
                    "or property donations.\n\n"
                    "---\n\n"
                    "[Greeting]\n\n"
                    "[Personal touch - comment on their life/plans]\n\n"
                    "Regarding your [Year] donation:\n\n"
                    "1. [Lead with the best strategy]: Appreciated stock is definitely "
                    "the way to go. The deduction will be the Fair Market Value, and the "
                    "gain does not have to be recognized.\n"
                    "2. The donation of appreciated [stock/assets] is limited to [X]% of "
                    "your adjusted gross income. If limited, the excess carries over - so "
                    "it is not lost.\n"
                    "3. You will need:\n"
                    "   a. [Documentation requirements]\n"
                    "   b. [IRS requirements - appraisal, contribution letter, etc.]\n"
                    "   c. [Planning opportunity if applicable]\n\n"
                    "[Offer of further planning help]\n\n"
                    "Have a great day,\n\n"
                    "Jane"
                ),
                category="general_inquiry",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "tax-guidance", "charitable", "donations", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Tax Concept Explanation",
                content=(
                    "CATEGORY: clarification\n"
                    "USE WHEN: Client asks for explanation of a tax concept they don't "
                    "understand (credits vs deductions, etc.).\n\n"
                    "---\n\n"
                    "Hi [Client Name] -\n\n"
                    "[Direct answer to their question in plain language]\n\n"
                    "[Show the math when helpful]:\n"
                    "* [Line item]: [Amount] [explanation]\n"
                    "* [Line item]: [Amount] [explanation]\n"
                    "* So, the net [result] is [Amount]\n\n"
                    "Make sense?\n\n"
                    "Jane"
                ),
                category="clarification",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "tax-explanation", "education", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Return Delivery to Client",
                content=(
                    "CATEGORY: status_update\n"
                    "USE WHEN: Notifying a client that their completed returns are ready "
                    "for review.\n\n"
                    "---\n\n"
                    "Hi [Client Name] -\n\n"
                    "I hope things are going well with you these days!\n\n"
                    "We have completed the following [Year] returns for [Entity Name]:\n\n"
                    "* Federal Return ([Form Type]): [Tax due/No tax due]\n"
                    "* [State] Return: [Tax due/No tax due]\n\n"
                    "[Timeline], Sandra Rivera (cc'd above) will upload the returns to "
                    "our portal for your review and approval. She will send you a "
                    "separate email when it has been uploaded.\n\n"
                    "[If personal return is also in progress:]\n"
                    "How is your personal tax information coming along? Please email "
                    "Sandra when it is ready for pickup and we will schedule a courier.\n\n"
                    "Please let me know if you have any questions.\n\n"
                    "Thanks and have a great day!\n\n"
                    "Jane"
                ),
                category="status_update",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "return-delivery", "completed", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Appointment / Phone Follow-Up",
                content=(
                    "CATEGORY: appointment\n"
                    "USE WHEN: Following up on a missed phone call or scheduling request.\n\n"
                    "---\n\n"
                    "Hi [Client Name] -\n\n"
                    "I tried to call you back by phone but missed you.\n\n"
                    "Is there a specific question you have for me? If so, email may be "
                    "the best option as things are quite busy at the office these days.\n\n"
                    "Alternatively, Sandra Rivera may be able to help you and can be "
                    "reached at our office number (below), Extension 3.\n\n"
                    "Thanks and have a great day!\n\n"
                    "Jane"
                ),
                category="appointment",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "appointment", "phone", "scheduling", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Late K-1 / Extension Estimate",
                content=(
                    "CATEGORY: status_update\n"
                    "USE WHEN: Client has late K-1s and needs extension with estimate.\n\n"
                    "---\n\n"
                    "Good morning,\n\n"
                    "Late K-1s are a common event, so we are on top of it.\n\n"
                    "For your extension estimate:\n\n"
                    "1. We will note the total of outstanding K-1s as $[estimated amount] "
                    "income.\n"
                    "2. If you become aware of any material open items that will change "
                    "this estimate, please let us know.\n\n"
                    "[Staff name] is on top of gathering your information, so please "
                    "continue to communicate with [him/her] on that project. I will be "
                    "very involved in the estimate calculations after most of your "
                    "information is received.\n\n"
                    "Thanks and have a great day,\n\n"
                    "Jane"
                ),
                category="status_update",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "late-k1", "extension", "estimate", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: IRS Notice Response to Client",
                content=(
                    "CATEGORY: urgent\n"
                    "USE WHEN: Client forwards an IRS notice or penalty letter.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "I hope you are doing well these days.\n\n"
                    "We received the attached IRS notice [describe what it is about].\n\n"
                    "1. [Explain what happened - e.g., 'As you know, this return was "
                    "timely filed by regular mail - and then returned.']\n"
                    "2. [Explain why the notice was generated - e.g., 'The IRS computers "
                    "generated this notice because the return was e-filed after the due "
                    "date.']\n"
                    "3. [Reassure - e.g., 'There should not be penalties or interest "
                    "related to this return.']\n\n"
                    "We are preparing an IRS letter to request [penalty abatement/correction]. "
                    "I'll be in touch as soon as it is ready.\n\n"
                    "[If resolution will take time:]\n"
                    "Unfortunately this is likely to take [timeframe] to resolve. The IRS "
                    "is very short-handed these days, so anything that requires a person "
                    "to review is slow.\n\n"
                    "Please continue to forward to me any notices you receive.\n\n"
                    "Thanks and have a great day,\n\n"
                    "Jane"
                ),
                category="urgent",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "irs-notice", "penalty", "urgent", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Potential Client / Referral Response",
                content=(
                    "CATEGORY: general_inquiry\n"
                    "USE WHEN: Someone refers a potential new client to the firm.\n\n"
                    "---\n\n"
                    "Great to hear from you!\n\n"
                    "The best fit for us is when they have complex tax issues (K-1s, "
                    "multiple accounts, business owners, etc.) This is when we can "
                    "bring value to the table.\n\n"
                    "[If timing is a factor:]\n"
                    "For [Year] returns, we would need to file an extension and work "
                    "through details after April 15th. Not sure if that would work for "
                    "them? If so, we'd gladly talk to them!\n\n"
                    "Thanks for thinking of us,\n\n"
                    "Jane"
                ),
                category="general_inquiry",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "new-client", "referral", "intake", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Redirect to Secure Contact / Staff",
                content=(
                    "CATEGORY: general_inquiry\n"
                    "USE WHEN: Directing a third party to send documents to the right "
                    "staff member.\n\n"
                    "---\n\n"
                    "Hi -\n\n"
                    "[Staff Name] works with me and it would be a great help if you can "
                    "direct [Client Name]'s tax documents directly to [Staff Name].\n\n"
                    "Thanks so much and have a great day!\n\n"
                    "Jane"
                ),
                category="general_inquiry",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "redirect", "staff-routing", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Internal Staff Processing Instructions",
                content=(
                    "CATEGORY: document_request (internal)\n"
                    "USE WHEN: Assigning return processing tasks to staff (Sandra, Simmi, etc.)\n\n"
                    "---\n\n"
                    "Hi Sandra,\n\n"
                    "Please:\n\n"
                    "1. Prep [Year] [Entity Name] for PDF delivery on portal.\n"
                    "2. Federal and [State].\n"
                    "3. Attach Federal extension.\n"
                    "4. Prep T ltr and filing instructions.\n"
                    "5. [Load K-1 and basis schedule to relevant 1040 if applicable].\n"
                    "6. Send to [Client Name] for approval.\n\n"
                    "Thanks!\n\n"
                    "Jane"
                ),
                category="document_request",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "internal", "staff-instructions", "processing", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Delaware / State Filing Clarification",
                content=(
                    "CATEGORY: clarification\n"
                    "USE WHEN: Client asks about state-specific filings they may or may "
                    "not handle themselves.\n\n"
                    "---\n\n"
                    "Hi [Client Name],\n\n"
                    "[State] filings are very straightforward - similar to property tax "
                    "assessments.\n\n"
                    "Typically, registered agents file these on your behalf. If you need "
                    "anything from us, please let us know.\n\n"
                    "Sandra (cc'd above) will send you a separate email (likely "
                    "[timeframe]) when the returns have been uploaded to our portal for "
                    "your review and approval.\n\n"
                    "Thanks,\n\n"
                    "Jane"
                ),
                category="clarification",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "state-filing", "delaware", "clarification", "jane-voice"],
                usage_count=0,
            ),
            KnowledgeEntry(
                id=uid(),
                title="Template: Tax Information Drop-Off Confirmation",
                content=(
                    "CATEGORY: general_inquiry\n"
                    "USE WHEN: Client confirms they will drop off or send tax documents.\n\n"
                    "---\n\n"
                    "Hi [Client Name] -\n\n"
                    "We'll look forward to receiving your information [day/date]. The "
                    "office will be open from [hours].\n\n"
                    "Please cc Sandra (cc'd above) on all emails so we don't miss "
                    "anything on our end.\n\n"
                    "Thanks and have a great day!\n\n"
                    "Jane"
                ),
                category="general_inquiry",
                entry_type="response_template",
                is_active=True,
                created_by_id=jane_id,
                tags=["template", "drop-off", "document-receipt", "jane-voice"],
                usage_count=0,
            ),
        ]

        # ── Sentinel entry ────────────────────────────────────────────────
        sentinel_entry = KnowledgeEntry(
            id=uid(),
            title=SENTINEL_TITLE,
            content="Internal marker for Jane email pattern seed. Do not delete.",
            category="internal",
            entry_type="snippet",
            is_active=False,
            created_by_id=jane_id,
        )

        # ── Insert all entries ────────────────────────────────────────────
        all_entries = policies + snippets + templates + [sentinel_entry]

        for entry in all_entries:
            db.add(entry)

        db.commit()
        print(f"\n  Done! Created {len(all_entries) - 1} knowledge base entries:")
        print(f"    - {len(policies)} policies")
        print(f"    - {len(snippets)} snippets")
        print(f"    - {len(templates)} response templates")
        print(f"    + 1 sentinel entry")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
