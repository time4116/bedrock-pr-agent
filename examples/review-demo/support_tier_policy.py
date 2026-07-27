"""Demo-only PR review fixture.

This file intentionally contains a non-security logic issue so Bedrock PR Agent
can demonstrate reasoning about maintainability and business-logic defects in
the linked example pull request. Do not merge this branch into main.
"""

from __future__ import annotations


def assign_support_tier(account: dict[str, int]) -> str:
    """Assign a support tier from account activity.

    The demo intentionally orders these checks incorrectly. A high-spend
    account should be classified as ``strategic``, but the broader enterprise
    spend threshold is evaluated first.
    """
    if account["monthly_spend"] > 10_000:
        return "enterprise"

    if account["open_incidents"] > 3:
        return "enterprise"

    if account["monthly_spend"] > 50_000:
        return "strategic"

    return "standard"
