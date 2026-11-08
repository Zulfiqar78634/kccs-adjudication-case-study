"""Notification obligations: independent clock, explicit calendars, delivery != success, storms keep every obligation."""
from datetime import date, datetime, time, timedelta

import pytest

from conftest import clock, principal
from kccs_evidence.assessment import build_assessment
from kccs_evidence.obligations import IllegalTransition, ObligationLedger, PolicyIncomplete, Regime, compute_due_at
from kccs_evidence.temporal import UTC, parse_pack_utc

H72 = Regime("ELAPSED_HOURS", hours=72)


def test_clock_starts_at_alert_receipt_not_excursion_or_disposition(store):
    a = build_assessment(store, principal("T-AURA"), "T-AURA", "EXC-110553", clock=clock)
    track = a["notification_track"]
    assert track["clock_start_utc"] == "2026-08-06T10:56:00Z" and track["due_at_utc"] == "2026-08-09T10:56:00Z"
    assert track["independent_of_disposition"] is True and track["paused_by_evidence_waits"] is False


def test_evidence_waits_do_not_move_the_deadline():
    led = ObligationLedger()
    t0 = datetime(2026, 8, 6, 10, 56, tzinfo=UTC)
    ob, _ = led.register("T-AURA", "EXC-110553", t0, H72)
    due = ob.due_at
    for reason in ("waiting for carrier setpoint CSV", "lab result (9-day turnaround)", "SOP revision conflict"):
        led.record_evidence_wait("T-AURA", "EXC-110553", reason, t0 + timedelta(hours=10))
    assert ob.due_at == due == t0 + timedelta(hours=72)
    assert led.breached(t0 + timedelta(hours=73)) == [ob]


def test_next_business_day_requires_explicit_timezone_and_calendar():
    alert = datetime(2026, 7, 3, 22, 0, tzinfo=UTC)            # Friday 18:00 New York
    with pytest.raises(PolicyIncomplete):
        compute_due_at(alert, Regime("NEXT_BUSINESS_DAY"))
    with pytest.raises(PolicyIncomplete):
        compute_due_at(alert, Regime("NEXT_BUSINESS_DAY", tz="America/New_York"))
    reg = Regime("NEXT_BUSINESS_DAY", tz="America/New_York", holidays=frozenset({date(2026, 7, 6)}), deadline_local_time=time(17, 0))
    # SYNTHETIC calendar: Monday 6 July treated as a holiday -> due Tuesday 17:00 EDT = 21:00 UTC
    assert compute_due_at(alert, reg) == datetime(2026, 7, 7, 21, 0, tzinfo=UTC)
    # The same alert evaluated in a different zone yields a different deadline: timezone is part of policy.
    reg_ct = Regime("NEXT_BUSINESS_DAY", tz="America/Chicago", holidays=frozenset(), deadline_local_time=time(17, 0))
    assert compute_due_at(alert, reg_ct) == datetime(2026, 7, 6, 22, 0, tzinfo=UTC)


def test_pinnacle_meridian_deadline_not_guessed_as_24h(store):
    a = build_assessment(store, principal("T-PINNACLE"), "T-PINNACLE", "EXC-112352", clock=clock)
    assert a["notification_track"]["status"] == "POLICY_INCOMPLETE_ESCALATE" and a["notification_track"]["due_at_utc"] is None


