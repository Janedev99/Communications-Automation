"""
Email provider abstraction.

Defines the EmailProvider ABC and two concrete implementations:
  - MSGraphProvider  — uses Microsoft Graph API via httpx
  - IMAPProvider     — uses stdlib imaplib + smtplib

Factory function `get_email_provider()` returns the configured provider.
"""
from __future__ import annotations

import email as email_lib
import email.header
import imaplib
import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import re

import html2text
import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


# Matches a run of 3 or more consecutive newlines (allowing whitespace-only
# lines in between, which is what Outlook's <p>&nbsp;</p> placeholder
# paragraphs produce after html2text conversion).
_EXCESSIVE_BLANK_LINES = re.compile(r'(?:[ \t\xa0]*\n){3,}')


def _html_to_text(html_content: str) -> str:
    """
    Convert an HTML email body to clean plain text suitable for AI input and
    plain-text UI rendering. Preserves links as `[text](url)` so nothing useful
    is silently dropped. Returns an empty string for empty / None-ish input.

    Excessive blank lines (4+ newlines in a row, often produced by Outlook's
    `<p>&nbsp;</p>` placeholder paragraphs stacked between real content) are
    collapsed to a single paragraph break — otherwise real client emails
    render with multi-line gaps that look broken in the dashboard.
    """
    if not html_content:
        return ""
    converter = html2text.HTML2Text()
    converter.body_width = 0          # don't wrap lines
    converter.ignore_links = False    # preserve URLs as [text](url)
    converter.ignore_images = True    # image markdown is noise for the categorizer
    converter.unicode_snob = True     # keep non-ASCII characters as-is
    converter.escape_snob = True      # don't insert backslash escapes for punctuation
    text = converter.handle(html_content).strip()
    # Collapse runs of 3+ blank lines (each potentially carrying trailing
    # whitespace / NBSP) down to one paragraph break.
    text = _EXCESSIVE_BLANK_LINES.sub('\n\n', text)
    return text


@dataclass
class AttachmentMeta:
    """Lightweight metadata about an email attachment (no binary content)."""
    filename: str
    size: int | None = None              # bytes; None if the provider didn't report it
    content_type: str | None = None      # MIME type, e.g. "application/pdf"
    # Provider-native attachment id. For MS Graph, this is the value at the
    # /messages/{id}/attachments/{aid} URL — needed to fetch the binary on
    # demand. May be None for legacy rows polled before this field existed,
    # or for the IMAP provider (which doesn't have a stable per-attachment
    # remote id). Download endpoint falls back to "look up by index" in that case.
    attachment_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size": self.size,
            "content_type": self.content_type,
            "attachment_id": self.attachment_id,
        }


@dataclass
class RawEmail:
    """
    Provider-agnostic representation of a fetched email.
    Enough data to create an EmailMessage + find/create an EmailThread.
    """
    message_id: str          # Value of the Message-ID header (globally unique)
    subject: str
    sender: str              # "Name <email@domain>" or just "email@domain"
    recipient: str
    body_text: str | None
    body_html: str | None
    received_at: datetime
    raw_headers: dict[str, str] = field(default_factory=dict)
    # Optional provider-native thread identifier
    provider_thread_id: str | None = None
    # References header for thread grouping
    references: str | None = None
    in_reply_to: str | None = None
    # Attachment metadata (filenames / sizes, no binary payloads)
    attachments: list[AttachmentMeta] = field(default_factory=list)


