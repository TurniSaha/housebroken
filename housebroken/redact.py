"""Secret scrubbing (SPEC §3.1 P4).

Applied to every span before it reaches a report (and, later, a judge prompt).
Conservative, well-known patterns only — the goal is to never leak a real
credential in a receipt, accepting occasional over-redaction. Order matters:
longer/more-specific patterns run before generic ones.

Each replacement preserves a short hint of what was scrubbed so a receipt stays
legible ("<redacted:aws-key>") without exposing the value.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # AWS access key id.
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<redacted:aws-key>"),
    # GitHub tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,255}\b"), "<redacted:github-token>"),
    # OpenAI / Anthropic style keys.
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{16,}\b"), "<redacted:api-key>"),
    # Slack tokens.
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), "<redacted:slack-token>"),
    # Google API key.
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "<redacted:google-key>"),
    # Bearer / Authorization header values.
    (re.compile(r"(?i)\b(bearer|authorization:?)\s+[A-Za-z0-9._\-]{12,}"),
     r"\1 <redacted:token>"),
    # Private key blocks.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "<redacted:private-key>"),
    # JWT.
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
     "<redacted:jwt>"),
    # Email addresses.
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "<redacted:email>"),
    # High-entropy value assigned to a secret-ish env var / key.
    (re.compile(
        r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY)"
        r"[A-Z0-9_]*)\s*[=:]\s*[\"']?([A-Za-z0-9/+_\-]{12,})[\"']?"),
     r"\1=<redacted:secret-value>"),
)


def redact(text: str) -> str:
    """Return ``text`` with recognized secrets replaced by labeled placeholders."""
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
