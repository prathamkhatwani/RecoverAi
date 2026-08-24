"""
Root-cause taxonomy -- the intellectual property of this build.

The plan is explicit about this: "Treat it as an actual lookup structure in code, not a
vague 'the AI figures it out' claim." So this module is a real, queryable lookup
structure. Nothing downstream is allowed to invent a root cause that is not declared
here, and every policy parameter (attempt caps, cooldowns, retry stance, network
penalty exposure) hangs off the taxonomy entry rather than being scattered through the
executor.

Layers in this file
-------------------
1. `RootCause`          -- the eight canonical causes from the plan's table.
2. `RecoveryAction`     -- exactly four bounded action lanes. A failure event flows to
                           exactly one lane. There is deliberately no "blanket retry".
3. `TAXONOMY`           -- RootCause -> TaxonomyEntry, the full policy record.
4. `DECLINE_CODES`      -- ISO-8583 / processor code -> RootCause, the unambiguous
                           fast path that the rules engine uses.
5. Helper lookups used by the classifier and the policy engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RootCause(str, Enum):
    """The eight canonical root causes. `UNKNOWN` is not a ninth cause -- it is the
    explicit admission that classification failed, which routes to human review."""

    INSUFFICIENT_FUNDS = "insufficient_funds"
    ISSUER_UNAVAILABLE = "issuer_unavailable"
    EXPIRED_CARD = "expired_card"
    AUTH_3DS_FAILURE = "auth_3ds_failure"
    FRAUD_BLOCK = "fraud_block"
    HARD_DECLINE = "hard_decline"
    GATEWAY_ERROR = "gateway_error"
    LAPSED_MANDATE = "lapsed_mandate"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    """The four bounded action lanes from the architecture diagram.

    `SUPPRESS` is not a fifth lane -- it is the absence of an action, used when the
    guardrail layer vetoes everything the policy engine proposed. Keeping it distinct
    from the four lanes is what lets the dashboard prove that a veto produced *no*
    outbound side effect rather than a quieter one.
    """

    SMART_RETRY = "smart_retry"
    CARD_UPDATER = "card_updater"
    CUSTOMER_NUDGE = "customer_nudge"
    HUMAN_REVIEW = "human_review"
    SUPPRESS = "suppress"


class RetryStance(str, Enum):
    """How the taxonomy answers the plan's "Retry?" column."""

    SCHEDULED = "yes_scheduled"          # retry, but only at a computed good moment
    IMMEDIATE = "yes_immediate"          # transient -- retry fast with backoff
    NO_BLIND_RETRY = "no_blind_retry"    # retry only after a repair step succeeds
    NEVER = "never"                      # no retry; a different lane owns this
    HARD_STOP = "hard_stop"              # stop permanently and flag the account


class ClassifierTier(str, Enum):
    """Which tier produced a classification. Surfaced in the UI so a judge can see
    exactly where the LLM earns its place and where it is not needed."""

    RULES = "rules"          # deterministic code/pattern match, high confidence
    LLM = "llm"              # live model call on the messy remainder
    OFFLINE = "offline"      # deterministic stand-in reasoner (no key / no network)
    FALLBACK = "fallback"    # every tier abstained -> UNKNOWN -> human review
    HUMAN = "human"          # an analyst worked the escalated case and named the cause


