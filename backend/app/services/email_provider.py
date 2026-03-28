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

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


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
        message_id: str | None = None,
    ) -> str:
        """Send an outbound email. Returns the Message-ID of the sent message."""
        ...

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
            "internetMessageHeaders"
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
            results.append(RawEmail(
                message_id=msg.get("internetMessageId", msg["id"]),
                subject=msg.get("subject", "(no subject)"),
                sender=msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                recipient=mailbox,
                body_text=msg.get("body", {}).get("content") if msg.get("body", {}).get("contentType") == "text" else None,
                body_html=msg.get("body", {}).get("content") if msg.get("body", {}).get("contentType") == "html" else None,
                received_at=datetime.fromisoformat(
                    msg["receivedDateTime"].replace("Z", "+00:00")
                ),
                raw_headers=raw_headers,
                provider_thread_id=msg.get("conversationId"),
                in_reply_to=raw_headers.get("In-Reply-To"),
                references=raw_headers.get("References"),
            ))
        return results

    def mark_as_read(self, message_id: str) -> None:
        # message_id here is the Graph message id (not internetMessageId)
        # In practice we need to track the Graph-native id separately.
        # For now we use the internetMessageId to look up and patch.
        mailbox = self._settings.msgraph_mailbox
        # Search for message by internetMessageId
        url = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages"
            f"?$filter=internetMessageId eq '{message_id}'"
            "&$select=id"
        )
        try:
            resp = self._client.get(url, headers=self._headers())
            resp.raise_for_status()
            msgs = resp.json().get("value", [])
            if msgs:
                graph_id = msgs[0]["id"]
                patch_url = f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}"
                self._client.patch(patch_url, headers=self._headers(), json={"isRead": True})
        except Exception as exc:
            logger.warning("MSGraph mark_as_read failed for %s: %s", message_id, exc)

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to_message_id: str | None = None,
        message_id: str | None = None,
    ) -> str:
        import uuid as _uuid
        mailbox = self._settings.msgraph_mailbox
        url = f"{self.GRAPH_BASE}/users/{mailbox}/sendMail"
        content_type = "html" if body_html else "text"
        content = body_html or body_text

        # Generate a Message-ID we control so we can track thread continuity
        if not message_id:
            domain = mailbox.split("@")[-1] if "@" in mailbox else "localhost"
            message_id = f"<{_uuid.uuid4()}@{domain}>"

        payload: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {"contentType": content_type, "content": content},
                "toRecipients": [{"emailAddress": {"address": to}}],
                "internetMessageHeaders": [
                    {"name": "Message-ID", "value": message_id},
                ],
            },
            "saveToSentItems": True,
        }
        if reply_to_message_id:
            payload["message"]["internetMessageHeaders"].extend([
                {"name": "In-Reply-To", "value": reply_to_message_id},
                {"name": "References", "value": reply_to_message_id},
            ])

        try:
            resp = self._client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            logger.info("MSGraph: sent email to %s subject=%r", to, subject)
            return message_id
        except httpx.HTTPStatusError as exc:
            logger.error("MSGraph send_email failed: %s", exc)
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

        # Extract body
        body_text: str | None = None
        body_html: str | None = None
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain" and body_text is None:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                elif ct == "text/html" and body_html is None:
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
            msg["References"] = reply_to_message_id

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