def test_failed_or_queued_delivery_is_not_success():
    led = ObligationLedger()
    t0 = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    ob, _ = led.register("T-NORDIA", "E1", t0, H72)
    led.transition("T-NORDIA", "E1", "NOTIFIABLE_CONFIRMED", at=t0, by="qa-1", expected_version=1, note="notifiable")
    led.transition("T-NORDIA", "E1", "SUBMISSION_QUEUED", at=t0, by="system", expected_version=2)
    assert not ob.satisfied
    led.transition("T-NORDIA", "E1", "DELIVERY_FAILED", at=t0, by="system", expected_version=3, note="SMTP 451")
    assert not ob.satisfied and ob in led.at_risk(t0 + timedelta(hours=70), timedelta(hours=4))
    with pytest.raises(IllegalTransition):
        led.transition("T-NORDIA", "E1", "ACKNOWLEDGED", at=t0, by="system", expected_version=4)
    led.transition("T-NORDIA", "E1", "SUBMISSION_QUEUED", at=t0, by="system", expected_version=4)
    led.transition("T-NORDIA", "E1", "SUBMITTED_AWAITING_ACK", at=t0, by="system", expected_version=5)
    assert not ob.satisfied
    led.transition("T-NORDIA", "E1", "ACKNOWLEDGED", at=t0, by="regulator-gateway", expected_version=6, note="ack ref 123")
    assert ob.satisfied


def test_concurrent_transition_rejected_by_version():
    led = ObligationLedger()
    t0 = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    led.register("T-AURA", "E1", t0, H72)
    led.transition("T-AURA", "E1", "NOTIFIABLE_CONFIRMED", at=t0, by="qa-1", expected_version=1, note="x")
    with pytest.raises(IllegalTransition, match="version conflict"):
        led.transition("T-AURA", "E1", "CLOSED_NOT_NOTIFIABLE", at=t0, by="qa-2", expected_version=1, note="y")


def test_not_notifiable_needs_named_human_and_rationale():
    led = ObligationLedger()
    t0 = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    led.register("T-AURA", "E1", t0, H72)
    with pytest.raises(IllegalTransition):
        led.transition("T-AURA", "E1", "CLOSED_NOT_NOTIFIABLE", at=t0, by="system", expected_version=1, note="auto")
    with pytest.raises(IllegalTransition):
        led.transition("T-AURA", "E1", "CLOSED_NOT_NOTIFIABLE", at=t0, by="qa-1", expected_version=1, note="")


def test_storm_keeps_every_obligation_real_inc_2502_rows(snapshot):
    storm = [r for r in snapshot.records if r.sheet == "01_Excursion_Events" and "chiller controller failure" in str(r.get("notes") or "")]
    assert len(storm) == 58                      # matches 00_README!R28 (57 + 1 among the 24)
    regimes = {t: H72 for t in {r.tenant_code for r in storm}}
    led = ObligationLedger()
    created = led.register_storm([(r.tenant_code, r.record_key, parse_pack_utc(r.get("alert_ts_utc"))) for r in storm], regimes, "INC-2502")
    assert created == 58 and len(led.all()) == 58
    assert led.register_storm([(r.tenant_code, r.record_key, parse_pack_utc(r.get("alert_ts_utc"))) for r in storm], regimes, "INC-2502") == 0


def test_storm_of_1912_synthetic_alerts_does_not_starve_other_tenants():
    """SYNTHETIC volume test: 1,912 storm alerts (INC-2502 size) plus 4 unrelated tenants' alerts."""
    led = ObligationLedger()
    t0 = datetime(2026, 2, 19, 9, 0, tzinfo=UTC)
    storm = [("T-VIRENT", f"STORM-{i}", t0 + timedelta(seconds=i)) for i in range(1912)]
    led.register_storm(storm, {"T-VIRENT": Regime("ELAPSED_HOURS", hours=360)}, "INC-2502")
    for i, tenant in enumerate(("T-AURA", "T-NORDIA", "T-AURA", "T-NORDIA")):
        led.register(tenant, f"OTHER-{i}", t0 + timedelta(minutes=5), H72)
    led.register("T-PINNACLE", "NBD-1", t0, Regime("NEXT_BUSINESS_DAY"))     # policy incomplete -> must surface first
    assert len(led.all()) == 1912 + 5
    worklist = led.at_risk(t0 + timedelta(hours=60), timedelta(hours=24))
    assert worklist[0].event_id == "NBD-1"
    assert {o.event_id for o in worklist[1:5]} == {f"OTHER-{i}" for i in range(4)}   # 72 h obligations ahead of 360 h storm