class EmailProvider(ABC):
    """Abstract base class for all email provider implementations."""

    @abstractmethod
    def connect(self) -> None:
        """Establish (or refresh) the connection / auth token."""
        ...

    @abstractmethod
    def fetch_new_emails(self) -> list[RawEmail]:
        """
        Fetch all unread/new emails from the inbox.

        Implementations must mark fetched emails as read (or otherwise ensure
        they won't be returned again on the next poll) ONLY after they have
        been successfully stored in the database — the caller (email_intake)
        handles that.
        """
        ...

    @abstractmethod
    def mark_as_read(self, message_id: str) -> None:
        """Mark a message as read in the remote mailbox."""
        ...

    @abstractmethod
    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """
        Send an outbound email. Returns the Message-ID of the sent message.

        reply_to_message_id: the Message-ID of the message being replied to
        references_header:   full References header value (parent References + parent ID)
                             preserving the full thread ancestry for email clients (T2.1)
        """
        ...

    def fetch_attachment(
        self,
        *,
        internet_message_id: str,
        attachment_id: str | None = None,
        attachment_index: int | None = None,
    ) -> tuple[bytes, str, str | None]:
        """
        Fetch a specific attachment's binary content for an already-polled
        message. Returns (content_bytes, filename, content_type).

        Caller provides either:
          - attachment_id (preferred — direct lookup, single API call), or
          - attachment_index (legacy fallback for rows polled before the id
            was persisted — provider lists attachments then picks by index)

        Default implementation raises — providers that can't support
        on-demand attachment fetch should leave this as the abstract raise so
        the API surface degrades clearly rather than silently failing.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support on-demand attachment fetch"
        )

    def move_message(
        self,
        *,
        internet_message_id: str,
        destination: str,
    ) -> None:
        """
        Move an already-polled message to a different folder in the remote
        mailbox.

        ``destination`` is a provider-agnostic logical name — implementations
        translate it. The supported values are:

          - ``"deleted_items"`` — Outlook Deleted Items / IMAP Trash
          - ``"junk_email"``   — Outlook Junk Email / IMAP Spam

        Used by the trash-management endpoints in ``api/emails.py`` so
        when staff delete or mark-as-spam a thread, the change propagates
        to Outlook (Jane's authoritative inbox). The propagation guarantee
        is what Gus called out in the 2026-05-21 meeting: deleting in our
        UI must also remove the email from Outlook.

        Default implementation raises — providers must opt in by overriding.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support move_message"
        )

    def disconnect(self) -> None:
        """Optional cleanup. Called on shutdown."""
        pass


# ── MS Graph Provider ─────────────────────────────────────────────────────────

