-- Augment the existing demo seed with rows that exercise the FEAT/jane-asks-batch-1
-- features: PII detection, save-to-folder, T1 auto-handled.
--
-- Idempotent: each INSERT checks for an existing row by a stable identifier.
-- Run via:
--   psql -h localhost -p 5433 -U jane_user -d jane_automation -f seed_demo_augment.sql

BEGIN;

-- ── 0. Restore the short W-2 thread body (was bloated for scroll testing) ────

UPDATE email_messages
SET body_text = E'Hi,\n\nI uploaded all my documents to the portal - W-2 from my main job at TechCorp, mortgage interest statements, a few 1099s, and donation receipts.\n\nThe one I cannot find is the W-2 from my part-time gig at Apex Retail. They told me they would mail it but I never set up online access, so I cannot pull it from their portal.\n\nWhat are my options? Do we file without it, or wait it out?\n\nThanks,\nDiane'
WHERE thread_id = 'd092d6f5-0f29-4229-9589-7fb31518dc33'
  AND direction = 'inbound';

-- ── 1. PII demo thread — client emails an SSN in plain text ─────────────────
-- The categorizer's PII detector runs at intake; for demo data we hand-craft
-- the resulting thread + escalation directly (intake never runs on seeds).

DO $$
DECLARE
    pii_thread_id  uuid := 'a1b2c3d4-1111-1111-1111-111111111111';
    pii_msg_id     uuid := 'a1b2c3d4-1111-1111-1111-222222222222';
    admin_user_id  uuid;
BEGIN
    SELECT id INTO admin_user_id FROM users WHERE role = 'admin' LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM email_threads WHERE id = pii_thread_id) THEN
        INSERT INTO email_threads (
            id, subject, client_email, client_name,
            status, category, category_confidence, ai_summary, suggested_reply_tone,
            tier, tier_set_at, tier_set_by, categorization_source,
            created_at, updated_at
        )
        VALUES (
            pii_thread_id,
            'Question about deduction — sending you my info',
            'mark.perreault@gmail.com',
            'Mark Perreault',
            'escalated',
            'clarification',
            0.82,
            'Client emailed asking about a deduction and pasted his SSN directly into the message body. PII detector flagged for staff review — do not auto-respond.',
            'professional',
            't3_escalate',
            now(),
            'system',
            'claude',
            now() - interval '2 hours',
            now() - interval '2 hours'
        );

        INSERT INTO email_messages (
            id, thread_id, message_id_header, sender, recipient,
            body_text, received_at, direction, is_processed
        )
        VALUES (
            pii_msg_id,
            pii_thread_id,
            '<demo-pii-001@example.com>',
            'mark.perreault@gmail.com',
            'jane@schilcpa.com',
            E'Hi Jane,\n\nQuick question on last year''s return - can I still amend to claim the home office deduction?\n\nMy SSN is 123-45-6789 in case you need to look it up.\n\nThanks,\nMark',
            now() - interval '2 hours',
            'inbound',
            true
        );

        INSERT INTO escalations (
            id, thread_id, severity, status, reason,
            assigned_to_id, created_at
        )
        VALUES (
            gen_random_uuid(),
            pii_thread_id,
            'medium',
            'pending',
            'Sensitive client data detected (Social Security Number) — please direct the client to the secure portal.',
            admin_user_id,
            now() - interval '2 hours'
        );
    END IF;
END $$;

-- ── 2. Saved-thread demo — Jane saved an important client email ─────────────
-- Reuse the existing "Status update on my 2025 tax return?" thread (sent &
-- closed) as a realistic example of an email worth keeping in a client folder.

DO $$
DECLARE
    saved_thread_id uuid := '6d7d550c-6913-4b7f-9df7-806afd4f6c17';
    admin_user_id   uuid;
BEGIN
    SELECT id INTO admin_user_id FROM users WHERE role = 'admin' LIMIT 1;

    UPDATE email_threads
    SET is_saved = true,
        saved_folder = 'Harmon — 2025 Return',
        saved_note = 'Final confirmation thread — keep with the return file. Client confirmed the withholding adjustment we made on Schedule 1.',
        saved_at = now() - interval '1 day',
        saved_by_id = admin_user_id
    WHERE id = saved_thread_id;
