"""
Domain models.

Plain dataclasses for the internal pipeline, plus small pydantic models for request
bodies. Money is always an integer in minor units (paise for INR) -- floats never touch
an amount, which is what makes the recovered-revenue totals reproducible to the rupee.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .taxonomy import ClassifierTier, RecoveryAction, RootCause


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Arm(str, Enum):
    """The two strategies run head-to-head over the identical failure stream."""

    AGENT = "agent"
    BASELINE = "baseline"


class MethodType(str, Enum):
    CARD = "card"
    UPI_AUTOPAY = "upi_autopay"
    ENACH = "enach"
    NETBANKING = "netbanking"


class AttemptKind(str, Enum):
    """What was actually attempted. Distinguishing these is the whole point: a naive
    system only ever has BLIND_RETRY available to it."""

    BLIND_RETRY = "blind_retry"              # baseline: fixed schedule, no diagnosis
    TIMED_RETRY = "timed_retry"              # agent: scheduled around liquidity
    BACKOFF_RETRY = "backoff_retry"          # agent: transient fault, fast backoff
    ALTERNATE_ROUTE = "alternate_route"      # agent: same charge, different processor
    POST_REPAIR_RETRY = "post_repair_retry"  # agent: retry after credential repaired
    CARD_UPDATER_LOOKUP = "card_updater_lookup"
    REAUTH_LINK = "reauth_link"
    REMANDATE_LINK = "remandate_link"
    NUDGE = "nudge"
    HUMAN_REVIEW = "human_review"


class Outcome(str, Enum):
    RECOVERED = "recovered"        # money captured
    FAILED = "failed"              # attempt made, declined again
    PENDING = "pending"            # awaiting a customer action
    SUPPRESSED = "suppressed"      # guardrail vetoed -- no side effect occurred
    ESCALATED = "escalated"        # handed to a human
    ABANDONED = "abandoned"        # policy gave up (correctly)


class GuardrailVerdict(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    MODIFY = "modify"     # action allowed but altered (deferred, reworded, downgraded)
    NA = "not_applicable"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class Customer:
    id: str
    name: str
    email: str
    phone: str
    timezone_offset_minutes: int      # relative to UTC; drives quiet-hours checks
    segment: str                      # "consumer" | "prosumer" | "smb"
    salary_day: int                   # day-of-month liquidity peak (1-28)
    consent_email: bool = True
    consent_sms: bool = True
    consent_whatsapp: bool = False
    opted_out: bool = False
    # Hard-stop flags. These override every other consideration in the guardrail layer.
    chargeback_filed: bool = False
    dispute_open: bool = False
    fraud_flag: bool = False
    lifetime_value_minor: int = 0
    tenure_days: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PaymentMethod:
    id: str
    customer_id: str
    type: MethodType
    network: str                     # VISA / MASTERCARD / RUPAY / UPI / NACH
    last4: str
    issuer: str
    exp_month: int
    exp_year: int
    # Whether the network's account-updater service has this BIN enrolled. The agent
    # cannot repair a credential the network will not tell it about, and modelling
    # that honestly matters more than an inflated recovery number.
    card_updater_enrolled: bool = True
    mandate_valid_until: str | None = None
    mandate_max_amount_minor: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class Payment:
    id: str
    customer_id: str
    method_id: str
    amount_minor: int
    currency: str
    description: str
    plan: str                        # subscription plan name
    billing_cycle: str               # "monthly" | "annual" | "usage"
    created_at: str                  # ISO-8601 UTC
    is_recurring: bool = True
    invoice_ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FailureEvent:
    """A payment failure as it actually arrives: a messy, gateway-specific string.

    `true_root_cause` is generator-only ground truth. It is never shown to the
    classifier -- it exists so the dashboard can score classification accuracy against
    a labelled set instead of asking judges to take the labels on faith.
    """

    id: str
    payment_id: str
    gateway: str
    gateway_txn_id: str
    raw_code: str
    raw_message: str
    http_status: int | None
    occurred_at: str
    attempt_no: int
    method_type: MethodType
    # --- ground truth (withheld from every classifier tier) ------------------
    true_root_cause: RootCause = RootCause.UNKNOWN
    is_ambiguous: bool = False          # generator marked this as messy-remainder
    recoverable_in_principle: bool = True

    def to_dict(self, include_truth: bool = False) -> dict:
        d = {
            "id": self.id,
            "payment_id": self.payment_id,
            "gateway": self.gateway,
            "gateway_txn_id": self.gateway_txn_id,
            "raw_code": self.raw_code,
            "raw_message": self.raw_message,
            "http_status": self.http_status,
            "occurred_at": self.occurred_at,
            "attempt_no": self.attempt_no,
            "method_type": self.method_type.value,
        }
        if include_truth:
            d["true_root_cause"] = self.true_root_cause.value
            d["is_ambiguous"] = self.is_ambiguous
            d["recoverable_in_principle"] = self.recoverable_in_principle
        return d

    def classifier_view(self) -> dict:
        """Exactly what the classifier is allowed to see."""
        return {
            "gateway": self.gateway,
            "raw_code": self.raw_code,
            "raw_message": self.raw_message,
            "http_status": self.http_status,
            "attempt_no": self.attempt_no,
            "method_type": self.method_type.value,
        }


@dataclass
class Classification:
    root_cause: RootCause
    confidence: float
    tier: ClassifierTier
    rationale: str
    normalized_reason: str            # the messy string, cleaned to canonical form
    signals: list[str] = field(default_factory=list)   # what drove the decision
    considered: list[dict] = field(default_factory=list)  # runner-up hypotheses
    latency_ms: int = 0
    model: str | None = None
    escalated_from_rules: bool = False
    rules_confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause.value,
            "confidence": round(self.confidence, 4),
            "tier": self.tier.value,
            "rationale": self.rationale,
            "normalized_reason": self.normalized_reason,
            "signals": self.signals,
            "considered": self.considered,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "escalated_from_rules": self.escalated_from_rules,
            "rules_confidence": self.rules_confidence,
        }


@dataclass
class GuardrailCheck:
    """One hard check, executed in code.

    Every check that runs is recorded -- including the ones that passed -- because
    "here is the list of things that were verified before anything left the building"
    is the artifact that earns trust.
    """

    id: str
    name: str
    verdict: GuardrailVerdict
    detail: str
    category: str          # "attempt_cap" | "cooldown" | "exposure" | "hard_stop" | "comms"
    severity: str = "info"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "verdict": self.verdict.value,
            "detail": self.detail,
            "category": self.category,
            "severity": self.severity,
        }


@dataclass
class ActionPlan:
    """What the policy engine proposes, before guardrails get a vote."""

    action: RecoveryAction
    kind: AttemptKind
    scheduled_at: str
    companion_action: RecoveryAction | None = None
    companion_kind: AttemptKind | None = None
    companion_scheduled_at: str | None = None
    channel: str | None = None
    message: str | None = None
    reason: str = ""
    delay_hours: float = 0.0
    timing_strategy: str = ""          # e.g. "payday+1", "exp_backoff", "immediate"
    alternate_route: str | None = None
    expected_success_rate: float = 0.0
    requires_human_signoff: bool = False

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "kind": self.kind.value,
            "scheduled_at": self.scheduled_at,
            "companion_action": self.companion_action.value if self.companion_action else None,
            "companion_kind": self.companion_kind.value if self.companion_kind else None,
            "companion_scheduled_at": self.companion_scheduled_at,
            "channel": self.channel,
            "message": self.message,
            "reason": self.reason,
            "delay_hours": round(self.delay_hours, 3),
            "timing_strategy": self.timing_strategy,
            "alternate_route": self.alternate_route,
            "expected_success_rate": round(self.expected_success_rate, 4),
            "requires_human_signoff": self.requires_human_signoff,
        }


@dataclass
class Decision:
    """The complete, auditable record of one event's journey through the system."""

    id: str
    run_id: str
    event_id: str
    payment_id: str
    customer_id: str
    arm: Arm
    amount_minor: int
    currency: str
    created_at: str

    classification: Classification
    proposed: ActionPlan
    final_action: RecoveryAction
    guardrails: list[GuardrailCheck] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    modified: bool = False
    escalated: bool = False
    ledger_seq: int | None = None
    ledger_hash: str | None = None
    sequence_no: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "payment_id": self.payment_id,
            "customer_id": self.customer_id,
            "arm": self.arm.value,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "created_at": self.created_at,
            "classification": self.classification.to_dict(),
            "proposed": self.proposed.to_dict(),
            "final_action": self.final_action.value,
            "guardrails": [g.to_dict() for g in self.guardrails],
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "modified": self.modified,
            "escalated": self.escalated,
            "ledger_seq": self.ledger_seq,
            "ledger_hash": self.ledger_hash,
            "sequence_no": self.sequence_no,
        }


