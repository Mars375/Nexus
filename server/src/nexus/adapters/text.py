"""Readable excerpts of text that comes from an executor (shared by the adapters)."""

from __future__ import annotations

from nexus import secrets

TEXT_MAX = 500


def cut(text: object) -> str | None:
    """A readable excerpt, or None: empty, or nothing left once secrets are masked (the event
    protocol refuses such a body, and a refused fact would hold the run back)."""
    if not isinstance(text, str):
        return None
    # A lone UTF-16 half (JSON allows "\ud800") cannot be encoded back: replaced first. Secrets
    # are masked on the WHOLE text, then it is cut: a key straddling the cut would otherwise
    # lose the beginning the scanner recognises and be published in clear.
    clean = text.encode("utf-8", "replace").decode("utf-8")
    cut_text = secrets.redact(clean)[0].strip()[:TEXT_MAX]
    return None if secrets.is_blank(cut_text) else cut_text
