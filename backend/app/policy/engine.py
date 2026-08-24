"""
The policy engine: diagnosis in, one bounded action out.

    "The agent should not have a general 'do something' capability. It should have four
     specific ones... The point is that the action is chosen because of the diagnosis, not
     because a timer went off."

This module is the join between the taxonomy and the executor. It is deliberately dull:
a diagnosis maps to a lane, a lane maps to a timing strategy, and the guardrail layer
gets the final word. There is no model call anywhere in this file, and no branch that
can produce an action outside the four lanes.

Three things it refuses to do, each of which a shallower build would do by default:

* **It will not act on an unclassified failure.** `UNKNOWN` routes to human review. An
  agent that guesses when it does not know is worse than no agent, because the wrong
  automated action lands on a real customer's card.
* **It will not ask the network for a credential the network does not have.** If the BIN
  is not enrolled with the account updater, the card-updater lane degrades to asking the
  customer, and the decision record says why.
* **It will not contact anyone about a failure they cannot act on.** Gateway errors and
  terminal declines produce no customer message at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import (
    ActionPlan,
    Arm,
    AttemptKind,
    Classification,
    Customer,
    Decision,
    FailureEvent,
    GuardrailCheck,
    GuardrailVerdict,
    MethodType,
    Payment,
    PaymentMethod,
)
from ..taxonomy import TAXONOMY, RecoveryAction, RootCause
from .comms import compose_nudge, preferred_channel
from .guardrails import GuardrailContext, GuardrailEngine, GuardrailOutcome
from .timing import baseline_retry_time, parse_iso, timing_for_cause, to_iso


# ---------------------------------------------------------------------------
# Display priors
# ---------------------------------------------------------------------------
# `expected_success_rate` is shown in the decision explorer as an estimate and is
# labelled as one. It never influences whether an action is taken -- the actual result
# comes from the shared outcome model, identically for both arms. Keeping the estimate
# separate from the outcome is what stops the comparison from being circular.

_PRIOR: dict[RootCause, float] = {
    RootCause.INSUFFICIENT_FUNDS: 0.46,
    RootCause.ISSUER_UNAVAILABLE: 0.78,
    RootCause.GATEWAY_ERROR: 0.86,
    RootCause.EXPIRED_CARD: 0.52,
    RootCause.AUTH_3DS_FAILURE: 0.41,
    RootCause.LAPSED_MANDATE: 0.34,
    RootCause.FRAUD_BLOCK: 0.11,
    RootCause.HARD_DECLINE: 0.04,
    RootCause.UNKNOWN: 0.0,
}

_KIND_FOR_STRATEGY: dict[str, AttemptKind] = {
    "liquidity_aware": AttemptKind.TIMED_RETRY,
    "exponential_backoff": AttemptKind.BACKOFF_RETRY,
    "immediate_alternate_route": AttemptKind.ALTERNATE_ROUTE,
    "post_repair": AttemptKind.POST_REPAIR_RETRY,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Action selection
# ---------------------------------------------------------------------------


def plan_action(
    classification: Classification,
    *,
    failed_at: datetime | None = None,
    customer: Customer | None = None,
    payment: Payment | None = None,
    method: PaymentMethod | None = None,
    attempt_index: int = 0,
    alternate_route_available: bool = True,
    credential_lookup_exhausted: bool = False,
) -> ActionPlan:
    """Map a diagnosis onto exactly one bounded action, with its timing and rationale.

    Callable with nothing but a `Classification`, which is what lets the dashboard's
    ad-hoc panel show the full decision for a hand-typed decline string.
    """
    cause = classification.root_cause
    entry = TAXONOMY[cause]
    reference = failed_at or _now()

    # --- unclassified: never act ----------------------------------------
    if cause is RootCause.UNKNOWN:
        return ActionPlan(
            action=RecoveryAction.HUMAN_REVIEW,
            kind=AttemptKind.HUMAN_REVIEW,
            scheduled_at=to_iso(reference),
            reason=(
                f"No diagnosis reached (confidence {classification.confidence:.0%}, below "
                f"the action threshold). Routed to human review. Acting on an "
                f"unclassified failure means guessing with a real customer's card, and "
                f"the correct answer to 'we do not know' is a person, not a retry."
            ),
            timing_strategy="immediate_review",
            expected_success_rate=0.0,
            requires_human_signoff=True,
        )

    # --- terminal: stop, and say why -------------------------------------
    # Gated on `terminal`, not on the retry stance. Several causes are marked "never
    # retry" while still being perfectly recoverable through a repair -- a failed 3DS
    # challenge cannot be retried server-side, but it is fixed by putting the auth link
    # back in front of the customer. Conflating "do not retry" with "give up" is the
    # single most common way a recovery system leaves money on the table.
    if entry.terminal:
        return ActionPlan(
            action=RecoveryAction.HUMAN_REVIEW,
            kind=AttemptKind.HUMAN_REVIEW,
            scheduled_at=to_iso(reference),
            reason=(
                f"{entry.label}: {entry.retry_answer} {entry.why_naive_retry_fails} "
                f"Flagged for a human with the diagnosis attached, and no charge attempt "
                f"is made."
            ),
            timing_strategy="hard_stop",
            expected_success_rate=_PRIOR[cause],
            requires_human_signoff=True,
        )

    primary = entry.primary_action
    companion = entry.companion_action

    # --- card updater is only real where the network supports it ---------
    downgrade_note = ""
    if primary is RecoveryAction.CARD_UPDATER:
        if method is not None and method.type is not MethodType.CARD:
            primary, companion = RecoveryAction.CUSTOMER_NUDGE, None
            downgrade_note = (
                " Account-updater services only cover card rails, so on this instrument "
                "the only route to a fresh credential is the customer."
            )
        elif method is not None and not method.card_updater_enrolled:
            primary, companion = RecoveryAction.CUSTOMER_NUDGE, None
            downgrade_note = (
                f" This BIN ({method.issuer}) is not enrolled with the network's account "
                f"updater, so no lookup can return a new credential. Downgraded to asking "
                f"the customer rather than burning an attempt on a token we know is dead."
            )
        elif credential_lookup_exhausted:
            primary, companion = RecoveryAction.CUSTOMER_NUDGE, None
            downgrade_note = (
                " The account updater has already been queried for this card and holds no "
                "newer credential. Asking it again returns the same answer, so the only "
                "remaining route is the customer."
            )

    # --- timing -----------------------------------------------------------
    when, lift, timing_why, strategy = timing_for_cause(
        cause, reference, customer, attempt_index,
        alternate_route_available=alternate_route_available,
    )
    delay_hours = max(0.0, (when - reference).total_seconds() / 3600)

    # --- build the plan per lane -----------------------------------------
    if primary is RecoveryAction.SMART_RETRY:
        kind = _KIND_FOR_STRATEGY.get(strategy, AttemptKind.TIMED_RETRY)
        route = "alternate_processor" if strategy == "immediate_alternate_route" else None
        plan = ActionPlan(
            action=RecoveryAction.SMART_RETRY,
            kind=kind,
            scheduled_at=to_iso(when),
            reason=f"{entry.label}: {entry.retry_answer} {timing_why}",
            delay_hours=delay_hours,
            timing_strategy=strategy,
            alternate_route=route,
            expected_success_rate=min(0.95, _PRIOR[cause] * min(1.35, 0.75 + lift / 10)),
        )

    elif primary is RecoveryAction.CARD_UPDATER:
        plan = ActionPlan(
            action=RecoveryAction.CARD_UPDATER,
            kind=AttemptKind.CARD_UPDATER_LOOKUP,
            scheduled_at=to_iso(reference),
            reason=(
                f"{entry.label}: {entry.retry_answer} Querying the network's account "
                f"updater for a replacement credential first; the retry is gated on that "
                f"lookup returning one. {timing_why}"
            ),
            delay_hours=0.0,
            timing_strategy="post_repair",
            expected_success_rate=_PRIOR[cause],
        )
        plan.companion_scheduled_at = to_iso(when)

    elif primary is RecoveryAction.CUSTOMER_NUDGE:
        kind = {
            RootCause.AUTH_3DS_FAILURE: AttemptKind.REAUTH_LINK,
            RootCause.LAPSED_MANDATE: AttemptKind.REMANDATE_LINK,
        }.get(cause, AttemptKind.NUDGE)
        plan = ActionPlan(
            action=RecoveryAction.CUSTOMER_NUDGE,
            kind=kind,
            scheduled_at=to_iso(when),
            reason=f"{entry.label}: {entry.retry_answer} {timing_why}{downgrade_note}",
            delay_hours=delay_hours,
            timing_strategy=strategy,
            expected_success_rate=_PRIOR[cause],
        )

    else:  # the taxonomy routes this cause straight to a person
        plan = ActionPlan(
            action=RecoveryAction.HUMAN_REVIEW,
            kind=AttemptKind.HUMAN_REVIEW,
            scheduled_at=to_iso(reference),
            reason=(
                f"{entry.label}: {entry.retry_answer} {entry.why_naive_retry_fails}"
                f"{downgrade_note}"
            ),
            timing_strategy="immediate_review",
            expected_success_rate=_PRIOR[cause],
            requires_human_signoff=True,
        )

    # --- companion action -------------------------------------------------
    if companion is RecoveryAction.CUSTOMER_NUDGE and customer is not None:
        plan.companion_action = RecoveryAction.CUSTOMER_NUDGE
        plan.companion_kind = AttemptKind.NUDGE
        plan.companion_scheduled_at = plan.companion_scheduled_at or to_iso(reference)

    # --- message copy -----------------------------------------------------
    if customer is not None and payment is not None and (
        plan.action is RecoveryAction.CUSTOMER_NUDGE
        or plan.companion_action is RecoveryAction.CUSTOMER_NUDGE
    ):
        nudge = compose_nudge(
            cause, customer, payment, method,
            retry_when_human=_human_when(when) if plan.action is RecoveryAction.SMART_RETRY else None,
        )
        if nudge is not None:
            plan.channel = nudge.channel
            plan.message = nudge.render()
        else:
            # No consented channel, or nothing worth saying. Drop the companion rather
            # than send a generic "payment failed" note.
            if plan.action is RecoveryAction.CUSTOMER_NUDGE:
                plan.action = RecoveryAction.HUMAN_REVIEW
                plan.kind = AttemptKind.HUMAN_REVIEW
                plan.requires_human_signoff = True
                plan.reason += (
                    " No consented contact channel is available, so the only remaining "
                    "route is a human deciding how to reach this customer."
                )
            plan.companion_action = None
            plan.companion_kind = None
            plan.companion_scheduled_at = None
    elif customer is not None and plan.action is RecoveryAction.CUSTOMER_NUDGE:
        plan.channel = preferred_channel(cause, customer)

    return plan


def _human_when(when: datetime) -> str:
    return when.strftime("%d %b at %H:%M")


# ---------------------------------------------------------------------------
# The naive comparator
# ---------------------------------------------------------------------------


def baseline_plan(
    event: FailureEvent,
    payment: Payment,
    customer: Customer,
    method: PaymentMethod,
    attempt_index: int,
) -> ActionPlan:
    """What the plan predicts most entries will ship: retry on a timer, email every time.

    Implemented faithfully rather than as a straw man. It gets the same attempt budget,
    the same outcome model, and the same recovery horizon. What it does not get is a
    diagnosis, so every failure looks identical to it -- which is precisely the thing
    being measured.
    """
    failed_at = parse_iso(event.occurred_at)
    when = baseline_retry_time(failed_at, attempt_index)
    interval = (attempt_index + 1) * 24

    plan = ActionPlan(
        action=RecoveryAction.SMART_RETRY,
        kind=AttemptKind.BLIND_RETRY,
        scheduled_at=to_iso(when),
        reason=(
            f"Fixed-schedule retry #{attempt_index + 1}, {interval}h after the failure. "
            f"No root cause considered -- the decline string was not examined beyond "
            f"'this payment failed'."
        ),
        delay_hours=float(interval),
        timing_strategy="fixed_24h",
        expected_success_rate=0.0,
    )

    from ..config import settings
    if settings.baseline.sends_email_each_attempt:
        plan.companion_action = RecoveryAction.CUSTOMER_NUDGE
        plan.companion_kind = AttemptKind.NUDGE
        plan.companion_scheduled_at = to_iso(when)
        plan.channel = "email"
        plan.message = (
            "Your payment failed\n\n"
            f"We were unable to process your payment of {payment.amount_minor / 100:.2f}. "
            "Please update your payment details to avoid interruption to your service.\n\n"
            "[Retry payment]"
        )
    return plan


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class DecisionOutcome:
    """A completed decision plus the guardrail trace that shaped it."""

    decision: Decision
    guardrails: GuardrailOutcome
    plan: ActionPlan

    @property
    def final_action(self) -> RecoveryAction:
        return self.guardrails.final_action


class PolicyEngine:
    """Proposes an action, then submits it to the guardrail layer for clearance."""

    def __init__(self, guardrails: GuardrailEngine | None = None) -> None:
        self.guardrails = guardrails or GuardrailEngine()
        # A second, isolated engine used only to observe what an unguarded loop would
        # have done. Kept separate so shadow evaluations never pollute the live counters.
        self._shadow = GuardrailEngine(self.guardrails.policy)
        self.baseline_violations: dict[str, int] = {}

    def reset(self) -> None:
        self.guardrails.reset()
        self._shadow.reset()
        self.baseline_violations = {}

    def decide(
        self,
        *,
        run_id: str,
        arm: Arm,
        event: FailureEvent,
        classification: Classification,
        payment: Payment,
        customer: Customer,
        method: PaymentMethod,
        attempt_index: int,
        total_prior_failures: int,
        sequence_no: int,
        now: datetime | None = None,
        credential_lookup_exhausted: bool = False,
    ) -> DecisionOutcome:
        reference = now or parse_iso(event.occurred_at)

        if arm is Arm.BASELINE:
            proposed = baseline_plan(event, payment, customer, method, attempt_index)
        else:
            proposed = plan_action(
                classification,
                failed_at=reference,
                customer=customer,
                payment=payment,
                method=method,
                attempt_index=attempt_index,
                credential_lookup_exhausted=credential_lookup_exhausted,
            )

        ctx = GuardrailContext(
            now=reference,
            arm=arm,
            event=event,
            payment=payment,
            customer=customer,
            method=method,
            root_cause=classification.root_cause,
            confidence=classification.confidence,
            total_prior_failures=total_prior_failures,
        )

        if arm is Arm.BASELINE:
            outcome = self._baseline_verdict(ctx, proposed)
        else:
            outcome = self.guardrails.evaluate(ctx, proposed)

        decision = Decision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            event_id=event.id,
            payment_id=payment.id,
            customer_id=customer.id,
            arm=arm,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            created_at=to_iso(reference),
            classification=classification,
            proposed=outcome.plan,
            final_action=outcome.final_action,
            guardrails=outcome.checks,
            blocked=outcome.blocked,
            block_reason=outcome.block_reason,
            modified=outcome.modified,
            escalated=outcome.escalated,
            sequence_no=sequence_no,
        )
        return DecisionOutcome(decision=decision, guardrails=outcome, plan=outcome.plan)

    def _baseline_verdict(
        self, ctx: GuardrailContext, plan: ActionPlan
    ) -> GuardrailOutcome:
        """The baseline arm has no guardrail layer -- that is what makes it naive.

        Rather than silently letting it do whatever it likes, the same checks are still
        *evaluated*, in an isolated shadow engine, so the dashboard can report exactly
        which controls an unguarded retry loop breaches. Those violations are counted and
        attributed, not asserted -- each one is traceable to a specific event.
        """
        evaluated = self._shadow.evaluate(ctx, plan)

        would_violate = [
            c for c in evaluated.checks
            if c.verdict is GuardrailVerdict.BLOCK and c.category in ("hard_stop", "comms")
        ]
        for c in would_violate:
            self.baseline_violations[c.id] = self.baseline_violations.get(c.id, 0) + 1

        # Its only real limit is its own fixed attempt budget.
        from ..config import settings
        exhausted = ctx.event.attempt_no > settings.baseline.max_attempts

        detail = (
            f"The naive arm has no guardrail layer by construction. Running the same "
            f"checks in shadow mode: it breaches {len(would_violate)} control(s) here"
            + (f" -- {', '.join(c.name for c in would_violate)}." if would_violate
               else ", none on this event.")
        )

        return GuardrailOutcome(
            final_action=(
                RecoveryAction.SUPPRESS if exhausted else RecoveryAction.SMART_RETRY
            ),
            plan=plan,
            checks=[
                GuardrailCheck(
                    id="baseline.no_guardrails",
                    name="Guardrail layer",
                    verdict=GuardrailVerdict.NA,
                    detail=detail,
                    category="baseline",
                    severity="warning" if would_violate else "info",
                )
            ] + would_violate,
            blocked=exhausted,
            block_reason=(
                f"Fixed attempt budget of {settings.baseline.max_attempts} exhausted."
                if exhausted else None
            ),
            modified=False,
            escalated=False,
            requires_human_signoff=False,
            shadow_breaches=[c.id for c in would_violate],
        )

    def commit_baseline_side_effects(
        self, ctx: GuardrailContext, when: datetime, *, sent_message: bool
    ) -> None:
        """Keep the shadow counters advancing so frequency breaches accumulate honestly."""
        self._shadow.commit_attempt(ctx, when, is_charge=True)
        if sent_message:
            self._shadow.commit_nudge(ctx, when)

    def shadow_violations(self, ctx: GuardrailContext, plan: ActionPlan) -> list[str]:
        """Which controls a given plan would breach, without recording anything."""
        probe = GuardrailEngine(self.guardrails.policy)
        result = probe.evaluate(ctx, plan)
        return [c.name for c in result.checks if c.verdict is GuardrailVerdict.BLOCK]


# ---------------------------------------------------------------------------
# Published policy, for the dashboard
# ---------------------------------------------------------------------------


def policy_matrix() -> list[dict]:
    """The full cause → action → timing → caps table.

    The plan calls the taxonomy "the real intellectual property"; publishing the derived
    policy as a table in the product -- rather than describing it on a slide -- is what
    makes that claim checkable in ten seconds.
    """
    rows = []
    for cause, entry in TAXONOMY.items():
        strategy = {
            RootCause.INSUFFICIENT_FUNDS: "Liquidity-aware (payday + 1, 11:00 local)",
            RootCause.ISSUER_UNAVAILABLE: "Exponential backoff (12m / 40m / 2h / 6h)",
            RootCause.GATEWAY_ERROR: "Immediate re-route (+3m, alternate processor)",
            RootCause.EXPIRED_CARD: "Gated on account-updater result (+20m)",
            RootCause.AUTH_3DS_FAILURE: "Gated on customer completing auth (+2h)",
            RootCause.LAPSED_MANDATE: "Gated on fresh mandate (+6h)",
        }.get(cause, "No retry")
        rows.append({
            "cause": cause.value,
            "label": entry.label,
            "signal": entry.signal,
            "retry_answer": entry.retry_answer,
            "retry_stance": entry.retry_stance.value,
            "primary_action": entry.primary_action.value,
            "companion_action": entry.companion_action.value if entry.companion_action else None,
            "timing_strategy": strategy,
            "max_attempts": entry.max_attempts,
            "cooldown_hours": entry.cooldown_hours,
            "max_lifetime_days": entry.max_lifetime_days,
            "requires_repair": entry.requires_repair,
            "terminal": entry.terminal,
            "network_penalty_weight": entry.network_penalty_weight,
            "severity": entry.severity,
            "color": entry.color,
            "why_naive_retry_fails": entry.why_naive_retry_fails,
            "estimated_recovery_prior": _PRIOR[cause],
            "baseline_behaviour": "Blind retry at 24h intervals + email on every attempt",
        })
    return rows