@dataclass
class Attempt:
    """A concrete side effect: a charge attempt, a lookup, a message, a review ticket."""

    id: str
    run_id: str
    payment_id: str
    decision_id: str
    arm: Arm
    attempt_no: int
    kind: AttemptKind
    attempted_at: str
    outcome: Outcome
    amount_recovered_minor: int = 0
    processing_cost_minor: int = 0      # per-attempt processor/gateway fee we burn
    network_penalty_points: float = 0.0 # retry-abuse exposure accrued
    customer_touch: bool = False        # did this put a message in front of a human
    detail: str = ""
    success_probability: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "payment_id": self.payment_id,
            "decision_id": self.decision_id,
            "arm": self.arm.value,
            "attempt_no": self.attempt_no,
            "kind": self.kind.value,
            "attempted_at": self.attempted_at,
            "outcome": self.outcome.value,
            "amount_recovered_minor": self.amount_recovered_minor,
            "processing_cost_minor": self.processing_cost_minor,
            "network_penalty_points": round(self.network_penalty_points, 4),
            "customer_touch": self.customer_touch,
            "detail": self.detail,
            "success_probability": round(self.success_probability, 4),
        }


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    event_count: int = Field(default=600, ge=10, le=5000)
    seed: int | None = None
    use_llm: bool = Field(
        default=False,
        description=(
            "Batch benchmarks default to the deterministic reasoner so the headline "
            "numbers are byte-for-byte reproducible. The live triage view is where "
            "the model actually runs."
        ),
    )
    label: str | None = None


