"""
The action executor.

One function matters here: `run_case`, which takes a single broken payment and walks it
through simulated time until it is recovered, abandoned, escalated, or the recovery window
closes. Both arms go through this same function; the only difference is which policy
produced the plan.

Two structural rules the executor enforces regardless of what any plan says:

* **It only dispatches actions the guardrail layer cleared.** A `SUPPRESS` or a
  `HUMAN_REVIEW` verdict ends the automated path -- there is no branch that reaches a
  charge attempt without a `PASS` on the caps, the cooldowns, and the hard stops.
* **It records the side effects it commits back into guardrail state.** Caps are only
  real if the counters advance, so every dispatched charge and every sent message is
  written back before the next iteration reads them.

The retry-gated-on-repair behaviour lives here too, and it is where a large part of the
difference between the two arms comes from: when the account updater returns a fresh
credential, the customer is never contacted at all, and the retry that follows is against
a live card instead of a dead one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..classifier import router as default_router
from ..config import settings
from ..models import (
    ActionPlan,
    Arm,
    Attempt,
    AttemptKind,
    Classification,
    Customer,
    Decision,
    FailureEvent,
    Outcome,
    Payment,
    PaymentMethod,
)
from ..policy import GuardrailContext, PolicyEngine
from ..policy.timing import parse_iso, to_iso
from ..synthetic.generator import LatentCase
from ..taxonomy import TAXONOMY, ClassifierTier, RecoveryAction, RootCause
from .outcomes import (
    HUMAN_REVIEW_COST_MINOR,
    RepairState,
    apply_repair,
    resolve_card_updater,
    resolve_charge,
    resolve_customer_action,
    resolve_human_review,
)


MAX_CYCLES = 6  # backstop; the caps and the recovery window bind long before this

#: How long a case sits in the human queue before an analyst returns a verdict. Escalation
#: costs money and time; it does not cost the whole receivable.
ANALYST_SLA_HOURS = 6.0

#: How long a self-serve ask is given to land before the case is reconsidered. Whether a
#: second ask actually goes out is decided by the comms guardrails, not here.
NUDGE_RESPONSE_WINDOW_HOURS = 48.0


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """Everything that happened to one payment in one arm."""

    payment_id: str
    arm: Arm
    amount_minor: int
    currency: str
    true_root_cause: RootCause
    recovered: bool = False
    recovered_amount_minor: int = 0
    final_outcome: Outcome = Outcome.FAILED
    decisions: list[Decision] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    time_to_recovery_hours: float | None = None
    escalated_to_human: bool = False
    recoverable_in_principle: bool = True

    # --- effort and cost, the other half of the scoreboard ------------------
    charge_attempts: int = 0
    customer_touches: int = 0
    suppressed_actions: int = 0
    processing_cost_minor: int = 0
    human_cost_minor: int = 0
    network_penalty_points: float = 0.0
    first_diagnosis: str | None = None
    diagnosis_tier: str | None = None
    diagnosis_correct: bool | None = None

    # --- compliance ---------------------------------------------------------
    #: Controls this arm breached, by check id. The agent's list is empty by construction:
    #: it cannot dispatch what the guardrail layer did not clear. The naive arm's is filled
    #: from shadow-mode evaluation, so a breach is attributed to a specific event rather
    #: than asserted in aggregate.
    breaches: list[str] = field(default_factory=list)

    @property
    def breached_compliance(self) -> bool:
        return bool(self.breaches)

    @property
    def total_cost_minor(self) -> int:
        return self.processing_cost_minor + self.human_cost_minor

    @property
    def net_recovered_minor(self) -> int:
        return self.recovered_amount_minor - self.total_cost_minor

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "arm": self.arm.value,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "true_root_cause": self.true_root_cause.value,
            "recovered": self.recovered,
            "recovered_amount_minor": self.recovered_amount_minor,
            "final_outcome": self.final_outcome.value,
            "time_to_recovery_hours": (
                round(self.time_to_recovery_hours, 2)
                if self.time_to_recovery_hours is not None else None
            ),
            "escalated_to_human": self.escalated_to_human,
            "recoverable_in_principle": self.recoverable_in_principle,
            "charge_attempts": self.charge_attempts,
            "customer_touches": self.customer_touches,
            "suppressed_actions": self.suppressed_actions,
            "processing_cost_minor": self.processing_cost_minor,
            "human_cost_minor": self.human_cost_minor,
            "total_cost_minor": self.total_cost_minor,
            "net_recovered_minor": self.net_recovered_minor,
            "network_penalty_points": round(self.network_penalty_points, 3),
            "first_diagnosis": self.first_diagnosis,
            "diagnosis_tier": self.diagnosis_tier,
            "diagnosis_correct": self.diagnosis_correct,
            "breaches": self.breaches,
            "breached_compliance": self.breached_compliance,
            "attempts": [a.to_dict() for a in self.attempts],
            "decisions": [d.to_dict() for d in self.decisions],
        }


def blind_classification() -> Classification:
    """The naive arm's stand-in for a diagnosis.

    It is not a diagnosis and is not dressed up as one. Recording it explicitly means the
    ledger shows, per event, exactly what the baseline knew when it acted: nothing.
    """
    return Classification(
        root_cause=RootCause.UNKNOWN,
        confidence=0.0,
        tier=ClassifierTier.FALLBACK,
        rationale=(
            "No diagnosis performed. The naive arm treats every failure identically -- "
            "the decline code was never examined beyond the fact that the payment failed."
        ),
        normalized_reason="payment failed",
        signals=[],
        model=None,
    )


def _analyst_classification(cause: RootCause, reason: str) -> Classification:
    """The diagnosis an analyst hands back after working an escalated case.

    Recorded as its own tier rather than laundered into the model's accuracy figure -- the
    classifier abstained, and the scoreboard should keep saying so.
    """
    return Classification(
        root_cause=cause,
        confidence=1.0,
        tier=ClassifierTier.HUMAN,
        rationale=reason,
        normalized_reason=TAXONOMY[cause].label.lower(),
        signals=["human_review"],
        model="analyst",
    )


# ---------------------------------------------------------------------------
# The case loop
# ---------------------------------------------------------------------------


async def run_case(
    *,
    run_id: str,
    arm: Arm,
    event: FailureEvent,
    payment: Payment,
    customer: Customer,
    method: PaymentMethod,
    latent: LatentCase,
    engine: PolicyEngine,
    classifier=None,
    use_llm: bool = False,
    sequence_start: int = 0,
) -> CaseResult:
    """Walk one broken payment to a terminal state."""
    classifier = classifier or default_router
    result = CaseResult(
        payment_id=payment.id,
        arm=arm,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        true_root_cause=latent.true_root_cause,
        recoverable_in_principle=latent.recoverable_in_principle,
    )

    original_failed_at = parse_iso(event.occurred_at)
    deadline = original_failed_at + timedelta(hours=latent.recovery_deadline_hours)
    repairs = RepairState()
    current = event
    clock = original_failed_at
    # Counts failed attempts *we* made. The failure that opened the case was the merchant's
    # own scheduled charge, so the "three failed retries then escalate" rule from the demo
    # script means three of ours, not two plus the one we inherited.
    failed_charges = 0
    retry_ordinal = 0
    seq = sequence_start
    analyst_used = False
    established: Classification | None = None
    lookup_exhausted = False

    for cycle in range(MAX_CYCLES):
        seq += 1

        # --- diagnose -----------------------------------------------------
        if established is not None:
            # A cause an analyst established by hand stands for the rest of the case.
            # Re-running the classifier here would re-ask a question a person has already
            # answered, and on an ambiguous string it would abstain again and buy a second
            # review of the same case.
            classification = established
        elif arm is Arm.AGENT:
            classification = await classifier.classify(
                current, method, customer,
                amount_minor=payment.amount_minor,
                history=[a.to_dict() for a in result.attempts],
                use_llm=use_llm,
                now=clock,
            )
        else:
            classification = blind_classification()

        if result.first_diagnosis is None:
            result.first_diagnosis = classification.root_cause.value
            result.diagnosis_tier = classification.tier.value
            if arm is Arm.AGENT:
                result.diagnosis_correct = (
                    classification.root_cause is latent.true_root_cause
                )

        # --- decide -------------------------------------------------------
        outcome = engine.decide(
            run_id=run_id, arm=arm, event=current, classification=classification,
            payment=payment, customer=customer, method=method,
            attempt_index=retry_ordinal, total_prior_failures=failed_charges,
            sequence_no=seq, now=clock,
            credential_lookup_exhausted=lookup_exhausted,
        )
        decision = outcome.decision
        result.decisions.append(decision)
        plan = outcome.plan
        ctx = GuardrailContext(
            now=clock, arm=arm, event=current, payment=payment, customer=customer,
            method=method, root_cause=classification.root_cause,
            confidence=classification.confidence, total_prior_failures=failed_charges,
        )

        action = outcome.final_action
        for breach in outcome.guardrails.shadow_breaches:
            if breach not in result.breaches:
                result.breaches.append(breach)

        # --- suppressed: nothing happens, and that is the point -----------
        if action is RecoveryAction.SUPPRESS:
            result.attempts.append(_attempt(
                run_id, payment, decision, arm, cycle + 1, AttemptKind.HUMAN_REVIEW,
                clock, Outcome.SUPPRESSED,
                detail=(
                    outcome.guardrails.block_reason
                    or "Guardrail veto: no action dispatched."
                ),
            ))
            result.suppressed_actions += 1
            result.final_outcome = Outcome.ABANDONED
            break

        # --- escalation: a person owns it now -----------------------------
        if action is RecoveryAction.HUMAN_REVIEW:
            awaiting = (
                classification.root_cause is RootCause.UNKNOWN and not analyst_used
            )
            review = resolve_human_review(latent, awaiting_diagnosis=awaiting)
            result.human_cost_minor += HUMAN_REVIEW_COST_MINOR
            result.escalated_to_human = True
            if review.repaired:
                apply_repair(repairs, latent.true_root_cause, clock)
            result.attempts.append(_attempt(
                run_id, payment, decision, arm, cycle + 1, AttemptKind.HUMAN_REVIEW,
                clock, Outcome.ESCALATED, detail=review.reason,
                probability=review.probability,
            ))

            # An escalation that ends the case would forfeit the money, which is the
            # opposite of what escalation is for. A person establishes what the machine
            # could not, and the case rejoins the automated path with the correct action
            # attached -- once. If the analyst cannot place it either, it closes here.
            if review.repaired:
                # A cleared risk decision earns exactly one authorised charge, dispatched
                # under the analyst's sign-off rather than by policy.
                clock = clock + timedelta(hours=ANALYST_SLA_HOURS)
                if clock <= deadline:
                    charge = resolve_charge(
                        latent, original_failed_at, clock,
                        kind=AttemptKind.TIMED_RETRY, repairs=repairs,
                        ordinal=retry_ordinal, method=method,
                    )
                    _apply_charge(result, run_id, payment, decision, arm, cycle + 1,
                                  AttemptKind.TIMED_RETRY, clock, charge, latent,
                                  original_failed_at)
                    engine.guardrails.commit_attempt(ctx, clock, is_charge=True)
                    if charge.success:
                        break
                result.final_outcome = Outcome.ESCALATED
                break

            if review.diagnosed and awaiting:
                analyst_used = True
                clock = clock + timedelta(hours=ANALYST_SLA_HOURS)
                if clock > deadline:
                    result.final_outcome = Outcome.ESCALATED
                    break
                established = _analyst_classification(latent.true_root_cause, review.reason)
                current = _next_event(current, clock)
                continue

            result.final_outcome = Outcome.ESCALATED
            break

        # --- card updater: repair first, then a gated retry ----------------
        if action is RecoveryAction.CARD_UPDATER:
            lookup = resolve_card_updater(latent, method)
            result.attempts.append(_attempt(
                run_id, payment, decision, arm, cycle + 1,
                AttemptKind.CARD_UPDATER_LOOKUP, clock,
                Outcome.RECOVERED if lookup.repaired else Outcome.FAILED,
                detail=lookup.reason, probability=lookup.probability,
            ))
            if lookup.repaired:
                apply_repair(repairs, RootCause.EXPIRED_CARD, clock)
                # The customer is never contacted. This is the cheapest recovery in the
                # system and a blind retry loop cannot find it.
                clock = parse_iso(plan.companion_scheduled_at or plan.scheduled_at)
                if clock > deadline:
                    result.final_outcome = Outcome.ABANDONED
                    break
                charge = resolve_charge(
                    latent, original_failed_at, clock,
                    kind=AttemptKind.POST_REPAIR_RETRY, repairs=repairs,
                    ordinal=retry_ordinal, method=method,
                )
                _apply_charge(result, run_id, payment, decision, arm, cycle + 1,
                              AttemptKind.POST_REPAIR_RETRY, clock, charge, latent,
                              original_failed_at)
                engine.guardrails.commit_attempt(ctx, clock, is_charge=True)
                retry_ordinal += 1
                if charge.success:
                    break
                failed_charges += 1
                current = _next_event(current, clock)
                continue

            # Lookup found nothing: fall through to the companion ask.
            lookup_exhausted = True
            if plan.companion_action is RecoveryAction.CUSTOMER_NUDGE and plan.message:
                clock = parse_iso(plan.companion_scheduled_at or plan.scheduled_at)
                repaired = _dispatch_message(
                    result, run_id, payment, decision, arm, cycle + 1, clock,
                    latent, repairs, retry_ordinal, targeted=True,
                    kind=AttemptKind.NUDGE, engine=engine, ctx=ctx,
                )
                if repaired:
                    clock = clock + timedelta(hours=3)
                    charge = resolve_charge(
                        latent, original_failed_at, clock,
                        kind=AttemptKind.POST_REPAIR_RETRY, repairs=repairs,
                        ordinal=retry_ordinal, method=method,
                    )
                    _apply_charge(result, run_id, payment, decision, arm, cycle + 1,
                                  AttemptKind.POST_REPAIR_RETRY, clock, charge, latent,
                                  original_failed_at)
                    engine.guardrails.commit_attempt(ctx, clock, is_charge=True)
                    retry_ordinal += 1
                    if charge.success:
                        break
                    failed_charges += 1
                    current = _next_event(current, clock)
                    continue
                clock = clock + timedelta(hours=NUDGE_RESPONSE_WINDOW_HOURS)
            else:
                clock = clock + timedelta(hours=NUDGE_RESPONSE_WINDOW_HOURS)

            result.final_outcome = Outcome.PENDING
            if clock > deadline:
                break
            current = _next_event(current, clock)
            continue

        # --- customer nudge: the only route on a repairable failure --------
        if action is RecoveryAction.CUSTOMER_NUDGE:
            clock = parse_iso(plan.scheduled_at)
            if clock > deadline:
                result.final_outcome = Outcome.ABANDONED
                break
            repaired = _dispatch_message(
                result, run_id, payment, decision, arm, cycle + 1, clock,
                latent, repairs, retry_ordinal, targeted=True, kind=plan.kind,
                engine=engine, ctx=ctx,
            )
            if repaired:
                clock = clock + timedelta(hours=2)
                charge = resolve_charge(
                    latent, original_failed_at, clock,
                    kind=AttemptKind.POST_REPAIR_RETRY, repairs=repairs,
                    ordinal=retry_ordinal, method=method,
                )
                _apply_charge(result, run_id, payment, decision, arm, cycle + 1,
                              AttemptKind.POST_REPAIR_RETRY, clock, charge, latent,
                              original_failed_at)
                engine.guardrails.commit_attempt(ctx, clock, is_charge=True)
                retry_ordinal += 1
                if charge.success:
                    break
                failed_charges += 1
                current = _next_event(current, clock)
                continue
            # No repair yet. Whether a second ask is warranted is the guardrail layer's
            # call, not the executor's -- so the case goes round again and the comms
            # frequency and spacing checks decide. When they refuse, the plan comes back
            # SUPPRESS and the case closes there.
            result.final_outcome = Outcome.PENDING
            clock = clock + timedelta(hours=NUDGE_RESPONSE_WINDOW_HOURS)
            if clock > deadline:
                break
            current = _next_event(current, clock)
            continue

        # --- smart retry (and the baseline's blind retry) -------------------
        if action is RecoveryAction.SMART_RETRY:
            # A companion message goes out first when one was cleared.
            if plan.companion_action is RecoveryAction.CUSTOMER_NUDGE and plan.message:
                msg_at = parse_iso(plan.companion_scheduled_at or plan.scheduled_at)
                if msg_at <= deadline:
                    _dispatch_message(
                        result, run_id, payment, decision, arm, cycle + 1, msg_at,
                        latent, repairs, retry_ordinal,
                        targeted=(arm is Arm.AGENT),
                        kind=AttemptKind.NUDGE, engine=engine, ctx=ctx,
                    )

            clock = parse_iso(plan.scheduled_at)
            if clock > deadline:
                result.attempts.append(_attempt(
                    run_id, payment, decision, arm, cycle + 1, plan.kind, clock,
                    Outcome.ABANDONED,
                    detail=(
                        f"Scheduled attempt falls past this subscription's "
                        f"{latent.recovery_deadline_hours / 24:.0f}-day cancellation "
                        f"point. Not dispatched."
                    ),
                ))
                result.final_outcome = Outcome.ABANDONED
                break

            charge = resolve_charge(
                latent, original_failed_at, clock, kind=plan.kind,
                repairs=repairs, ordinal=retry_ordinal, method=method,
            )
            _apply_charge(result, run_id, payment, decision, arm, cycle + 1,
                          plan.kind, clock, charge, latent, original_failed_at)
            engine.guardrails.commit_attempt(ctx, clock, is_charge=True)
            if arm is Arm.BASELINE:
                engine.commit_baseline_side_effects(
                    ctx, clock, sent_message=bool(plan.message)
                )
            retry_ordinal += 1
            if charge.success:
                break
            failed_charges += 1
            current = _next_event(current, clock)
            continue

        break

    if result.recovered and result.final_outcome is not Outcome.RECOVERED:
        result.final_outcome = Outcome.RECOVERED
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attempt(
    run_id: str,
    payment: Payment,
    decision: Decision,
    arm: Arm,
    attempt_no: int,
    kind: AttemptKind,
    when: datetime,
    outcome: Outcome,
    *,
    detail: str = "",
    probability: float = 0.0,
    recovered_minor: int = 0,
    cost_minor: int = 0,
    penalty: float = 0.0,
    customer_touch: bool = False,
) -> Attempt:
    return Attempt(
        id=f"att_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        payment_id=payment.id,
        decision_id=decision.id,
        arm=arm,
        attempt_no=attempt_no,
        kind=kind,
        attempted_at=to_iso(when),
        outcome=outcome,
        amount_recovered_minor=recovered_minor,
        processing_cost_minor=cost_minor,
        network_penalty_points=penalty,
        customer_touch=customer_touch,
        detail=detail,
        success_probability=probability,
    )


def _apply_charge(
    result: CaseResult,
    run_id: str,
    payment: Payment,
    decision: Decision,
    arm: Arm,
    attempt_no: int,
    kind: AttemptKind,
    when: datetime,
    charge,
    latent: LatentCase,
    original_failed_at: datetime,
) -> None:
    """Book a charge attempt: its cost always, its revenue only if it cleared."""
    result.charge_attempts += 1
    result.processing_cost_minor += charge.cost_minor
    result.network_penalty_points += charge.network_penalty_points

    if charge.success:
        result.recovered = True
        result.recovered_amount_minor = payment.amount_minor
        result.final_outcome = Outcome.RECOVERED
        result.time_to_recovery_hours = (when - original_failed_at).total_seconds() / 3600

    result.attempts.append(_attempt(
        run_id, payment, decision, arm, attempt_no, kind, when,
        Outcome.RECOVERED if charge.success else Outcome.FAILED,
        detail=charge.reason,
        probability=charge.probability,
        recovered_minor=payment.amount_minor if charge.success else 0,
        cost_minor=charge.cost_minor,
        penalty=charge.network_penalty_points,
    ))


def _dispatch_message(
    result: CaseResult,
    run_id: str,
    payment: Payment,
    decision: Decision,
    arm: Arm,
    attempt_no: int,
    when: datetime,
    latent: LatentCase,
    repairs: RepairState,
    ordinal: int,
    *,
    targeted: bool,
    kind: AttemptKind,
    engine: PolicyEngine,
    ctx: GuardrailContext,
) -> bool:
    """Send one customer message and report whether it repaired the payment."""
    res = resolve_customer_action(latent, kind=kind, ordinal=ordinal, targeted=targeted)
    result.customer_touches += 1
    result.processing_cost_minor += res.cost_minor
    if res.repaired:
        apply_repair(repairs, latent.true_root_cause, when)

    result.attempts.append(_attempt(
        run_id, payment, decision, arm, attempt_no, kind, when,
        Outcome.RECOVERED if res.success else (
            Outcome.PENDING if res.pending else Outcome.FAILED
        ),
        detail=res.reason, probability=res.probability, cost_minor=res.cost_minor,
        customer_touch=True,
    ))
    engine.guardrails.commit_nudge(ctx, when)
    return res.repaired


def _next_event(current: FailureEvent, when: datetime) -> FailureEvent:
    """The same underlying condition producing the same decline, one attempt later.

    Reusing the raw strings is the realistic choice: an expired card does not start
    returning a different code because we tried again. It also keeps the run
    deterministic, which the reproducibility claim depends on.
    """
    return FailureEvent(
        id=f"{current.id}_r{current.attempt_no}",
        payment_id=current.payment_id,
        gateway=current.gateway,
        gateway_txn_id=f"{current.gateway_txn_id}-r{current.attempt_no}",
        raw_code=current.raw_code,
        raw_message=current.raw_message,
        http_status=current.http_status,
        occurred_at=to_iso(when),
        attempt_no=current.attempt_no + 1,
        method_type=current.method_type,
        true_root_cause=current.true_root_cause,
        is_ambiguous=current.is_ambiguous,
        recoverable_in_principle=current.recoverable_in_principle,
    )
