"""
Policy layer: what to do about a diagnosis, and what we refuse to do regardless.

Split into four modules on purpose, because they answer four different questions and
should be reviewable independently:

    timing.py      -- *when* to act (liquidity-aware, backoff, re-route, post-repair)
    comms.py       -- *what to say*, and the prohibited-phrasing scanner
    guardrails.py  -- what is *forbidden*, as hard checks over state
    engine.py      -- the join: diagnosis in, one cleared action out

Nothing in this package imports the classifier, and nothing in it calls a model.
"""

from .comms import (
    Nudge,
    ToneScan,
    compose_nudge,
    message_catalogue,
    preferred_channel,
    scan_message_tone,
    tone_rules_catalogue,
)
from .engine import (
    DecisionOutcome,
    PolicyEngine,
    baseline_plan,
    plan_action,
    policy_matrix,
)
from .guardrails import (
    GuardrailContext,
    GuardrailEngine,
    GuardrailOutcome,
    GuardrailState,
    guardrail_catalogue,
)
from .timing import (
    baseline_retry_time,
    in_quiet_hours,
    local_time,
    next_allowed_contact_time,
    parse_iso,
    timing_for_cause,
    to_iso,
)

__all__ = [
    "DecisionOutcome",
    "GuardrailContext",
    "GuardrailEngine",
    "GuardrailOutcome",
    "GuardrailState",
    "Nudge",
    "PolicyEngine",
    "ToneScan",
    "baseline_plan",
    "baseline_retry_time",
    "compose_nudge",
    "guardrail_catalogue",
    "in_quiet_hours",
    "local_time",
    "message_catalogue",
    "next_allowed_contact_time",
    "parse_iso",
    "plan_action",
    "policy_matrix",
    "preferred_channel",
    "scan_message_tone",
    "timing_for_cause",
    "to_iso",
    "tone_rules_catalogue",
]