class LiveStreamRequest(BaseModel):
    event_count: int = Field(default=40, ge=1, le=1000)
    seed: int | None = None
    use_llm: bool = True
    interval_ms: int = Field(default=220, ge=0, le=5000)
    ambiguous_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class PolicyPatch(BaseModel):
    max_attempts_per_method_per_week: int | None = Field(default=None, ge=0, le=20)
    max_attempts_per_method_per_day: int | None = Field(default=None, ge=0, le=10)
    autonomous_exposure_ceiling_minor: int | None = Field(default=None, ge=0)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    max_nudges_per_customer_per_week: int | None = Field(default=None, ge=0, le=20)
    escalate_after_failed_attempts: int | None = Field(default=None, ge=1, le=10)


class ClassifyRequest(BaseModel):
    """Ad-hoc classification -- the "try it yourself" panel in the dashboard.

    Judges typing their own garbage decline string into the box and watching the
    classifier handle it is worth more than any slide.
    """

    raw_message: str = Field(min_length=1, max_length=2000)
    raw_code: str = Field(default="", max_length=200)
    gateway: str = Field(default="manual", max_length=60)
    http_status: int | None = None
    use_llm: bool = True


class TamperRequest(BaseModel):
    """Deliberately corrupt one ledger row to prove the hash chain detects it."""

    seq: int = Field(ge=1)
    new_action: str | None = None


def jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/enums into JSON-safe primitives."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
