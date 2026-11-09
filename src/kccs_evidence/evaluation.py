"""Evaluation layer: the only module that reads historical outcome fields.

It compares kernel assessments with what humans/engines did, and reports
disagreements as review candidates. It does NOT compute accuracy: the 420 rows
are a stratified evidence pack (00_README!R28), prior outcomes are not ground
truth (auto-closures were never audited, 00_README!R36), and the kernel never
outputs a disposition, so there is nothing to score it against.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from .assessment import OUTCOME_FIELDS
from .config_loader import load_config
from .obligations import PolicyIncomplete, Regime, compute_due_at
from .temporal import parse_pack_utc

# Hand-written expectation per override reason (09_Override_Reasons): which kernel finding
# would surface the reviewer's concern. Written by reading the verbatim reason only.
OVERRIDE_EXPECTATIONS: dict[str, tuple[list[str], str]] = {
    "EXC-110532": ([], "OUT_OF_SCOPE: duplicate physical excursion detection (Q6) not implemented"),
    "EXC-110588": ([], "OUT_OF_SCOPE: missing-leg telemetry completeness not in pack"),
    "EXC-110511": ([], "PREVENTED_BY_CONSTRUCTION: precedents are tenant-filtered before retrieval (test_tenant_isolation)"),
    "EXC-110490": (
        ["SOP_REVISION_OVERLAP", "SOP_NONE_IN_FORCE", "NO_SOP_INDEXED", "SOP_BOUNDARY_AMBIGUOUS", "ORIGIN_FACILITY_UNRESOLVED"],
        "SOP revision in force at Bhiwandi",
    ),
    "EXC-110497": (["STABILITY_REFERENCED_STUDY_INADMISSIBLE"], "wrong-presentation study STB-4417"),
    "EXC-110581": (["CARRIER_ID=CNT-2023-0441"], "Aeroflux GmbH vs Pvt Ltd: the Frankfurt leg must resolve to the GmbH contract"),
    "EXC-110462": ([], "OUT_OF_SCOPE: packaging integrity not in pack"),
    "EXC-110469": (["DOCK_DOOR_ALIGNMENT_UNVERIFIED"], "door/excursion timestamp alignment"),
    "EXC-110602": (["SOP_HANDWRITTEN_ANNOTATION", "SOP_ACCEPTANCE_LIMIT_CONTENT_UNAVAILABLE"], "handwritten annexure limit"),
    "EXC-110504": (["GATEWAY_GAP_SPANS_EXCURSION", "GATEWAY_GAP_IN_WINDOW", "INTERPOLATED_READINGS"], "gateway gap / interpolation"),
    "EXC-110595": ([], "AUTHORITY_FIELD: output_language pt-BR is surfaced in disposition_authority, translation not implemented"),
    "EXC-110455": (["LANE_HISTORY_PRESENT"], "repeated lane excursions"),
    "EXC-110483": (["COLD_EXCURSION"], "freeze below 0 °C"),
    "EXC-110476": (["PRODUCT_AMBIGUOUS", "SPEC_DISAGREES_WITH_CURRENT_MASTER"], "two master rows / wrong spec"),
    "EXC-110525": (["BMS_TENANT_ATTRIBUTION_DERIVED"], "BMS outage batch auto-close; product in room"),
    "EXC-110448": (["FIRMWARE_BULLETIN_APPLIES"], "firmware TT-2.14.3"),
    "EXC-110441": (["CUMULATIVE_UNVERIFIABLE", "BATCH_EXPOSURE_HISTORY_UNAVAILABLE"], "72 h cumulative allowance relied on"),
    "EXC-110567": ([], "OUT_OF_SCOPE: reefer setpoint record (carrier CSV) not in pack"),
    "EXC-110546": (["BATCH_EXPOSURE_HISTORY_UNAVAILABLE"], "same batch, earlier excursion"),
    "EXC-110518": (["CONTRACT_NO_COLD_CHAIN_CLAUSE"], "Ganga Roadlines, no cold-chain clause"),
    "EXC-110574": (["PRODUCT_MASTER_ALLOWANCE_IS_REFER_QA"], "'Refer QA' is not an allowance"),
    "EXC-110553": ([], "NOTIFICATION_TRACK: separate clock means disposition need not be rushed to meet the report"),
    "EXC-110539": ([], "OUT_OF_SCOPE: permitted dry-ice replenishment operation needs the operations log"),
    "EXC-110560": ([], "OUT_OF_SCOPE: expiry-shortening rules not in pack"),
}
PACK_WIDE_BLOCKERS = {"TEMPERATURE_SERIES_NOT_AVAILABLE", "SOP_ACCEPTANCE_LIMIT_CONTENT_UNAVAILABLE"}


def _codes(a: dict[str, Any]) -> set[str]:
    codes = {f["code"] for f in a["findings"]}
    for chk in a["evidence"]["stability"]["limit_checks"]:
        codes.add(chk["status"])
    carrier = a["entities"]["carrier"]
    if carrier.get("resolved_id"):
        codes.add(f"CARRIER_ID={carrier['resolved_id']}")
    return codes


def evaluate(events: list, at_alert: dict[str, dict], at_extract: dict[str, dict], overrides: dict[str, dict]) -> dict[str, Any]:
    """events: source records of 01 (full rows, evaluation-only use)."""
    out: dict[str, Any] = {
        "warning": (
            "Stratified 420-row evidence pack. Nothing here is a population accuracy, automation rate or "
            "closure estimate. Disagreements are review candidates, not proof that either side was right."
        )
    }
    # 1. coverage and abstention
    for label, assessments in (("at_alert_reconstructed", at_alert), ("at_extract_2026-09-14", at_extract)):
        status = Counter(a["disposition_evidence_status"] for a in assessments.values())
        case_specific = Counter()
        only_pack_wide = 0
        for a in assessments.values():
            cs = set(a["blocking_reasons"]) - PACK_WIDE_BLOCKERS
            only_pack_wide += not cs
            for c in cs:
                case_specific[c] += 1
        dims = defaultdict(Counter)
        for a in assessments.values():
            e = a["entities"]
            for k in ("product", "origin", "destination", "carrier"):
                dims[k][e[k]["status"]] += 1
            dims["stability"][a["evidence"]["stability"]["status"]] += 1
            for s in a["evidence"]["sop_origin"] or [{"status": "NO_TEM_DOCUMENT_INDEXED"}]:
                dims["sop_origin"][s["status"]] += 1
            dims["notification"][a["notification_track"]["status"]] += 1
        out[label] = {
            "status": dict(status),
            "abstain_only_on_pack_wide_gaps": only_pack_wide,
            "case_specific_blockers": dict(case_specific.most_common()),
            "dimension_status": {k: dict(v) for k, v in dims.items()},
        }
    # 2. historical outcome vs kernel (review candidates)
    rows = []
    cross = Counter()
    for e in events:
        a = at_alert[e.record_key]
        cs = sorted(set(a["blocking_reasons"]) - PACK_WIDE_BLOCKERS)
        hist = e.get("rules_engine_recommendation")
        cross[(hist, "case_specific_blockers" if cs else "pack_wide_only")] += 1
        if hist == "AUTO_CLOSE" and cs:
            rows.append(
                {
                    "event_id": e.record_key,
                    "tenant": e.tenant_code,
                    "historical": hist,
                    "triage_outcome": e.get("triage_outcome"),
                    "kernel_case_specific_blockers": cs,
                }
            )
    out["historical_vs_kernel"] = {
        "counts": {f"{k[0]} / {k[1]}": v for k, v in sorted(cross.items(), key=str)},
        "auto_closed_despite_case_specific_gaps": {"n": len(rows), "examples": rows[:15]},
        "note": "The kernel does not decide closure; these auto-closures had evidence gaps that a closure policy should check.",
    }
    # 3. firmware re-adjudication: what was knowable when
    fw_rows = []
    for e in events:
        if e.get("logger_fw") != "TT-2.14.3":
            continue
        then = "FIRMWARE_BULLETIN_APPLIES" in _codes(at_alert[e.record_key])
        now = "FIRMWARE_BULLETIN_APPLIES" in _codes(at_extract[e.record_key])
        fw_rows.append((e.record_key, e.get("alert_ts_utc"), then, now, e.get("reopened_later")))
    out["firmware_TT-2.14.3"] = {
        "events": len(fw_rows),
        "flagged_at_alert": sum(r[2] for r in fw_rows),
        "flagged_at_extract": sum(r[3] for r in fw_rows),
        "historically_reopened": sum(r[4] == "Y" for r in fw_rows),
        "alert_before_bulletin_and_reopened": [r[0] for r in fw_rows if not r[2] and r[4] == "Y"][:10],
        "note": "At-alert view cannot know the 2026-04-11 bulletin for earlier alerts; the at-extract view flags them for re-review without editing the original assessment.",
    }
    # 4. override reasons: did the kernel surface the reviewer's concern?
    ov = []
    for eid, o in overrides.items():
        exp, why = OVERRIDE_EXPECTATIONS.get(eid, ([], "no expectation recorded"))
        got = _codes(at_alert[eid]) if eid in at_alert else set()
        hit = sorted(set(exp) & got)
        if not exp:
            verdict = why.split(":")[0]
        elif not hit:
            verdict = "NOT_SURFACED"
        elif set(hit) <= PACK_WIDE_BLOCKERS:
            verdict = "SURFACED_ONLY_GENERICALLY"
        else:
            verdict = "SURFACED"
        ov.append(
            {
                "event_id": eid,
                "engine_said": o.get("engine_said"),
                "reviewer_decided": o.get("reviewer_decided"),
                "concern": why,
                "expected_any_of": exp,
                "kernel_codes_matching": hit,
                "verdict": verdict,
                "kernel_blocking": at_alert[eid]["blocking_reasons"] if eid in at_alert else [],
            }
        )
    out["override_reasons"] = {"summary": dict(Counter(x["verdict"] for x in ov)), "rows": ov}
    # 5. notification clock check on rows the pack flags reportable
    notes = []
    regimes = load_config("reference_facts.json")["notification_regimes"]
    for e in events:
        if e.get("regulator_reportable") != "Y":
            continue
        alert = parse_pack_utc(e.get("alert_ts_utc"))
        cfg = regimes.get(e.tenant_code)
        try:
            due = compute_due_at(alert, Regime.from_config(cfg))
            filed = alert + timedelta(hours=float(e.get("hours_to_notification")))
            kernel_late = filed > due
            agree = kernel_late == (e.get("reported_within_window") == "N")
            notes.append(
                {
                    "event_id": e.record_key,
                    "tenant": e.tenant_code,
                    "window_h_in_pack": e.get("reg_window_hours"),
                    "kernel_due_utc": due.strftime("%Y-%m-%dT%H:%MZ"),
                    "hours_to_notification": e.get("hours_to_notification"),
                    "kernel_says_late": kernel_late,
                    "pack_says_within": e.get("reported_within_window"),
                    "consistent": agree,
                    "disposition_days": e.get("days_to_disposition"),
                }
            )
        except PolicyIncomplete as exc:
            notes.append(
                {
                    "event_id": e.record_key,
                    "tenant": e.tenant_code,
                    "window_h_in_pack": e.get("reg_window_hours"),
                    "kernel_due_utc": None,
                    "reason": str(exc),
                    "pack_says_within": e.get("reported_within_window"),
                }
            )
    out["notification_check"] = {
        "rows": notes,
        "late_in_pack": sum(n["pack_says_within"] == "N" for n in notes),
        "inconsistent_with_kernel_clock": [n["event_id"] for n in notes if n.get("consistent") is False],
        "not_computable_next_business_day": [n["event_id"] for n in notes if n.get("kernel_due_utc") is None],
    }
    out["outcome_fields_used_here_only"] = list(OUTCOME_FIELDS)
    return out
