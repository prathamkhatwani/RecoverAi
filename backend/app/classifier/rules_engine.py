"""
Rules-based first pass.

"Rules handle the majority of decline codes, which are unambiguous; the LLM earns its
place on the messy remainder."

This tier is deterministic, sub-millisecond, free, and fully explainable. It runs on
every event and reports both a cause and a calibrated confidence. When confidence sits
below the escalation floor, it *abstains* and hands the event upward -- abstention is a
first-class outcome here, not a failure.

Three evidence sources, in descending order of trust:

  1. Exact decline-code registry hit           -> very high confidence
  2. Message-phrase patterns                   -> high confidence
  3. Context signals (expiry date, mandate     -> corroborating only; never enough on
     validity, HTTP status, attempt history)      their own to reach the act threshold

Every contributing signal is recorded so the decision explorer can show the reader
exactly which piece of evidence carried the classification.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import Classification, FailureEvent, MethodType, PaymentMethod
from ..taxonomy import (
    ClassifierTier,
    RootCause,
    is_ambiguous_code,
    lookup_code,
    normalise_token,
)


# Below this, the rules tier abstains and the event escalates to the reasoning tier.
ESCALATION_THRESHOLD = 0.72

# Below this, no tier is allowed to drive an action; the event goes to human review.
ACT_THRESHOLD = 0.55


@dataclass(frozen=True)
class Pattern:
    """One message-phrase rule."""

    cause: RootCause
    regex: re.Pattern[str]
    weight: float
    label: str


def _p(cause: RootCause, pattern: str, weight: float, label: str) -> Pattern:
    return Pattern(cause, re.compile(pattern, re.IGNORECASE), weight, label)


# ---------------------------------------------------------------------------
# Message patterns
# ---------------------------------------------------------------------------
# Ordered by specificity within each cause. Weights are evidence strength, not
# probability -- they are combined and then squashed into a confidence.

PATTERNS: tuple[Pattern, ...] = (
    # --- hard decline (checked first: most consequential to get right) -----
    _p(RootCause.HARD_DECLINE, r"\bstolen\b", 0.95, "message says 'stolen'"),
    _p(RootCause.HARD_DECLINE, r"\blost card\b|\blost_card\b", 0.92, "message says 'lost card'"),
    _p(RootCause.HARD_DECLINE, r"do[\s_-]*not[\s_-]*hono[u]?r", 0.90, "'do not honour'"),
    _p(RootCause.HARD_DECLINE, r"pick[\s_-]*up[\s_-]*card|capture card|card be retained", 0.90, "issuer asked to retain card"),
    _p(RootCause.HARD_DECLINE, r"account[\s_-]*closed|closed account", 0.90, "account closed"),
    _p(RootCause.HARD_DECLINE, r"blocked first use|card[\s_-]*blocked|never activated", 0.85, "card blocked / not activated"),
    _p(RootCause.HARD_DECLINE, r"card[\s_-]*not[\s_-]*supported|restricted card", 0.80, "instrument not permitted"),

    # --- fraud / risk ------------------------------------------------------
    _p(RootCause.FRAUD_BLOCK, r"fraud", 0.90, "message mentions fraud"),
    _p(RootCause.FRAUD_BLOCK, r"risk (engine|rules?|filter)|radar_rule|risk[\s_-]*block", 0.88, "risk engine / filter hit"),
    _p(RootCause.FRAUD_BLOCK, r"security violation", 0.85, "security violation"),
    _p(RootCause.FRAUD_BLOCK, r"velocity[\s_-]*\w*|review_required=true", 0.72, "velocity rule / review flag"),

    # --- insufficient funds -----------------------------------------------
    _p(RootCause.INSUFFICIENT_FUNDS, r"insuff|not sufficient|\bnsf\b", 0.93, "insufficient funds phrase"),
    _p(RootCause.INSUFFICIENT_FUNDS, r"low balance|insufficient balance|not enough balance", 0.93, "low balance phrase"),
    _p(RootCause.INSUFFICIENT_FUNDS, r"withdrawal limit|limit exceeded|exceeds.*limit", 0.80, "limit exceeded"),
    _p(RootCause.INSUFFICIENT_FUNDS, r"adding funds|add funds", 0.70, "advises adding funds"),

    # --- expired / invalid card -------------------------------------------
    _p(RootCause.EXPIRED_CARD, r"expired", 0.90, "message says 'expired'"),
    _p(RootCause.EXPIRED_CARD, r"card[\s_-]*exp\b|exp[\s_-]*date|card_exp=", 0.85, "expiry field referenced"),
    _p(RootCause.EXPIRED_CARD, r"invalid card (number|details)|incorrect_number", 0.78, "invalid card number"),
    _p(RootCause.EXPIRED_CARD, r"action=update_card|update your card", 0.80, "gateway advises card update"),

    # --- 3DS / OTP --------------------------------------------------------
    _p(RootCause.AUTH_3DS_FAILURE, r"\b3ds\b|3[\s_-]*d[\s_-]*secure|acs_timeout", 0.90, "3DS referenced"),
    _p(RootCause.AUTH_3DS_FAILURE, r"\botp\b", 0.90, "OTP referenced"),
    _p(RootCause.AUTH_3DS_FAILURE, r"authentication (could not|failed|required|not completed)", 0.86, "authentication not completed"),
    _p(RootCause.AUTH_3DS_FAILURE, r"\bsca\b|additional customer auth|customer auth required", 0.85, "SCA / additional auth required"),
    _p(RootCause.AUTH_3DS_FAILURE, r"challenge not completed", 0.88, "challenge abandoned"),

    # --- issuer unavailable ----------------------------------------------
    _p(RootCause.ISSUER_UNAVAILABLE, r"issuer (or switch )?(inoperative|unavail|not available|down)", 0.92, "issuer inoperative"),
    # Terminal-width abbreviations. Real acquirer feeds truncate aggressively and
    # "ISS UNAVAIL" is not a lesser signal than the same words spelled out.
    _p(RootCause.ISSUER_UNAVAILABLE, r"\biss\b[\s_-]*unavail|\bissuer\b[\s_-]*unav", 0.92, "issuer unavailable (abbreviated)"),
    _p(RootCause.ISSUER_UNAVAILABLE, r"switch[\s_-]*(inop|unavail|down)|\bhost\b[\s_-]*(down|unavail)", 0.90, "switch/host down"),
    _p(RootCause.ISSUER_UNAVAILABLE, r"issuer could not be reached|bank (server )?(down|did not respond)", 0.90, "issuer unreachable"),
    _p(RootCause.ISSUER_UNAVAILABLE, r"system malfunction", 0.85, "system malfunction"),
    _p(RootCause.ISSUER_UNAVAILABLE, r"maintenance", 0.72, "bank maintenance window"),
    _p(RootCause.ISSUER_UNAVAILABLE, r"retry[\s_-]*(shortly|after)|retry_after=", 0.55, "gateway suggests retry"),

    # --- gateway / processing --------------------------------------------
    _p(RootCause.GATEWAY_ERROR, r"upstream (connection )?(reset|=?5\d\d)", 0.90, "upstream 5xx / reset"),
    _p(RootCause.GATEWAY_ERROR, r"\b50[0-4]\b|service unavailable|internal (switch )?error", 0.88, "processor 5xx"),
    _p(RootCause.GATEWAY_ERROR, r"timeout at processor|no auth decision", 0.88, "no authorisation decision received"),
    _p(RootCause.GATEWAY_ERROR, r"error occurred while processing|could not process the payment", 0.62, "generic processing error"),
    _p(RootCause.GATEWAY_ERROR, r"unexpected response from upstream|body_truncated", 0.58, "malformed upstream response"),

    # --- mandate ---------------------------------------------------------
    _p(RootCause.LAPSED_MANDATE, r"mandate (revoked|expired|not found)", 0.94, "mandate revoked/expired"),
    _p(RootCause.LAPSED_MANDATE, r"standing instruction|\bsi expired\b", 0.90, "standing instruction gone"),
    _p(RootCause.LAPSED_MANDATE, r"autopay.*revok|revok.*payer", 0.92, "autopay mandate revoked by payer"),
    _p(RootCause.LAPSED_MANDATE, r"enach|\bnach\b", 0.60, "eNACH rail referenced"),
    _p(RootCause.LAPSED_MANDATE, r"subscription (cancelled|canceled)|no longer active", 0.82, "subscription/mandate inactive"),
    _p(RootCause.LAPSED_MANDATE, r"action=re_register|re-?register", 0.80, "gateway advises re-registration"),
)


# Embedded ISO codes: gateways bury the real code inside prose ("rc=51", "ERR_54").
_CODE_IN_MESSAGE = (
    re.compile(r"\brc\s*=\s*([0-9a-z]{1,4})\b", re.IGNORECASE),
    re.compile(r"\berr[_-]?([0-9]{2,3}[a-z]?)\b", re.IGNORECASE),
    re.compile(r"\brc-([0-9]{2,3})\b", re.IGNORECASE),
    re.compile(r"\bcode[:\s=]+([0-9]{2,3})\b", re.IGNORECASE),
)

_HTTP_IN_MESSAGE = re.compile(r"\b(upstream|status|returned)\D{0,12}(50[0-4])\b", re.IGNORECASE)

# House prefixes gateways bolt onto an otherwise standard ISO 8583 code.
_CODE_PREFIX = re.compile(
    r"^(rc|err|error|code|resp|response|decline|dc|sc|status)[\s_:\-]*", re.IGNORECASE
)


def _code_variants(raw: str) -> list[str]:
    """Plausible registry keys for a gateway's own spelling of a decline code.

    `RC-91` -> `91`; `ERR_54A` -> `54A`, `54`. Ordered most-specific-first so an exact
    alphanumeric match wins over its numeric stem.
    """
    token = (raw or "").strip()
    if not token:
        return []
    out: list[str] = []
    stripped = _CODE_PREFIX.sub("", token).strip(" _-:")
    for candidate in (stripped, stripped.upper(), stripped.lstrip("0")):
        if candidate and candidate != token and candidate not in out:
            out.append(candidate)
    digits = re.match(r"^([0-9]{2,3})", stripped)
    if digits and digits.group(1) not in out and digits.group(1) != token:
        out.append(digits.group(1))
    return out

# Strings that explicitly assert nothing. Matching one is positive evidence that the
# message is non-diagnostic, which suppresses weak pattern noise instead of letting it
# masquerade as a real signal.
_NULL_REASON = re.compile(
    r"bank_reason:\s*(null|none|)\s*(::|$)|rc=\s*(::|$)|no reason supplied|"
    r"contact (your bank|support|your card issuer)|refer to issuer",
    re.IGNORECASE,
)

_GENERIC_DECLINE = re.compile(
    r"^\s*(decline[d]?|txn not approved|generic_decline|card_declined|"
    r"auth failed|payment failed|txn unsuccessful|the card was declined\.?|"
    r"transaction could not be completed)\s*\.?\s*$",
    re.IGNORECASE,
)


@dataclass
class RulesResult:
    """Outcome of the rules pass, including the abstain decision."""

    cause: RootCause
    confidence: float
    signals: list[str]
    considered: list[dict]
    normalized_reason: str
    should_escalate: bool
    ambiguity_reason: str | None
    context_hints: list[str]


def _squash(score: float) -> float:
    """Map accumulated evidence to a bounded confidence.

    Two independent 0.9 signals should read as "very sure" without ever reaching a
    dishonest 1.0, so this saturates smoothly and caps at 0.985.
    """
    return min(0.985, 1.0 - (1.0 - min(score, 0.99)) ** 1.35)


def _clean_message(raw: str) -> str:
    """Canonicalise a gateway string for display and for prompt input."""
    text = " ".join(raw.strip().split())
    if text.isupper() and len(text) > 12:
        text = text.capitalize()
    return text


def _extract_embedded_codes(message: str) -> list[str]:
    found: list[str] = []
    for rx in _CODE_IN_MESSAGE:
        for m in rx.finditer(message):
            token = m.group(1)
            if token and token.lower() not in ("u30", "xx", ""):
                found.append(token)
    m = _HTTP_IN_MESSAGE.search(message)
    if m:
        found.append(m.group(2))
    return found


def collect_context_hints(
    event: FailureEvent,
    method: PaymentMethod | None,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Corroborating facts from surrounding records.

    Deliberately never sufficient on their own: an expired-looking expiry date is
    suggestive, not conclusive. These hints raise a hypothesis and are handed to the
    reasoning tier, which is what lets it crack "Payment failed :: bank_reason: null".
    """
    hints: list[str] = []
    if method is None:
        return hints

    ref = now or datetime.now(timezone.utc)

    if method.type is MethodType.CARD:
        # Last moment of the expiry month.
        exp_end = datetime(
            method.exp_year + (1 if method.exp_month == 12 else 0),
            1 if method.exp_month == 12 else method.exp_month + 1,
            1, tzinfo=timezone.utc,
        )
        if exp_end <= ref:
            hints.append(
                f"stored card expired {method.exp_month:02d}/{method.exp_year} "
                f"(before the failure timestamp)"
            )
        elif (exp_end - ref).days < 45:
            hints.append(f"stored card expires soon ({method.exp_month:02d}/{method.exp_year})")

    if method.mandate_valid_until:
        try:
            until = datetime.fromisoformat(method.mandate_valid_until.replace("Z", "+00:00"))
            if until <= ref:
                hints.append(f"mandate on this method lapsed on {until.date().isoformat()}")
        except ValueError:
            pass

    if method.type in (MethodType.UPI_AUTOPAY, MethodType.ENACH):
        hints.append(f"instrument is a recurring mandate rail ({method.type.value})")

    if method.type is MethodType.CARD and not method.card_updater_enrolled:
        hints.append(f"{method.network} BIN is not enrolled in network account updater")

    if event.http_status and event.http_status >= 500:
        hints.append(f"gateway returned HTTP {event.http_status} (our side, no issuer decision)")

    if event.attempt_no >= 3:
        hints.append(f"this is attempt #{event.attempt_no} on the same payment")

    try:
        occurred = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
        if occurred.day >= 26 or occurred.day <= 3:
            hints.append(f"failure landed on day {occurred.day} of the month (month-boundary)")
    except ValueError:
        pass

    return hints


