"""Scratch harness: run both arms over one stream and print the headline.

Superseded by app/simulator once that lands; kept because a single-file reproduction of
the headline number is the fastest way to check a modelling change.
"""

import asyncio
import sys
from collections import defaultdict

from app.executor import run_case
from app.models import Arm
from app.money import format_minor
from app.policy import PolicyEngine
from app.synthetic.generator import generate_stream
from app.taxonomy import RootCause


async def main(n: int = 300) -> None:
    stream = generate_stream(event_count=n)
    payments = stream.payments
    customers = stream.customers
    methods = stream.methods

    print(f"at risk: {format_minor(stream.total_at_risk_minor)}  events: {len(stream.events)}")

    totals: dict[Arm, dict] = {}
    per_cause: dict[Arm, dict] = {}

    for arm in (Arm.AGENT, Arm.BASELINE):
        engine = PolicyEngine()
        agg = dict(cases=0, amount=0, charges=0, touches=0, cost=0, penalty=0.0,
                   correct=0, judged=0, escalated=0, breach_cases=0, breach_amount=0)
        by_cause: dict[str, dict] = defaultdict(
            lambda: dict(n=0, rec=0, amount=0, at_risk=0, charges=0, touches=0)
        )
        seq = 0
        for ev in stream.events:
            pay = payments[ev.payment_id]
            method = methods[pay.method_id]
            cust = customers[pay.customer_id]
            latent = stream.latent[ev.id]
            res = await run_case(
                run_id="bench", arm=arm, event=ev, payment=pay, customer=cust,
                method=method, latent=latent, engine=engine, use_llm=False,
                sequence_start=seq,
            )
            seq += len(res.decisions) + 1
            c = by_cause[latent.true_root_cause.value]
            c["n"] += 1
            c["at_risk"] += pay.amount_minor
            c["charges"] += res.charge_attempts
            c["touches"] += res.customer_touches
            if res.recovered:
                agg["cases"] += 1
                agg["amount"] += res.recovered_amount_minor
                c["rec"] += 1
                c["amount"] += res.recovered_amount_minor
                if res.breached_compliance:
                    agg["breach_cases"] += 1
                    agg["breach_amount"] += res.recovered_amount_minor
                if res.time_to_recovery_hours is not None:
                    agg.setdefault("ttr", []).append(res.time_to_recovery_hours)
            agg["charges"] += res.charge_attempts
            agg["touches"] += res.customer_touches
            agg["cost"] += res.total_cost_minor
            agg["penalty"] += res.network_penalty_points
            agg["escalated"] += 1 if res.escalated_to_human else 0
            if res.diagnosis_correct is not None:
                agg["judged"] += 1
                agg["correct"] += 1 if res.diagnosis_correct else 0
        totals[arm] = agg
        per_cause[arm] = by_cause

    a, b = totals[Arm.AGENT], totals[Arm.BASELINE]
    acc = a["correct"] / a["judged"] if a["judged"] else None

    def pct(x, y):
        return f"{(x - y) / y * 100:+.1f}%" if y else "n/a"

    def median(xs):
        if not xs:
            return 0.0
        s = sorted(xs)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    a_ttr, b_ttr = median(a.get("ttr", [])), median(b.get("ttr", []))

    print(f"\n{'':22} {'agent':>14} {'baseline':>14}   delta")
    rows = [
        ("recovered revenue", format_minor(a["amount"]), format_minor(b["amount"]),
         pct(a["amount"], b["amount"])),
        ("cases recovered", a["cases"], b["cases"], pct(a["cases"], b["cases"])),
        ("charge attempts", a["charges"], b["charges"], pct(a["charges"], b["charges"])),
        ("customer touches", a["touches"], b["touches"], pct(a["touches"], b["touches"])),
        ("operating cost", format_minor(a["cost"]), format_minor(b["cost"]),
         pct(a["cost"], b["cost"])),
        ("network penalty", f"{a['penalty']:.1f}", f"{b['penalty']:.1f}",
         pct(a["penalty"], b["penalty"])),
        ("escalated to human", a["escalated"], b["escalated"], "-"),
        ("median hrs to recover", f"{a_ttr:.1f}", f"{b_ttr:.1f}", pct(a_ttr, b_ttr)),
        ("net recovered", format_minor(a["amount"] - a["cost"]),
         format_minor(b["amount"] - b["cost"]),
         pct(a["amount"] - a["cost"], b["amount"] - b["cost"])),
        ("revenue from breaches", format_minor(a["breach_amount"]),
         format_minor(b["breach_amount"]), "-"),
    ]
    for label, x, y, d in rows:
        print(f"{label:22} {str(x):>14} {str(y):>14}   {d}")
    print(f"{'classifier accuracy':22} {acc:>14.1%} {'-':>14}")
    clean = b["amount"] - b["breach_amount"]
    print(f"\nbaseline revenue excluding cases it could only reach by breaching a hard "
          f"stop: {format_minor(clean)}  ->  agent {pct(a['amount'], clean)}")

    print(f"\n{'cause':22} {'n':>4} {'agent rec':>10} {'base rec':>10} "
          f"{'agent Rs':>12} {'base Rs':>12} {'a.chg':>6} {'b.chg':>6}")
    for cause in RootCause:
        ca = per_cause[Arm.AGENT].get(cause.value)
        cb = per_cause[Arm.BASELINE].get(cause.value)
        if not ca:
            continue
        print(f"{cause.value:22} {ca['n']:>4} {ca['rec']:>10} {cb['rec']:>10} "
              f"{ca['amount']//100:>12,} {cb['amount']//100:>12,} "
              f"{ca['charges']:>6} {cb['charges']:>6}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
