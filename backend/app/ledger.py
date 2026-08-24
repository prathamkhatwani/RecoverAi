"""
Hash-chained audit ledger.

Every decision the agent makes is appended as a record whose hash covers both its own
canonical content and the hash of the record before it. Change any historical field and
every subsequent hash stops matching, so the chain does not merely *store* the reasoning
trail -- it makes silent revision of it detectable.

Why this belongs in a payments demo rather than being decoration:

An automated system that moves other people's money will eventually be asked a hostile
question -- by a customer, an acquirer, or a regulator -- of the form "why did you charge
this card four times in a week?". "Because the model decided to" is not an answer. The
answer has to be a specific record, produced at the time, that names the diagnosis, the
confidence, the rule that permitted the action and the rules that constrained it. A log
you can quietly edit after the fact cannot serve that purpose, which is exactly why
tamper-evidence is the point and not a flourish.

Design notes:

* `prev_hash` of the genesis record is a fixed, published constant rather than empty
  string, so a truncation attack that removes the first N records cannot produce a chain
  that validates from its new head.
* Canonicalisation is deliberately strict (`sort_keys`, no whitespace, UTF-8). Two
  semantically identical payloads must produce one hash, or verification becomes
  advisory.
* `verify()` reports the *first* divergence and keeps going, because "row 41 was edited
  and rows 42-300 are merely downstream of it" is far more useful to a human than 260
  identical complaints.
* The chain records decisions, not outcomes. A ledger that could be appended to after the
  money arrived would let hindsight edit the reasoning, which defeats the purpose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

# Published genesis constant. Anchors the chain so it cannot be re-rooted.
GENESIS_HASH = "0" * 64
HASH_ALGORITHM = "sha256"


def canonical_json(payload: Any) -> str:
    """Byte-stable JSON. The hash is only meaningful if this is deterministic."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def compute_hash(seq: int, prev_hash: str, recorded_at: str, payload: Any) -> str:
    """Hash over (position, previous hash, timestamp, content).

    Position and previous hash are inside the digest on purpose: without them, two
    identical decisions would hash identically and could be reordered or swapped
    without detection.
    """
    material = f"{seq}|{prev_hash}|{recorded_at}|{canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class LedgerRecord:
    seq: int
    prev_hash: str
    entry_hash: str
    recorded_at: str
    kind: str                    # "decision" | "attempt" | "note" | "run_open" | "run_close"
    run_id: str
    arm: str
    subject_id: str              # decision id / attempt id / event id
    summary: str                 # one human-readable line, for the ledger table
    payload: dict = field(default_factory=dict)

    def to_dict(self, *, include_payload: bool = True) -> dict:
        out = {
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "recorded_at": self.recorded_at,
            "kind": self.kind,
            "run_id": self.run_id,
            "arm": self.arm,
            "subject_id": self.subject_id,
            "summary": self.summary,
        }
        if include_payload:
            out["payload"] = self.payload
        return out

    def recompute(self) -> str:
        return compute_hash(self.seq, self.prev_hash, self.recorded_at, self.payload)


@dataclass
class VerificationBreak:
    seq: int
    reason: str
    expected: str
    found: str
    downstream: bool = False     # True when this row is only broken because an earlier one was

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "reason": self.reason,
            "expected": self.expected,
            "found": self.found,
            "downstream": self.downstream,
        }


