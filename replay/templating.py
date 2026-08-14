"""Substitutes {{variable}} placeholders in step params and signal values with real input
values at replay time. Locators are never templated (they describe *how to find* an element,
not data), so only Signal.value and Step.params go through this.
"""
from __future__ import annotations

import re
from typing import Any

from artifacts_lib.schema import Signal

_TEMPLATE_RE = re.compile(r"\{\{(\w+)\}\}")


def substitute(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                raise KeyError(f"template variable '{{{{{key}}}}}' not provided in inputs")
            return str(variables[key])
        return _TEMPLATE_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def substitute_signal(signal: Signal, variables: dict[str, Any]) -> Signal:
    return signal.model_copy(update={"value": substitute(signal.value, variables)})
