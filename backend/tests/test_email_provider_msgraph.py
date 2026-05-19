"""
Tests for MSGraphProvider — focused on the body-extraction path that was
silently dropping `body_text` on every HTML email returned by Microsoft
Graph (the default body shape).

The bug: the previous mapping made body_text / body_html mutually exclusive
based on contentType, so an HTML response left body_text=None — blanking the
dashboard and forcing the AI categorizer to read raw HTML (with <style>,
<head>, inline CSS). The fix stores HTML as-is in body_html AND derives a
clean plain-text version into body_text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.services.email_provider import MSGraphProvider, _html_to_text


# ── _html_to_text helper ──────────────────────────────────────────────────────

class TestHtmlToText:
    def test_empty_input_returns_empty_string(self):
        assert _html_to_text("") == ""

    def test_none_input_returns_empty_string(self):
        # None can sneak in from `body_obj.get("content")` if the provider
        # ever sends `content: null` — the helper must not raise.
        assert _html_to_text(None) == ""  # type: ignore[arg-type]

    def test_plain_paragraph(self):
        html = "<p>Hello world</p>"
        assert _html_to_text(html) == "Hello world"

    def test_preserves_links_as_markdown(self):
        html = '<p>See <a href="https://example.com/x">our docs</a> for more.</p>'
        out = _html_to_text(html)
        assert "[our docs](https://example.com/x)" in out

    def test_strips_style_and_script_noise(self):
        # This is the realistic MS Graph shape — <style> in <head> with CSS
        # that the AI absolutely should not see as "email content."
        html = """
        <html>
          <head>
            <style type="text/css">body { font-family: Arial; color: #333; }</style>
          </head>
          <body>
            <p>Please send the Q3 statements when you have a chance.</p>
          </body>
        </html>
        """
        out = _html_to_text(html)
        assert "Please send the Q3 statements" in out
        assert "font-family" not in out
        assert "Arial" not in out

    def test_no_line_wrapping(self):
        # body_width=0 is intentional — wrapping at 78 chars would corrupt
        # threading quotes and confuse the categorizer's "is this quoted
        # history?" heuristics.
        long_line = "word " * 40
        html = f"<p>{long_line}</p>"
        out = _html_to_text(html).strip()
        # Single logical line, no mid-sentence newlines
        assert "\n" not in out

    def test_collapses_excessive_blank_lines(self):
        """
        Outlook composes paragraphs as `<p>&nbsp;</p>` stacked between real
        content, which html2text renders as runs of 3-6+ consecutive newlines.
        That looks like a UI bug ("excessive whitespace gaps") even though
        the data round-trips correctly. Collapse to a single paragraph break.
        """
        # Realistic shape: Outlook puts 2-3 empty paragraphs between blocks.
        # html2text turns each into "\n\n  \n" → multi-line gap.
        html = (
            "<p>Dear Jane,</p>"
            "<p>&nbsp;</p><p>&nbsp;</p><p>&nbsp;</p>"
            "<p>Please send the Q3 statements.</p>"
            "<p>&nbsp;</p><p>&nbsp;</p>"
            "<p>Best, Caroline</p>"
        )
        out = _html_to_text(html)
        # No run of 3+ newlines should remain anywhere in the output.
        assert "\n\n\n" not in out, (
            f"Run of 3+ newlines survived collapse: {out!r}"
        )
        # But single paragraph breaks should still exist (don't over-collapse).
        assert "\n\n" in out, "Paragraph breaks must survive collapse"
        # Content order preserved
        assert out.index("Dear Jane,") < out.index("Q3 statements") < out.index("Caroline")

    def test_collapses_nbsp_blank_lines(self):
        """
        Some HTML emails have lines that look blank but actually contain a
        non-breaking space (\\xa0) or stray tabs. After html2text, those
        appear as "\\n  \\n" rather than "\\n\\n", so a naive `\\n{3,}` regex
        would miss them. Collapse should still flatten these.
        """
        html = "<p>Line one</p><p> </p><p> </p><p> </p><p>Line five</p>"
        out = _html_to_text(html)
        # Count actual newlines between the two visible lines — should be exactly 2
        between = out.split("Line one")[1].split("Line five")[0]
        assert between.count("\n") == 2, (
            f"NBSP-padded blank lines didn't collapse cleanly: {between!r}"
        )

    def test_preserves_non_ascii(self):
        # unicode_snob=True — currency, accents, em-dashes must survive
        # because real client emails contain them and the categorizer's
        # signal extraction depends on them.
        html = "<p>Total: €1,234 — payée le 5 mai</p>"
        out = _html_to_text(html)
        assert "€" in out
        assert "—" in out
        assert "payée" in out


# ── MSGraphProvider body extraction ───────────────────────────────────────────

def _make_provider() -> MSGraphProvider:
    """
    Build a provider with auth + httpx short-circuited so tests can inject
    a fake Graph response without needing real tokens or network access.
    """
    provider = MSGraphProvider(get_settings())
    provider._access_token = "test-token"
    provider._token_expires_at = datetime.now(timezone.utc).replace(year=2099)
    provider._client = MagicMock()
    return provider


def _fake_graph_response(messages: list[dict]) -> MagicMock:
    """Build a MagicMock httpx response wrapping a Graph /messages payload."""
    resp = MagicMock()
    resp.json.return_value = {"value": messages}
    resp.raise_for_status.return_value = None
    return resp


def _base_message(**overrides) -> dict:
    """Minimum Graph message shape — overrideable per test."""
    msg = {
        "id": "graph-id-1",
        "internetMessageId": "<test-1@example.com>",
        "subject": "Test subject",
        "from": {"emailAddress": {"address": "client@example.com"}},
        "receivedDateTime": "2026-05-19T10:00:00Z",
        "conversationId": "conv-1",
        "internetMessageHeaders": [],
        "hasAttachments": False,
        "attachments": [],
        "body": {"contentType": "html", "content": "<p>default</p>"},
    }
    msg.update(overrides)
    return msg


class TestMsgraphBodyExtraction:
    """The core bug-fix tests: body_text must be populated on HTML emails."""

    def test_html_body_populates_both_fields(self):
        # The case that was broken: M365 returns HTML, both fields must populate.
        provider = _make_provider()
        provider._client.get.return_value = _fake_graph_response([
            _base_message(body={
                "contentType": "html",
                "content": (
                    "<html><head><style>p { color: red; }</style></head>"
                    "<body><p>Hi Jane — please send <b>last year's K-1s</b> "
                    'when you can. Reply to <a href="mailto:ops@apex.com">'
                    "ops@apex.com</a>.</p></body></html>"
                ),
            }),
        ])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        raw = results[0]
        # body_html stored as-is (UI / future rich-render path)
        assert raw.body_html is not None
        assert "<style>" in raw.body_html
        # body_text derived — clean, no CSS, links preserved
        assert raw.body_text is not None
        assert "last year's K-1s" in raw.body_text
        assert "color: red" not in raw.body_text
        assert "<style>" not in raw.body_text
        assert "(mailto:ops@apex.com)" in raw.body_text

    def test_text_body_populates_only_body_text(self):
        # Plain-text emails from Graph (rare but possible — some clients
        # negotiate text/plain) should only set body_text.
        provider = _make_provider()
        provider._client.get.return_value = _fake_graph_response([
            _base_message(body={
                "contentType": "text",
                "content": "Just a quick note — no HTML here.",
            }),
        ])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        assert results[0].body_text == "Just a quick note — no HTML here."
        assert results[0].body_html is None

    def test_missing_body_object_yields_none_for_both(self):
        # Defensive: malformed Graph response where `body` is missing entirely.
        provider = _make_provider()
        msg = _base_message()
        del msg["body"]
        provider._client.get.return_value = _fake_graph_response([msg])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        assert results[0].body_text is None
        assert results[0].body_html is None

    def test_empty_content_yields_none_for_both(self):
        # Empty body string — don't store an empty string, store None so
        # downstream code's `body_text or body_html or ""` fallback works.
        provider = _make_provider()
        provider._client.get.return_value = _fake_graph_response([
            _base_message(body={"contentType": "html", "content": ""}),
        ])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        assert results[0].body_text is None
        assert results[0].body_html is None

    def test_null_subject_coerced_to_placeholder(self):
        """
        Real iCloud-sent emails arrive with `"subject": null`. The previous
        code used `msg.get("subject", "(no subject)")` which only defaults on
        a missing key — a present-but-null value still returned None and
        crashed downstream callers (notably _is_bounce's subject.strip()),
        which then never marked the message as read → infinite retry loop on
        every poll cycle. Coerce to "(no subject)" at the boundary.
        """
        provider = _make_provider()
        msg = _base_message()
        msg["subject"] = None  # iCloud / certain auto-replies do this
        provider._client.get.return_value = _fake_graph_response([msg])

        results = provider.fetch_new_emails()

        assert len(results) == 1
        assert results[0].subject == "(no subject)"
        assert isinstance(results[0].subject, str), (
            "Subject must always be a str — downstream code (_is_bounce, "
            "categorizer prompt builder) assumes the str contract"
        )

    def test_null_from_yields_empty_sender_string(self):
        """
        Some system / quarantine messages arrive with `"from": null`. Same
        defensive principle: coerce to empty string so downstream code can
        rely on `raw.sender` being a string.
        """
        provider = _make_provider()
        msg = _base_message()
        msg["from"] = None
        provider._client.get.return_value = _fake_graph_response([msg])

        results = provider.fetch_new_emails()

        assert results[0].sender == ""
        assert isinstance(results[0].sender, str)

    def test_unknown_content_type_yields_none_for_both(self):
        # Defensive: if Graph ever returns an unexpected contentType (e.g.
        # "multipart"), we don't guess — we leave both None and let the
        # categorizer skip / staff investigate.
        provider = _make_provider()
        provider._client.get.return_value = _fake_graph_response([
            _base_message(body={"contentType": "multipart", "content": "data"}),
        ])

        results = provider.fetch_new_emails()

        assert results[0].body_text is None
        assert results[0].body_html is None
