"""
Action executor and the shared outcome model.

`outcomes.py` decides what happens when an action is taken, identically for both arms.
`runner.py` dispatches only what the guardrail layer cleared and walks a case to a
terminal state.
"""

from .outcomes import (
    HUMAN_REVIEW_COST_MINOR,
    MESSAGE_COST_MINOR,
    MODEL_ASSUMPTIONS,
    PROCESSING_COST_MINOR,
    AttemptResult,
    RepairState,
    apply_repair,
    assumptions_table,
    charge_probability,
    resolve_card_updater,
    resolve_charge,
    resolve_customer_action,
    resolve_human_review,
)
from .runner import CaseResult, blind_classification, run_case

__all__ = [
    "AttemptResult",
    "CaseResult",
    "HUMAN_REVIEW_COST_MINOR",
    "MESSAGE_COST_MINOR",
    "MODEL_ASSUMPTIONS",
    "PROCESSING_COST_MINOR",
    "RepairState",
    "apply_repair",
    "assumptions_table",
    "blind_classification",
    "charge_probability",
    "resolve_card_updater",
    "resolve_charge",
    "resolve_customer_action",
    "resolve_human_review",
    "run_case",
]