# ---------------------------------------------------------------------------
# Taxonomy entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaxonomyEntry:
    """One row of the plan's root-cause table, plus the policy parameters that the
    engine needs to act on it."""

    cause: RootCause
    label: str
    signal: str                     # human-readable signal, shown in the UI matrix
    recovery_action: str            # human-readable action, shown in the UI matrix
    retry_answer: str               # human-readable "Retry?" column
    retry_stance: RetryStance

    primary_action: RecoveryAction
    # A companion action is a *second* lane firing for the same event -- e.g.
    # insufficient funds gets a scheduled retry AND a soft nudge. It is modelled
    # explicitly so the executor never improvises extra outbound messages.
    companion_action: RecoveryAction | None

    # --- policy parameters -------------------------------------------------
    max_attempts: int               # agent-side attempt cap for this cause
    cooldown_hours: float           # minimum spacing between attempts
    max_lifetime_days: int          # give up after this long
    requires_repair: bool           # a repair step must succeed before any retry
    terminal: bool                  # no automated recovery path exists at all

    # Retrying these causes is what gets merchants penalised by the card networks.
    # 0.0 = harmless to retry, 1.0 = every retry is actively damaging.
    network_penalty_weight: float

    # --- presentation ------------------------------------------------------
    severity: str                   # "critical" | "warning" | "info"
    color: str                      # stable token consumed by the frontend palette
    description: str
    why_naive_retry_fails: str      # the sentence that wins the argument on stage

    # Codes that map here unambiguously (documentation + rules engine seeding).
    codes: tuple[str, ...] = field(default_factory=tuple)

    # Whether an attempt on this cause consumes the *global* per-method attempt budget.
    #
    # The network schemes cap retries because every retry is another authorisation request
    # the issuer had to decide. An issuer host that never answered, or our own gateway
    # returning a 5xx, produced no decision at all -- there is nothing for the issuer to
    # have been bothered by, and the scheme counters do not move. So those causes are
    # exempt from the global cap while remaining bound by their own `max_attempts`, which
    # is what lets a four-rung outage ladder run inside an hour without the daily cap
    # cutting it off after two.
    counts_against_network_cap: bool = True


# ---------------------------------------------------------------------------
# THE TABLE
# ---------------------------------------------------------------------------

