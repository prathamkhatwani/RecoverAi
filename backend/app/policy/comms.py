"""
Customer communication: what we say, on which channel, and what we refuse to say.

The plan lists communication guardrails alongside the retry caps -- "quiet hours, channel
consent, no debt-collection wording where it is not appropriate" -- so message copy is
generated here, from the diagnosis, and then scanned by the same layer that scans
everything else.

Two ideas do the work:

* **The message is a function of the root cause.** A nudge for an expired card asks the
  customer to update a card and says which one. A nudge for a failed 3DS challenge sends
  an authentication link. Neither of them says "your payment failed, please pay". Generic
  dunning copy is exactly what the naive baseline sends, and it converts badly because it
  tells the customer nothing they can act on.

* **Our own copy is subject to the tone scanner.** The scanner is not decorative
  validation applied to hypothetical bad input -- every message this module produces is
  run through it before dispatch, so a careless template change fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Customer, MethodType, Payment, PaymentMethod
from ..money import format_minor
from ..taxonomy import RootCause


# ---------------------------------------------------------------------------
# Tone scanner
# ---------------------------------------------------------------------------
# Phrases characteristic of debt collection, and coercive or shaming framing. A
# subscription payment that failed because a card expired is an administrative event,
# and language that implies delinquency is both wrong and, in several jurisdictions,
# regulated.

_BANNED: tuple[tuple[str, str], ...] = (
    (r"\bdebt\b", "implies delinquency"),
    (r"\bcollections?\b(?!\s+of\s+data)", "debt-collection framing"),
    (r"\bdelinquen\w*", "implies delinquency"),
    (r"\boverdue\b", "implies delinquency on an administrative failure"),
    (r"\bdefault(ed|ing)?\b", "implies delinquency"),
    (r"\bpay (now|immediately|at once)\b", "coercive urgency"),
    (r"\bfinal (notice|warning)\b", "collections escalation language"),
    (r"\blegal action\b", "threat"),
    (r"\bwill be (reported|referred)\b", "threat"),
    (r"\bcredit (score|bureau|rating)\b", "threat of credit consequences"),
    (r"\bsuspend(ed)? (your )?(account|service)s?\b", "service-loss threat"),
    (r"\bterminat(e|ed|ion)\b", "service-loss threat"),
    (r"\bpenalt(y|ies)\b", "punitive framing"),
    (r"\blate fee\b", "punitive framing"),
    (r"\bfailure to (pay|comply)\b", "collections framing"),
    (r"\byou owe\b", "collections framing"),
    (r"\boutstanding (amount|balance|dues?)\b", "collections framing"),
    (r"\bimmediately\b", "coercive urgency"),
    (r"\burgent(ly)?\b", "manufactured urgency"),
    (r"\bact now\b", "manufactured urgency"),
    (r"\blast chance\b", "manufactured urgency"),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), why) for p, why in _BANNED)


@dataclass
class ToneScan:
    blocked: bool
    hits: list[dict] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {"blocked": self.blocked, "hits": self.hits, "detail": self.detail}


def scan_message_tone(message: str) -> ToneScan:
    """Reject debt-collection and coercive phrasing.

    Deliberately a hard string check rather than a model call: a compliance control that
    depends on a model being in a good mood is not a control.
    """
    hits: list[dict] = []
    for pattern, why in _COMPILED:
        match = pattern.search(message)
        if match:
            hits.append({"phrase": match.group(0), "reason": why})

    if not hits:
        words = len(message.split())
        return ToneScan(
            blocked=False,
            detail=(
                f"Copy scanned against {len(_COMPILED)} prohibited phrasing patterns "
                f"({words} words checked): clean. No collections framing, no threats, "
                f"no manufactured urgency."
            ),
        )

    listed = ", ".join(f"{h['phrase']!r} ({h['reason']})" for h in hits[:4])
    return ToneScan(
        blocked=True,
        hits=hits,
        detail=(
            f"Copy rejected: {len(hits)} prohibited phrase(s) -- {listed}. "
            f"A failed subscription charge is an administrative event, not a debt."
        ),
    )


# ---------------------------------------------------------------------------
# Message composition
# ---------------------------------------------------------------------------


@dataclass
class Nudge:
    channel: str
    subject: str
    body: str
    cta_label: str
    cta_kind: str          # "update_card" | "complete_auth" | "remandate" | "informational"
    self_serve: bool

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "subject": self.subject,
            "body": self.body,
            "cta_label": self.cta_label,
            "cta_kind": self.cta_kind,
            "self_serve": self.self_serve,
        }

    def render(self) -> str:
        return f"{self.subject}\n\n{self.body}\n\n[{self.cta_label}]"


def _instrument_phrase(method: PaymentMethod | None) -> str:
    if method is None:
        return "your saved payment method"
    if method.type is MethodType.CARD:
        return f"your {method.network.title()} card ending {method.last4}"
    if method.type is MethodType.UPI_AUTOPAY:
        return "your UPI AutoPay mandate"
    if method.type is MethodType.ENACH:
        return "your bank e-mandate"
    return f"your {method.issuer} net-banking instruction"


def preferred_channel(cause: RootCause, customer: Customer) -> str | None:
    """Pick a consented channel, preferring the one suited to the ask.

    Repairs that need a link and a form are better on email; time-sensitive
    authentication prompts are better on the phone the customer is holding.
    """
    if customer.opted_out:
        return None

    if cause in (RootCause.AUTH_3DS_FAILURE, RootCause.INSUFFICIENT_FUNDS):
        order = ("whatsapp", "sms", "email")
    else:
        order = ("email", "whatsapp", "sms")

    consent = {
        "email": customer.consent_email,
        "sms": customer.consent_sms,
        "whatsapp": customer.consent_whatsapp,
    }
    for channel in order:
        if consent.get(channel):
            return channel
    return None


def compose_nudge(
    cause: RootCause,
    customer: Customer,
    payment: Payment,
    method: PaymentMethod | None,
    *,
    channel: str | None = None,
    retry_when_human: str | None = None,
) -> Nudge | None:
    """Build the message for a diagnosed cause, or None if no message is warranted.

    Returning None matters: for a terminal decline or a gateway error there is nothing
    useful to tell the customer, and inventing something to send would be the naive
    behaviour this build exists to beat.
    """
    channel = channel or preferred_channel(cause, customer)
    if channel is None:
        return None

    amount = format_minor(payment.amount_minor, payment.currency)
    instrument = _instrument_phrase(method)
    first_name = customer.name.split()[0] if customer.name else "there"
    plan_name = payment.plan or payment.description or "your subscription"

    if cause is RootCause.EXPIRED_CARD:
        return Nudge(
            channel=channel,
            subject=f"{instrument.capitalize()} has expired",
            body=(
                f"Hi {first_name} -- we tried to renew {plan_name} ({amount}) and "
                f"{instrument} has passed its expiry date, so the bank could not "
                f"authorise it. Adding the new card takes about a minute and we will "
                f"complete the renewal straight away. Nothing else on your account "
                f"has changed."
            ),
            cta_label="Update card",
            cta_kind="update_card",
            self_serve=True,
        )

    if cause is RootCause.AUTH_3DS_FAILURE:
        return Nudge(
            channel=channel,
            subject=f"One step left to renew {plan_name}",
            body=(
                f"Hi {first_name} -- your bank asked for an extra verification step on "
                f"the {amount} renewal and the check was not completed, so the charge "
                f"did not go through. {instrument.capitalize()} is fine. Tap below to "
                f"finish verifying with your bank and we will take it from there."
            ),
            cta_label="Verify with your bank",
            cta_kind="complete_auth",
            self_serve=True,
        )

    if cause is RootCause.LAPSED_MANDATE:
        return Nudge(
            channel=channel,
            subject=f"Renew the auto-debit permission for {plan_name}",
            body=(
                f"Hi {first_name} -- the standing auto-debit permission behind "
                f"{instrument} is no longer active, so the {amount} renewal could not "
                f"be collected. Re-approving it in your banking app takes a moment. We "
                f"have not attempted the debit again, because doing so without a live "
                f"mandate is not something we will do."
            ),
            cta_label="Re-approve auto-debit",
            cta_kind="remandate",
            self_serve=True,
        )

    if cause is RootCause.INSUFFICIENT_FUNDS:
        when = f" We will try again on {retry_when_human}." if retry_when_human else ""
        return Nudge(
            channel=channel,
            subject=f"Heads up: {plan_name} renewal did not go through",
            body=(
                f"Hi {first_name} -- the bank declined the {amount} renewal on "
                f"{instrument} for available balance.{when} If you would rather it came "
                f"from a different account, you can switch the payment method below. "
                f"No action is needed otherwise."
            ),
            cta_label="Change payment method",
            cta_kind="update_card",
            self_serve=True,
        )

    if cause is RootCause.ISSUER_UNAVAILABLE:
        return Nudge(
            channel=channel,
            subject=f"{plan_name} renewal will retry shortly",
            body=(
                f"Hi {first_name} -- your bank's systems were briefly unreachable when "
                f"we tried the {amount} renewal. This is on the bank's side, not yours. "
                f"We are retrying automatically and will confirm once it clears."
            ),
            cta_label="View invoice",
            cta_kind="informational",
            self_serve=False,
        )

    # Terminal, fraud-flagged, gateway-side, and unclassified failures get no message.
    # There is nothing the customer can act on, and a generic "payment failed" note is
    # both useless and alarming.
    return None


def message_catalogue() -> list[dict]:
    """Template inventory for the dashboard, showing which causes get contacted at all."""
    from ..taxonomy import TAXONOMY

    rows = []
    for cause, entry in TAXONOMY.items():
        contacted = cause in (
            RootCause.EXPIRED_CARD, RootCause.AUTH_3DS_FAILURE, RootCause.LAPSED_MANDATE,
            RootCause.INSUFFICIENT_FUNDS, RootCause.ISSUER_UNAVAILABLE,
        )
        rows.append({
            "cause": cause.value,
            "label": entry.label,
            "customer_contacted": contacted,
            "ask": {
                RootCause.EXPIRED_CARD: "Replace the stored credential",
                RootCause.AUTH_3DS_FAILURE: "Complete the bank's verification step",
                RootCause.LAPSED_MANDATE: "Re-approve the auto-debit permission",
                RootCause.INSUFFICIENT_FUNDS: "Optional: switch account. Retry is timed.",
                RootCause.ISSUER_UNAVAILABLE: "Nothing -- informational only",
            }.get(cause, "No message -- nothing the customer can act on"),
        })
    return rows


def tone_rules_catalogue() -> list[dict]:
    """The prohibited-phrasing list, published in the UI rather than described."""
    seen: dict[str, str] = {}
    for pattern, why in _BANNED:
        seen.setdefault(why, "")
        seen[why] = (seen[why] + ", " if seen[why] else "") + pattern
    return [{"reason": why, "patterns": pats} for why, pats in seen.items()]
