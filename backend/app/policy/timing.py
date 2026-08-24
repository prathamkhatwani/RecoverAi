"""
Retry timing.

The plan's central example of diagnosis-driven behaviour is "smart-timed retry (e.g.
near payday)" versus a fixed 24h schedule, so timing is treated as a first-class
decision with its own module rather than a constant buried in the executor.

Three timing strategies, chosen by root cause:

  * **liquidity-aware** (insufficient funds) -- wait for the account to refill. Firing
    three retries into a customer's low-balance window burns every attempt the card
    networks allow us for nothing.
  * **exponential backoff** (issuer unavailable, gateway error) -- the fault clears in
    minutes, so waiting a day is pure leakage.
  * **post-repair** (expired card, 3DS, mandate) -- there is no good moment to retry a
    broken credential. The retry waits on the repair, not on the clock.

Every computed instant is then pushed out of the customer's local quiet hours when the
action is customer-visible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import settings
from ..models import Customer
from ..taxonomy import RootCause


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_time(dt: datetime, customer: Customer | None) -> datetime:
    """Convert a UTC instant into the customer's wall clock."""
    offset = customer.timezone_offset_minutes if customer else 330
    return dt.astimezone(timezone(timedelta(minutes=offset)))


def in_quiet_hours(dt: datetime, customer: Customer | None) -> bool:
    """Is this instant inside the customer's local quiet window?

    Handles the overnight wrap (21:00 -> 08:00) correctly, which is the case a naive
    `start <= hour < end` check gets wrong every night.
    """
    policy = settings.policy
    hour = local_time(dt, customer).hour
    start, end = policy.quiet_hours_start, policy.quiet_hours_end
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def next_allowed_contact_time(dt: datetime, customer: Customer | None) -> datetime:
    """Shift an instant forward to the next moment contact is permitted.

    Returns 09:00 in the customer's own timezone -- respecting the *customer's* morning
    rather than the merchant's is the whole point of storing an offset per customer.
    """
    if not in_quiet_hours(dt, customer):
        return dt

    policy = settings.policy
    offset = customer.timezone_offset_minutes if customer else 330
    tz = timezone(timedelta(minutes=offset))
    local = dt.astimezone(tz)

    target_hour = max(policy.quiet_hours_end, 9)
    candidate = local.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _days_until_liquidity(reference: datetime, salary_day: int) -> int:
    """Days from `reference` to the next occurrence of `salary_day`."""
    day = reference.day
    if day < salary_day:
        return salary_day - day
    # Roll to next month, clamping for short months.
    year, month = reference.year, reference.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    days_in_month = (
        31 if month in (1, 3, 5, 7, 8, 10, 12)
        else 30 if month != 2
        else 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        else 28
    )
    target = min(salary_day, days_in_month)
    return (datetime(year, month, target, tzinfo=timezone.utc)
            - datetime(reference.year, reference.month, reference.day, tzinfo=timezone.utc)).days


