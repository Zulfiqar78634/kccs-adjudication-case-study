"""Regulatory notification obligations: an independent clock and state machine.

* The clock starts at alert receipt (alert_ts_utc; 00_README!R43, R46), never at
  disposition, and nothing in the disposition/evidence workflow can move it:
  `due_at` is computed once from (alert_received_at, regime) and stored.
* NEXT_BUSINESS_DAY needs an explicit timezone, holiday calendar and deadline
  time; without them computation fails loudly (PolicyIncomplete).
* Only ACKNOWLEDGED (regulator receipt) or a signed human NOT_NOTIFIABLE
  determination satisfies an obligation. A queued or transport-accepted
  submission does not.
* Storm handling groups obligations for triage but always keeps one obligation
  per alert; registration is idempotent by (tenant, event_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .temporal import UTC, iso


class PolicyIncomplete(ValueError):
    pass


class IllegalTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class Regime:
    kind: str  # ELAPSED_HOURS | NEXT_BUSINESS_DAY
    hours: float | None = None
    tz: str | None = None
    holidays: frozenset = frozenset()
    deadline_local_time: time | None = None
    source: str | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Regime:
        return cls(kind=cfg["kind"], hours=cfg.get("hours"), source=cfg.get("source"))


def compute_due_at(alert_received_at: datetime, regime: Regime) -> datetime:
    if alert_received_at.tzinfo is None:
        raise PolicyIncomplete("alert time must be timezone-aware")
    if regime.kind == "ELAPSED_HOURS":
        if regime.hours is None:
            raise PolicyIncomplete("ELAPSED_HOURS regime without hours")
        return alert_received_at + timedelta(hours=regime.hours)
    if regime.kind == "NEXT_BUSINESS_DAY":
        missing = [n for n, v in (("tz", regime.tz), ("deadline_local_time", regime.deadline_local_time)) if v is None]
        if missing or regime.holidays is None:
            raise PolicyIncomplete(f"NEXT_BUSINESS_DAY requires explicit {missing or ['holiday calendar']}")
        zone = ZoneInfo(regime.tz)
        d = alert_received_at.astimezone(zone).date() + timedelta(days=1)
        while d.weekday() >= 5 or d in regime.holidays:
            d += timedelta(days=1)
        return datetime.combine(d, regime.deadline_local_time, tzinfo=zone).astimezone(UTC)
    raise PolicyIncomplete(f"unknown regime kind {regime.kind}")


OPEN_STATES = {"OPEN_UNDETERMINED", "NOTIFIABLE_CONFIRMED", "SUBMISSION_QUEUED", "SUBMITTED_AWAITING_ACK", "DELIVERY_FAILED"}
TRANSITIONS = {
    "OPEN_UNDETERMINED": {"NOTIFIABLE_CONFIRMED", "CLOSED_NOT_NOTIFIABLE", "SUBMISSION_QUEUED"},
    "NOTIFIABLE_CONFIRMED": {"SUBMISSION_QUEUED"},
    "SUBMISSION_QUEUED": {"SUBMITTED_AWAITING_ACK", "DELIVERY_FAILED"},
    "DELIVERY_FAILED": {"SUBMISSION_QUEUED"},
    "SUBMITTED_AWAITING_ACK": {"ACKNOWLEDGED", "DELIVERY_FAILED"},
    "ACKNOWLEDGED": set(),
    "CLOSED_NOT_NOTIFIABLE": set(),
}


@dataclass
class Obligation:
    obligation_id: str
    tenant: str
    event_id: str
    clock_start: datetime
    due_at: datetime | None
    regime_kind: str
    state: str = "OPEN_UNDETERMINED"
    group_id: str | None = None
    version: int = 1
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        return self.state in ("ACKNOWLEDGED", "CLOSED_NOT_NOTIFIABLE")


class ObligationLedger:
    """In-memory reference implementation of the obligation state machine (production: DB table + outbox)."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Obligation] = {}

    def register(self, tenant: str, event_id: str, alert_received_at: datetime, regime: Regime, group_id: str | None = None) -> tuple[Obligation, bool]:
        key = (tenant, event_id)
        if key in self._by_key:
            return self._by_key[key], False
        try:
            due = compute_due_at(alert_received_at, regime)
        except PolicyIncomplete:
            due = None  # escalated immediately by at_risk(); never silently dropped
        ob = Obligation(f"OBL-{tenant}-{event_id}", tenant, event_id, alert_received_at, due, regime.kind, group_id=group_id)
        ob.history.append({"state": ob.state, "at": iso(alert_received_at), "by": "system", "note": "registered at alert receipt"})
        self._by_key[key] = ob
        return ob, True

    def register_storm(self, alerts: list[tuple[str, str, datetime]], regime_for: dict[str, Regime], group_id: str) -> int:
        created = 0
        for tenant, event_id, at in alerts:
            _, new = self.register(tenant, event_id, at, regime_for[tenant], group_id=group_id)
            created += int(new)
        return created

    def transition(self, tenant: str, event_id: str, new_state: str, *, at: datetime, by: str, expected_version: int, note: str = "") -> Obligation:
        ob = self._by_key[(tenant, event_id)]
        if ob.version != expected_version:
            raise IllegalTransition(f"version conflict: expected {expected_version}, current {ob.version}")
        if new_state not in TRANSITIONS[ob.state]:
            raise IllegalTransition(f"{ob.state} -> {new_state} not allowed")
        if new_state == "CLOSED_NOT_NOTIFIABLE" and (by == "system" or not note):
            raise IllegalTransition("a not-notifiable determination needs a named human and a rationale")
        ob.state = new_state
        ob.version += 1
        ob.history.append({"state": new_state, "at": iso(at), "by": by, "note": note})
        return ob

    def record_evidence_wait(self, tenant: str, event_id: str, reason: str, at: datetime) -> Obligation:
        """Disposition-side waits are logged for context only; due_at is not touched."""
        ob = self._by_key[(tenant, event_id)]
        ob.history.append({"state": ob.state, "at": iso(at), "by": "system", "note": f"disposition waiting: {reason} (clock unaffected)"})
        return ob

    def all(self) -> list[Obligation]:
        return list(self._by_key.values())

    def at_risk(self, now: datetime, margin: timedelta) -> list[Obligation]:
        """Earliest-deadline-first worklist; obligations with no computable deadline come first."""
        open_obs = [o for o in self._by_key.values() if o.state in OPEN_STATES]
        risky = [o for o in open_obs if o.due_at is None or o.due_at - now <= margin]
        return sorted(risky, key=lambda o: (o.due_at is not None, o.due_at or now))

    def breached(self, now: datetime) -> list[Obligation]:
        return [o for o in self._by_key.values() if o.state in OPEN_STATES and o.due_at is not None and now > o.due_at]
