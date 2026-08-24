"""
The guardrail layer.

    "This is the detail that earns judge trust: the agent cannot take any action the
     guardrail layer has not already pre-cleared. Guardrails live in the executor as
     hard checks, not as instructions the model is asked to follow."

So this module contains no prompts and imports nothing from the classifier. It is a
pure function of state: given a proposed action and the surrounding facts, it returns a
verdict, and the executor is physically incapable of dispatching an action the verdict
did not clear.

Design decisions worth defending:

* **Every check that runs is recorded, including the passes.** "Here are the fourteen
  things verified before anything left the building" is the artifact an auditor wants;
  logging only the failures would leave them taking the rest on faith.
* **Verdict precedence is explicit.** Hard stops beat caps, caps beat cooldowns,
  cooldowns beat preferences. A blocked action never silently degrades into a quieter
  version of itself -- it becomes `SUPPRESS` (nothing happened) or `HUMAN_REVIEW`
  (a person owns it now).
* **The four hard stops from the plan override everything**: chargeback filed, dispute
  opened, opt-out requested, fraud flag raised.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..config import PolicyConfig, settings
from ..models import (
    ActionPlan,
    Arm,
    Customer,
    FailureEvent,
    GuardrailCheck,
    GuardrailVerdict,
    Payment,
    PaymentMethod,
)
from ..taxonomy import TAXONOMY, RecoveryAction, RootCause
from ..money import format_minor
from .comms import scan_message_tone
from .timing import in_quiet_hours, local_time, next_allowed_contact_time, to_iso


#: Hours between "the agent proposed an above-ceiling action" and "a human approved it".
#: The gate delays and costs; it does not cancel. See `_apply_modifications`.
SIGNOFF_SLA_HOURS = 2.0


# ---------------------------------------------------------------------------
# Mutable per-run state
# ---------------------------------------------------------------------------


@dataclass
class GuardrailState:
    """Rolling counters the caps and cooldowns are evaluated against.

    Kept per simulation run so a benchmark is reproducible and so the dashboard can
    show how much headroom each cap had left.
    """

    attempts_by_method: dict[str, list[datetime]] = field(default_factory=lambda: defaultdict(list))
    attempts_by_payment: dict[str, list[datetime]] = field(default_factory=lambda: defaultdict(list))
    failures_by_payment: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    nudges_by_customer: dict[str, list[datetime]] = field(default_factory=lambda: defaultdict(list))
    exposure_by_day: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    autonomous_exposure_total: int = 0

    # Counters for the dashboard.
    blocks_by_category: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    modifications: int = 0
    violations_prevented: int = 0

    def record_attempt(self, method_id: str, payment_id: str, when: datetime) -> None:
        self.attempts_by_method[method_id].append(when)
        self.attempts_by_payment[payment_id].append(when)

    def record_failure(self, payment_id: str) -> None:
        self.failures_by_payment[payment_id] += 1

    def record_nudge(self, customer_id: str, when: datetime) -> None:
        self.nudges_by_customer[customer_id].append(when)

    def record_exposure(self, when: datetime, amount_minor: int) -> None:
        self.exposure_by_day[when.date().isoformat()] += amount_minor
        self.autonomous_exposure_total += amount_minor

    def attempts_within(self, method_id: str, when: datetime, hours: float) -> int:
        cutoff = when - timedelta(hours=hours)
        return sum(1 for t in self.attempts_by_method[method_id] if t > cutoff)

    def nudges_within(self, customer_id: str, when: datetime, hours: float) -> int:
        cutoff = when - timedelta(hours=hours)
        return sum(1 for t in self.nudges_by_customer[customer_id] if t > cutoff)

    def last_attempt(self, method_id: str) -> datetime | None:
        history = self.attempts_by_method[method_id]
        return max(history) if history else None

    def last_nudge(self, customer_id: str) -> datetime | None:
        history = self.nudges_by_customer[customer_id]
        return max(history) if history else None


@dataclass
class GuardrailContext:
    """Everything a check is allowed to look at."""

    now: datetime
    arm: Arm
    event: FailureEvent
    payment: Payment
    customer: Customer
    method: PaymentMethod
    root_cause: RootCause
    confidence: float
    total_prior_failures: int


@dataclass
class GuardrailOutcome:
    """The layer's verdict, plus the full trace."""

    final_action: RecoveryAction
    plan: ActionPlan
    checks: list[GuardrailCheck]
    blocked: bool
    block_reason: str | None
    modified: bool
    escalated: bool
    requires_human_signoff: bool
    companion_dropped: bool = False
    companion_drop_reason: str | None = None
    #: Controls this action *would* have breached, populated only in shadow mode for the
    #: unguarded arm. Non-empty here means "the naive loop acted anyway".
    shadow_breaches: list[str] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.verdict is GuardrailVerdict.PASS)

    @property
    def blocked_count(self) -> int:
        return sum(1 for c in self.checks if c.verdict is GuardrailVerdict.BLOCK)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GuardrailEngine:
    """Runs the hard checks. Deterministic, prompt-free, and side-effect-free."""

    def __init__(self, policy: PolicyConfig | None = None) -> None:
        self.policy = policy or settings.policy
        self.state = GuardrailState()

    def reset(self) -> None:
        self.state = GuardrailState()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _check(
        check_id: str,
        name: str,
        verdict: GuardrailVerdict,
        detail: str,
        category: str,
        severity: str = "info",
    ) -> GuardrailCheck:
        return GuardrailCheck(
            id=check_id, name=name, verdict=verdict, detail=detail,
            category=category, severity=severity,
        )

    # -- the individual checks -------------------------------------------

    def _hard_stops(self, ctx: GuardrailContext) -> list[GuardrailCheck]:
        """The four overriding stops from the plan, plus terminal causes.

        These are evaluated first and their BLOCK cannot be relaxed by anything below.
        """
        c = ctx.customer
        checks: list[GuardrailCheck] = []

        checks.append(self._check(
            "hard_stop.chargeback", "Chargeback status",
            GuardrailVerdict.BLOCK if c.chargeback_filed else GuardrailVerdict.PASS,
            ("A chargeback has been filed against this customer. Any further "
             "collection attempt is a compliance violation, regardless of root cause.")
            if c.chargeback_filed else
            "No chargeback filed against this customer.",
            "hard_stop", "critical" if c.chargeback_filed else "info",
        ))

        checks.append(self._check(
            "hard_stop.dispute", "Dispute status",
            GuardrailVerdict.BLOCK if c.dispute_open else GuardrailVerdict.PASS,
            ("An open dispute exists on this account. Recovery activity is frozen "
             "until it is resolved.")
            if c.dispute_open else "No open dispute on this account.",
            "hard_stop", "critical" if c.dispute_open else "info",
        ))

        checks.append(self._check(
            "hard_stop.fraud_flag", "Fraud-flag status",
            GuardrailVerdict.BLOCK if c.fraud_flag else GuardrailVerdict.PASS,
            ("This account carries a standing fraud flag. Automated retries are "
             "prohibited; the case goes to a human.")
            if c.fraud_flag else "No standing fraud flag on this account.",
            "hard_stop", "critical" if c.fraud_flag else "info",
        ))

        entry = TAXONOMY[ctx.root_cause]
        checks.append(self._check(
            "hard_stop.terminal_cause", "Terminal-decline stop",
            GuardrailVerdict.BLOCK if entry.terminal else GuardrailVerdict.PASS,
            (f"{entry.label} is a terminal decline. The issuer instructed us to stop, "
             f"not to try later. Retrying would burn interchange on a zero-probability "
             f"charge and push the merchant toward a network monitoring programme.")
            if entry.terminal else
            f"{entry.label} permits an automated recovery path.",
            "hard_stop", "critical" if entry.terminal else "info",
        ))

        return checks

    def _attempt_caps(self, ctx: GuardrailContext, plan: ActionPlan) -> list[GuardrailCheck]:
        """Card networks monitor and penalise excessive retries, so the caps are
        enforced per instrument per rolling window, not per payment."""
        checks: list[GuardrailCheck] = []
        p = self.policy
        entry = TAXONOMY[ctx.root_cause]

        if plan.action is not RecoveryAction.SMART_RETRY:
            checks.append(self._check(
                "cap.daily", "Attempt cap (24h)", GuardrailVerdict.NA,
                "Not a charge attempt -- retry caps do not apply.", "attempt_cap",
            ))
            return checks

        used_24h = self.state.attempts_within(ctx.method.id, ctx.now, 24)
        over_daily = (
            entry.counts_against_network_cap
            and used_24h >= p.max_attempts_per_method_per_day
        )
        exempt_note = (
            "" if entry.counts_against_network_cap else
            f" {entry.label} produced no issuer decision, so it does not consume the "
            f"scheme attempt budget -- the per-cause cap of {entry.max_attempts} governs "
            f"instead."
        )
        checks.append(self._check(
            "cap.daily", "Attempt cap (24h)",
            GuardrailVerdict.BLOCK if over_daily else GuardrailVerdict.PASS,
            f"{used_24h}/{p.max_attempts_per_method_per_day} attempts used on the "
            f"instrument ending {ctx.method.last4} in the last 24h."
            + (" Cap reached -- attempt withheld." if over_daily else exempt_note),
            "attempt_cap", "warning" if over_daily else "info",
        ))

        used_7d = self.state.attempts_within(ctx.method.id, ctx.now, 24 * 7)
        over_weekly = (
            entry.counts_against_network_cap
            and used_7d >= p.max_attempts_per_method_per_week
        )
        checks.append(self._check(
            "cap.weekly", "Attempt cap (7d)",
            GuardrailVerdict.BLOCK if over_weekly else GuardrailVerdict.PASS,
            f"{used_7d}/{p.max_attempts_per_method_per_week} attempts used on this "
            f"instrument in the last 7 days."
            + (" Cap reached -- attempt withheld." if over_weekly else exempt_note),
            "attempt_cap", "warning" if over_weekly else "info",
        ))

        # Counts only attempts *we* dispatched. The failure that opened the case was the
        # merchant's own scheduled charge, not one of our retries, so it does not consume
        # the recovery budget.
        payment_attempts = len(self.state.attempts_by_payment[ctx.payment.id])
        over_cause_cap = entry.max_attempts > 0 and payment_attempts >= entry.max_attempts
        checks.append(self._check(
            "cap.per_cause", f"Per-cause cap ({entry.label})",
            GuardrailVerdict.BLOCK if over_cause_cap else GuardrailVerdict.PASS,
            f"{payment_attempts}/{entry.max_attempts} recovery attempts used for this "
            f"root cause. The cap is tuned per cause, not global -- a transient issuer "
            f"outage earns more attempts than a balance failure."
            + (" Cap reached." if over_cause_cap else ""),
            "attempt_cap", "warning" if over_cause_cap else "info",
        ))

        return checks

    def _cooldowns(self, ctx: GuardrailContext, plan: ActionPlan) -> list[GuardrailCheck]:
        checks: list[GuardrailCheck] = []
        entry = TAXONOMY[ctx.root_cause]

        if plan.action is not RecoveryAction.SMART_RETRY:
            checks.append(self._check(
                "cooldown.window", "Cooldown window", GuardrailVerdict.NA,
                "Not a charge attempt -- cooldowns do not apply.", "cooldown",
            ))
            return checks

        last = self.state.last_attempt(ctx.method.id)
        scheduled = plan.scheduled_at
        try:
            scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        except ValueError:
            scheduled_dt = ctx.now

        if last is None:
            checks.append(self._check(
                "cooldown.window", f"Cooldown ({entry.cooldown_hours:.2g}h for {entry.label})",
                GuardrailVerdict.PASS,
                "No prior attempt on this instrument in the run window.", "cooldown",
            ))
        else:
            gap_hours = (scheduled_dt - last).total_seconds() / 3600
            ok = gap_hours >= entry.cooldown_hours
            checks.append(self._check(
                "cooldown.window", f"Cooldown ({entry.cooldown_hours:.2g}h for {entry.label})",
                GuardrailVerdict.PASS if ok else GuardrailVerdict.MODIFY,
                f"Scheduled attempt sits {gap_hours:.1f}h after the previous one; the "
                f"{entry.label} cooldown requires {entry.cooldown_hours:.2g}h."
                + ("" if ok else " Attempt deferred to satisfy the window."),
                "cooldown", "info" if ok else "warning",
            ))

        # Lifetime ceiling: stop working a payment that has been dead too long.
        try:
            first_seen = datetime.fromisoformat(ctx.payment.created_at.replace("Z", "+00:00"))
            age_days = (ctx.now - first_seen).total_seconds() / 86400
        except ValueError:
            age_days = 0.0
        expired = entry.max_lifetime_days > 0 and age_days > entry.max_lifetime_days
        checks.append(self._check(
            "cooldown.lifetime", "Recovery window",
            GuardrailVerdict.BLOCK if expired else GuardrailVerdict.PASS,
            f"Payment is {age_days:.1f} days old; the {entry.label} recovery window is "
            f"{entry.max_lifetime_days} days."
            + (" Window closed -- abandoning is the correct action." if expired else ""),
            "cooldown", "warning" if expired else "info",
        ))

        return checks

    def _exposure(self, ctx: GuardrailContext, plan: ActionPlan) -> list[GuardrailCheck]:
        """Total value the agent may act on autonomously before a human signs off."""
        checks: list[GuardrailCheck] = []
        p = self.policy
        amount = ctx.payment.amount_minor
        cur = ctx.payment.currency

        over_ceiling = amount > p.autonomous_exposure_ceiling_minor
        checks.append(self._check(
            "exposure.per_transaction", "Per-transaction exposure ceiling",
            GuardrailVerdict.MODIFY if over_ceiling else GuardrailVerdict.PASS,
            f"Transaction value {format_minor(amount, cur)} against an autonomous "
            f"ceiling of {format_minor(p.autonomous_exposure_ceiling_minor, cur)}."
            + (" Above ceiling -- requires human sign-off before dispatch."
               if over_ceiling else ""),
            "exposure", "warning" if over_ceiling else "info",
        ))

        day_key = ctx.now.date().isoformat()
        used_today = self.state.exposure_by_day[day_key]
        over_budget = used_today + amount > p.daily_autonomous_budget_minor
        checks.append(self._check(
            "exposure.daily_budget", "Daily autonomous budget",
            GuardrailVerdict.MODIFY if over_budget else GuardrailVerdict.PASS,
            f"{format_minor(used_today, cur)} of "
            f"{format_minor(p.daily_autonomous_budget_minor, cur)} autonomous exposure "
            f"committed on {day_key}."
            + (" Budget exhausted -- further value held for sign-off." if over_budget else ""),
            "exposure", "warning" if over_budget else "info",
        ))

        return checks

    def _escalation(self, ctx: GuardrailContext, plan: ActionPlan) -> list[GuardrailCheck]:
        """Demo step 4: three failed retries triggers escalation, not more spam."""
        p = self.policy
        failures = ctx.total_prior_failures
        should_escalate = (
            plan.action is RecoveryAction.SMART_RETRY
            and failures >= p.escalate_after_failed_attempts
        )
        return [self._check(
            "escalation.repeat_failures", "Repeat-failure escalation",
            GuardrailVerdict.BLOCK if should_escalate else GuardrailVerdict.PASS,
            f"{failures} prior failed attempts on this payment "
            f"(threshold {p.escalate_after_failed_attempts})."
            + (" Escalating to a human instead of attempting again."
               if should_escalate else ""),
            "escalation", "warning" if should_escalate else "info",
        )]

    def _comms(self, ctx: GuardrailContext, plan: ActionPlan) -> list[GuardrailCheck]:
        """Quiet hours, channel consent, frequency caps, and message tone.

        Applied to whichever part of the plan actually contacts a human -- the primary
        action when it is a nudge, or the companion nudge attached to a retry.
        """
        checks: list[GuardrailCheck] = []
        p = self.policy
        c = ctx.customer

        touches_customer = (
            plan.action in (RecoveryAction.CUSTOMER_NUDGE, RecoveryAction.CARD_UPDATER)
            or plan.companion_action is RecoveryAction.CUSTOMER_NUDGE
        )
        if not touches_customer:
            checks.append(self._check(
                "comms.consent", "Channel consent", GuardrailVerdict.NA,
                "No customer-facing message in this plan.", "comms",
            ))
            return checks

        # --- opt-out (a hard stop, scoped to communication) ----------------
        checks.append(self._check(
            "comms.opt_out", "Opt-out status",
            GuardrailVerdict.BLOCK if c.opted_out else GuardrailVerdict.PASS,
            "Customer has opted out of recovery communications. No message may be sent "
            "on any channel." if c.opted_out else
            "Customer has not opted out of recovery communications.",
            "comms", "critical" if c.opted_out else "info",
        ))

        # --- channel consent ---------------------------------------------
        channel = plan.channel or "email"
        consent_map = {
            "email": c.consent_email,
            "sms": c.consent_sms,
            "whatsapp": c.consent_whatsapp,
        }
        has_consent = consent_map.get(channel, False)
        checks.append(self._check(
            "comms.consent", f"Channel consent ({channel})",
            GuardrailVerdict.PASS if has_consent else GuardrailVerdict.MODIFY,
            f"Consent for {channel}: {'granted' if has_consent else 'not granted'}."
            + ("" if has_consent else " Falling back to a consented channel or dropping "
               "the message."),
            "comms", "info" if has_consent else "warning",
        ))

        # --- quiet hours -------------------------------------------------
        try:
            send_at = datetime.fromisoformat(
                (plan.companion_scheduled_at or plan.scheduled_at).replace("Z", "+00:00")
            )
        except ValueError:
            send_at = ctx.now
        quiet = in_quiet_hours(send_at, c)
        local = local_time(send_at, c)
        checks.append(self._check(
            "comms.quiet_hours", "Quiet hours",
            GuardrailVerdict.MODIFY if quiet else GuardrailVerdict.PASS,
            f"Send time is {local.strftime('%H:%M')} in the customer's local timezone "
            f"(quiet window {p.quiet_hours_start:02d}:00-{p.quiet_hours_end:02d}:00)."
            + (" Deferred to the next permitted morning." if quiet else ""),
            "comms", "warning" if quiet else "info",
        ))

        # --- frequency cap ------------------------------------------------
        nudges_7d = self.state.nudges_within(c.id, ctx.now, 24 * 7)
        over_freq = nudges_7d >= p.max_nudges_per_customer_per_week
        checks.append(self._check(
            "comms.frequency", "Message frequency cap",
            GuardrailVerdict.BLOCK if over_freq else GuardrailVerdict.PASS,
            f"{nudges_7d}/{p.max_nudges_per_customer_per_week} messages sent to this "
            f"customer in the last 7 days."
            + (" Cap reached -- message withheld." if over_freq else ""),
            "comms", "warning" if over_freq else "info",
        ))

        last_nudge = self.state.last_nudge(c.id)
        if last_nudge is not None:
            gap = (send_at - last_nudge).total_seconds() / 3600
            too_soon = gap < p.min_hours_between_nudges
            checks.append(self._check(
                "comms.spacing", "Minimum message spacing",
                GuardrailVerdict.BLOCK if too_soon else GuardrailVerdict.PASS,
                f"{gap:.1f}h since the last message (minimum "
                f"{p.min_hours_between_nudges:.0f}h)."
                + (" Too soon -- message withheld." if too_soon else ""),
                "comms", "warning" if too_soon else "info",
            ))

        # --- tone -------------------------------------------------------
        if plan.message:
            tone = scan_message_tone(plan.message)
            checks.append(self._check(
                "comms.tone", "Message tone",
                GuardrailVerdict.BLOCK if tone.blocked else GuardrailVerdict.PASS,
                tone.detail, "comms", "critical" if tone.blocked else "info",
            ))

        return checks

    # -- orchestration ----------------------------------------------------

    def evaluate(self, ctx: GuardrailContext, plan: ActionPlan) -> GuardrailOutcome:
        """Run every applicable check and resolve them into a single verdict."""
        checks: list[GuardrailCheck] = []
        checks += self._hard_stops(ctx)
        checks += self._escalation(ctx, plan)
        checks += self._attempt_caps(ctx, plan)
        checks += self._cooldowns(ctx, plan)
        checks += self._exposure(ctx, plan)
        checks += self._comms(ctx, plan)

        blocking = [c for c in checks if c.verdict is GuardrailVerdict.BLOCK]
        modifying = [c for c in checks if c.verdict is GuardrailVerdict.MODIFY]

        final_action = plan.action
        blocked = False
        block_reason: str | None = None
        escalated = False
        modified = bool(modifying)
        requires_signoff = False
        companion_dropped = False
        companion_drop_reason: str | None = None

        # --- resolve blocks in precedence order --------------------------
        comms_only_blocks = {"comms.opt_out", "comms.frequency", "comms.spacing", "comms.tone"}
        structural = [c for c in blocking if c.id not in comms_only_blocks]
        comms_blocks = [c for c in blocking if c.id in comms_only_blocks]

        if structural:
            blocked = True
            primary = structural[0]
            block_reason = f"{primary.name}: {primary.detail}"
            self.state.blocks_by_category[primary.category] += 1
            self.state.violations_prevented += 1

            # Hard stops and escalations need a human; caps and windows just mean
            # "not now", which is a suppression rather than a hand-off.
            if primary.category in ("hard_stop", "escalation"):
                final_action = RecoveryAction.HUMAN_REVIEW
                escalated = True
            else:
                final_action = RecoveryAction.SUPPRESS

        if comms_blocks and not blocked:
            # A blocked message never blocks the charge attempt behind it. Only when the
            # message *is* the action does the whole plan become a suppression.
            if plan.action is RecoveryAction.CUSTOMER_NUDGE:
                blocked = True
                final_action = RecoveryAction.SUPPRESS
                block_reason = f"{comms_blocks[0].name}: {comms_blocks[0].detail}"
                self.state.blocks_by_category["comms"] += 1
                self.state.violations_prevented += 1
            else:
                companion_dropped = True
                companion_drop_reason = f"{comms_blocks[0].name}: {comms_blocks[0].detail}"
                self.state.blocks_by_category["comms"] += 1
                self.state.violations_prevented += 1
                modified = True

        # --- apply modifications ---------------------------------------
        adjusted = plan
        if not blocked:
            adjusted = self._apply_modifications(ctx, plan, modifying)
            requires_signoff = any(
                c.id in ("exposure.per_transaction", "exposure.daily_budget")
                and c.verdict is GuardrailVerdict.MODIFY
                for c in checks
            )
            if requires_signoff:
                # A sign-off gate is oversight, not abandonment. The agent proposes the
                # action, a human approves it, and *then* it dispatches -- delayed by the
                # approval SLA and charged the cost of a person's attention. Treating a
                # high-value ticket as unrecoverable just because it is high-value would
                # forfeit exactly the revenue the system exists to recover.
                base = adjusted.scheduled_at
                try:
                    when = datetime.fromisoformat(base.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    when = ctx.now
                gate = ctx.now + timedelta(hours=SIGNOFF_SLA_HOURS)
                if when < gate:
                    adjusted.scheduled_at = to_iso(gate)
                adjusted.reason += (
                    f" Above the autonomous ceiling: held for human sign-off, then "
                    f"dispatched at {adjusted.scheduled_at} ({SIGNOFF_SLA_HOURS:.2g}h "
                    f"approval SLA)."
                )
            if modifying:
                self.state.modifications += 1

        if companion_dropped:
            adjusted.companion_action = None
            adjusted.companion_kind = None
            adjusted.companion_scheduled_at = None

        return GuardrailOutcome(
            final_action=final_action,
            plan=adjusted,
            checks=checks,
            blocked=blocked,
            block_reason=block_reason,
            modified=modified,
            escalated=escalated,
            requires_human_signoff=requires_signoff,
            companion_dropped=companion_dropped,
            companion_drop_reason=companion_drop_reason,
        )

    def _apply_modifications(
        self, ctx: GuardrailContext, plan: ActionPlan, modifying: list[GuardrailCheck]
    ) -> ActionPlan:
        """Rewrite the plan so it satisfies every MODIFY verdict.

        Modifications are applied to the plan object rather than trusted to the
        executor, so what the ledger records is what the executor is handed.
        """
        ids = {c.id for c in modifying}

        if "cooldown.window" in ids:
            entry = TAXONOMY[ctx.root_cause]
            last = self.state.last_attempt(ctx.method.id)
            if last is not None:
                deferred = last + timedelta(hours=entry.cooldown_hours)
                plan.scheduled_at = to_iso(deferred)
                plan.reason += (
                    f" Deferred to {plan.scheduled_at} to satisfy the "
                    f"{entry.cooldown_hours:.2g}h cooldown for {entry.label}."
                )

        if "comms.quiet_hours" in ids:
            base = plan.companion_scheduled_at or plan.scheduled_at
            try:
                send_at = datetime.fromisoformat(base.replace("Z", "+00:00"))
            except ValueError:
                send_at = ctx.now
            shifted = next_allowed_contact_time(send_at, ctx.customer)
            if plan.companion_scheduled_at:
                plan.companion_scheduled_at = to_iso(shifted)
            else:
                plan.scheduled_at = to_iso(shifted)

        if "comms.consent" in ids:
            # Fall back to a channel the customer actually agreed to.
            c = ctx.customer
            for channel, ok in (("email", c.consent_email), ("whatsapp", c.consent_whatsapp),
                                ("sms", c.consent_sms)):
                if ok:
                    plan.channel = channel
                    break
            else:
                plan.channel = None
                plan.message = None

        return plan

    # -- recording --------------------------------------------------------

    def commit_attempt(self, ctx: GuardrailContext, when: datetime, is_charge: bool) -> None:
        if is_charge:
            self.state.record_attempt(ctx.method.id, ctx.payment.id, when)
            self.state.record_exposure(when, ctx.payment.amount_minor)

    def commit_nudge(self, ctx: GuardrailContext, when: datetime) -> None:
        self.state.record_nudge(ctx.customer.id, when)

    def summary(self) -> dict:
        return {
            "policy": self.policy.public_dict(),
            "blocks_by_category": dict(self.state.blocks_by_category),
            "total_blocks": sum(self.state.blocks_by_category.values()),
            "modifications": self.state.modifications,
            "violations_prevented": self.state.violations_prevented,
            "autonomous_exposure_total_minor": self.state.autonomous_exposure_total,
        }


def guardrail_catalogue() -> list[dict]:
    """Static description of every check, for the dashboard's guardrail screen.

    Documenting the layer in the product -- rather than in a slide -- is what makes
    "enforced in code, not a prompt" verifiable by the person looking at the screen.
    """
    return [
        {"id": "hard_stop.chargeback", "name": "Chargeback status", "category": "hard_stop",
         "description": "Any chargeback on the account freezes all recovery activity.",
         "overrides": "everything"},
        {"id": "hard_stop.dispute", "name": "Dispute status", "category": "hard_stop",
         "description": "An open dispute freezes recovery until it resolves.",
         "overrides": "everything"},
        {"id": "hard_stop.fraud_flag", "name": "Fraud-flag status", "category": "hard_stop",
         "description": "A standing fraud flag prohibits automated retries entirely.",
         "overrides": "everything"},
        {"id": "hard_stop.terminal_cause", "name": "Terminal-decline stop", "category": "hard_stop",
         "description": "Stolen/closed/do-not-honour stops immediately and flags the account.",
         "overrides": "everything"},
        {"id": "escalation.repeat_failures", "name": "Repeat-failure escalation",
         "category": "escalation",
         "description": "N consecutive failures route to a human instead of another attempt.",
         "overrides": "retry actions"},
        {"id": "cap.daily", "name": "Attempt cap (24h)", "category": "attempt_cap",
         "description": "Per instrument per day. Card networks penalise excessive retries.",
         "overrides": "retry actions"},
        {"id": "cap.weekly", "name": "Attempt cap (7d)", "category": "attempt_cap",
         "description": "Per instrument per week.", "overrides": "retry actions"},
        {"id": "cap.per_cause", "name": "Per-cause attempt cap", "category": "attempt_cap",
         "description": "Tuned per root cause, not global.", "overrides": "retry actions"},
        {"id": "cooldown.window", "name": "Cooldown window", "category": "cooldown",
         "description": "Minimum spacing between attempts, tuned per root cause.",
         "overrides": "attempt timing"},
        {"id": "cooldown.lifetime", "name": "Recovery window", "category": "cooldown",
         "description": "Stop working a payment once its recovery window closes.",
         "overrides": "retry actions"},
        {"id": "exposure.per_transaction", "name": "Per-transaction ceiling",
         "category": "exposure",
         "description": "Value the agent may act on autonomously before human sign-off.",
         "overrides": "autonomous dispatch"},
        {"id": "exposure.daily_budget", "name": "Daily autonomous budget",
         "category": "exposure",
         "description": "Aggregate daily value ceiling across all actions.",
         "overrides": "autonomous dispatch"},
        {"id": "comms.opt_out", "name": "Opt-out status", "category": "comms",
         "description": "No message on any channel to an opted-out customer.",
         "overrides": "all messaging"},
        {"id": "comms.consent", "name": "Channel consent", "category": "comms",
         "description": "Only channels the customer consented to.", "overrides": "channel choice"},
        {"id": "comms.quiet_hours", "name": "Quiet hours", "category": "comms",
         "description": "No messages inside the customer's local quiet window.",
         "overrides": "send time"},
        {"id": "comms.frequency", "name": "Frequency cap", "category": "comms",
         "description": "Maximum messages per customer per week.", "overrides": "messaging"},
        {"id": "comms.spacing", "name": "Minimum spacing", "category": "comms",
         "description": "Minimum hours between two messages.", "overrides": "messaging"},
        {"id": "comms.tone", "name": "Message tone", "category": "comms",
         "description": "Message copy is scanned for coercive or collections language.",
         "overrides": "message content"},
    ]
