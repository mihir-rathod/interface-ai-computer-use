"""Coerces a raw extracted string (what Surface.act(EXTRACT) reads off the page, e.g.
"$4,231.55") into the type output_schema declares for that field. Surface deliberately doesn't
know about output_schema at all -- this is where that gap gets closed, on replay's side of the
boundary.
"""
from __future__ import annotations

import re
from typing import Any


def coerce_output(raw: str | None, prop_schema: dict[str, Any] | None) -> Any:
    if raw is None or prop_schema is None:
        return raw
    declared = prop_schema.get("type")
    types = declared if isinstance(declared, list) else [declared] if declared else []
    cleaned = raw.strip()

    if "number" in types:
        numeric = re.sub(r"[^0-9.\-]", "", cleaned)
        try:
            return float(numeric)
        except ValueError:
            return cleaned  # doesn't look numeric -- leave as-is so a checkpoint/caller can catch it
    if "integer" in types:
        numeric = re.sub(r"[^0-9\-]", "", cleaned)
        try:
            return int(numeric)
        except ValueError:
            return cleaned
    if "boolean" in types:
        return cleaned.lower() in ("true", "yes", "1")
    return cleaned
