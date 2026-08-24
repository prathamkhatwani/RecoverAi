"""
Head-to-head simulation.

Runs the *same* failure stream through two arms and reports the difference. This module
is the plan's measurement requirement, and its whole value rests on one property: both
arms are handed identical inputs and identical luck. Anything else is a demo, not a
benchmark.

What makes the comparison fair (and why each of these is here):

* One `GeneratedStream` per run. Same payments, same customers, same raw gateway strings,
  same latent truth.
* Pre-drawn randomness. Each case carries a fixed vector of uniforms drawn before either
  arm runs, and both arms index into it by *the state being tested* rather than by
  attempt number -- so neither arm can win by rolling more dice.
* Both arms are scored on the same ledger of costs: processing fees, human review time,
  customer contacts, and network retry-abuse exposure.
* The naive arm is additionally evaluated against the guardrails in shadow mode. It is
  not stopped by them (that is what makes it naive), but every control it would have
  breached is recorded, so revenue it could only reach by breaching a hard stop is a
  computed number rather than a rhetorical point.

The last one matters more than it looks. Without it, the honest reading of a naive
baseline that charges a fraud-flagged account and gets paid is "the baseline won that
case". With it, the reading is "the baseline collected money it was not allowed to
touch", which is the actual difference between the two systems.
"""

from __future__ import annotations

import asyncio
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ..classifier.llm_client import llm_client
from ..classifier.router import ClassifierRouter
from ..executor import CaseResult, run_case
from ..ledger import AuditLedger, ledger as global_ledger
from ..models import Arm, Outcome
from ..policy import PolicyEngine
from ..synthetic.generator import GeneratedStream, generate_stream
from ..taxonomy import TAXONOMY, RootCause


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class ArmMetrics:
    """One arm's scoreboard. Money is in minor units throughout."""

    arm: str
    cases: int = 0
    at_risk_minor: int = 0
    recovered_cases: int = 0
    recovered_minor: int = 0

    charge_attempts: int = 0
    customer_touches: int = 0
    suppressed_actions: int = 0
    processing_cost_minor: int = 0
    human_cost_minor: int = 0
    network_penalty_points: float = 0.0
    escalated_to_human: int = 0

    # Diagnosis quality (agent arm only; the baseline does not diagnose).
    diagnoses_judged: int = 0
    diagnoses_correct: int = 0
    abstentions: int = 0

    # Compliance
    breach_cases: int = 0
    breach_minor: int = 0
    breach_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    times_to_recovery: list[float] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # How many cases were unrecoverable no matter what either arm did. Reported so the
    # recovery rate is read against what was actually winnable.
    unrecoverable_cases: int = 0
    unrecoverable_minor: int = 0

    def add(self, res: CaseResult) -> None:
        self.cases += 1
        self.at_risk_minor += res.amount_minor
        self.charge_attempts += res.charge_attempts
        self.customer_touches += res.customer_touches
        self.suppressed_actions += res.suppressed_actions
        self.processing_cost_minor += res.processing_cost_minor
        self.human_cost_minor += res.human_cost_minor
        self.network_penalty_points += res.network_penalty_points
        self.escalated_to_human += 1 if res.escalated_to_human else 0

        if not res.recoverable_in_principle:
            self.unrecoverable_cases += 1
            self.unrecoverable_minor += res.amount_minor

        if res.diagnosis_tier:
            self.tier_counts[res.diagnosis_tier] += 1
        if res.first_diagnosis == RootCause.UNKNOWN.value:
            self.abstentions += 1
        if res.diagnosis_correct is not None:
            self.diagnoses_judged += 1
            self.diagnoses_correct += 1 if res.diagnosis_correct else 0

        if res.recovered:
            self.recovered_cases += 1
            self.recovered_minor += res.recovered_amount_minor
            if res.time_to_recovery_hours is not None:
                self.times_to_recovery.append(res.time_to_recovery_hours)
            if res.breached_compliance:
                self.breach_cases += 1
                self.breach_minor += res.recovered_amount_minor
        for check_id in res.breaches:
            self.breach_counts[check_id] += 1

    # -- derived ----------------------------------------------------------

    @property
    def total_cost_minor(self) -> int:
        return self.processing_cost_minor + self.human_cost_minor

    @property
    def net_recovered_minor(self) -> int:
        return self.recovered_minor - self.total_cost_minor

    @property
    def recovery_rate(self) -> float:
        return self.recovered_cases / self.cases if self.cases else 0.0

    @property
    def revenue_recovery_rate(self) -> float:
        return self.recovered_minor / self.at_risk_minor if self.at_risk_minor else 0.0

    @property
    def winnable_recovery_rate(self) -> float:
        """Recovery rate over cases that were recoverable at all.

        A stream where 15% of failures are stolen cards has a hard ceiling. Reporting
        against that ceiling is the honest denominator.
        """
        winnable = self.cases - self.unrecoverable_cases
        return self.recovered_cases / winnable if winnable else 0.0

    @property
    def diagnosis_accuracy(self) -> float | None:
        if not self.diagnoses_judged:
            return None
        return self.diagnoses_correct / self.diagnoses_judged

    @property
    def attempts_per_recovery(self) -> float | None:
        if not self.recovered_cases:
            return None
        return self.charge_attempts / self.recovered_cases

    @property
    def median_hours_to_recovery(self) -> float | None:
        if not self.times_to_recovery:
            return None
        return round(statistics.median(self.times_to_recovery), 2)

    @property
    def clean_recovered_minor(self) -> int:
        """Recovered revenue excluding cases only reachable by breaching a hard stop."""
        return self.recovered_minor - self.breach_minor

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "cases": self.cases,
            "at_risk_minor": self.at_risk_minor,
            "recovered_cases": self.recovered_cases,
            "recovered_minor": self.recovered_minor,
            "clean_recovered_minor": self.clean_recovered_minor,
            "net_recovered_minor": self.net_recovered_minor,
            "recovery_rate": round(self.recovery_rate, 4),
            "revenue_recovery_rate": round(self.revenue_recovery_rate, 4),
            "winnable_recovery_rate": round(self.winnable_recovery_rate, 4),
            "charge_attempts": self.charge_attempts,
            "customer_touches": self.customer_touches,
            "suppressed_actions": self.suppressed_actions,
            "processing_cost_minor": self.processing_cost_minor,
            "human_cost_minor": self.human_cost_minor,
            "total_cost_minor": self.total_cost_minor,
            "network_penalty_points": round(self.network_penalty_points, 2),
            "escalated_to_human": self.escalated_to_human,
            "attempts_per_recovery": (
                round(self.attempts_per_recovery, 2)
                if self.attempts_per_recovery is not None else None
            ),
            "median_hours_to_recovery": self.median_hours_to_recovery,
            "diagnosis_accuracy": (
                round(self.diagnosis_accuracy, 4)
                if self.diagnosis_accuracy is not None else None
            ),
            "diagnoses_judged": self.diagnoses_judged,
            "abstentions": self.abstentions,
            "tier_counts": dict(self.tier_counts),
            "unrecoverable_cases": self.unrecoverable_cases,
            "unrecoverable_minor": self.unrecoverable_minor,
            "breach_cases": self.breach_cases,
            "breach_minor": self.breach_minor,
            "breach_counts": dict(self.breach_counts),
        }


