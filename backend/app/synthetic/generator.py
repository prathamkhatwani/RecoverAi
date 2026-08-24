"""
Synthetic failure-stream generator (sprint days 1-2).

Two jobs, kept strictly separate:

1. **Surface data** -- customers, payment methods, payments and the messy gateway
   strings a classifier is allowed to see.
2. **Latent truth** -- what is *actually* wrong with each payment and what would
   genuinely fix it. The classifier never sees this. The outcome model reads it, and
   the dashboard scores classification accuracy against it.

Keeping latent truth out of the classifier's view is what makes the accuracy number on
the dashboard meaningful rather than decorative, and keeping it identical across both
arms is what makes the A/B fair: the agent and the naive baseline face the same eight
hundred broken payments with the same underlying repairability. Only the strategy
differs.

Everything is driven by a seeded `random.Random`, so a given seed reproduces the same
stream -- and therefore the same headline numbers -- on any machine.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..models import Customer, FailureEvent, MethodType, Payment, PaymentMethod
from ..taxonomy import RootCause
from .gateways import GATEWAYS_BY_KEY, pick_gateway, render_failure


# ---------------------------------------------------------------------------
# Simulated clock
# ---------------------------------------------------------------------------
# A fixed epoch, not `now`, so the demo's headline numbers are byte-identical on every
# run and on every machine. Override with SIM_EPOCH if you want a different window.

SIM_EPOCH = datetime(2026, 8, 10, 0, 0, 0, tzinfo=timezone.utc)
STREAM_WINDOW_DAYS = 14        # failures arrive across this window
RECOVERY_HORIZON_DAYS = 30     # how long a recovery attempt may keep trying


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Realistic decline distribution
# ---------------------------------------------------------------------------
# Weighted for a subscription merchant on Indian rails: 3DS/OTP abandonment and
# mandate lapses are far more prevalent here than in card-present Western mixes, and
# do-not-honour is chronically over-represented in every published decline taxonomy.

CAUSE_DISTRIBUTION: dict[RootCause, float] = {
    RootCause.INSUFFICIENT_FUNDS: 0.30,
    RootCause.AUTH_3DS_FAILURE: 0.15,
    RootCause.HARD_DECLINE: 0.14,
    RootCause.EXPIRED_CARD: 0.12,
    RootCause.LAPSED_MANDATE: 0.09,
    RootCause.ISSUER_UNAVAILABLE: 0.08,
    RootCause.GATEWAY_ERROR: 0.07,
    RootCause.FRAUD_BLOCK: 0.05,
}

# Share of events whose gateway string is non-diagnostic. The rules tier cannot solve
# these from the string; they are the reasoning tier's entire justification.
DEFAULT_AMBIGUOUS_RATIO = 0.26

# Which method types a cause can plausibly occur on.
_METHOD_AFFINITY: dict[RootCause, tuple[MethodType, ...]] = {
    RootCause.INSUFFICIENT_FUNDS: (MethodType.CARD, MethodType.UPI_AUTOPAY, MethodType.ENACH),
    RootCause.ISSUER_UNAVAILABLE: (MethodType.CARD, MethodType.UPI_AUTOPAY, MethodType.NETBANKING),
    RootCause.EXPIRED_CARD: (MethodType.CARD,),
    RootCause.AUTH_3DS_FAILURE: (MethodType.CARD, MethodType.UPI_AUTOPAY),
    RootCause.FRAUD_BLOCK: (MethodType.CARD, MethodType.NETBANKING),
    RootCause.HARD_DECLINE: (MethodType.CARD,),
    RootCause.GATEWAY_ERROR: (MethodType.CARD, MethodType.UPI_AUTOPAY, MethodType.ENACH,
                              MethodType.NETBANKING),
    RootCause.LAPSED_MANDATE: (MethodType.UPI_AUTOPAY, MethodType.ENACH, MethodType.CARD),
}

PLANS: tuple[tuple[str, int, str], ...] = (
    # (plan name, amount in paise, billing cycle)
    ("Starter Monthly",     499_00,     "monthly"),
    ("Growth Monthly",      1_499_00,   "monthly"),
    ("Pro Monthly",         2_999_00,   "monthly"),
    ("Business Monthly",    4_999_00,   "monthly"),
    ("Team Annual",         49_999_00,  "annual"),
    ("Enterprise Annual",   2_49_999_00, "annual"),
    ("Usage Overage",       0,          "usage"),     # amount randomised
)

PLAN_WEIGHTS = (0.26, 0.24, 0.17, 0.13, 0.09, 0.03, 0.08)

_FIRST_NAMES = (
    "Aarav", "Diya", "Vihaan", "Ananya", "Kabir", "Ishita", "Reyansh", "Meera",
    "Arjun", "Saanvi", "Advik", "Aditi", "Rohan", "Kavya", "Dhruv", "Nisha",
    "Farhan", "Zoya", "Neel", "Tara", "Yash", "Riya", "Aryan", "Sneha",
    "Imran", "Lakshmi", "Vikram", "Pooja", "Siddharth", "Anjali",
)
_LAST_NAMES = (
    "Sharma", "Iyer", "Nair", "Reddy", "Kapoor", "Banerjee", "Mehta", "Chauhan",
    "Pillai", "Ghosh", "Rao", "Joshi", "Malhotra", "Desai", "Khan", "Verma",
    "Bose", "Shetty", "Gupta", "Kulkarni",
)
_ISSUERS = (
    "HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank", "Kotak Mahindra",
    "IndusInd Bank", "Yes Bank", "Punjab National Bank", "IDFC First", "Federal Bank",
)
_NETWORKS = ("VISA", "MASTERCARD", "RUPAY", "AMEX")
_NETWORK_WEIGHTS = (0.44, 0.32, 0.21, 0.03)


# ---------------------------------------------------------------------------
# Latent truth
# ---------------------------------------------------------------------------


@dataclass
class LatentCase:
    """The hidden state of one broken payment.

    Read only by the outcome model. Both arms are scored against the same instance of
    this object, which is the structural reason the benchmark is a fair fight: the
    baseline is not handed worse luck, it is handed the same luck and a worse policy.
    """

    event_id: str
    true_root_cause: RootCause

    # Is there *any* action that recovers this money? Some payments are genuinely dead
    # (stolen card, real fraud, churned customer) and a system that claims otherwise is
    # lying. Roughly a fifth of this stream is unrecoverable by design.
    recoverable_in_principle: bool

    # --- cause-specific mechanics -----------------------------------------
    # Insufficient funds: the account refills on this day of the month. A retry lands
    # well or badly depending on how close it is to that refill.
    liquidity_day: int = 1
    liquidity_strength: float = 0.7        # how completely the refill fixes the balance

    # Transient faults: the outage clears this many hours after the failure.
    outage_clears_after_hours: float = 0.0

    # Expired card: does the network's account-updater actually hold a new credential?
    card_updater_has_new_credential: bool = False
    # Will the customer update the card themselves if asked?
    customer_will_update_card: bool = False

    # 3DS: will the customer complete the challenge if a fresh link is put in front
    # of them? Independent of how many times we silently retry, which is the point.
    customer_will_complete_auth: bool = False

    # Mandate: will the customer re-authorise?
    customer_will_remandate: bool = False

    # Fraud: risk filters have false positives, and only a human finds them.
    fraud_is_false_positive: bool = False

    # After this many hours the subscription is involuntarily cancelled and the money
    # is gone regardless of strategy. Slow policies lose revenue to this clock.
    recovery_deadline_hours: float = 24.0 * RECOVERY_HORIZON_DAYS

    # A private, pre-drawn sequence of uniforms. Attempt k in *either* arm consumes
    # `luck[k]`, so identical actions taken at identical times get identical results.
    # This removes RNG noise from the comparison entirely.
    luck: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "true_root_cause": self.true_root_cause.value,
            "recoverable_in_principle": self.recoverable_in_principle,
            "liquidity_day": self.liquidity_day,
            "liquidity_strength": round(self.liquidity_strength, 3),
            "outage_clears_after_hours": round(self.outage_clears_after_hours, 2),
            "card_updater_has_new_credential": self.card_updater_has_new_credential,
            "customer_will_update_card": self.customer_will_update_card,
            "customer_will_complete_auth": self.customer_will_complete_auth,
            "customer_will_remandate": self.customer_will_remandate,
            "fraud_is_false_positive": self.fraud_is_false_positive,
            "recovery_deadline_hours": round(self.recovery_deadline_hours, 1),
        }


@dataclass
class GeneratedStream:
    """Everything one simulation run needs."""

    seed: int
    epoch: datetime
    customers: dict[str, Customer]
    methods: dict[str, PaymentMethod]
    payments: dict[str, Payment]
    events: list[FailureEvent]
    latent: dict[str, LatentCase]
    ambiguous_ratio: float

    @property
    def total_at_risk_minor(self) -> int:
        return sum(self.payments[e.payment_id].amount_minor for e in self.events)

    def cause_histogram(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.events:
            out[e.true_root_cause.value] = out.get(e.true_root_cause.value, 0) + 1
        return out


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def _pick_cause(rng: random.Random) -> RootCause:
    causes = list(CAUSE_DISTRIBUTION)
    weights = [CAUSE_DISTRIBUTION[c] for c in causes]
    return rng.choices(causes, weights=weights, k=1)[0]


def _make_customer(rng: random.Random, idx: int) -> Customer:
    name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
    handle = name.lower().replace(" ", ".")
    segment = rng.choices(("consumer", "prosumer", "smb"), weights=(0.62, 0.26, 0.12))[0]

    # Hard-stop flags are rare but must exist: they are the cases that prove the
    # guardrail layer overrides every other consideration.
    chargeback = rng.random() < 0.020
    dispute = rng.random() < 0.025
    fraud_flag = rng.random() < 0.018
    opted_out = rng.random() < 0.035

    tenure = rng.randint(12, 1400)
    return Customer(
        id=f"cust_{idx:05d}",
        name=name,
        email=f"{handle}@{rng.choice(('gmail.com', 'outlook.com', 'zoho.in', 'proton.me'))}",
        phone=f"+91{rng.randint(70000, 99999)}{rng.randint(10000, 99999)}",
        # India is UTC+5:30; a slice of customers sit elsewhere so quiet-hours logic
        # has to be timezone-aware rather than assuming one office.
        timezone_offset_minutes=rng.choices((330, 0, -300, -480, 60), weights=(0.78, 0.05, 0.07, 0.05, 0.05))[0],
        segment=segment,
        salary_day=rng.choices(
            (1, 2, 5, 7, 10, 25, 28),
            weights=(0.30, 0.10, 0.16, 0.12, 0.10, 0.12, 0.10),
        )[0],
        consent_email=rng.random() < 0.97,
        consent_sms=rng.random() < 0.72,
        consent_whatsapp=rng.random() < 0.58,
        opted_out=opted_out,
        chargeback_filed=chargeback,
        dispute_open=dispute,
        fraud_flag=fraud_flag,
        lifetime_value_minor=rng.randint(1_000_00, 8_00_000_00),
        tenure_days=tenure,
    )


def _make_method(
    rng: random.Random,
    customer: Customer,
    idx: int,
    cause: RootCause,
    epoch: datetime,
) -> PaymentMethod:
    """Build a method consistent with the cause.

    Consistency matters: an "expired card" case must carry a genuinely past expiry
    date, because that is the context signal the reasoning tier uses to crack an
    ambiguous string. Fabricating the label without the corroborating field would make
    the reasoning demo hollow.
    """
    mtype = rng.choice(_METHOD_AFFINITY[cause])

    if cause is RootCause.EXPIRED_CARD:
        # Expiry strictly in the past relative to the simulated clock.
        months_ago = rng.randint(1, 20)
        exp_dt = epoch - timedelta(days=30 * months_ago)
        exp_month, exp_year = exp_dt.month, exp_dt.year
    else:
        months_ahead = rng.randint(3, 60)
        exp_dt = epoch + timedelta(days=30 * months_ahead)
        exp_month, exp_year = exp_dt.month, exp_dt.year

    mandate_until: str | None = None
    mandate_max: int | None = None
    if mtype in (MethodType.UPI_AUTOPAY, MethodType.ENACH) or cause is RootCause.LAPSED_MANDATE:
        if cause is RootCause.LAPSED_MANDATE:
            # Already lapsed -- again, the corroborating field has to be real.
            mandate_until = iso(epoch - timedelta(days=rng.randint(1, 120)))
        else:
            mandate_until = iso(epoch + timedelta(days=rng.randint(60, 900)))
        mandate_max = rng.choice((5_000_00, 15_000_00, 50_000_00, 1_00_000_00))

    network = (
        "UPI" if mtype is MethodType.UPI_AUTOPAY
        else "NACH" if mtype is MethodType.ENACH
        else "NETBANKING" if mtype is MethodType.NETBANKING
        else rng.choices(_NETWORKS, weights=_NETWORK_WEIGHTS)[0]
    )

    return PaymentMethod(
        id=f"pm_{idx:05d}",
        customer_id=customer.id,
        type=mtype,
        network=network,
        last4=f"{rng.randint(0, 9999):04d}",
        issuer=rng.choice(_ISSUERS),
        exp_month=exp_month,
        exp_year=exp_year,
        # RuPay/AMEX account-updater coverage is patchier than Visa/Mastercard, and
        # modelling that gap honestly is what keeps the card-updater lift believable.
        card_updater_enrolled=(
            rng.random() < (0.86 if network in ("VISA", "MASTERCARD") else 0.34)
            if mtype is MethodType.CARD else False
        ),
        mandate_valid_until=mandate_until,
        mandate_max_amount_minor=mandate_max,
    )


def _make_payment(
    rng: random.Random, customer: Customer, method: PaymentMethod, idx: int, occurred: datetime
) -> Payment:
    plan_name, amount, cycle = rng.choices(PLANS, weights=PLAN_WEIGHTS, k=1)[0]
    if amount == 0:      # usage overage
        amount = rng.randint(200_00, 15_000_00)
    # Annual plans on a low-value segment are implausible; nudge them down.
    if cycle == "annual" and customer.segment == "consumer" and rng.random() < 0.6:
        plan_name, amount, cycle = "Growth Monthly", 1_499_00, "monthly"

    return Payment(
        id=f"pay_{idx:05d}",
        customer_id=customer.id,
        method_id=method.id,
        amount_minor=amount,
        currency="INR",
        description=f"{plan_name} renewal",
        plan=plan_name,
        billing_cycle=cycle,
        created_at=iso(occurred),
        is_recurring=cycle != "usage",
        invoice_ref=f"INV-2026-{idx:05d}",
    )


def _make_latent(
    rng: random.Random, event_id: str, cause: RootCause, customer: Customer, method: PaymentMethod
) -> LatentCase:
    """Assign the hidden mechanics for one case.

    The probabilities here encode a view of how payments actually behave -- they are
    the model's assumptions, stated in one place so they can be argued with rather than
    buried in the executor. `docs/OUTCOME_MODEL.md` explains every number.
    """
    latent = LatentCase(
        event_id=event_id,
        true_root_cause=cause,
        recoverable_in_principle=True,
        liquidity_day=customer.salary_day,
        luck=[rng.random() for _ in range(12)],
    )

    if cause is RootCause.INSUFFICIENT_FUNDS:
        # Most NSF customers are solvent within a cycle; a minority are genuinely
        # churning and no timing trick saves them.
        latent.recoverable_in_principle = rng.random() < 0.82
        latent.liquidity_strength = rng.uniform(0.55, 0.95)
        latent.recovery_deadline_hours = 24.0 * rng.randint(14, 30)

    elif cause is RootCause.ISSUER_UNAVAILABLE:
        latent.recoverable_in_principle = rng.random() < 0.97
        # Issuer host outages clear in minutes to a few hours.
        latent.outage_clears_after_hours = rng.choices(
            (0.15, 0.5, 1.5, 4.0, 12.0), weights=(0.34, 0.28, 0.20, 0.12, 0.06)
        )[0]
        latent.recovery_deadline_hours = 24.0 * 7

    elif cause is RootCause.GATEWAY_ERROR:
        latent.recoverable_in_principle = rng.random() < 0.98
        latent.outage_clears_after_hours = rng.choices(
            (0.02, 0.1, 0.4, 2.0), weights=(0.45, 0.30, 0.18, 0.07)
        )[0]
        latent.recovery_deadline_hours = 24.0 * 3

    elif cause is RootCause.EXPIRED_CARD:
        latent.recoverable_in_principle = rng.random() < 0.88
        # The updater only helps if the BIN is enrolled AND the issuer has pushed a
        # replacement credential.
        latent.card_updater_has_new_credential = (
            method.card_updater_enrolled and rng.random() < 0.68
        )
        latent.customer_will_update_card = rng.random() < 0.46
        latent.recovery_deadline_hours = 24.0 * rng.randint(14, 30)

    elif cause is RootCause.AUTH_3DS_FAILURE:
        latent.recoverable_in_principle = rng.random() < 0.90
        # Abandonment is mostly friction, not refusal: given a fresh link, most finish.
        latent.customer_will_complete_auth = rng.random() < 0.71
        latent.recovery_deadline_hours = 24.0 * rng.randint(7, 21)

    elif cause is RootCause.LAPSED_MANDATE:
        latent.recoverable_in_principle = rng.random() < 0.74
        latent.customer_will_remandate = rng.random() < 0.58
        latent.recovery_deadline_hours = 24.0 * rng.randint(14, 30)

    elif cause is RootCause.FRAUD_BLOCK:
        # The crux of the fraud lane: a real share of risk blocks are false positives
        # on good customers, and only a human review recovers them.
        latent.fraud_is_false_positive = rng.random() < 0.38
        latent.recoverable_in_principle = latent.fraud_is_false_positive
        latent.recovery_deadline_hours = 24.0 * 10

    elif cause is RootCause.HARD_DECLINE:
        # Stolen/closed/do-not-honour. A sliver are recoverable via a different
        # instrument after human contact; the rest are simply gone.
        latent.recoverable_in_principle = rng.random() < 0.06
        latent.recovery_deadline_hours = 24.0 * 5

    return latent


def generate_stream(
    event_count: int,
    seed: int | None = None,
    *,
    ambiguous_ratio: float | None = None,
    epoch: datetime | None = None,
) -> GeneratedStream:
    """Produce a full labelled failure stream.

    One customer/method/payment per event keeps the object graph legible in the UI,
    with a deliberate minority of repeat offenders so attempt caps, cooldowns and the
    escalate-after-three-failures rule have real cases to fire on.
    """
    seed = settings.random_seed if seed is None else seed
    ratio = DEFAULT_AMBIGUOUS_RATIO if ambiguous_ratio is None else ambiguous_ratio
    epoch = epoch or SIM_EPOCH
    rng = random.Random(seed)

    customers: dict[str, Customer] = {}
    methods: dict[str, PaymentMethod] = {}
    payments: dict[str, Payment] = {}
    events: list[FailureEvent] = []
    latent: dict[str, LatentCase] = {}

    window_seconds = STREAM_WINDOW_DAYS * 24 * 3600

    for i in range(event_count):
        cause = _pick_cause(rng)

        # Arrival time. Business-hours weighting makes quiet-hours guardrails
        # meaningful instead of a formality that never triggers.
        offset = rng.random() ** 0.85 * window_seconds
        occurred = epoch + timedelta(seconds=offset)
        hour_shift = rng.choices(range(24), weights=(
            [0.6] * 6 + [1.4] * 4 + [2.2] * 6 + [1.6] * 5 + [0.9] * 3
        ))[0]
        occurred = occurred.replace(hour=hour_shift, minute=rng.randint(0, 59),
                                    second=rng.randint(0, 59))

        customer = _make_customer(rng, i)
        method = _make_method(rng, customer, i, cause, epoch)
        payment = _make_payment(rng, customer, method, i, occurred)

        customers[customer.id] = customer
        methods[method.id] = method
        payments[payment.id] = payment

        # A quarter of the stream is a repeat failure already mid-recovery, so the
        # escalation and cap rules have live cases from the first second of the demo.
        attempt_no = rng.choices((1, 2, 3, 4), weights=(0.74, 0.14, 0.09, 0.03))[0]

        ambiguous = rng.random() < ratio
        gateway = pick_gateway(rng)
        raw_code, raw_message, http_status = render_failure(
            rng, gateway, cause, ambiguous=ambiguous
        )

        event_id = f"evt_{i:05d}"
        event = FailureEvent(
            id=event_id,
            payment_id=payment.id,
            gateway=gateway.key,
            gateway_txn_id=f"{gateway.key[:3]}_{rng.randint(10**9, 10**10 - 1)}",
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            occurred_at=iso(occurred),
            attempt_no=attempt_no,
            method_type=method.type,
            true_root_cause=cause,
            is_ambiguous=ambiguous,
        )

        case = _make_latent(rng, event_id, cause, customer, method)
        event.recoverable_in_principle = case.recoverable_in_principle

        events.append(event)
        latent[event_id] = case

    events.sort(key=lambda e: e.occurred_at)

    return GeneratedStream(
        seed=seed,
        epoch=epoch,
        customers=customers,
        methods=methods,
        payments=payments,
        events=events,
        latent=latent,
        ambiguous_ratio=ratio,
    )


def stream_profile(stream: GeneratedStream) -> dict:
    """Summary shown on the dashboard's data-provenance panel, so the synthetic set is
    documented in the product rather than hidden behind a slide."""
    from ..taxonomy import TAXONOMY

    hist = stream.cause_histogram()
    total = len(stream.events)
    by_gateway: dict[str, int] = {}
    ambiguous = 0
    at_risk_by_cause: dict[str, int] = {}
    recoverable = 0

    for e in stream.events:
        by_gateway[e.gateway] = by_gateway.get(e.gateway, 0) + 1
        if e.is_ambiguous:
            ambiguous += 1
        amt = stream.payments[e.payment_id].amount_minor
        at_risk_by_cause[e.true_root_cause.value] = (
            at_risk_by_cause.get(e.true_root_cause.value, 0) + amt
        )
        if stream.latent[e.id].recoverable_in_principle:
            recoverable += 1

    return {
        "seed": stream.seed,
        "epoch": iso(stream.epoch),
        "window_days": STREAM_WINDOW_DAYS,
        "event_count": total,
        "total_at_risk_minor": stream.total_at_risk_minor,
        "ambiguous_count": ambiguous,
        "ambiguous_ratio": round(ambiguous / total, 4) if total else 0.0,
        "recoverable_in_principle": recoverable,
        "recoverable_ratio": round(recoverable / total, 4) if total else 0.0,
        "by_gateway": [
            {
                "gateway": k,
                "name": GATEWAYS_BY_KEY[k].name,
                "count": v,
                "share": round(v / total, 4) if total else 0.0,
            }
            for k, v in sorted(by_gateway.items(), key=lambda kv: -kv[1])
        ],
        "by_cause": [
            {
                "cause": cause,
                "label": TAXONOMY[RootCause(cause)].label,
                "count": count,
                "share": round(count / total, 4) if total else 0.0,
                "at_risk_minor": at_risk_by_cause.get(cause, 0),
                "target_share": CAUSE_DISTRIBUTION.get(RootCause(cause), 0.0),
            }
            for cause, count in sorted(hist.items(), key=lambda kv: -kv[1])
        ],
    }
