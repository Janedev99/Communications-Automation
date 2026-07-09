"""
Email provider abstraction.

Defines the EmailProvider ABC and two concrete implementations:
  - MSGraphProvider  — uses Microsoft Graph API via httpx
  - IMAPProvider     — uses stdlib imaplib + smtplib

Factory function `get_email_provider()` returns the configured provider.
"""
from __future__ import annotations

import base64
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
from typing import Any, Iterator

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
    # Full original To/CC address lists (FEAT/reply-recipients) — feeds
    # Reply All. Empty list (not None) when the provider reported zero
    # recipients in that slot; email_intake.py stores an empty list as NULL.
    to_recipients: list[str] = field(default_factory=list)
    cc_recipients: list[str] = field(default_factory=list)
    raw_headers: dict[str, str] = field(default_factory=dict)
    # Optional provider-native thread identifier
    provider_thread_id: str | None = None
    # References header for thread grouping
    references: str | None = None
    in_reply_to: str | None = None
    # Attachment metadata (filenames / sizes, no binary payloads)
    attachments: list[AttachmentMeta] = field(default_factory=list)


# Microsoft Graph rejects sendMail request bodies above ~4 MB, and base64
# inflates binary by ~33%, so ~3 MB of raw attachment is the safe inline ceiling.
# Above it, Graph requires the create-draft → upload-session flow.
GRAPH_INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024
# Hard ceiling for a single outbound message's total attachment size. Recipient
# mail servers commonly bounce anything larger, so we reject before sending.
MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024
# Graph upload-session chunk size MUST be a multiple of 320 KiB (327680 bytes).
_GRAPH_UPLOAD_CHUNK = 5 * 327680  # 1.6 MiB