def classify_with_rules(
    event: FailureEvent,
    method: PaymentMethod | None = None,
    *,
    now: datetime | None = None,
) -> RulesResult:
    """Run the deterministic first pass. Never raises; abstains instead."""
    message = _clean_message(event.raw_message)
    raw_code = (event.raw_code or "").strip()
    scores: dict[RootCause, float] = {}
    signals: list[str] = []

    non_diagnostic = bool(_NULL_REASON.search(message) or _GENERIC_DECLINE.match(message))

    # --- 1. exact code registry ------------------------------------------
    # The code field gets the same normalisation the message body does. Gateways wrap
    # the same ISO value in house prefixes ("RC-91", "ERR_51", "rc-99"), and without
    # this the registry resolved `rc=91` buried in prose while missing `RC-91` sitting
    # in the dedicated code field -- treating the structured field as more opaque than
    # the unstructured one, which is backwards.
    code_cause = lookup_code(raw_code)
    matched_code = raw_code
    if not code_cause and raw_code:
        for variant in _code_variants(raw_code):
            candidate = lookup_code(variant)
            if candidate:
                code_cause, matched_code = candidate, variant
                break
    if code_cause:
        scores[code_cause] = scores.get(code_cause, 0.0) + 0.94
        detail = (
            f"decline code `{raw_code}` maps to {code_cause.value} in the registry"
            if matched_code == raw_code
            else f"decline code `{raw_code}` normalises to `{matched_code}` "
                 f"-> {code_cause.value} in the registry"
        )
        signals.append(detail)
    elif is_ambiguous_code(raw_code) or any(
        is_ambiguous_code(v) for v in _code_variants(raw_code)
    ):
        non_diagnostic = True
        signals.append(f"code `{raw_code}` is registered but non-diagnostic")

    # --- 2. codes buried in prose ----------------------------------------
    for token in _extract_embedded_codes(message):
        embedded = lookup_code(token)
        if embedded:
            scores[embedded] = scores.get(embedded, 0.0) + 0.80
            signals.append(f"code `{token}` extracted from message text -> {embedded.value}")

    # --- 3. message phrase patterns --------------------------------------
    for pat in PATTERNS:
        if pat.regex.search(message):
            weight = pat.weight
            # A phrase hit inside an explicitly reason-less string is far weaker.
            if non_diagnostic:
                weight *= 0.45
            scores[pat.cause] = scores.get(pat.cause, 0.0) + weight
            signals.append(f"{pat.label} -> {pat.cause.value}")

    # --- 4. HTTP status --------------------------------------------------
    if event.http_status and event.http_status >= 500:
        scores[RootCause.GATEWAY_ERROR] = scores.get(RootCause.GATEWAY_ERROR, 0.0) + 0.78
        signals.append(f"HTTP {event.http_status} from processor -> gateway_error")

    context_hints = collect_context_hints(event, method, now=now)

    if not scores:
        return RulesResult(
            cause=RootCause.UNKNOWN,
            confidence=0.0,
            signals=signals,
            considered=[],
            normalized_reason=message,
            should_escalate=True,
            ambiguity_reason="no decline code or message pattern matched",
            context_hints=context_hints,
        )

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top_cause, top_score = ranked[0]
    confidence = _squash(top_score)

    # A close second means genuine ambiguity between two causes, so shrink confidence
    # toward the escalation floor rather than pretending the margin was decisive.
    if len(ranked) > 1:
        margin = top_score - ranked[1][1]
        if margin < 0.25:
            confidence *= 0.72 + margin
        # Contradictory evidence (e.g. hard decline vs insufficient funds) is exactly
        # the case worth spending a model call on.
        if margin < 0.12:
            confidence = min(confidence, 0.66)

    if non_diagnostic:
        confidence = min(confidence, 0.60)

    considered = [
        {"cause": c.value, "score": round(s, 3), "confidence": round(_squash(s), 3)}
        for c, s in ranked[:4]
    ]

    ambiguity_reason: str | None = None
    if non_diagnostic:
        ambiguity_reason = "gateway string is non-diagnostic (no usable reason supplied)"
    elif confidence < ESCALATION_THRESHOLD and len(ranked) > 1:
        ambiguity_reason = (
            f"competing hypotheses: {ranked[0][0].value} vs {ranked[1][0].value}"
        )
    elif confidence < ESCALATION_THRESHOLD:
        ambiguity_reason = "single weak signal, below the confidence floor"

    return RulesResult(
        cause=top_cause,
        confidence=confidence,
        signals=signals,
        considered=considered,
        normalized_reason=message,
        should_escalate=confidence < ESCALATION_THRESHOLD,
        ambiguity_reason=ambiguity_reason,
        context_hints=context_hints,
    )


