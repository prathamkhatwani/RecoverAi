"""
Money formatting.

Amounts live as integer minor units everywhere in the pipeline. This module is the only
place they become strings, so display conventions stay consistent between guardrail
prose, nudge copy, and the ledger.

The dashboard toggles between INR and USD. The conversion rate is fixed and declared
rather than fetched: a demo whose headline number moves with the FX market is not
reproducible, and a judge re-running the benchmark should get the same figure.
"""

from __future__ import annotations

# Declared, fixed, and shown in the UI. Not a live rate, on purpose.
USD_PER_INR = 1 / 88.0

SYMBOLS = {"INR": "₹", "USD": "$"}


def format_minor(amount_minor: int, currency: str = "INR", *, compact: bool = False) -> str:
    """Render minor units as a display string in `currency`.

    `compact` uses Indian lakh/crore grouping for INR and K/M for USD, which keeps
    dashboard tiles readable at a glance.
    """
    currency = (currency or "INR").upper()
    symbol = SYMBOLS.get(currency, "")
    major = amount_minor / 100.0
    if currency == "USD":
        major = major * USD_PER_INR

    if not compact:
        return f"{symbol}{major:,.2f}" if major < 1000 else f"{symbol}{major:,.0f}"

    if currency == "INR":
        if major >= 1_00_00_000:
            return f"{symbol}{major / 1_00_00_000:.2f} Cr"
        if major >= 1_00_000:
            return f"{symbol}{major / 1_00_000:.2f} L"
        if major >= 1_000:
            return f"{symbol}{major / 1_000:.1f} K"
        return f"{symbol}{major:,.0f}"

    if major >= 1_000_000:
        return f"{symbol}{major / 1_000_000:.2f} M"
    if major >= 1_000:
        return f"{symbol}{major / 1_000:.1f} K"
    return f"{symbol}{major:,.0f}"


def to_currency_minor(amount_minor_inr: int, currency: str) -> int:
    """Convert INR minor units into the requested currency's minor units."""
    if (currency or "INR").upper() == "USD":
        return int(round(amount_minor_inr * USD_PER_INR))
    return amount_minor_inr


def fx_disclosure() -> dict:
    """Surfaced in the UI next to the currency toggle, so the rate is never implicit."""
    return {
        "base": "INR",
        "alternate": "USD",
        "usd_per_inr": round(USD_PER_INR, 8),
        "inr_per_usd": 88.0,
        "note": (
            "Fixed demo rate, declared rather than fetched -- a benchmark whose headline "
            "number moves with the FX market is not reproducible."
        ),
    }