TAXONOMY: dict[RootCause, TaxonomyEntry] = {
    RootCause.INSUFFICIENT_FUNDS: TaxonomyEntry(
        cause=RootCause.INSUFFICIENT_FUNDS,
        label="Insufficient funds",
        signal="Code 51/61, recurring pattern",
        recovery_action="Smart-timed retry (near payday) + soft nudge",
        retry_answer="Yes, scheduled",
        retry_stance=RetryStance.SCHEDULED,
        primary_action=RecoveryAction.SMART_RETRY,
        companion_action=RecoveryAction.CUSTOMER_NUDGE,
        max_attempts=3,
        cooldown_hours=48.0,
        max_lifetime_days=21,
        requires_repair=False,
        terminal=False,
        network_penalty_weight=0.15,
        severity="warning",
        color="amber",
        description=(
            "The card and the mandate are both healthy; the account simply did not "
            "have the balance at the moment of capture. This is a timing problem "
            "wearing the costume of a payment problem."
        ),
        why_naive_retry_fails=(
            "Retrying at a fixed 24h interval burns all three attempts inside the "
            "customer's low-balance window. Waiting for salary credit converts the "
            "same card at roughly 3x the rate for one third of the attempts."
        ),
        codes=("51", "61", "NSF", "insufficient_funds"),
    ),
    RootCause.ISSUER_UNAVAILABLE: TaxonomyEntry(
        cause=RootCause.ISSUER_UNAVAILABLE,
        label="Issuer system unavailable",
        signal="Code 91/96, transient",
        recovery_action="Fast retry with exponential backoff",
        retry_answer="Yes, immediate",
        retry_stance=RetryStance.IMMEDIATE,
        primary_action=RecoveryAction.SMART_RETRY,
        companion_action=None,
        max_attempts=5,
        cooldown_hours=0.25,
        max_lifetime_days=2,
        requires_repair=False,
        terminal=False,
        network_penalty_weight=0.0,
        severity="info",
        color="sky",
        description=(
            "The issuing bank's authorisation host did not answer in time. Nothing is "
            "wrong with the instrument or the customer -- the far end blinked."
        ),
        why_naive_retry_fails=(
            "A 24h fixed schedule is catastrophically slow for a fault that clears in "
            "minutes. By the time a naive retry fires, the dunning email has already "
            "alarmed a customer whose card was always fine."
        ),
        codes=("91", "96", "issuer_unavailable", "issuer_down"),
        counts_against_network_cap=False,
    ),
    RootCause.EXPIRED_CARD: TaxonomyEntry(
        cause=RootCause.EXPIRED_CARD,
        label="Expired / invalid card",
        signal="Code 54/14",
        recovery_action='Card-updater lookup + "update card" prompt',
        retry_answer="No blind retry",
        retry_stance=RetryStance.NO_BLIND_RETRY,
        primary_action=RecoveryAction.CARD_UPDATER,
        companion_action=RecoveryAction.CUSTOMER_NUDGE,
        max_attempts=2,
        cooldown_hours=24.0,
        max_lifetime_days=30,
        requires_repair=True,
        terminal=False,
        network_penalty_weight=0.35,
        severity="warning",
        color="violet",
        description=(
            "The stored credential is dead. The customer relationship is perfectly "
            "healthy -- the token pointing at their card is not."
        ),
        why_naive_retry_fails=(
            "The same expired number cannot start working because you asked it three "
            "more times. Every blind retry is a guaranteed decline that counts against "
            "the merchant's ratio. A network card-updater lookup repairs the credential "
            "silently and the charge clears on the first attempt after repair."
        ),
        codes=("54", "14", "expired_card", "invalid_card"),
    ),
    RootCause.AUTH_3DS_FAILURE: TaxonomyEntry(
        cause=RootCause.AUTH_3DS_FAILURE,
        label="3DS / OTP failure",
        signal="Authentication timeout",
        recovery_action="Trigger re-authentication flow",
        retry_answer="No",
        retry_stance=RetryStance.NEVER,
        primary_action=RecoveryAction.CUSTOMER_NUDGE,
        companion_action=None,
        max_attempts=2,
        cooldown_hours=6.0,
        max_lifetime_days=14,
        requires_repair=True,
        terminal=False,
        network_penalty_weight=0.10,
        severity="warning",
        color="indigo",
        description=(
            "The money was never authorised because the customer never finished the "
            "challenge -- OTP not entered, bank page timed out, app switch lost the "
            "session. Extremely common on Indian recurring rails."
        ),
        why_naive_retry_fails=(
            "A server-side retry cannot complete a challenge that requires a human to "
            "type a code. The only thing that recovers this is putting a live "
            "authentication link back in front of the customer."
        ),
        codes=("3ds_timeout", "authentication_failed", "otp_timeout", "1A"),
    ),
    RootCause.FRAUD_BLOCK: TaxonomyEntry(
        cause=RootCause.FRAUD_BLOCK,
        label="Fraud / risk block",
        signal="Code 59, risk-filter flag",
        recovery_action="Route to human review",
        retry_answer="No",
        retry_stance=RetryStance.NEVER,
        primary_action=RecoveryAction.HUMAN_REVIEW,
        companion_action=None,
        max_attempts=0,
        cooldown_hours=0.0,
        max_lifetime_days=0,
        requires_repair=True,
        terminal=False,
        network_penalty_weight=0.85,
        severity="critical",
        color="rose",
        description=(
            "A risk filter -- the issuer's, the gateway's, or ours -- stopped this "
            "charge. A meaningful share of these are false positives on entirely "
            "legitimate customers, which is exactly why a human, not a retry loop, "
            "has to look at them."
        ),
        why_naive_retry_fails=(
            "Hammering a risk-blocked transaction is the single fastest way to "
            "escalate a soft filter into a permanent block on the merchant account. "
            "The upside is a false positive worth one recovery; the downside is the "
            "processing relationship."
        ),
        codes=("59", "fraud_suspected", "risk_block", "R01"),
    ),
    RootCause.HARD_DECLINE: TaxonomyEntry(
        cause=RootCause.HARD_DECLINE,
        label="Hard decline",
        signal="Stolen / closed / do-not-honour (04/07/41/43)",
        recovery_action="Stop immediately, flag account",
        retry_answer="Hard stop",
        retry_stance=RetryStance.HARD_STOP,
        primary_action=RecoveryAction.HUMAN_REVIEW,
        companion_action=None,
        max_attempts=0,
        cooldown_hours=0.0,
        max_lifetime_days=0,
        requires_repair=False,
        terminal=True,
        network_penalty_weight=1.0,
        severity="critical",
        color="red",
        description=(
            "Pick up card, stolen card, closed account, do-not-honour. The issuer is "
            "not asking us to try later; it is telling us to stop."
        ),
        why_naive_retry_fails=(
            "This is the case that makes blanket retry indefensible. Retrying a "
            "reported-stolen card is a compliance event, not a growth tactic -- it "
            "burns interchange fees on a zero-probability charge and pushes the "
            "merchant toward a network monitoring programme."
        ),
        codes=("04", "07", "41", "43", "stolen_card", "do_not_honour", "pickup_card"),
    ),
    RootCause.GATEWAY_ERROR: TaxonomyEntry(
        cause=RootCause.GATEWAY_ERROR,
        label="Gateway / processing error",
        signal="HTTP 5xx from processor",
        recovery_action="Immediate retry, alternate route if available",
        retry_answer="Yes, immediate",
        retry_stance=RetryStance.IMMEDIATE,
        primary_action=RecoveryAction.SMART_RETRY,
        companion_action=None,
        max_attempts=4,
        cooldown_hours=0.1,
        max_lifetime_days=1,
        requires_repair=False,
        terminal=False,
        network_penalty_weight=0.0,
        severity="info",
        color="teal",
        description=(
            "Our own side of the rail failed -- a 5xx, a timeout, a dropped webhook. "
            "The customer did nothing and the issuer never saw a decision."
        ),
        why_naive_retry_fails=(
            "Not retrying fast enough is the failure mode here, and it is pure "
            "leakage: near-certain revenue abandoned because a queue hiccuped. "
            "Routing the retry through an alternate processor recovers almost all of "
            "it within minutes."
        ),
        codes=("gateway_error", "http_500", "http_502", "http_503", "http_504", "96T"),
        counts_against_network_cap=False,
    ),
    RootCause.LAPSED_MANDATE: TaxonomyEntry(
        cause=RootCause.LAPSED_MANDATE,
        label="Lapsed mandate (recurring)",
        signal="Mandate expired or revoked",
        recovery_action="Trigger re-mandate registration flow",
        retry_answer="No blind retry",
        retry_stance=RetryStance.NO_BLIND_RETRY,
        primary_action=RecoveryAction.CUSTOMER_NUDGE,
        companion_action=None,
        max_attempts=1,
        cooldown_hours=24.0,
        max_lifetime_days=30,
        requires_repair=True,
        terminal=False,
        network_penalty_weight=0.20,
        severity="warning",
        color="fuchsia",
        description=(
            "The standing authorisation itself is gone -- a UPI Autopay mandate "
            "revoked in the payer app, an eNACH debit authority expired, a card "
            "subscription de-registered. There is no longer any legal instruction to "
            "debit this customer."
        ),
        why_naive_retry_fails=(
            "Debiting without a live mandate is not a soft failure, it is an "
            "unauthorised debit attempt. No amount of retrying creates consent. Only "
            "a fresh registration flow does."
        ),
        codes=(
            "mandate_revoked", "mandate_expired", "subscription_cancelled",
            "BAD_REQUEST_PAYMENT_UPI_MANDATE_REVOKED", "enach_expired",
        ),
    ),
    RootCause.UNKNOWN: TaxonomyEntry(
        cause=RootCause.UNKNOWN,
        label="Unclassified",
        signal="No tier reached the confidence floor",
        recovery_action="Route to human review, never guess",
        retry_answer="No",
        retry_stance=RetryStance.NEVER,
        primary_action=RecoveryAction.HUMAN_REVIEW,
        companion_action=None,
        max_attempts=0,
        cooldown_hours=0.0,
        max_lifetime_days=0,
        requires_repair=True,
        terminal=False,
        network_penalty_weight=0.5,
        severity="critical",
        color="slate",
        description=(
            "Neither the rules engine nor the reasoning tier could identify this "
            "failure with enough confidence to act. Abstaining is a feature: an "
            "honest 'I don't know' routed to a human beats a confident wrong action."
        ),
        why_naive_retry_fails=(
            "A naive system has no concept of not knowing, so it applies the same "
            "retry schedule to failures it has never seen before -- which is how "
            "novel decline patterns turn into silent, repeated compliance risk."
        ),
        codes=(),
    ),
}