class MSGraphProvider(EmailProvider):
    """
    Microsoft Graph API email provider.

    Uses the OAuth2 client-credentials flow (daemon/service app) to access
    a shared mailbox on behalf of the organisation.

    Auth token is cached in memory and refreshed when expired.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client = httpx.Client(timeout=30)

    def connect(self) -> None:
        """Fetch a new OAuth2 access token using client credentials."""
        url = self.TOKEN_URL_TEMPLATE.format(tenant=self._settings.msgraph_tenant_id)
        resp = self._client.post(url, data={
            "grant_type": "client_credentials",
            "client_id": self._settings.msgraph_client_id,
            "client_secret": self._settings.msgraph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        })
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        logger.info("MSGraphProvider: access token acquired, expires in %ds", expires_in)

    def _ensure_token(self) -> None:
        now = datetime.now(timezone.utc)
        if self._access_token is None or (
            self._token_expires_at and now >= self._token_expires_at
        ):
            self.connect()

    def _headers(self) -> dict[str, str]:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

    def fetch_new_emails(self) -> list[RawEmail]:
        mailbox = self._settings.msgraph_mailbox
        url = (
            f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders/Inbox/messages"
            "?$filter=isRead eq false"
            "&$select=id,subject,from,toRecipients,body,bodyPreview,"
            "receivedDateTime,conversationId,internetMessageId,"
            "internetMessageHeaders,hasAttachments,attachments"
            "&$expand=attachments($select=id,name,size,contentType,isInline)"
            "&$top=50"
            "&$orderby=receivedDateTime asc"
        )
        try:
            resp = self._client.get(url, headers=self._headers())
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("MSGraph fetch failed: %s", exc)
            return []

        messages = resp.json().get("value", [])
        results: list[RawEmail] = []
        for msg in messages:
            raw_headers = {
                h["name"]: h["value"]
                for h in msg.get("internetMessageHeaders") or []
            }

            # Extract attachment metadata (skip inline/embedded images)
            attachments: list[AttachmentMeta] = []
            if msg.get("hasAttachments"):
                for att in msg.get("attachments") or []:
                    if att.get("isInline"):
                        continue  # Skip inline images embedded in HTML body
                    attachments.append(AttachmentMeta(
                        filename=att.get("name") or "attachment",
                        size=att.get("size"),
                        content_type=att.get("contentType"),
                        attachment_id=att.get("id"),
                    ))

            # Body extraction — MS Graph returns a single `body` object with
            # either contentType="html" (default) or "text". Older code mapped
            # the two fields as mutually exclusive, leaving body_text=None on
            # every HTML email — which blanked the dashboard and forced the AI
            # categorizer to read raw HTML (with <style>, <head>, inline CSS).
            # Now: store HTML as-is in body_html AND derive a clean plain-text
            # version into body_text so both consumers get what they expect.
            body_obj = msg.get("body") or {}
            content = body_obj.get("content") or ""
            content_type = (body_obj.get("contentType") or "").lower()
            if content_type == "html":
                body_html: str | None = content or None
                body_text: str | None = _html_to_text(content) or None
            elif content_type == "text":
                body_html = None
                body_text = content or None
            else:
                body_html = None
                body_text = None

            # Coerce nullable Graph fields. `msg.get("subject", default)` doesn't
            # protect against `"subject": null` — that returns None, which then
            # crashes downstream calls like `subject.strip()` (seen in real
            # production data: iCloud-sent emails routinely omit the subject).
            # Same for `from`: occasional system messages have a null `from`.
            sender_obj = (msg.get("from") or {}).get("emailAddress") or {}
            results.append(RawEmail(
                message_id=msg.get("internetMessageId") or msg["id"],
                subject=msg.get("subject") or "(no subject)",
                sender=sender_obj.get("address") or "",
                recipient=mailbox,
                body_text=body_text,
                body_html=body_html,
                received_at=datetime.fromisoformat(
                    msg["receivedDateTime"].replace("Z", "+00:00")
                ),
                raw_headers=raw_headers,
                provider_thread_id=msg.get("conversationId"),
                in_reply_to=raw_headers.get("In-Reply-To"),
                references=raw_headers.get("References"),
                attachments=attachments,
            ))
        return results

    def _resolve_graph_message_id(self, internet_message_id: str) -> str | None:
        """
        Translate a stored internetMessageId (e.g. "<abc@example.com>") into the
        Graph-native message id needed for /messages/{id}/... endpoints.
        Returns None if the message isn't found in the mailbox (deleted, moved,
        etc.) so callers can surface a clean 404.
        """
        mailbox = self._settings.msgraph_mailbox
        # Escape single quotes — OData filter injection vector
        safe_id = internet_message_id.replace("'", "''")
        url = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages"
            f"?$filter=internetMessageId eq '{safe_id}'"
            "&$select=id"
        )
        resp = self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        msgs = resp.json().get("value", [])
        return msgs[0]["id"] if msgs else None

    def mark_as_read(self, message_id: str) -> None:
        # message_id here is the internetMessageId we stored at poll time.
        try:
            graph_id = self._resolve_graph_message_id(message_id)
            if graph_id is None:
                return
            mailbox = self._settings.msgraph_mailbox
            patch_url = f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}"
            self._client.patch(patch_url, headers=self._headers(), json={"isRead": True})
        except Exception as exc:
            logger.warning("MSGraph mark_as_read failed for %s: %s", message_id, exc)

    def fetch_attachment(
        self,
        *,
        internet_message_id: str,
        attachment_id: str | None = None,
        attachment_index: int | None = None,
    ) -> tuple[bytes, str, str | None]:
        """
        Fetch a single attachment's binary content from MS Graph.

        Prefers `attachment_id` (stored at poll time on new rows) for a direct
        lookup. Falls back to `attachment_index` for legacy rows by listing
        the message's attachments and picking the Nth non-inline one.

        Raises:
          - LookupError if the message itself can't be found in the mailbox
            (deleted / moved by the user)
          - IndexError if attachment_index is out of range for the message
          - ValueError if neither identifier is provided
        """
        if attachment_id is None and attachment_index is None:
            raise ValueError("Provide either attachment_id or attachment_index")

        import base64
        mailbox = self._settings.msgraph_mailbox
        graph_id = self._resolve_graph_message_id(internet_message_id)
        if graph_id is None:
            raise LookupError(
                f"Message {internet_message_id!r} not found in mailbox — "
                "may have been deleted or moved"
            )

        # Resolve attachment_id from index if needed (legacy path).
        if attachment_id is None:
            list_url = (
                f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}/attachments"
                "?$select=id,name,contentType,isInline"
            )
            list_resp = self._client.get(list_url, headers=self._headers())
            list_resp.raise_for_status()
            atts = [
                a for a in (list_resp.json().get("value") or [])
                if not a.get("isInline")  # match the poll-time filter exactly
            ]
            if not 0 <= attachment_index < len(atts):
                raise IndexError(
                    f"Attachment index {attachment_index} out of range "
                    f"(message has {len(atts)} non-inline attachments)"
                )
            attachment_id = atts[attachment_index]["id"]

        # Fetch the full attachment object — `contentBytes` is a base64 string
        # for the standard fileAttachment resource type. Use $value for a raw
        # binary response if the type is itemAttachment (calendar invites etc.)
        # but that's rare; defaulting to /$value works for fileAttachment too.
        get_url = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}"
            f"/attachments/{attachment_id}"
        )
        resp = self._client.get(get_url, headers=self._headers())
        resp.raise_for_status()
        att = resp.json()
        content_b64 = att.get("contentBytes")
        if not content_b64:
            raise LookupError(
                f"Attachment {attachment_id!r} has no contentBytes "
                "(may be an itemAttachment / inaccessible reference)"
            )
        return (
            base64.b64decode(content_b64),
            att.get("name") or "attachment",
            att.get("contentType"),
        )

    # Logical → Graph well-known folder ID mapping. Graph accepts these
    # string aliases anywhere a folder ID is required, so we don't have to
    # resolve them via /mailFolders lookups. Other destinations (drafts,
    # sentitems, archive) aren't exposed because the trash UI only needs
    # these two — keep the surface tight.
    _DESTINATION_FOLDER_IDS = {
        "deleted_items": "deleteditems",
        "junk_email": "junkemail",
    }

    def move_message(
        self,
        *,
        internet_message_id: str,
        destination: str,
    ) -> None:
        """
        Move a single message into one of the trash-management folders.

        Resolves the stored internetMessageId to the Graph-native id first
        (using the same helper that mark_as_read / fetch_attachment use),
        then POSTs to /messages/{id}/move with the well-known folder id.

        Silently returns if the message can't be found in the mailbox — it
        may have already been moved or deleted out-of-band. The thread-level
        endpoint that calls us iterates many messages and one missing
        message shouldn't block the rest of the move.
        """
        folder_id = self._DESTINATION_FOLDER_IDS.get(destination)
        if folder_id is None:
            raise ValueError(
                f"Unknown destination {destination!r}; expected one of "
                f"{sorted(self._DESTINATION_FOLDER_IDS)}"
            )
        graph_id = self._resolve_graph_message_id(internet_message_id)
        if graph_id is None:
            logger.info(
                "MSGraph move_message: message %s not found in mailbox — "
                "treating as already-moved",
                internet_message_id,
            )
            return
        mailbox = self._settings.msgraph_mailbox
        url = f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}/move"
        try:
            resp = self._client.post(
                url,
                headers=self._headers(),
                json={"destinationId": folder_id},
            )
            resp.raise_for_status()
            logger.info(
                "MSGraph: moved message %s to %s",
                internet_message_id, destination,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MSGraph move_message failed for %s → %s: %s | response_body=%s",
                internet_message_id, destination, exc, exc.response.text[:500],
            )
            raise

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """
        Send via Graph's /sendMail action.

        Note on threading headers: Microsoft Graph rejects any
        ``internetMessageHeaders`` entry whose name does not start with ``x-``
        / ``X-``. ``Message-ID``, ``In-Reply-To``, and ``References`` are
        reserved transport headers that Exchange generates itself — attempting
        to set them via Graph returns HTTP 400 ``ErrorInvalidInternetMessageHeader``
        ("The internet message header name should start with 'x-' or 'X-'").
        This is *the* reason every /sendMail call after the M365 cutover
        failed: the IMAP/SMTP path could author these headers, the Graph path
        cannot. The ``reply_to_message_id`` / ``references_header`` /
        ``message_id`` arguments are kept in the signature for interface parity
        with ``IMAPProvider`` but are not transmitted on the Graph path. Thread
        continuity for replies routes through Exchange's own ``conversationId``
        rather than RFC5322 headers; a follow-up that switches replies to
        ``POST /messages/{parent}/createReply`` will restore client-side
        threading in Outlook/Gmail. See FIX/msgraph-invalid-headers.
        """
        import uuid as _uuid
        mailbox = self._settings.msgraph_mailbox
        url = f"{self.GRAPH_BASE}/users/{mailbox}/sendMail"
        content_type = "html" if body_html else "text"
        content = body_html or body_text

        # Generated id is returned to the caller for DB tracking. Graph will
        # assign its own Message-ID at the Exchange transport layer and we
        # cannot influence it from /sendMail — the returned value is a local
        # correlation id only, not the on-wire Message-ID.
        if not message_id:
            domain = mailbox.split("@")[-1] if "@" in mailbox else "localhost"
            message_id = f"<{_uuid.uuid4()}@{domain}>"

        payload: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {"contentType": content_type, "content": content},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }

        try:
            resp = self._client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            logger.info("MSGraph: sent email to %s subject=%r", to, subject)
            return message_id
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MSGraph send_email failed: %s | response_body=%s",
                exc, exc.response.text[:500],
            )
            raise

    def disconnect(self) -> None:
        self._client.close()


# ── IMAP / SMTP Provider ───────────────────────────────────────────────────────

def _decode_header_value(raw: str) -> str:
    """Decode a potentially RFC 2047-encoded email header value."""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


class IMAPProvider(EmailProvider):
    """
    IMAP + SMTP email provider using Python's stdlib.

    Connects to an IMAP server to read mail and SMTP server to send.
    Reconnects automatically if the connection drops.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._imap: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        """Open (or reopen) the IMAP connection and log in."""
        if self._imap is not None:
            try:
                self._imap.noop()
                return  # Already connected and alive
            except Exception:
                pass  # Connection dropped — reconnect below

        s = self._settings
        if s.imap_use_ssl:
            self._imap = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
        else:
            self._imap = imaplib.IMAP4(s.imap_host, s.imap_port)

        self._imap.login(s.imap_username, s.imap_password)
        logger.info("IMAPProvider: connected to %s:%d", s.imap_host, s.imap_port)

    def _get_imap(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        self.connect()
        assert self._imap is not None
        return self._imap

    def fetch_new_emails(self) -> list[RawEmail]:
        imap = self._get_imap()
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        message_numbers = data[0].split() if data[0] else []
        results: list[RawEmail] = []

        for num in message_numbers:
            try:
                _, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                if not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]  # type: ignore[index]
                if not isinstance(raw_bytes, bytes):
                    continue

                msg = email_lib.message_from_bytes(raw_bytes)
                raw = self._parse_message(msg)
                if raw:
                    results.append(raw)
            except Exception as exc:
                logger.warning("IMAPProvider: failed to parse message %s: %s", num, exc)

        return results

    def _parse_message(self, msg: email_lib.message.Message) -> RawEmail | None:
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            return None  # Can't deduplicate without Message-ID

        subject = _decode_header_value(msg.get("Subject", "(no subject)"))
        sender = _decode_header_value(msg.get("From", ""))
        recipient = _decode_header_value(msg.get("To", self._settings.imap_username))

        # Parse received date
        date_str = msg.get("Date", "")
        try:
            from email.utils import parsedate_to_datetime
            received_at = parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)

        # Extract body and attachment metadata
        body_text: str | None = None
        body_html: str | None = None
        attachments: list[AttachmentMeta] = []

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disposition = part.get_content_disposition() or ""

                if disposition == "attachment":
                    # Extract attachment metadata only — no binary content stored
                    raw_filename = part.get_filename() or "attachment"
                    filename = _decode_header_value(raw_filename)
                    payload = part.get_payload(decode=True)
                    size = len(payload) if isinstance(payload, bytes) else None
                    attachments.append(AttachmentMeta(
                        filename=filename,
                        size=size,
                        content_type=ct,
                    ))
                elif ct == "text/plain" and body_text is None and disposition != "attachment":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                elif ct == "text/html" and body_html is None and disposition != "attachment":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                ct = msg.get_content_type()
                text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
                if ct == "text/html":
                    body_html = text
                else:
                    body_text = text

        raw_headers = dict(msg.items())

        return RawEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            recipient=recipient,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            raw_headers=raw_headers,
            in_reply_to=msg.get("In-Reply-To"),
            references=msg.get("References"),
            attachments=attachments,
        )

    def mark_as_read(self, message_id: str) -> None:
        """Mark a message as read by its Message-ID header."""
        try:
            imap = self._get_imap()
            imap.select("INBOX")
            # Search by header
            _, data = imap.search(None, f'HEADER Message-ID "{message_id}"')
            nums = data[0].split() if data[0] else []
            for num in nums:
                imap.store(num, "+FLAGS", "\\Seen")
        except Exception as exc:
            logger.warning("IMAPProvider mark_as_read failed for %s: %s", message_id, exc)

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        import uuid as _uuid
        s = self._settings

        # Generate a Message-ID we control for thread continuity
        if not message_id:
            domain = s.smtp_username.split("@")[-1] if "@" in s.smtp_username else "localhost"
            message_id = f"<{_uuid.uuid4()}@{domain}>"

        msg = MIMEMultipart("alternative") if body_html else MIMEText(body_text, "plain")
        msg["From"] = s.smtp_username
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
        # T2.1: Set full References chain for proper email thread display in clients
        ref_value = references_header or reply_to_message_id
        if ref_value:
            msg["References"] = ref_value

        if body_html:
            assert isinstance(msg, MIMEMultipart)
            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

        context = ssl.create_default_context()
        try:
            if s.smtp_use_tls:
                with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.login(s.smtp_username, s.smtp_password)
                    server.sendmail(s.smtp_username, to, msg.as_string())
            else:
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context) as server:
                    server.login(s.smtp_username, s.smtp_password)
                    server.sendmail(s.smtp_username, to, msg.as_string())
            logger.info("IMAPProvider: sent email to %s subject=%r", to, subject)
            return message_id
        except smtplib.SMTPException as exc:
            logger.error("IMAPProvider send_email failed: %s", exc)
            raise

    def disconnect(self) -> None:
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None


# ── Factory ────────────────────────────────────────────────────────────────────

_provider: EmailProvider | None = None


def get_email_provider(settings: Settings | None = None) -> EmailProvider:
    """
    Return a cached email provider instance (singleton).

    Reads EMAIL_PROVIDER from settings; defaults to IMAP.
    """
    global _provider
    if _provider is not None:
        return _provider

    if settings is None:
        settings = get_settings()

    provider_name = settings.email_provider.lower()
    if provider_name == "msgraph":
        _provider = MSGraphProvider(settings)
    elif provider_name == "imap":
        _provider = IMAPProvider(settings)
    else:
        raise ValueError(
            f"Unknown EMAIL_PROVIDER={provider_name!r}. Must be 'msgraph' or 'imap'."
        )
    return _provider