@dataclass
class CauseComparison:
    """Per-root-cause head to head. The plan asks for this breakdown explicitly."""

    cause: str
    label: str
    cases: int = 0
    at_risk_minor: int = 0
    agent_recovered: int = 0
    baseline_recovered: int = 0
    agent_minor: int = 0
    baseline_minor: int = 0
    agent_charges: int = 0
    baseline_charges: int = 0
    agent_touches: int = 0
    baseline_touches: int = 0
    classified_correctly: int = 0
    classified_total: int = 0
    recoverable_cases: int = 0

    def to_dict(self) -> dict:
        entry = TAXONOMY[RootCause(self.cause)]
        return {
            "cause": self.cause,
            "label": self.label,
            "color": entry.color,
            "primary_action": entry.primary_action.value,
            "retry_answer": entry.retry_answer,
            "cases": self.cases,
            "recoverable_cases": self.recoverable_cases,
            "at_risk_minor": self.at_risk_minor,
            "agent_recovered": self.agent_recovered,
            "baseline_recovered": self.baseline_recovered,
            "agent_minor": self.agent_minor,
            "baseline_minor": self.baseline_minor,
            "agent_charges": self.agent_charges,
            "baseline_charges": self.baseline_charges,
            "agent_touches": self.agent_touches,
            "baseline_touches": self.baseline_touches,
            "revenue_delta_minor": self.agent_minor - self.baseline_minor,
            "revenue_delta_pct": (
                round((self.agent_minor - self.baseline_minor) / self.baseline_minor, 4)
                if self.baseline_minor else None
            ),
            "classification_accuracy": (
                round(self.classified_correctly / self.classified_total, 4)
                if self.classified_total else None
            ),
        }


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


def _pct_delta(a: float, b: float) -> float | None:
    """Relative change from b to a. None when the baseline is zero (no honest ratio)."""
    if not b:
        return None
    return round((a - b) / b, 4)