@dataclass
class EmailAttachment:
    """An outbound attachment to send with an email. Unlike AttachmentMeta
    (inbound, metadata-only), this carries the binary payload."""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"

    @property
    def size(self) -> int:
        return len(self.content)


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
        cc: list[str] | None = None,
        attachments: list[EmailAttachment] | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """
        Send an outbound email. Returns the Message-ID of the sent message.

        cc:                  optional list of Cc recipient addresses
        attachments:         optional list of EmailAttachment (filename + bytes);
                             total size is capped at MAX_TOTAL_ATTACHMENT_SIZE
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
    ) -> tuple[Iterator[bytes], str, str | None]:
        """
        Fetch a specific attachment's binary content for an already-polled
        message. Returns ``(chunk_iterator, filename, content_type)``.

        The iterator yields binary chunks streamed directly from the upstream
        provider. Callers (e.g. ``StreamingResponse``) iterate without
        buffering the full content in memory. The underlying upstream
        response is held open by the iterator and released when iteration
        completes or the consumer disconnects.

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

    def fetch_inline_attachment(
        self,
        *,
        internet_message_id: str,
        content_id: str,
    ) -> tuple[Iterator[bytes], str | None]:
        """
        Fetch an inline (embedded) image's binary by its Content-ID — the value
        an HTML body references via ``<img src="cid:...">``. Returns
        ``(chunk_iterator, content_type)``.

        Fetched on demand at render time (same philosophy as ``fetch_attachment``)
        so it works for already-polled messages without storing inline binaries.
        Default raises — providers without inline support degrade clearly.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support inline image fetch"
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

    def forward_message(
        self,
        *,
        internet_message_id: str,
        to: list[str],
        cc: list[str] | None = None,
        comment: str | None = None,
    ) -> str:
        """
        Forward an already-polled message to new recipients, optionally with a
        comment prepended above the quoted original.

        Returns a Message-ID (or provider correlation id) for the forwarded
        copy — same best-effort contract as send_email's returned id.

        Default implementation raises — providers that can't support
        server-side forwarding should leave this as the abstract raise so the
        API surface degrades clearly (501) rather than silently failing.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support forward_message"
        )

    def list_mail_folders(self, parent_id: str | None = None) -> list[dict]:
        """
        List one level of mail folders (read-only). ``parent_id=None`` = top
        level; otherwise the children of that folder. Returns dicts:
        ``{id, display_name, child_folder_count, total_item_count,
        unread_item_count}``.

        Default is an empty list so non-Graph providers (IMAP, etc.) degrade
        cleanly — the folder feature simply shows nothing. Read-only: no
        implementation may create, move, or DELETE a folder.
        """
        return []

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
            "&$select=id,subject,from,toRecipients,ccRecipients,body,bodyPreview,"
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
            to_addrs = [
                r.get("emailAddress", {}).get("address")
                for r in (msg.get("toRecipients") or [])
                if r.get("emailAddress", {}).get("address")
            ]
            cc_addrs = [
                r.get("emailAddress", {}).get("address")
                for r in (msg.get("ccRecipients") or [])
                if r.get("emailAddress", {}).get("address")
            ]
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
                to_recipients=to_addrs,
                cc_recipients=cc_addrs,
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

    def list_mail_folders(self, parent_id: str | None = None) -> list[dict]:
        """List one level of Outlook mail folders (READ-ONLY — GET only).

        Follows @odata.nextLink pagination. parent_id=None -> top-level
        /mailFolders; otherwise /mailFolders/{parent_id}/childFolders.
        """
        mailbox = self._settings.msgraph_mailbox
        if parent_id:
            url: str | None = (
                f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders/{parent_id}/childFolders"
            )
        else:
            url = f"{self.GRAPH_BASE}/users/{mailbox}/mailFolders"
        params: dict | None = {
            "$select": "id,displayName,childFolderCount,totalItemCount,unreadItemCount",
            "$top": 100,
        }
        out: list[dict] = []
        while url:
            resp = self._client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            body = resp.json()
            for f in body.get("value", []):
                out.append({
                    "id": f["id"],
                    "display_name": f.get("displayName") or "(unnamed)",
                    "child_folder_count": f.get("childFolderCount") or 0,
                    "total_item_count": f.get("totalItemCount") or 0,
                    "unread_item_count": f.get("unreadItemCount") or 0,
                })
            # nextLink is a fully-formed URL and already carries the query;
            # drop params so we don't double-append them.
            url = body.get("@odata.nextLink")
            params = None
        return out

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
    ) -> tuple[Iterator[bytes], str, str | None]:
        """
        Stream a single attachment's binary content from MS Graph.

        Two-call pattern: a small JSON ``?$select=name,contentType`` lookup
        for the metadata, then ``/$value`` opened with ``httpx.stream()`` for
        the binary body. The binary is yielded chunk-by-chunk so the route
        never has the full file resident in memory — 50MB attachments
        download with ~64KB peak memory instead of 50MB peak.

        Prefers ``attachment_id`` (stored at poll time on new rows) for a
        direct lookup. Falls back to ``attachment_index`` for legacy rows by
        listing the message's attachments and picking the Nth non-inline one.

        Raises:
          - LookupError if the message itself can't be found in the mailbox
            (deleted / moved by the user)
          - IndexError if attachment_index is out of range for the message
          - ValueError if neither identifier is provided
        """
        if attachment_id is None and attachment_index is None:
            raise ValueError("Provide either attachment_id or attachment_index")

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
                # NOTE: in the legacy path we already have name + contentType
                # from the list response (atts[attachment_index]); we still
                # do the explicit metadata fetch below to keep both paths
                # using the same shape. The extra call is tiny relative to
                # the streamed binary.
            attachment_id = atts[attachment_index]["id"]

        attachment_base = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}"
            f"/attachments/{attachment_id}"
        )

        # 1. Metadata first — small JSON, ~1KB. Selects only name + contentType
        # so contentBytes (the base64 payload that used to drive the in-memory
        # spike) is never sent over the wire.
        meta_url = f"{attachment_base}?$select=name,contentType"
        meta_resp = self._client.get(meta_url, headers=self._headers())
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        filename = meta.get("name") or "attachment"
        content_type = meta.get("contentType")

        # 2. Binary stream — open the upstream response inside a generator so
        # the connection stays alive while StreamingResponse consumes chunks
        # and closes cleanly on completion or client disconnect.
        def _chunks() -> Iterator[bytes]:
            with self._client.stream("GET", f"{attachment_base}/$value", headers=self._headers()) as resp:
                resp.raise_for_status()
                yield from resp.iter_bytes(chunk_size=64 * 1024)

        return (_chunks(), filename, content_type)

    def fetch_inline_attachment(
        self,
        *,
        internet_message_id: str,
        content_id: str,
    ) -> tuple[Iterator[bytes], str | None]:
        """
        Stream an inline image (referenced by ``<img src="cid:...">`` in the
        HTML body) from MS Graph, matched by its Content-ID.

        Lists the message's inline attachments, matches contentId to the
        requested cid (angle brackets stripped, case-insensitive), then streams
        that attachment's ``/$value`` — same chunked pattern as
        ``fetch_attachment`` so the binary never fully buffers in memory.

        Raises:
          - LookupError if the message or a matching inline image isn't found.
        """
        mailbox = self._settings.msgraph_mailbox
        graph_id = self._resolve_graph_message_id(internet_message_id)
        if graph_id is None:
            raise LookupError(
                f"Message {internet_message_id!r} not found in mailbox — "
                "may have been deleted or moved"
            )

        wanted = content_id.strip().strip("<>").lower()
        # `contentId` is a property of the fileAttachment DERIVED type, not the
        # base `attachment` resource the collection returns — selecting it bare
        # ("...,contentId") makes Graph 400. The OData type-cast
        # `microsoft.graph.fileAttachment/contentId` selects it correctly
        # (returns null for non-file attachments, which we skip anyway).
        list_url = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}/attachments"
            "?$select=id,name,contentType,isInline,microsoft.graph.fileAttachment/contentId"
        )
        list_resp = self._client.get(list_url, headers=self._headers())
        list_resp.raise_for_status()
        match: dict | None = None
        for a in list_resp.json().get("value") or []:
            if not a.get("isInline"):
                continue
            cid = (a.get("contentId") or "").strip().strip("<>").lower()
            if cid == wanted:
                match = a
                break
        if match is None:
            raise LookupError(
                f"Inline image with content-id {content_id!r} not found in message"
            )

        attachment_base = (
            f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}"
            f"/attachments/{match['id']}"
        )
        content_type = match.get("contentType")

        def _chunks() -> Iterator[bytes]:
            with self._client.stream(
                "GET", f"{attachment_base}/$value", headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                yield from resp.iter_bytes(chunk_size=64 * 1024)

        return (_chunks(), content_type)

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

    def forward_message(
        self,
        *,
        internet_message_id: str,
        to: list[str],
        cc: list[str] | None = None,
        comment: str | None = None,
    ) -> str:
        """
        Forward a message via Graph's createForward + send flow.

        createForward drafts a forward copy — Graph auto-quotes the original
        body and carries its attachments — with `comment` prepended, then
        POST .../send dispatches it. Returns the draft's internetMessageId
        when Graph reports one; otherwise falls back to a local correlation
        id (mirrors send_email's contract for the no-attachment path).

        Raises LookupError if internet_message_id can't be resolved in the
        mailbox (deleted / moved) — the caller maps that to 404.
        """
        import uuid as _uuid

        mailbox = self._settings.msgraph_mailbox
        graph_id = self._resolve_graph_message_id(internet_message_id)
        if graph_id is None:
            raise LookupError(
                f"Message {internet_message_id!r} not found in mailbox — "
                "may have been deleted or moved"
            )

        payload: dict[str, Any] = {
            "comment": comment or "",
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        }
        if cc:
            payload["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]

        try:
            resp = self._client.post(
                f"{self.GRAPH_BASE}/users/{mailbox}/messages/{graph_id}/createForward",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            created = resp.json()
            draft_id = created["id"]
            forwarded_message_id = created.get("internetMessageId")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MSGraph createForward failed: %s | %s", exc, exc.response.text[:500]
            )
            raise

        try:
            send_resp = self._client.post(
                f"{self.GRAPH_BASE}/users/{mailbox}/messages/{draft_id}/send",
                headers=self._headers(),
            )
            send_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MSGraph forward send failed: %s | %s", exc, exc.response.text[:500]
            )
            # createForward succeeded but send didn't — an orphaned draft
            # would otherwise sit in Jane's Drafts folder forever (and could
            # be accidentally sent later by anyone with mailbox access).
            # Best-effort cleanup: never let a delete failure mask the
            # original send error the caller needs to see.
            try:
                cleanup = self._client.delete(
                    f"{self.GRAPH_BASE}/users/{mailbox}/messages/{draft_id}",
                    headers=self._headers(),
                )
                cleanup.raise_for_status()
            except Exception as cleanup_exc:
                logger.error(
                    "MSGraph: failed to delete orphaned forward draft %s: %s",
                    draft_id, cleanup_exc,
                )
            raise

        logger.info("MSGraph: forwarded message %s to %s", internet_message_id, to)
        if forwarded_message_id:
            return forwarded_message_id
        domain = mailbox.split("@")[-1] if "@" in mailbox else "localhost"
        return f"<fwd-{_uuid.uuid4()}@{domain}>"

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
        attachments: list[EmailAttachment] | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """
        Send via Graph. Messages WITHOUT attachments use the single-call
        /sendMail action. Messages WITH attachments (any size) use the
        create-draft → attach → send flow, because only the draft-create
        response reveals the Exchange-assigned ``internetMessageId`` — the
        value the attachment-download endpoint later needs to resolve the
        sent copy in Sent Items (``/sendMail`` returns 202 with no body, so
        sends through it are never resolvable). Within the draft flow, small
        attachment sets ride inline on the create call; sets larger than
        GRAPH_INLINE_ATTACHMENT_LIMIT use chunked upload sessions (Graph
        rejects large request bodies).

        Returns the real ``internetMessageId`` for attachment sends; the
        local correlation id otherwise (nothing to download → never resolved).

        Note on threading headers: Microsoft Graph rejects any
        ``internetMessageHeaders`` entry whose name does not start with ``x-``
        / ``X-``. ``Message-ID``, ``In-Reply-To``, and ``References`` are
        reserved transport headers that Exchange generates itself — attempting
        to set them via Graph returns HTTP 400 ``ErrorInvalidInternetMessageHeader``.
        The ``reply_to_message_id`` / ``references_header`` / ``message_id``
        arguments are kept for interface parity with ``IMAPProvider`` but are not
        transmitted on the Graph path; thread continuity routes through Exchange's
        own ``conversationId``. See FIX/msgraph-invalid-headers.
        """
        import uuid as _uuid
        mailbox = self._settings.msgraph_mailbox
        content_type = "html" if body_html else "text"
        content = body_html or body_text

        # Generated id is returned to the caller for DB tracking. Graph assigns
        # its own Message-ID at the transport layer; this is a local correlation
        # id only.
        if not message_id:
            domain = mailbox.split("@")[-1] if "@" in mailbox else "localhost"
            message_id = f"<{_uuid.uuid4()}@{domain}>"

        attachments = attachments or []
        total = sum(a.size for a in attachments)
        if total > MAX_TOTAL_ATTACHMENT_SIZE:
            raise ValueError(
                f"Attachments total {total} bytes exceeds the "
                f"{MAX_TOTAL_ATTACHMENT_SIZE}-byte send limit."
            )

        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]

        # Path A — no attachments: single /sendMail call. Graph never reveals
        # the sent message's internetMessageId on this path, so the caller
        # keeps the local correlation id — acceptable, because with no
        # attachments there is nothing to download later.
        if not attachments:
            url = f"{self.GRAPH_BASE}/users/{mailbox}/sendMail"
            payload = {"message": message, "saveToSentItems": True}
            try:
                resp = self._client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                logger.info(
                    "MSGraph: sent email to %s subject=%r (no attachments)",
                    to, subject,
                )
                return message_id
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "MSGraph send_email failed: %s | response_body=%s",
                    exc, exc.response.text[:500],
                )
                raise

        # Path B — any attachments: create-draft → attach → send. Captures the
        # Exchange-assigned internetMessageId so the sent copy is resolvable
        # in Sent Items for on-demand attachment download.
        real_message_id = self._send_via_draft(mailbox, message, attachments, total)
        logger.info(
            "MSGraph: sent email to %s subject=%r via draft flow (%d attachment(s), %d bytes)",
            to, subject, len(attachments), total,
        )
        return real_message_id or message_id

    def _send_via_draft(
        self,
        mailbox: str,
        message: dict[str, Any],
        attachments: list[EmailAttachment],
        total: int,
    ) -> str | None:
        """Create a draft, attach files, send the draft. Returns the
        Exchange-assigned internetMessageId from the draft-create response
        (None if Graph omits it — the caller falls back to its local id).

        Used for every send WITH attachments. Sets totalling at most
        GRAPH_INLINE_ATTACHMENT_LIMIT ride inline (base64) on the create
        call; larger sets are uploaded per-file via chunked upload sessions
        (Graph rejects large request bodies)."""
        base = f"{self.GRAPH_BASE}/users/{mailbox}"
        inline = total <= GRAPH_INLINE_ATTACHMENT_LIMIT
        create_payload = dict(message)
        if inline:
            create_payload["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a.filename,
                    "contentType": a.content_type,
                    "contentBytes": base64.b64encode(a.content).decode("ascii"),
                }
                for a in attachments
            ]
        try:
            resp = self._client.post(
                f"{base}/messages", headers=self._headers(), json=create_payload
            )
            resp.raise_for_status()
            created = resp.json()
            draft_id = created["id"]
            internet_message_id = created.get("internetMessageId")
        except httpx.HTTPStatusError as exc:
            logger.error("MSGraph create-draft failed: %s | %s", exc, exc.response.text[:500])
            raise

        if not inline:
            for a in attachments:
                self._upload_one_attachment(base, draft_id, a)

        try:
            resp = self._client.post(
                f"{base}/messages/{draft_id}/send", headers=self._headers()
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("MSGraph send-draft failed: %s | %s", exc, exc.response.text[:500])
            raise
        return internet_message_id

    def _upload_one_attachment(
        self, base: str, draft_id: str, a: EmailAttachment
    ) -> None:
        """Create an upload session for one attachment and PUT it in 320 KiB-
        aligned chunks. The upload URL is pre-authenticated, so chunk PUTs carry
        only Content-Length / Content-Range — never the Graph auth header."""
        session_body = {
            "AttachmentItem": {
                "attachmentType": "file",
                "name": a.filename,
                "size": a.size,
                "contentType": a.content_type,
            }
        }
        try:
            resp = self._client.post(
                f"{base}/messages/{draft_id}/attachments/createUploadSession",
                headers=self._headers(), json=session_body,
            )
            resp.raise_for_status()
            upload_url = resp.json()["uploadUrl"]
        except httpx.HTTPStatusError as exc:
            logger.error("MSGraph createUploadSession failed: %s | %s", exc, exc.response.text[:500])
            raise

        size = a.size
        for start in range(0, size, _GRAPH_UPLOAD_CHUNK):
            chunk = a.content[start:start + _GRAPH_UPLOAD_CHUNK]
            end = start + len(chunk) - 1
            try:
                put = self._client.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                    content=chunk,
                )
                put.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "MSGraph upload chunk %d-%d/%d failed: %s | %s",
                    start, end, size, exc, exc.response.text[:500],
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

        # Full To/Cc address lists (FEAT/reply-recipients) — getaddresses parses
        # "Name <addr>, Name2 <addr2>" forms; decode the raw header first so
        # RFC 2047-encoded display names don't interfere with address extraction.
        from email.utils import getaddresses
        to_recipients = [
            addr for _, addr in getaddresses([_decode_header_value(msg.get("To", ""))]) if addr
        ]
        cc_recipients = [
            addr for _, addr in getaddresses([_decode_header_value(msg.get("Cc", ""))]) if addr
        ]

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
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
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
        cc: list[str] | None = None,
        attachments: list[EmailAttachment] | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        import uuid as _uuid
        from email import encoders as _encoders
        from email.mime.base import MIMEBase
        s = self._settings
        cc = cc or []
        attachments = attachments or []
        total = sum(a.size for a in attachments)
        if total > MAX_TOTAL_ATTACHMENT_SIZE:
            raise ValueError(
                f"Attachments total {total} bytes exceeds the "
                f"{MAX_TOTAL_ATTACHMENT_SIZE}-byte send limit."
            )

        # Generate a Message-ID we control for thread continuity
        if not message_id:
            domain = s.smtp_username.split("@")[-1] if "@" in s.smtp_username else "localhost"
            message_id = f"<{_uuid.uuid4()}@{domain}>"

        # Body part: plain, or multipart/alternative when HTML is present.
        if body_html:
            body_part: Any = MIMEMultipart("alternative")
            body_part.attach(MIMEText(body_text, "plain"))
            body_part.attach(MIMEText(body_html, "html"))
        else:
            body_part = MIMEText(body_text, "plain")

        # Wrap in multipart/mixed only when there are attachments.
        if attachments:
            msg: Any = MIMEMultipart("mixed")
            msg.attach(body_part)
            for a in attachments:
                maintype, _, subtype = (
                    a.content_type or "application/octet-stream"
                ).partition("/")
                part = MIMEBase(maintype or "application", subtype or "octet-stream")
                part.set_payload(a.content)
                _encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", "attachment", filename=a.filename
                )
                msg.attach(part)
        else:
            msg = body_part

        msg["From"] = s.smtp_username
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
        # T2.1: Set full References chain for proper email thread display in clients
        ref_value = references_header or reply_to_message_id
        if ref_value:
            msg["References"] = ref_value

        recipients = [to, *cc]
        context = ssl.create_default_context()
        try:
            if s.smtp_use_tls:
                with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.login(s.smtp_username, s.smtp_password)
                    server.sendmail(s.smtp_username, recipients, msg.as_string())
            else:
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context) as server:
                    server.login(s.smtp_username, s.smtp_password)
                    server.sendmail(s.smtp_username, recipients, msg.as_string())
            logger.info(
                "IMAPProvider: sent email to %s subject=%r (%d attachment(s))",
                to, subject, len(attachments),
            )
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
