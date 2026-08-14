"""The floor for ASSIGNMENT_ORIGINAL.md 3.4 ("never persist secrets... into artifacts or
logs"): the one real secret this system ever handles is the operator password typed during a
login capability, so redact it at the one call site that has the context to recognize it.

This is deliberately narrow, not a generic recursive redactor -- a policy-driven allowlist and
broader PII redaction is the safety module's job (Phase 6). This just makes sure nothing
sensitive can hit disk even before that module exists.
"""
from __future__ import annotations

from typing import Any

_SENSITIVE_MARKERS = ("password", "secret", "token", "credential")


def is_sensitive_field(label: str | None) -> bool:
    if not label:
        return False
    lowered = label.lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def redact_type_params(params: dict[str, Any], semantic_description: str | None) -> dict[str, Any]:
    if is_sensitive_field(semantic_description) and "text" in params:
        return {**params, "text": "***REDACTED***"}
    return params
