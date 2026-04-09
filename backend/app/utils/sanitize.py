"""
Text sanitization utilities.

strip_html() is used before passing any user-supplied content to AI services
to prevent HTML-based prompt injection attacks.
"""
from __future__ import annotations

import re

# Match any HTML tag: opening, closing, self-closing, or with attributes
_HTML_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE | re.DOTALL)


def strip_html(text: str) -> str:
    """
    Remove all HTML tags from text, returning plain content.

    This is a defence-in-depth measure applied before sending email bodies
    to Claude to prevent HTML-injected prompt injection payloads from being
    interpreted as AI instructions.

    Examples
    --------
    >>> strip_html("<b>Hello</b> <script>ignore this</script>world")
    'Hello world'
    >>> strip_html("No tags here")
    'No tags here'
    """
    if not text:
        return text
    return _HTML_TAG_RE.sub("", text)
