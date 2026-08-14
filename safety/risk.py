"""Classifies whether an action is safe/reversible or risky/irreversible --
ASSIGNMENT_ORIGINAL.md 3.4. Deliberately independent of whatever risk_level a saved artifact
step *claims*: Surface.act() re-classifies live, at execution time, rather than trusting a value
that could be stale or hand-edited (defense in depth against a tampered or wrong artifact).
Binary by design, matching Step.risk_level's own two-value model (artifacts_lib/schema.py).
"""
from __future__ import annotations

from artifacts_lib.schema import ActionType, StepRiskLevel

# Reading/observing/navigating is never itself irreversible -- only an action that could
# change state (click/type/select/dismiss) is a candidate.
_ALWAYS_SAFE_ACTIONS = {ActionType.EXTRACT, ActionType.NAVIGATE, ActionType.WAIT_FOR}

# Deliberately does NOT include "open account" / "open sub-account" -- MockBank's "Open
# Sub-Account" link is a plain navigational link to the form (no side effect), and it's a CLICK,
# not a NAVIGATE, so it isn't caught by _ALWAYS_SAFE_ACTIONS above. Including that phrase here
# would misclassify a harmless navigation as irreversible. "confirm" alone already correctly
# catches the actual irreversible step -- MockBank's "Confirm & Open Account" button.
#
# Deliberately does NOT include "submit" -- found via a real false positive: a hand-written
# fixture's Target.semantic_description read "login submit button" (a human-authored
# description, not the element's actual accessible name, which is just "Log In"), and that got
# the login button blocked as irreversible. "submit" is generic enough to show up in
# descriptive text without meaning "this changes state" -- none of MockBank's actual button
# labels ("Log In", "Search", "Continue", "Confirm & Open Account") contain it, so dropping it
# loses no real detection here. The fixtures were also fixed to describe elements by their
# accessible name, matching the convention WebSurface.compute_target() already uses for
# LLM-discovered artifacts, precisely so semantic_description stays a reliable classification
# signal rather than free-text prose.
_RISK_KEYWORDS = ("confirm", "delete", "remove", "transfer", "withdraw", "close account")


class RiskClassifier:
    def classify(
        self,
        action_type: ActionType,
        semantic_description: str | None = None,
        current_path: str | None = None,
    ) -> StepRiskLevel:
        if action_type in _ALWAYS_SAFE_ACTIONS:
            return StepRiskLevel.SAFE
        haystack = f"{semantic_description or ''} {current_path or ''}".lower()
        if any(keyword in haystack for keyword in _RISK_KEYWORDS):
            return StepRiskLevel.IRREVERSIBLE
        return StepRiskLevel.SAFE