END $$;

-- ── 3. T1 auto-handled demo — short status-update reply that AI handled solo ─

DO $$
DECLARE
    t1_thread_id uuid := 'b2c3d4e5-2222-2222-2222-111111111111';
    t1_in_msg_id uuid := 'b2c3d4e5-2222-2222-2222-222222222222';
    t1_out_msg_id uuid := 'b2c3d4e5-2222-2222-2222-333333333333';
    t1_draft_id  uuid := 'b2c3d4e5-2222-2222-2222-444444444444';
    admin_user_id uuid;
BEGIN
    SELECT id INTO admin_user_id FROM users WHERE role = 'admin' LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM email_threads WHERE id = t1_thread_id) THEN
        INSERT INTO email_threads (
            id, subject, client_email, client_name,
            status, category, category_confidence, ai_summary, suggested_reply_tone,
            tier, tier_set_at, tier_set_by, categorization_source,
            auto_sent_at, created_at, updated_at
        )
        VALUES (
            t1_thread_id,
            'Did you receive my Q3 estimate payment confirmation?',
            'paula.greenfield@gmail.com',
            'Paula Greenfield',
            'sent',
            'status_update',
            0.96,
            'Routine confirmation request — client wanted to verify Q3 estimate payment was received. AI replied with the standard "yes, received and posted" response autonomously.',
            'professional',
            't1_auto',
            now() - interval '5 hours',
            'system',
            'claude',
            now() - interval '4 hours',
            now() - interval '5 hours',
            now() - interval '4 hours'
        );

        INSERT INTO email_messages (
            id, thread_id, message_id_header, sender, recipient,
            body_text, received_at, direction, is_processed
        )
        VALUES (
            t1_in_msg_id,
            t1_thread_id,
            '<demo-t1-001-in@example.com>',
            'paula.greenfield@gmail.com',
            'jane@schilcpa.com',
            E'Hi Jane,\n\nJust checking — did my Q3 estimate payment go through? I see the debit on my bank statement but wanted to confirm you have it on file.\n\nThanks,\nPaula',
            now() - interval '5 hours',
            'inbound',
            true
        ),
        (
            t1_out_msg_id,
            t1_thread_id,
            '<demo-t1-001-out@example.com>',
            'Schiller CPA <jane@schilcpa.com>',
            'paula.greenfield@gmail.com',
            E'Hi Paula,\n\nYes — your Q3 estimate payment posted on schedule and is on file. You''re all set through Q3, with Q4 due in mid-January.\n\nLet me know if you need anything else.\n\nThanks,\nSchiller CPA',
            now() - interval '4 hours',
            'outbound',
            true
        );

        INSERT INTO draft_responses (
            id, thread_id, body_text, original_body_text, status, version,
            ai_model, ai_prompt_tokens, ai_completion_tokens,
            reviewed_by_id, reviewed_at, created_at
        )
        VALUES (
            t1_draft_id,
            t1_thread_id,
            E'Hi Paula,\n\nYes — your Q3 estimate payment posted on schedule and is on file. You''re all set through Q3, with Q4 due in mid-January.\n\nLet me know if you need anything else.\n\nThanks,\nSchiller CPA',
            E'Hi Paula,\n\nYes — your Q3 estimate payment posted on schedule and is on file. You''re all set through Q3, with Q4 due in mid-January.\n\nLet me know if you need anything else.\n\nThanks,\nSchiller CPA',
            'sent',
            1,
            'claude-sonnet-4-5',
            420,
            85,
            admin_user_id,
            now() - interval '4 hours',
            now() - interval '5 hours'
        );
    END IF;
END $$;

-- ── 4. Backfill tier on already-escalated threads ───────────────────────────
-- Pre-seed escalations were created before tier was wired up, so they show
-- t2_review even though their status is escalated. Bring them in line so the
-- Escalated tab and the auto-handled chip both render correctly without
-- relying purely on the column-drift tolerant filter.

UPDATE email_threads
SET tier = 't3_escalate',
    tier_set_at = COALESCE(tier_set_at, updated_at),
    tier_set_by = COALESCE(tier_set_by, 'backfill')
WHERE status = 'escalated' AND tier <> 't3_escalate';

COMMIT;

\echo 'Demo augment applied.'