def to_classification(event: FailureEvent, result: RulesResult, latency_ms: int) -> Classification:
    """Wrap a confident rules result as a pipeline Classification."""
    top = result.signals[0] if result.signals else "no signal"
    rationale = (
        f"Deterministic match: {top}. "
        f"Gateway `{event.gateway}` reported code `{event.raw_code}`. "
        f"No model call needed -- this decline code is unambiguous."
    )
    return Classification(
        root_cause=result.cause,
        confidence=result.confidence,
        tier=ClassifierTier.RULES,
        rationale=rationale,
        normalized_reason=result.normalized_reason,
        signals=result.signals[:6],
        considered=result.considered,
        latency_ms=latency_ms,
        model=None,
        escalated_from_rules=False,
        rules_confidence=result.confidence,
    )


def timed_rules_pass(
    event: FailureEvent, method: PaymentMethod | None = None, *, now: datetime | None = None
) -> tuple[RulesResult, int]:
    start = time.perf_counter()
    result = classify_with_rules(event, method, now=now)
    return result, max(0, int((time.perf_counter() - start) * 1000))


def pattern_stats() -> dict:
    """Surfaced in the UI so the rules tier is inspectable, not a black box."""
    by_cause: dict[str, int] = {}
    for p in PATTERNS:
        by_cause[p.cause.value] = by_cause.get(p.cause.value, 0) + 1
    from ..taxonomy import DECLINE_CODES

    return {
        "pattern_count": len(PATTERNS),
        "code_registry_size": len(DECLINE_CODES),
        "escalation_threshold": ESCALATION_THRESHOLD,
        "act_threshold": ACT_THRESHOLD,
        "patterns_by_cause": by_cause,
        "patterns": [
            {"cause": p.cause.value, "label": p.label, "weight": p.weight,
             "regex": p.regex.pattern}
            for p in PATTERNS
        ],
    }