# The four bounded lanes, in the order the architecture diagram draws them.
ACTION_LANES: tuple[RecoveryAction, ...] = (
    RecoveryAction.SMART_RETRY,
    RecoveryAction.CARD_UPDATER,
    RecoveryAction.CUSTOMER_NUDGE,
    RecoveryAction.HUMAN_REVIEW,
)

ACTION_LABELS: dict[RecoveryAction, str] = {
    RecoveryAction.SMART_RETRY: "Smart retry",
    RecoveryAction.CARD_UPDATER: "Card updater",
    RecoveryAction.CUSTOMER_NUDGE: "Customer nudge",
    RecoveryAction.HUMAN_REVIEW: "Human review",
    RecoveryAction.SUPPRESS: "Suppressed by guardrail",
}


# ---------------------------------------------------------------------------
# Decline-code registry
# ---------------------------------------------------------------------------
# The unambiguous fast path. "Rules handle the majority of decline codes, which are
# unambiguous; the LLM earns its place on the messy remainder."
#
# Keys are normalised (lower-case, no spaces/punctuation) so the rules engine can look
# up a code extracted from any gateway's string shape.

DECLINE_CODES: dict[str, RootCause] = {
    # --- ISO-8583 response codes ------------------------------------------
    "51": RootCause.INSUFFICIENT_FUNDS,
    "61": RootCause.INSUFFICIENT_FUNDS,
    "65": RootCause.INSUFFICIENT_FUNDS,      # activity limit exceeded
    "13": RootCause.INSUFFICIENT_FUNDS,      # invalid amount, in practice limit-ish
    "91": RootCause.ISSUER_UNAVAILABLE,
    "96": RootCause.ISSUER_UNAVAILABLE,
    "92": RootCause.ISSUER_UNAVAILABLE,      # no routing to issuer
    "98": RootCause.ISSUER_UNAVAILABLE,
    "54": RootCause.EXPIRED_CARD,
    "14": RootCause.EXPIRED_CARD,
    "15": RootCause.EXPIRED_CARD,            # no such issuer
    "59": RootCause.FRAUD_BLOCK,
    "34": RootCause.FRAUD_BLOCK,             # suspected fraud
    "63": RootCause.FRAUD_BLOCK,             # security violation
    "04": RootCause.HARD_DECLINE,            # pick up card
    "07": RootCause.HARD_DECLINE,            # pick up card, special condition
    "41": RootCause.HARD_DECLINE,            # lost card
    "43": RootCause.HARD_DECLINE,            # stolen card
    "05": RootCause.HARD_DECLINE,            # do not honour
    "78": RootCause.HARD_DECLINE,            # blocked / never activated
    "1a": RootCause.AUTH_3DS_FAILURE,        # additional customer auth required

    # --- HTTP-shaped processor failures -----------------------------------
    "500": RootCause.GATEWAY_ERROR,
    "502": RootCause.GATEWAY_ERROR,
    "503": RootCause.GATEWAY_ERROR,
    "504": RootCause.GATEWAY_ERROR,
    "http500": RootCause.GATEWAY_ERROR,
    "http502": RootCause.GATEWAY_ERROR,
    "http503": RootCause.GATEWAY_ERROR,
    "http504": RootCause.GATEWAY_ERROR,

    # --- Razorpay-style symbolic codes ------------------------------------
    # Modelled on Razorpay's published error/reason vocabulary, which is what makes
    # the synthetic stream read as credible to a payments audience.
    "bad_request_payment_upi_mandate_revoked": RootCause.LAPSED_MANDATE,
    "bad_request_payment_mandate_expired": RootCause.LAPSED_MANDATE,
    "bad_request_card_expired": RootCause.EXPIRED_CARD,
    "bad_request_payment_failed": RootCause.UNKNOWN,   # deliberately ambiguous
    "gateway_error": RootCause.GATEWAY_ERROR,
    "payment_authentication_failed": RootCause.AUTH_3DS_FAILURE,
    "payment_declined_by_bank": RootCause.UNKNOWN,     # deliberately ambiguous
    "insufficient_balance": RootCause.INSUFFICIENT_FUNDS,
    "card_expired": RootCause.EXPIRED_CARD,
    "mandate_revoked": RootCause.LAPSED_MANDATE,
    "mandate_expired": RootCause.LAPSED_MANDATE,
    "enach_expired": RootCause.LAPSED_MANDATE,
    "subscription_cancelled": RootCause.LAPSED_MANDATE,

    # --- Stripe-style symbolic codes --------------------------------------
    "insufficient_funds": RootCause.INSUFFICIENT_FUNDS,
    "expired_card": RootCause.EXPIRED_CARD,
    "incorrect_number": RootCause.EXPIRED_CARD,
    "invalid_card": RootCause.EXPIRED_CARD,
    "issuer_not_available": RootCause.ISSUER_UNAVAILABLE,
    "processing_error": RootCause.GATEWAY_ERROR,
    "try_again_later": RootCause.ISSUER_UNAVAILABLE,
    "fraudulent": RootCause.FRAUD_BLOCK,
    "stolen_card": RootCause.HARD_DECLINE,
    "lost_card": RootCause.HARD_DECLINE,
    "pickup_card": RootCause.HARD_DECLINE,
    "do_not_honour": RootCause.HARD_DECLINE,
    "do_not_honor": RootCause.HARD_DECLINE,
    "card_not_supported": RootCause.HARD_DECLINE,
    "authentication_required": RootCause.AUTH_3DS_FAILURE,
    "authentication_failed": RootCause.AUTH_3DS_FAILURE,
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def entry(cause: RootCause | str) -> TaxonomyEntry:
    """Fetch the taxonomy record for a cause. Accepts the enum or its string value."""
    if isinstance(cause, str):
        try:
            cause = RootCause(cause)
        except ValueError:
            cause = RootCause.UNKNOWN
    return TAXONOMY[cause]


def all_causes(include_unknown: bool = False) -> list[RootCause]:
    """The eight real causes, in the plan's table order."""
    causes = [c for c in RootCause if c is not RootCause.UNKNOWN]
    return causes + [RootCause.UNKNOWN] if include_unknown else causes


def normalise_token(raw: str) -> str:
    """Collapse a gateway's code/message fragment into a registry lookup key.

    Gateways disagree about case, separators and padding for the same code, so
    ``ERR_51``, ``err-51`` and ``51`` all have to land on the same key.
    """
    keep = []
    for ch in raw.strip().lower():
        if ch.isalnum():
            keep.append(ch)
        elif keep and keep[-1] != "_":
            keep.append("_")
    return "".join(keep).strip("_")


def lookup_code(raw_code: str | None) -> RootCause | None:
    """Resolve a raw gateway code to a root cause, or None if it is not in the
    registry. Returning None is meaningful -- it is what escalates to the next tier."""
    if not raw_code:
        return None
    token = normalise_token(raw_code)
    if not token:
        return None
    if token in DECLINE_CODES:
        cause = DECLINE_CODES[token]
        return None if cause is RootCause.UNKNOWN else cause
    # Numeric codes are often zero-padded inconsistently ("4" vs "04").
    if token.isdigit():
        for variant in (token.lstrip("0") or "0", token.zfill(2)):
            if variant in DECLINE_CODES:
                cause = DECLINE_CODES[variant]
                return None if cause is RootCause.UNKNOWN else cause
    return None


def is_ambiguous_code(raw_code: str | None) -> bool:
    """True for codes that are *registered* but deliberately non-diagnostic --
    the messy remainder the reasoning tier exists to handle."""
    if not raw_code:
        return False
    return DECLINE_CODES.get(normalise_token(raw_code)) is RootCause.UNKNOWN


def causes_for_action(action: RecoveryAction) -> list[RootCause]:
    """Which causes route to a given lane. Used by the dashboard's Sankey view."""
    out = []
    for cause, e in TAXONOMY.items():
        if e.primary_action is action or e.companion_action is action:
            out.append(cause)
    return out


def taxonomy_table() -> list[dict]:
    """Serialise the taxonomy for the frontend's Root-cause matrix screen.

    The dashboard renders the plan's table verbatim from this, which means the UI can
    never drift from the policy the engine actually enforces.
    """
    rows = []
    for cause in all_causes(include_unknown=True):
        e = TAXONOMY[cause]
        rows.append(
            {
                "cause": e.cause.value,
                "label": e.label,
                "signal": e.signal,
                "recovery_action": e.recovery_action,
                "retry_answer": e.retry_answer,
                "retry_stance": e.retry_stance.value,
                "primary_action": e.primary_action.value,
                "companion_action": e.companion_action.value if e.companion_action else None,
                "max_attempts": e.max_attempts,
                "cooldown_hours": e.cooldown_hours,
                "max_lifetime_days": e.max_lifetime_days,
                "requires_repair": e.requires_repair,
                "terminal": e.terminal,
                "network_penalty_weight": e.network_penalty_weight,
                "severity": e.severity,
                "color": e.color,
                "description": e.description,
                "why_naive_retry_fails": e.why_naive_retry_fails,
                "codes": list(e.codes),
            }
        )
    return rows


def code_registry_table() -> list[dict]:
    """Serialise the decline-code registry, grouped by cause, for the UI."""
    grouped: dict[str, list[str]] = {}
    for code, cause in DECLINE_CODES.items():
        grouped.setdefault(cause.value, []).append(code)
    return [
        {"cause": cause, "codes": sorted(codes), "count": len(codes)}
        for cause, codes in sorted(grouped.items())
    ]


def validate_taxonomy() -> list[str]:
    """Self-check invoked by the test suite and at app startup.

    A taxonomy that silently disagrees with itself would undermine every number on the
    dashboard, so the failure is loud rather than subtle.
    """
    problems: list[str] = []

    for cause in RootCause:
        if cause not in TAXONOMY:
            problems.append(f"taxonomy missing entry for {cause.value}")

    for cause, e in TAXONOMY.items():
        if e.cause is not cause:
            problems.append(f"{cause.value}: entry.cause mismatch ({e.cause.value})")
        if e.primary_action is RecoveryAction.SUPPRESS:
            problems.append(f"{cause.value}: SUPPRESS is not a dispatchable lane")
        if e.terminal and e.max_attempts != 0:
            problems.append(f"{cause.value}: terminal cause must have max_attempts=0")
        if e.retry_stance is RetryStance.HARD_STOP and e.max_attempts != 0:
            problems.append(f"{cause.value}: hard stop must have max_attempts=0")
        if e.retry_stance in (RetryStance.SCHEDULED, RetryStance.IMMEDIATE) and e.max_attempts < 1:
            problems.append(f"{cause.value}: retryable cause needs max_attempts>=1")
        if not 0.0 <= e.network_penalty_weight <= 1.0:
            problems.append(f"{cause.value}: network_penalty_weight out of range")
        if e.companion_action is e.primary_action:
            problems.append(f"{cause.value}: companion duplicates primary action")

    for code, cause in DECLINE_CODES.items():
        if normalise_token(code) != code:
            problems.append(f"decline code {code!r} is not stored normalised")
        if cause not in TAXONOMY:
            problems.append(f"decline code {code!r} maps to unknown cause")

    return problems


def assert_taxonomy_valid() -> None:
    problems = validate_taxonomy()
    if problems:
        raise AssertionError("taxonomy invariants violated:\n  - " + "\n  - ".join(problems))


def summarise_for_prompt(causes: Iterable[RootCause] | None = None) -> str:
    """Render the taxonomy as a compact block for the LLM system prompt.

    The model classifies *into this fixed set* rather than free-associating, which is
    what keeps its output parseable and its labels comparable to the rules tier.
    """
    lines = []
    for cause in causes or all_causes():
        e = TAXONOMY[cause]
        lines.append(
            f"- {e.cause.value}: {e.label}. Signal: {e.signal}. "
            f"Action taken: {e.recovery_action}. Retry policy: {e.retry_answer}."
        )
    return "\n".join(lines)