@dataclass
class SimulationResult:
    run_id: str
    label: str
    seed: int
    event_count: int
    created_at: str
    used_llm: bool
    total_at_risk_minor: int
    ambiguous_ratio: float
    agent: ArmMetrics
    baseline: ArmMetrics
    by_cause: list[CauseComparison]
    cases: dict[str, list[CaseResult]] = field(default_factory=dict)
    classifier_stats: dict = field(default_factory=dict)
    duration_ms: int = 0

    # -- the headline -----------------------------------------------------

    def headline(self) -> dict:
        """The claim, computed. Every number here is derived, none is asserted.

        Ordered so the two figures the plan names as the target come first.
        """
        a, b = self.agent, self.baseline
        return {
            "revenue_uplift_pct": _pct_delta(a.recovered_minor, b.recovered_minor),
            "attempt_reduction_pct": _pct_delta(a.charge_attempts, b.charge_attempts),
            "touch_reduction_pct": _pct_delta(a.customer_touches, b.customer_touches),
            "net_revenue_uplift_pct": _pct_delta(
                a.net_recovered_minor, b.net_recovered_minor
            ),
            "network_penalty_reduction_pct": _pct_delta(
                a.network_penalty_points, b.network_penalty_points
            ),
            "time_to_recovery_reduction_pct": (
                _pct_delta(a.median_hours_to_recovery, b.median_hours_to_recovery)
                if a.median_hours_to_recovery and b.median_hours_to_recovery else None
            ),
            "uplift_vs_compliant_baseline_pct": _pct_delta(
                a.recovered_minor, b.clean_recovered_minor
            ),
            "agent_recovered_minor": a.recovered_minor,
            "baseline_recovered_minor": b.recovered_minor,
            "baseline_breach_minor": b.breach_minor,
            "agent_breach_minor": a.breach_minor,
            "agent_charge_attempts": a.charge_attempts,
            "baseline_charge_attempts": b.charge_attempts,
            "diagnosis_accuracy": (
                round(a.diagnosis_accuracy, 4) if a.diagnosis_accuracy else None
            ),
            "statement": self.statement(),
        }

    def statement(self) -> str:
        """The sentence, generated from the run rather than written in advance."""
        rev = _pct_delta(self.agent.recovered_minor, self.baseline.recovered_minor)
        att = _pct_delta(self.agent.charge_attempts, self.baseline.charge_attempts)
        if rev is None or att is None:
            return "Insufficient baseline activity to state a comparison."
        return (
            f"Across {self.event_count} identical failures, diagnosis-driven recovery "
            f"collected {rev:+.1%} more revenue while making {abs(att):.1%} fewer "
            f"charge attempts than fixed-schedule retry."
        )

    def meets_plan_target(self) -> dict:
        """Explicit pass/fail against the target the plan names.

        Stated as a check rather than a boast: a benchmark you cannot fail is not a
        benchmark, so the thresholds are named and the result is computed.
        """
        rev = _pct_delta(self.agent.recovered_minor, self.baseline.recovered_minor) or 0.0
        att = _pct_delta(self.agent.charge_attempts, self.baseline.charge_attempts) or 0.0
        return {
            "revenue_target_pct": 0.30,
            "revenue_actual_pct": round(rev, 4),
            "revenue_met": rev >= 0.30,
            "attempt_reduction_target_pct": 0.60,
            "attempt_reduction_actual_pct": round(-att, 4),
            "attempt_reduction_met": (-att) >= 0.60,
            "both_met": rev >= 0.30 and (-att) >= 0.60,
        }

    def to_dict(self, *, include_cases: bool = False) -> dict:
        out = {
            "run_id": self.run_id,
            "label": self.label,
            "seed": self.seed,
            "event_count": self.event_count,
            "created_at": self.created_at,
            "used_llm": self.used_llm,
            "total_at_risk_minor": self.total_at_risk_minor,
            "ambiguous_ratio": round(self.ambiguous_ratio, 4),
            "duration_ms": self.duration_ms,
            "agent": self.agent.to_dict(),
            "baseline": self.baseline.to_dict(),
            "by_cause": [c.to_dict() for c in self.by_cause],
            "headline": self.headline(),
            "plan_target": self.meets_plan_target(),
            "classifier": self.classifier_stats,
        }
        if include_cases:
            out["cases"] = {
                arm: [c.to_dict() for c in results]
                for arm, results in self.cases.items()
            }
        return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_simulation(
    *,
    event_count: int = 600,
    seed: int | None = None,
    use_llm: bool = False,
    label: str | None = None,
    stream: GeneratedStream | None = None,
    record_ledger: bool = True,
    ledger_target: AuditLedger | None = None,
    progress: Callable[[int, int], None] | None = None,
    run_id: str | None = None,
) -> SimulationResult:
    """Run both arms over one stream and return the comparison.

    `record_ledger` writes the agent arm's decisions into the hash chain. The baseline's
    are deliberately not chained: it is a strawman we are measuring, not a system whose
    reasoning anyone will ever have to defend.
    """
    started = datetime.now(timezone.utc)
    stream = stream or generate_stream(event_count=event_count, seed=seed)
    rid = run_id or f"run_{uuid.uuid4().hex[:10]}"
    chain = ledger_target if ledger_target is not None else global_ledger

    agent = ArmMetrics(arm=Arm.AGENT.value)
    baseline = ArmMetrics(arm=Arm.BASELINE.value)
    by_cause: dict[str, CauseComparison] = {}
    cases: dict[str, list[CaseResult]] = {Arm.AGENT.value: [], Arm.BASELINE.value: []}

    classifier = ClassifierRouter(llm_client) if use_llm else None
    if use_llm:
        llm_client.begin_run()

    if record_ledger:
        chain.append(
            kind="run_open",
            run_id=rid,
            arm="",
            subject_id=rid,
            summary=(
                f"Run opened: {len(stream.events)} failures, seed {stream.seed}, "
                f"{'live model' if use_llm else 'deterministic reasoner'}"
            ),
            payload={
                "run_id": rid,
                "seed": stream.seed,
                "event_count": len(stream.events),
                "use_llm": use_llm,
                "total_at_risk_minor": stream.total_at_risk_minor,
                "ambiguous_ratio": stream.ambiguous_ratio,
                "cause_histogram": stream.cause_histogram(),
            },
        )

    for arm, metrics in ((Arm.AGENT, agent), (Arm.BASELINE, baseline)):
        # A fresh engine per arm. Guardrail state (attempt counters, nudge history) must
        # not leak across arms, or the second one inherits the first one's caps.
        engine = PolicyEngine()
        sequence = 0

        for index, event in enumerate(stream.events):
            payment = stream.payments[event.payment_id]
            method = stream.methods[payment.method_id]
            customer = stream.customers[payment.customer_id]
            latent = stream.latent[event.id]

            result = await run_case(
                run_id=rid,
                arm=arm,
                event=event,
                payment=payment,
                customer=customer,
                method=method,
                latent=latent,
                engine=engine,
                classifier=classifier,
                use_llm=use_llm and arm is Arm.AGENT,
                sequence_start=sequence,
            )
            sequence += len(result.decisions) + 1

            metrics.add(result)
            cases[arm.value].append(result)

            cause = latent.true_root_cause
            bucket = by_cause.setdefault(
                cause.value,
                CauseComparison(cause=cause.value, label=TAXONOMY[cause].label),
            )
            if arm is Arm.AGENT:
                bucket.cases += 1
                bucket.at_risk_minor += payment.amount_minor
                bucket.agent_recovered += 1 if result.recovered else 0
                bucket.agent_minor += result.recovered_amount_minor
                bucket.agent_charges += result.charge_attempts
                bucket.agent_touches += result.customer_touches
                bucket.recoverable_cases += 1 if result.recoverable_in_principle else 0
                if result.diagnosis_correct is not None:
                    bucket.classified_total += 1
                    bucket.classified_correctly += 1 if result.diagnosis_correct else 0
                if record_ledger:
                    for decision in result.decisions:
                        chain.append_decision(decision)
                    for attempt in result.attempts:
                        chain.append_attempt(attempt)
            else:
                bucket.baseline_recovered += 1 if result.recovered else 0
                bucket.baseline_minor += result.recovered_amount_minor
                bucket.baseline_charges += result.charge_attempts
                bucket.baseline_touches += result.customer_touches

            if progress and index % 25 == 0:
                progress(index, len(stream.events))

    ordered = [by_cause[c.value] for c in RootCause if c.value in by_cause]

    result = SimulationResult(
        run_id=rid,
        label=label or f"{len(stream.events)} events, seed {stream.seed}",
        seed=stream.seed,
        event_count=len(stream.events),
        created_at=started.isoformat().replace("+00:00", "Z"),
        used_llm=use_llm,
        total_at_risk_minor=stream.total_at_risk_minor,
        ambiguous_ratio=stream.ambiguous_ratio,
        agent=agent,
        baseline=baseline,
        by_cause=ordered,
        cases=cases,
        classifier_stats=(classifier.stats() if classifier else {}),
        duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    )

    if record_ledger:
        chain.append(
            kind="run_close",
            run_id=rid,
            arm="",
            subject_id=rid,
            summary=result.statement(),
            payload={
                "run_id": rid,
                "headline": result.headline(),
                "plan_target": result.meets_plan_target(),
                "agent": agent.to_dict(),
                "baseline": baseline.to_dict(),
            },
        )

    return result


def run_simulation_sync(**kwargs) -> SimulationResult:
    """Convenience for scripts and tests."""
    return asyncio.run(run_simulation(**kwargs))