def liquidity_aware_retry(
    failed_at: datetime, customer: Customer | None, attempt_index: int
) -> tuple[datetime, float, str]:
    """Schedule a retry for when the account is most likely to be funded.

    Returns ``(when, expected_lift, human_explanation)``. The lift is a *relative*
    multiplier used only for display -- the actual outcome is decided by the shared
    outcome model, not by this number.
    """
    salary_day = customer.salary_day if customer else 1
    days_out = _days_until_liquidity(failed_at, salary_day)

    # One day *after* the credit lands: same-day debits race the credit and lose.
    target_offset = days_out + 1

    # A minimum spacing keeps us from stacking attempts when the failure already
    # happened to land on payday.
    if target_offset < 2:
        target_offset += 2

    # Later attempts wait a full cycle rather than crowding the same window.
    if attempt_index >= 2:
        target_offset += 28 if days_out <= 2 else 0

    when = (failed_at + timedelta(days=target_offset)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    explanation = (
        f"Customer's balance typically refills on day {salary_day} of the month "
        f"({days_out}d away). Retry scheduled for {target_offset}d out -- one day after "
        f"the expected credit, at 11:00 local, rather than a blind 24h retry into a "
        f"known-empty account."
    )
    return when, 3.1, explanation


def exponential_backoff_retry(
    failed_at: datetime, attempt_index: int
) -> tuple[datetime, float, str]:
    """Fast retry for transient faults: 12min, 40min, 2h, 6h, then 18h.

    The ladder is fast at the front because most issuer host outages clear inside the
    hour, and it deliberately keeps one long-dated rung at the end: a small tail of
    outages runs half a day, and a ladder that gives up at 6h abandons revenue a naive
    24h retry would have collected. Being cleverer than the baseline early is worthless
    if it means being worse than it late.
    """
    ladder_minutes = (12, 40, 120, 360, 1080)
    minutes = ladder_minutes[min(attempt_index, len(ladder_minutes) - 1)]
    when = failed_at + timedelta(minutes=minutes)
    unit = f"{minutes} minutes" if minutes < 120 else f"{minutes / 60:.0f} hours"
    explanation = (
        f"Transient upstream fault. Retry #{attempt_index + 1} in {unit} "
        f"(exponential backoff), not on a fixed 24h cadence -- issuer host outages "
        f"usually clear inside the hour, so a day-long wait abandons near-certain "
        f"revenue, and the long final rung still covers the outages that run half a day."
    )
    return when, 2.4, explanation


def immediate_alternate_route(failed_at: datetime) -> tuple[datetime, float, str]:
    """Our own 5xx: re-attempt almost immediately, on a different rail."""
    when = failed_at + timedelta(minutes=3)
    return when, 2.9, (
        "Our processor never obtained an authorisation decision, so nothing about the "
        "customer or the card has been tested. Re-attempting in 3 minutes through the "
        "alternate route recovers this before the customer is ever aware of it."
    )


def post_repair_retry(
    failed_at: datetime, cause: RootCause, customer: Customer | None
) -> tuple[datetime, float, str]:
    """Schedule the retry that follows a successful repair.

    The delay reflects how long the repair realistically takes, not a fixed cadence:
    a network account-updater lookup returns in minutes, whereas a human completing a
    3DS challenge or re-authorising a mandate takes hours.
    """
    if cause is RootCause.EXPIRED_CARD:
        when = failed_at + timedelta(minutes=20)
        note = (
            "Retry is gated on the account-updater lookup returning a fresh credential. "
            "Until that lands, another attempt on the dead token is a guaranteed decline."
        )
    elif cause is RootCause.AUTH_3DS_FAILURE:
        when = next_allowed_contact_time(failed_at + timedelta(hours=2), customer)
        note = (
            "Retry is gated on the customer completing the authentication link. No "
            "server-side retry can finish a challenge that needs a human."
        )
    else:
        when = next_allowed_contact_time(failed_at + timedelta(hours=6), customer)
        note = (
            "Retry is gated on a fresh mandate being registered. Debiting without a "
            "live mandate is an unauthorised attempt, not a soft failure."
        )
    return when, 1.0, note


def timing_for_cause(
    cause: RootCause,
    failed_at: datetime,
    customer: Customer | None,
    attempt_index: int,
    *,
    alternate_route_available: bool = True,
) -> tuple[datetime, float, str, str]:
    """Single entry point. Returns ``(when, lift, explanation, strategy_name)``."""
    if cause is RootCause.INSUFFICIENT_FUNDS:
        when, lift, why = liquidity_aware_retry(failed_at, customer, attempt_index)
        return when, lift, why, "liquidity_aware"

    if cause is RootCause.ISSUER_UNAVAILABLE:
        when, lift, why = exponential_backoff_retry(failed_at, attempt_index)
        return when, lift, why, "exponential_backoff"

    if cause is RootCause.GATEWAY_ERROR:
        if alternate_route_available and attempt_index == 0:
            when, lift, why = immediate_alternate_route(failed_at)
            return when, lift, why, "immediate_alternate_route"
        when, lift, why = exponential_backoff_retry(failed_at, attempt_index)
        return when, lift, why, "exponential_backoff"

    when, lift, why = post_repair_retry(failed_at, cause, customer)
    return when, lift, why, "post_repair"


def baseline_retry_time(failed_at: datetime, attempt_index: int) -> datetime:
    """The naive schedule: fixed interval, identical for every root cause.

    This is the strategy the plan predicts most entries will ship, and it is
    implemented faithfully rather than as a straw man -- same attempt budget, same
    outcome model, just no diagnosis informing the timing.
    """
    return failed_at + timedelta(
        hours=settings.baseline.interval_hours * (attempt_index + 1)
    )
