"""
Three fake gateways with genuinely inconsistent decline vocabularies.

Demo step 1 is "stream in failed payments with inconsistent raw decline strings from
three fake gateways", so the inconsistency has to be real rather than cosmetic. Each
gateway here has its own code shape, its own message register, and its own idea of
where the useful information lives:

  NimbusPay  -- modern Stripe-like: snake_case symbolic codes, clean short messages.
  OrbitPG    -- legacy ISO-8583 passthrough: numeric codes with junk prefixes,
                SHOUTING abbreviations, zero-padding applied inconsistently.
  KaveriGW   -- Indian bank aggregator: verbose multi-clause strings where the real
                reason is buried behind `::` separators, plus HTTP status leakage.

A useful chunk of every gateway's output is deliberately *non-diagnostic* -- "payment
failed", "declined by bank" -- because that messy remainder is precisely where the
reasoning tier has to earn its place.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..taxonomy import RootCause


@dataclass(frozen=True)
class GatewayProfile:
    key: str
    name: str
    style: str
    share: float           # traffic share, must sum to 1.0 across profiles
    emits_http_status: bool


GATEWAYS: tuple[GatewayProfile, ...] = (
    GatewayProfile("nimbuspay", "NimbusPay", "modern symbolic", 0.42, False),
    GatewayProfile("orbitpg", "OrbitPG", "legacy ISO-8583", 0.33, False),
    GatewayProfile("kaverigw", "KaveriGW", "bank aggregator passthrough", 0.25, True),
)

GATEWAYS_BY_KEY = {g.key: g for g in GATEWAYS}


# ---------------------------------------------------------------------------
# Per-gateway, per-cause vocabularies
# ---------------------------------------------------------------------------
# Each entry is (raw_code, raw_message). Multiple variants per cause so no single
# string becomes a giveaway pattern the rules engine could overfit to.

_NIMBUS: dict[RootCause, list[tuple[str, str]]] = {
    RootCause.INSUFFICIENT_FUNDS: [
        ("insufficient_funds", "Your card has insufficient funds."),
        ("insufficient_funds", "card_declined: insufficient_funds"),
        ("card_declined", "The card was declined for insufficient funds."),
    ],
    RootCause.ISSUER_UNAVAILABLE: [
        ("issuer_not_available", "The card issuer could not be reached."),
        ("try_again_later", "processing_error: issuer unavailable, retry shortly"),
    ],
    RootCause.EXPIRED_CARD: [
        ("expired_card", "The card has expired."),
        ("expired_card", "card_declined: expired_card (exp 04/2025)"),
        ("invalid_card", "Card number or expiry is no longer valid."),
    ],
    RootCause.AUTH_3DS_FAILURE: [
        ("authentication_required", "This payment requires 3D Secure authentication."),
        ("authentication_failed", "3ds challenge not completed within 300s"),
    ],
    RootCause.FRAUD_BLOCK: [
        ("fraudulent", "The payment was blocked by our risk rules."),
        ("card_declined", "card_declined: fraudulent — radar_rule_triggered"),
    ],
    RootCause.HARD_DECLINE: [
        ("stolen_card", "The card has been reported stolen."),
        ("lost_card", "The card has been reported lost."),
        ("do_not_honor", "card_declined: do_not_honor"),
        ("pickup_card", "The issuer requested the card be retained."),
    ],
    RootCause.GATEWAY_ERROR: [
        ("processing_error", "An error occurred while processing the card."),
        ("api_connection_error", "Upstream connection reset before authorization."),
    ],
    RootCause.LAPSED_MANDATE: [
        ("subscription_cancelled", "The saved mandate is no longer active."),
        ("mandate_revoked", "setup_intent revoked by customer"),
    ],
}

_ORBIT: dict[RootCause, list[tuple[str, str]]] = {
    RootCause.INSUFFICIENT_FUNDS: [
        ("ERR_51", "NOT SUFFICIENT FUNDS"),
        ("51", "DECLINE - NSF"),
        ("061", "WITHDRAWAL LIMIT EXCEEDED"),
        ("RC-51", "INSUFF FUNDS/BAL"),
    ],
    RootCause.ISSUER_UNAVAILABLE: [
        ("ERR_91", "ISSUER OR SWITCH INOPERATIVE"),
        ("96", "SYSTEM MALFUNCTION - RETRY"),
        ("RC-91", "ISS UNAVAIL"),
    ],
    RootCause.EXPIRED_CARD: [
        ("ERR_54", "EXPIRED CARD"),
        ("54", "DECLINE - CARD EXP"),
        ("014", "INVALID CARD NUMBER"),
    ],
    RootCause.AUTH_3DS_FAILURE: [
        ("ERR_1A", "ADDL CUSTOMER AUTH REQUIRED"),
        ("1A", "SCA REQUIRED - NOT COMPLETED"),
    ],
    RootCause.FRAUD_BLOCK: [
        ("ERR_59", "SUSPECTED FRAUD"),
        ("59", "DECLINE - RISK FILTER HIT"),
        ("063", "SECURITY VIOLATION"),
    ],
    RootCause.HARD_DECLINE: [
        ("ERR_43", "STOLEN CARD - PICKUP"),
        ("41", "LOST CARD - PICKUP"),
        ("ERR_05", "DO NOT HONOUR"),
        ("07", "PICKUP CARD SPECIAL CONDITION"),
        ("078", "BLOCKED FIRST USE"),
    ],
    RootCause.GATEWAY_ERROR: [
        ("ERR_96T", "TIMEOUT AT PROCESSOR"),
        ("500", "INTERNAL SWITCH ERROR"),
    ],
    RootCause.LAPSED_MANDATE: [
        ("ERR_MANDATE", "STANDING INSTRUCTION NOT FOUND"),
        ("mandate_expired", "SI EXPIRED"),
    ],
}

_KAVERI: dict[RootCause, list[tuple[str, str]]] = {
    RootCause.INSUFFICIENT_FUNDS: [
        ("BAD_REQUEST_ERROR",
         "Payment failed :: bank_reason: Insufficient balance in account :: rc=51 :: retryable=true"),
        ("insufficient_balance",
         "Txn declined by issuing bank. Reason: low balance. Please retry after adding funds."),
        ("BAD_REQUEST_PAYMENT_FAILED",
         "gateway_response :: status=FAILED :: desc=NOT ENOUGH BALANCE :: bank=HDFC"),
    ],
    RootCause.ISSUER_UNAVAILABLE: [
        ("GATEWAY_ERROR",
         "Upstream bank did not respond :: rc=91 :: bank=SBI :: transient=true"),
        ("issuer_down",
         "Bank server down for maintenance. Reason: ISSUER UNAVAILABLE :: retry_after=900s"),
    ],
    RootCause.EXPIRED_CARD: [
        ("BAD_REQUEST_CARD_EXPIRED",
         "Card is expired :: rc=54 :: card_exp=03/2025 :: action=update_card"),
        ("card_expired",
         "Txn declined :: bank_reason: CARD EXPIRED OR INVALID :: network=VISA"),
    ],
    RootCause.AUTH_3DS_FAILURE: [
        ("payment_authentication_failed",
         "OTP not submitted by customer within timeout :: 3ds_version=2.2 :: status=N"),
        ("BAD_REQUEST_ERROR",
         "Payment failed :: bank_reason: Authentication could not be completed :: acs_timeout=true"),
    ],
    RootCause.FRAUD_BLOCK: [
        ("risk_block",
         "Transaction held by risk engine :: rule=VELOCITY_IP_24H :: rc=59 :: review_required=true"),
        ("BAD_REQUEST_ERROR",
         "Payment failed :: bank_reason: Suspected fraudulent activity :: flagged_by=issuer"),
    ],
    RootCause.HARD_DECLINE: [
        ("payment_declined_by_bank",
         "Txn declined :: bank_reason: DO NOT HONOUR :: rc=05 :: retryable=false"),
        ("BAD_REQUEST_ERROR",
         "Payment failed :: bank_reason: Card reported stolen, capture card :: rc=43"),
        ("account_closed",
         "Debit failed :: bank_reason: ACCOUNT CLOSED :: rc=78"),
    ],
    RootCause.GATEWAY_ERROR: [
        ("GATEWAY_ERROR",
         "We could not process the payment :: upstream=502 :: route=RAIL_A :: transient=true"),
        ("gateway_error",
         "Processor returned 503 Service Unavailable :: no auth decision received"),
    ],
    RootCause.LAPSED_MANDATE: [
        ("BAD_REQUEST_PAYMENT_UPI_MANDATE_REVOKED",
         "UPI Autopay mandate revoked by payer in PSP app :: umn=**** :: action=re_register"),
        ("enach_expired",
         "eNACH debit rejected :: bank_reason: MANDATE EXPIRED :: valid_till=2026-01-31"),
    ],
}

_VOCAB: dict[str, dict[RootCause, list[tuple[str, str]]]] = {
    "nimbuspay": _NIMBUS,
    "orbitpg": _ORBIT,
    "kaverigw": _KAVERI,
}


# ---------------------------------------------------------------------------
# The messy remainder
# ---------------------------------------------------------------------------
# Non-diagnostic strings. The true cause is unrecoverable from the string alone --
# it can only be inferred from surrounding context (a card whose expiry has passed,
# a revoked mandate on the method record, an HTTP 5xx, a month-end failure pattern).
# This is exactly the case the plan reserves for the reasoning tier.

_AMBIGUOUS: dict[str, list[tuple[str, str]]] = {
    "nimbuspay": [
        ("card_declined", "The card was declined."),
        ("card_declined", "Your card was declined. Contact your card issuer for more information."),
        ("processing_error", "The payment could not be completed."),
        ("generic_decline", "card_declined: generic_decline"),
    ],
    "orbitpg": [
        ("ERR_XX", "DECLINE"),
        ("05", "TXN NOT APPROVED"),
        ("RC-99", "REFER TO ISSUER"),
        ("ERR_UNKNOWN", "AUTH FAILED - NO REASON SUPPLIED"),
    ],
    "kaverigw": [
        ("BAD_REQUEST_PAYMENT_FAILED",
         "Payment failed :: bank_reason: null :: rc= :: please contact support"),
        ("payment_declined_by_bank",
         "Txn unsuccessful. Please contact your bank for details."),
        ("BAD_REQUEST_ERROR",
         "Payment failed :: bank_reason: Transaction could not be completed :: rc=U30"),
        ("GATEWAY_ERROR",
         "Unexpected response from upstream :: body_truncated :: correlation_id=**"),
    ],
}


# HTTP statuses KaveriGW leaks into the envelope. Genuine 5xx only for gateway errors;
# a 200 on a declined charge is normal (the API call succeeded, the charge did not).
_HTTP_BY_CAUSE: dict[RootCause, list[int]] = {
    RootCause.GATEWAY_ERROR: [500, 502, 503, 504],
    RootCause.ISSUER_UNAVAILABLE: [200, 200, 504],
}


def pick_gateway(rng: random.Random) -> GatewayProfile:
    return rng.choices(GATEWAYS, weights=[g.share for g in GATEWAYS], k=1)[0]


def render_failure(
    rng: random.Random,
    gateway: GatewayProfile,
    cause: RootCause,
    *,
    ambiguous: bool,
) -> tuple[str, str, int | None]:
    """Produce (raw_code, raw_message, http_status) for one failure event.

    When `ambiguous` is set, the string is drawn from the non-diagnostic pool and
    carries no reliable trace of `cause` -- the reasoning tier must recover it from
    context instead.
    """
    if ambiguous:
        code, message = rng.choice(_AMBIGUOUS[gateway.key])
    else:
        variants = _VOCAB[gateway.key].get(cause)
        if not variants:
            code, message = rng.choice(_AMBIGUOUS[gateway.key])
        else:
            code, message = rng.choice(variants)

    http_status: int | None = None
    if gateway.emits_http_status:
        pool = _HTTP_BY_CAUSE.get(cause)
        # An ambiguous gateway-error case keeps its 5xx: that is a legitimate context
        # signal a good reasoner should pick up even when the prose says nothing.
        http_status = rng.choice(pool) if pool else 200

    # Gateways are inconsistent about whitespace and casing even within one vocabulary.
    if rng.random() < 0.12:
        message = message.upper()
    if rng.random() < 0.08:
        message = f"  {message}  "
    if rng.random() < 0.06:
        code = code.lower()

    return code, message, http_status


def gateway_table() -> list[dict]:
    """Serialised for the dashboard's gateway legend."""
    return [
        {
            "key": g.key,
            "name": g.name,
            "style": g.style,
            "share": g.share,
            "emits_http_status": g.emits_http_status,
            "sample": _VOCAB[g.key][RootCause.INSUFFICIENT_FUNDS][0][1],
            "ambiguous_sample": _AMBIGUOUS[g.key][0][1],
            "vocabulary_size": sum(len(v) for v in _VOCAB[g.key].values())
            + len(_AMBIGUOUS[g.key]),
        }
        for g in GATEWAYS
    ]