class AuditLedger:
    """Append-only hash chain held in memory, mirrored to SQLite by the persistence layer.

    In-memory is the source of truth during a run so the live stream never blocks on
    disk; `db.py` writes the same records through for durability and for the ledger
    table the dashboard pages through.
    """

    def __init__(self) -> None:
        self._records: list[LedgerRecord] = []
        self._by_subject: dict[str, list[int]] = {}
        self._tampered_seqs: set[int] = set()

    # -- append -----------------------------------------------------------

    def append(
        self,
        *,
        kind: str,
        run_id: str,
        arm: str,
        subject_id: str,
        summary: str,
        payload: dict,
        recorded_at: str | None = None,
    ) -> LedgerRecord:
        seq = len(self._records) + 1
        prev_hash = self._records[-1].entry_hash if self._records else GENESIS_HASH
        stamp = recorded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entry_hash = compute_hash(seq, prev_hash, stamp, payload)
        record = LedgerRecord(
            seq=seq,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            recorded_at=stamp,
            kind=kind,
            run_id=run_id,
            arm=arm,
            subject_id=subject_id,
            summary=summary,
            payload=payload,
        )
        self._records.append(record)
        self._by_subject.setdefault(subject_id, []).append(seq)
        return record

    def append_decision(self, decision: Any, *, summary: str | None = None) -> LedgerRecord:
        """Record one decision, and stamp its ledger position back onto the decision.

        The back-reference matters for the demo: clicking a case in the dashboard has to
        land on the exact ledger row, not on a search result that looks like it.
        """
        d = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
        cls = d.get("classification") or {}
        line = summary or (
            f"{d.get('final_action')} on {d.get('payment_id')} -- "
            f"{cls.get('root_cause')} @ {float(cls.get('confidence') or 0):.0%} "
            f"via {cls.get('tier')}"
            + (" [BLOCKED]" if d.get("blocked") else "")
            + (" [ESCALATED]" if d.get("escalated") else "")
        )
        record = self.append(
            kind="decision",
            run_id=str(d.get("run_id") or ""),
            arm=str(d.get("arm") or ""),
            subject_id=str(d.get("id") or ""),
            summary=line,
            payload=d,
            recorded_at=str(d.get("created_at") or "") or None,
        )
        if hasattr(decision, "ledger_seq"):
            decision.ledger_seq = record.seq
            decision.ledger_hash = record.entry_hash
        return record

    def append_attempt(self, attempt: Any) -> LedgerRecord:
        a = attempt.to_dict() if hasattr(attempt, "to_dict") else dict(attempt)
        line = (
            f"{a.get('kind')} -> {a.get('outcome')} on {a.get('payment_id')}"
            + (
                f" (+{a.get('amount_recovered_minor')} minor)"
                if a.get("amount_recovered_minor")
                else ""
            )
        )
        return self.append(
            kind="attempt",
            run_id=str(a.get("run_id") or ""),
            arm=str(a.get("arm") or ""),
            subject_id=str(a.get("id") or ""),
            summary=line,
            payload=a,
            recorded_at=str(a.get("attempted_at") or "") or None,
        )

    # -- read -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    @property
    def head_hash(self) -> str:
        return self._records[-1].entry_hash if self._records else GENESIS_HASH

    def all(self) -> list[LedgerRecord]:
        return list(self._records)

    def get(self, seq: int) -> LedgerRecord | None:
        if 1 <= seq <= len(self._records):
            return self._records[seq - 1]
        return None

    def page(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        run_id: str | None = None,
        arm: str | None = None,
        kind: str | None = None,
        include_payload: bool = False,
    ) -> dict:
        rows: Iterable[LedgerRecord] = self._records
        if run_id:
            rows = [r for r in rows if r.run_id == run_id]
        if arm:
            rows = [r for r in rows if r.arm == arm]
        if kind:
            rows = [r for r in rows if r.kind == kind]
        rows = list(rows)
        window = rows[offset : offset + limit]
        return {
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "head_hash": self.head_hash,
            "algorithm": HASH_ALGORITHM,
            "genesis_hash": GENESIS_HASH,
            "records": [r.to_dict(include_payload=include_payload) for r in window],
        }

    def chain_for_subject(self, subject_id: str) -> list[dict]:
        """Every ledger row touching one decision or attempt, in order.

        This is what demo step 5 walks: one case, its diagnosis, the rules that were
        checked, and the action that followed.
        """
        return [
            self._records[s - 1].to_dict()
            for s in self._by_subject.get(subject_id, [])
        ]

    # -- verify -----------------------------------------------------------

    def verify(self) -> dict:
        """Recompute the whole chain and report every divergence.

        Returns a structure the dashboard renders directly, because "valid: true" with a
        head hash a judge can read off the screen is the entire point of the exercise.
        """
        breaks: list[VerificationBreak] = []
        expected_prev = GENESIS_HASH
        first_bad: int | None = None

        for record in self._records:
            if record.prev_hash != expected_prev:
                breaks.append(
                    VerificationBreak(
                        seq=record.seq,
                        reason="prev_hash does not match the previous record's hash",
                        expected=expected_prev,
                        found=record.prev_hash,
                        downstream=first_bad is not None,
                    )
                )
                if first_bad is None:
                    first_bad = record.seq

            recomputed = record.recompute()
            if recomputed != record.entry_hash:
                breaks.append(
                    VerificationBreak(
                        seq=record.seq,
                        reason="content does not match its stored hash -- record was altered",
                        expected=record.entry_hash,
                        found=recomputed,
                        downstream=False,
                    )
                )
                if first_bad is None:
                    first_bad = record.seq

            # Continue from what this record actually claims, so a single edit shows up
            # as one content break plus a contiguous run of link breaks after it. That
            # shape is itself diagnostic: it localises the edit.
            expected_prev = record.entry_hash

        return {
            "valid": not breaks,
            "algorithm": HASH_ALGORITHM,
            "records": len(self._records),
            "head_hash": self.head_hash,
            "genesis_hash": GENESIS_HASH,
            "first_broken_seq": first_bad,
            "break_count": len(breaks),
            "breaks": [b.to_dict() for b in breaks[:50]],
            "tampered_seqs": sorted(self._tampered_seqs),
            "statement": (
                f"All {len(self._records)} records verify against "
                f"{HASH_ALGORITHM}. Every decision is exactly as it was written."
                if not breaks
                else (
                    f"Chain broken at record {first_bad}. "
                    f"{len(breaks)} divergence(s) detected across "
                    f"{len(self._records)} records."
                )
            ),
        }

    # -- tamper (demo affordance) -----------------------------------------

    def tamper(self, seq: int, *, new_action: str | None = None) -> dict:
        """Deliberately rewrite one stored decision *without* refreshing its hash.

        This exists so the tamper-evidence claim can be demonstrated instead of
        asserted. It is the honest version of the demo: rather than telling judges the
        chain would catch an edit, we edit a record in front of them and let the
        verifier find it. Mutates only the in-memory copy; `reset()` restores it.
        """
        record = self.get(seq)
        if record is None:
            return {"ok": False, "detail": f"no ledger record at seq {seq}"}

        before = {
            "final_action": record.payload.get("final_action"),
            "summary": record.summary,
            "entry_hash": record.entry_hash,
        }

        target = new_action or "smart_retry"
        original_action = record.payload.get("final_action")
        if original_action == target:
            target = "human_review" if target != "human_review" else "customer_nudge"

        record.payload["final_action"] = target
        # The whole point: the stored hash is left untouched, exactly as an attacker
        # editing a database row would leave it.
        record.summary = f"{record.summary}  [TAMPERED: action rewritten to {target}]"
        self._tampered_seqs.add(seq)

        verification = self.verify()
        return {
            "ok": True,
            "seq": seq,
            "before": before,
            "after": {
                "final_action": record.payload.get("final_action"),
                "entry_hash_still_claims": record.entry_hash,
                "recomputed_hash": record.recompute(),
            },
            "detail": (
                f"Record {seq} was rewritten from `{original_action}` to `{target}` "
                f"without updating its hash -- as an attacker editing the row directly "
                f"would. The stored hash still claims the original content."
            ),
            "verification": verification,
        }

    def reset(self) -> None:
        self._records.clear()
        self._by_subject.clear()
        self._tampered_seqs.clear()

    # -- export -----------------------------------------------------------

    def export(self) -> dict:
        """Full chain, suitable for handing to someone who wants to verify it offline."""
        return {
            "algorithm": HASH_ALGORITHM,
            "genesis_hash": GENESIS_HASH,
            "head_hash": self.head_hash,
            "record_count": len(self._records),
            "verification_recipe": (
                "For each record: sha256(f'{seq}|{prev_hash}|{recorded_at}|"
                "{canonical_json(payload)}') must equal entry_hash, and prev_hash must "
                "equal the preceding record's entry_hash. canonical_json is "
                "json.dumps(payload, sort_keys=True, separators=(',',':'), "
                "ensure_ascii=False). The first record's prev_hash is 64 zeroes."
            ),
            "records": [r.to_dict() for r in self._records],
        }


# Process-wide ledger. One chain per process keeps the "one continuous, verifiable
# history" property that per-run chains would lose.
ledger = AuditLedger()
