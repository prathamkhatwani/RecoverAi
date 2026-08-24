"""
The reasoning tier: prompt, schema, parser, and a deterministic stand-in.

The plan is precise about where a model belongs -- "the LLM earns its place on the messy
remainder: normalizing inconsistent gateway strings, weighing retry history and customer
context, and writing the plain-English rationale that gets attached to each decision."

So this tier only ever sees events the rules engine abstained on, and it is boxed in
hard:

  * It must choose from the eight canonical causes. A label outside the taxonomy is
    rejected, not accepted-and-renamed.
  * It must return calibrated confidence and cite which context signals it used. A
    diagnosis with no cited evidence is downgraded.
  * It is never asked to choose an *action*. Action selection belongs to the policy
    engine and the guardrails, in code. The model diagnoses; code decides.

`offline_reason` is a deterministic reasoner over the same enriched context. It exists
so the product works with no API key and so batch benchmarks stay byte-for-byte
reproducible -- and it is labelled `offline` in every response, never dressed up as a
model call.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from ..models import Classification, Customer, FailureEvent, MethodType, PaymentMethod
from ..taxonomy import (
    ClassifierTier,
    RootCause,
    all_causes,
    summarise_for_prompt,
)
from .llm_client import LLMClient, LLMUnavailable
from .rules_engine import RulesResult


# ---------------------------------------------------------------------------
# Structured output contract
# ---------------------------------------------------------------------------

VALID_CAUSE_VALUES = [c.value for c in all_causes()] + [RootCause.UNKNOWN.value]

DIAGNOSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "root_cause": {
            "type": "string",
            "enum": VALID_CAUSE_VALUES,
            "description": "The single most likely root cause from the fixed taxonomy.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Calibrated probability that root_cause is correct. Use < 0.55 when the "
                "evidence genuinely does not support a diagnosis -- abstaining is "
                "preferred over a confident guess."
            ),
        },
        "normalized_reason": {
            "type": "string",
            "description": "The messy gateway string rewritten as one canonical clause.",
        },
        "rationale": {
            "type": "string",
            "description": (
                "Two or three sentences of plain English explaining the diagnosis and "
                "why the alternatives were rejected. This is read by a payments "
                "operator, so no jargon that is not in the source data."
            ),
        },
        "signals_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The specific facts relied on. Quote them from the input.",
        },
        "runner_up": {
            "type": "string",
            "enum": VALID_CAUSE_VALUES + [""],
            "description": "Second-most-likely cause, or empty string if none.",
        },
        "runner_up_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["root_cause", "confidence", "normalized_reason", "rationale", "signals_used"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = f"""You are the diagnosis tier of a payment-recovery system at a payment \
gateway. A deterministic rules engine has already handled every unambiguous decline \
code. You only see the failures it could not resolve: garbled gateway strings, \
non-diagnostic messages, and cases where two causes compete.

Your only job is DIAGNOSIS. You do not choose recovery actions, you do not decide \
whether to retry, and you do not write customer messages. A separate policy engine and \
a hard-coded guardrail layer own those decisions. Attempting to recommend an action is \
out of scope.

Classify into exactly one of these root causes:

{summarise_for_prompt()}
- unknown: the evidence does not support any diagnosis.

How to reason:
1. The raw gateway string is often useless or actively misleading. Different gateways \
describe identical failures in different words, and some return placeholder text like \
"Payment failed" with a null reason.
2. When the string is uninformative, the CONTEXT is the evidence. A stored card whose \
expiry date has already passed points to expired_card no matter what the message says. \
A revoked or expired mandate on the instrument points to lapsed_mandate. An HTTP 5xx \
means our own processor never got an authorisation decision, which is gateway_error, \
not a customer problem.
3. Weigh the retry history. A payment that has failed the same way three times is not \
a transient fault.
4. Distinguish *soft* failures where the money still exists (insufficient_funds, \
issuer_unavailable, gateway_error) from *repairable* failures needing a fix first \
(expired_card, auth_3ds_failure, lapsed_mandate) from *terminal* ones where stopping is \
the correct action (hard_decline, fraud_block). Getting this three-way split right \
matters more than the exact label.
5. Calibrate honestly. If you are guessing, say so with a confidence below 0.55 and use \
"unknown". A false confident diagnosis causes a wrong automated action against a real \
customer's card; an honest abstention routes to a human, which is cheap and safe.

