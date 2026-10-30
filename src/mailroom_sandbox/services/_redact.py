"""Keep credentials in endpoint URLs out of diagnostics and published snapshots."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_URL = re.compile(r"https?://[^\s<>\"']+")


def redact_urls(text: str) -> str:
    """Remove userinfo, query values and fragments from URLs in diagnostic text."""
    def replace(match: re.Match[str]) -> str:
        try:
            parts = urlsplit(match.group())
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path,
                               "REDACTED" if parts.query else "", ""))
        except ValueError:
            return "[invalid endpoint]"

    return _URL.sub(replace, text)