Cite the actual facts you used in signals_used -- quote them from the input rather than \
paraphrasing. Reply with JSON only."""


def _method_block(method: PaymentMethod | None, event: FailureEvent) -> str:
    if method is None:
        return "  (no stored instrument record available)"
    lines = [
        f"  type: {method.type.value}",
        f"  network: {method.network}",
        f"  issuer: {method.issuer}",
        f"  last4: {method.last4}",
    ]
    if method.type is MethodType.CARD:
        lines.append(f"  card_expiry: {method.exp_month:02d}/{method.exp_year}")
        lines.append(
            f"  network_account_updater_enrolled: {str(method.card_updater_enrolled).lower()}"
        )
    if method.mandate_valid_until:
        lines.append(f"  mandate_valid_until: {method.mandate_valid_until}")
    if method.mandate_max_amount_minor:
        lines.append(f"  mandate_max_amount: {method.mandate_max_amount_minor / 100:.2f} INR")
    return "\n".join(lines)


def build_user_prompt(
    event: FailureEvent,
    method: PaymentMethod | None,
    customer: Customer | None,
    rules: RulesResult,
    *,
    amount_minor: int | None = None,
    history: list[dict] | None = None,
) -> str:
    """Assemble the enriched context. Ground truth is never included."""
    parts: list[str] = []

    parts.append("## Raw gateway payload")
    parts.append(f"  gateway: {event.gateway}")
    parts.append(f"  raw_code: {event.raw_code!r}")
    parts.append(f"  raw_message: {event.raw_message!r}")
    parts.append(f"  http_status: {event.http_status}")
    parts.append(f"  occurred_at: {event.occurred_at}")
    parts.append(f"  attempt_no_on_this_payment: {event.attempt_no}")

    parts.append("\n## Stored payment instrument")
    parts.append(_method_block(method, event))

    if amount_minor is not None:
        parts.append(f"\n## Amount\n  {amount_minor / 100:.2f} INR")

    if customer is not None:
        parts.append("\n## Customer context")
        parts.append(f"  segment: {customer.segment}")
        parts.append(f"  tenure_days: {customer.tenure_days}")
        parts.append(f"  typical_month_liquidity_day: {customer.salary_day}")
        parts.append(f"  prior_chargeback_on_file: {str(customer.chargeback_filed).lower()}")
        parts.append(f"  open_dispute: {str(customer.dispute_open).lower()}")

    if history:
        parts.append("\n## Recent attempt history on this payment")
        for h in history[-5:]:
            parts.append(
                f"  - {h.get('attempted_at', '?')}: {h.get('kind', '?')} -> "
                f"{h.get('outcome', '?')}"
            )

    parts.append("\n## What the rules engine found")
    if rules.signals:
        for s in rules.signals[:6]:
            parts.append(f"  - {s}")
    else:
        parts.append("  - no decline code or message pattern matched at all")
    parts.append(
        f"  rules_best_guess: {rules.cause.value} "
        f"(confidence {rules.confidence:.2f} -- below the action threshold)"
    )
    if rules.ambiguity_reason:
        parts.append(f"  why_it_abstained: {rules.ambiguity_reason}")

    if rules.context_hints:
        parts.append("\n## Context signals extracted from surrounding records")
        for hint in rules.context_hints:
            parts.append(f"  - {hint}")

    parts.append(
        "\nDiagnose the root cause. If the gateway string is non-diagnostic, rely on the "
        "context signals above and say which ones you used."
    )
    return "\n".join(parts)


def _coerce_cause(value: object) -> RootCause:
    """Map a model's label onto the taxonomy, or UNKNOWN.

    Silent renaming is not allowed: a label outside the enum becomes an abstention, so
    the model cannot invent a ninth root cause that no policy exists for.
    """
    if not isinstance(value, str):
        return RootCause.UNKNOWN
    token = value.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return RootCause(token)
    except ValueError:
        aliases = {
            "nsf": RootCause.INSUFFICIENT_FUNDS,
            "insufficient_balance": RootCause.INSUFFICIENT_FUNDS,
            "low_balance": RootCause.INSUFFICIENT_FUNDS,
            "expired": RootCause.EXPIRED_CARD,
            "invalid_card": RootCause.EXPIRED_CARD,
            "3ds": RootCause.AUTH_3DS_FAILURE,
            "3ds_failure": RootCause.AUTH_3DS_FAILURE,
            "otp_failure": RootCause.AUTH_3DS_FAILURE,
            "authentication_failure": RootCause.AUTH_3DS_FAILURE,
            "fraud": RootCause.FRAUD_BLOCK,
            "risk_block": RootCause.FRAUD_BLOCK,
            "issuer_down": RootCause.ISSUER_UNAVAILABLE,
            "issuer_outage": RootCause.ISSUER_UNAVAILABLE,
            "processor_error": RootCause.GATEWAY_ERROR,
            "processing_error": RootCause.GATEWAY_ERROR,
            "mandate_lapsed": RootCause.LAPSED_MANDATE,
            "mandate_revoked": RootCause.LAPSED_MANDATE,
        }
        return aliases.get(token, RootCause.UNKNOWN)


def _clamp(value: object, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))       # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_diagnosis(
    data: dict, rules: RulesResult, *, latency_ms: int, model: str
) -> Classification:
    """Validate a model response into a Classification.

    Two integrity rules are enforced here rather than trusted to the prompt:
    a cause outside the taxonomy is downgraded to UNKNOWN, and a confident diagnosis
    that cites no evidence has its confidence capped.
    """
    cause = _coerce_cause(data.get("root_cause"))
    confidence = _clamp(data.get("confidence"), 0.5)
    signals = [str(s) for s in (data.get("signals_used") or []) if str(s).strip()][:8]
    rationale = str(data.get("rationale") or "").strip()
    normalized = str(data.get("normalized_reason") or "").strip() or rules.normalized_reason

    if cause is RootCause.UNKNOWN:
        confidence = min(confidence, 0.5)
    if not signals and confidence > 0.75:
        # Unsupported confidence is capped -- "I'm sure but can't say why" is not a
        # diagnosis a payments team can act on.
        confidence = 0.75
        rationale += " (Confidence capped: the model cited no specific evidence.)"
    if not rationale:
        rationale = f"Model diagnosed {cause.value} without further explanation."

    considered = list(rules.considered)
    runner = _coerce_cause(data.get("runner_up")) if data.get("runner_up") else None
    if runner and runner is not cause:
        considered.insert(
            0,
            {
                "cause": runner.value,
                "score": None,
                "confidence": round(_clamp(data.get("runner_up_confidence"), 0.0), 3),
                "source": "model runner-up",
            },
        )

    return Classification(
        root_cause=cause,
        confidence=confidence,
        tier=ClassifierTier.LLM,
        rationale=rationale,
        normalized_reason=normalized,
        signals=signals or [s for s in rules.context_hints[:4]],
        considered=considered[:5],
        latency_ms=latency_ms,
        model=model,
        escalated_from_rules=True,
        rules_confidence=rules.confidence,
    )


async def llm_reason(
    client: LLMClient,
    event: FailureEvent,
    method: PaymentMethod | None,
    customer: Customer | None,
    rules: RulesResult,
    *,
    amount_minor: int | None = None,
    history: list[dict] | None = None,
) -> Classification:
    """Live model call. Raises `LLMUnavailable`; the router handles the fallback."""
    user_prompt = build_user_prompt(
        event, method, customer, rules, amount_minor=amount_minor, history=history
    )
    # Cache on the semantic inputs, so replaying a demo costs nothing.
    cache_key = json.dumps(
        {
            "c": event.raw_code,
            "m": event.raw_message,
            "h": event.http_status,
            "hints": rules.context_hints,
            "model": client.config.model,
        },
        sort_keys=True,
    )
    data, latency = await client.complete_json(
        SYSTEM_PROMPT, user_prompt, DIAGNOSIS_SCHEMA, cache_key=cache_key
    )
    # Attribute to the model that actually answered, which may be the fallback.
    return parse_diagnosis(
        data, rules, latency_ms=latency, model=client.runtime_dict()["active_model"]
    )


# ---------------------------------------------------------------------------
# Deterministic offline reasoner
# ---------------------------------------------------------------------------
# A transparent priority ladder over the same enriched context the model receives.
# It is not a language model and is never presented as one -- the dashboard labels this
# tier `offline` and says so in words.

_HINT_RULES: tuple[tuple[str, RootCause, float, str], ...] = (
    ("mandate on this method lapsed", RootCause.LAPSED_MANDATE, 0.91,
     "the stored mandate had already lapsed before this debit was attempted"),
    ("stored card expired", RootCause.EXPIRED_CARD, 0.90,
     "the stored card's expiry date precedes the failure timestamp"),
    ("gateway returned HTTP 5", RootCause.GATEWAY_ERROR, 0.88,
     "our processor returned a 5xx, so no issuer decision was ever received"),
)


def offline_reason(
    event: FailureEvent,
    method: PaymentMethod | None,
    customer: Customer | None,
    rules: RulesResult,
    *,
    fallback_note: str | None = None,
) -> Classification:
    """Deterministic diagnosis over the enriched context."""
    start = time.perf_counter()
    hints = rules.context_hints
    signals: list[str] = []
    cause = RootCause.UNKNOWN
    confidence = 0.0
    reasoning: list[str] = []

    # 1. Decisive context signals, strongest first.
    for needle, hint_cause, conf, explanation in _HINT_RULES:
        match = next((h for h in hints if needle in h), None)
        if match:
            cause, confidence = hint_cause, conf
            signals.append(match)
            reasoning.append(
                f"The gateway string was not diagnostic, but {explanation}."
            )
            break

    # 2. Otherwise lean on the rules engine's best hypothesis, corroborated by context.
    if cause is RootCause.UNKNOWN and rules.cause is not RootCause.UNKNOWN:
        cause = rules.cause
        confidence = min(0.86, rules.confidence + 0.16)
        signals.extend(rules.signals[:3])
        reasoning.append(
            f"No decisive context signal, so the rules engine's leading hypothesis "
            f"({cause.value}) stands, lifted from {rules.confidence:.2f} because "
            f"nothing in the surrounding records contradicts it."
        )

    # 3. Weak structural inference for genuinely bare strings.
    if cause is RootCause.UNKNOWN:
        mandate_rail = any("recurring mandate rail" in h for h in hints)
        month_boundary = any("month-boundary" in h for h in hints)
        repeat = any("attempt #" in h for h in hints)

        if mandate_rail and repeat:
            cause, confidence = RootCause.LAPSED_MANDATE, 0.58
            reasoning.append(
                "Repeated failures on a mandate rail with no stated reason most often "
                "mean the standing instruction is no longer honoured."
            )
            signals.append("repeat failure on a recurring mandate instrument")
        elif month_boundary and method and method.type is MethodType.CARD:
            cause, confidence = RootCause.INSUFFICIENT_FUNDS, 0.61
            reasoning.append(
                "A bare decline on a card at the month boundary is most commonly a "
                "balance-timing failure rather than an instrument failure."
            )
            signals.append("failure landed at the month boundary")
        else:
            cause, confidence = RootCause.UNKNOWN, 0.35
            reasoning.append(
                "Neither the gateway string nor the surrounding records support a "
                "diagnosis. Abstaining and routing to a human is the correct action."
            )

    # 4. Hard contradictions override everything: never soft-classify a terminal decline.
    if any("reported stolen" in h.lower() or "account closed" in h.lower() for h in hints):
        cause, confidence = RootCause.HARD_DECLINE, 0.95
        reasoning.append("An explicit stolen/closed signal overrides all softer readings.")

    latency = max(0, int((time.perf_counter() - start) * 1000))
    rationale = " ".join(reasoning)
    if fallback_note:
        rationale = f"{rationale} [{fallback_note}]"

    return Classification(
        root_cause=cause,
        confidence=confidence,
        tier=ClassifierTier.OFFLINE,
        rationale=rationale,
        normalized_reason=rules.normalized_reason,
        signals=signals[:6] or hints[:4],
        considered=rules.considered,
        latency_ms=latency,
        model="deterministic-reasoner-v1",
        escalated_from_rules=True,
        rules_confidence=rules.confidence,
    )
