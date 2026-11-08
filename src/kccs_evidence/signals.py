"""Specification parsing, stability-limit parsing, telemetry quality and firmware uncertainty.

All arithmetic here is a reviewer aid. Aggregates (min/max/mean/duration) are
not a temperature series; cumulative or once-only conditions cannot be verified
without batch exposure history, which the pack does not contain.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .config_loader import load_config
from .model import BLOCKING, INFO, REVIEW, Finding
from .temporal import parse_iso_utc

NUM = r"[-+]?\d+(?:\.\d+)?"


def parse_spec_range(text: str | None) -> tuple[float | None, float | None] | None:
    """Return (low, high) °C, with None for an open side; None if not parseable without assumption."""
    if not text:
        return None
    t = text.replace("–", "-").replace("—", "-").replace("≤", "<=").replace("°", "")
    m = re.search(rf"(?<![\d.])({NUM})\s*C?\s*(?:-|to|/)\s*({NUM})\s*C?", t, re.I)
    if m and not re.search(r"nominal", t, re.I):
        lo, hi = float(m.group(1)), float(m.group(2))
        if "/" in m.group(0) and lo > 0 and "+" not in m.group(0) and hi < lo:
            return None
        return (min(lo, hi), max(lo, hi))
    m = re.search(rf"\(\s*({NUM})\s*,\s*({NUM})\s*\)", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (min(a, b), max(a, b))
    m = re.search(rf"below\s+({NUM})", t, re.I)
    if m:
        return (None, float(m.group(1)))
    m = re.search(rf"<=\s*({NUM})", t)
    if m:
        return (None, float(m.group(1)))
    return None


def parse_limit(text: str | None) -> dict[str, Any]:
    if not text:
        return {"kind": "ABSENT"}
    t = text.replace("≤", "<=").replace("°", "").casefold()
    pats = [
        (rf"one excursion, up to ({NUM}) h below ({NUM})", lambda m: {"kind": "SINGLE_BELOW_CEILING", "hours": float(m[1]), "ceiling_c": float(m[2]), "once_only": True}),
        (rf"<=\s*({NUM}) h to ({NUM}) c, once only", lambda m: {"kind": "SINGLE_BELOW_CEILING", "hours": float(m[1]), "ceiling_c": float(m[2]), "once_only": True}),
        (rf"single excursion <=\s*({NUM}) h to ({NUM})", lambda m: {"kind": "SINGLE_BELOW_CEILING", "hours": float(m[1]), "ceiling_c": float(m[2]), "once_only": True}),
        (rf"one excursion, up to ({NUM}) h above ({NUM})", lambda m: {"kind": "SINGLE_ABOVE_THRESHOLD", "hours": float(m[1]), "threshold_c": float(m[2]), "once_only": True}),
        (rf"cumulative ({NUM}) h above ({NUM})", lambda m: {"kind": "CUMULATIVE_ABOVE", "hours": float(m[1]), "threshold_c": float(m[2])}),
        (rf"excursions to ({NUM}) ?c.*?up to ({NUM}) d", lambda m: {"kind": "CUMULATIVE_CEILING_DAYS", "ceiling_c": float(m[1]), "days": float(m[2])}),
        (rf"no excursion above ({NUM}) c beyond ({NUM}) h", lambda m: {"kind": "CEILING_WITH_DURATION", "ceiling_c": float(m[1]), "hours": float(m[2])}),
        (rf"no hold above ({NUM}) c beyond ({NUM}) h", lambda m: {"kind": "CEILING_WITH_DURATION", "ceiling_c": float(m[1]), "hours": float(m[2])}),
        (rf"no excursion above ({NUM}) c permitted", lambda m: {"kind": "CEILING", "ceiling_c": float(m[1])}),
        (r"do not thaw and refreeze", lambda m: {"kind": "NOT_EVALUABLE_FROM_AGGREGATES"}),
        (r"do not freeze", lambda m: {"kind": "NO_FREEZE"}),
        (r"dry ice replenishment permitted", lambda m: {"kind": "NOT_EVALUABLE_FROM_AGGREGATES"}),
        (r"no excursion permitted", lambda m: {"kind": "NONE_PERMITTED"}),
        (r"refer qa", lambda m: {"kind": "REFER_QA"}),
    ]
    for p, build in pats:
        m = re.search(p, t)
        if m:
            out = build(m)
            out["text"] = text
            return out
    return {"kind": "UNPARSED", "text": text}


def firmware_uncertainty(logger_fw: str | None, logger_vendor: str | None, knowledge_cutoff: datetime) -> dict[str, Any] | None:
    for b in load_config("reference_facts.json")["firmware_bulletins"]:
        if b["firmware"] == logger_fw and b["vendor"] == logger_vendor and parse_iso_utc(b["known_from_utc"]) <= knowledge_cutoff:
            return b
    return None


def evaluate_limit(limit: dict[str, Any], ev: dict[str, Any], spec: tuple | None, fw: dict | None) -> dict[str, Any]:
    """Compare one event's aggregates with a parsed limit. Returns status + explanation."""
    mx, mn, dur = ev["max_temp_c"], ev["min_temp_c"], ev["duration_min"]
    up = fw["magnitude_c_max"] if fw and fw["direction"] == "UNDER_REPORTS" else 0.0
    max_band, min_band = (mx, mx + up), (mn, mn + up)
    unverifiable: list[str] = []
    kind = limit["kind"]
    above = spec is not None and spec[1] is not None and max_band[1] > spec[1]
    below_only = spec is not None and spec[0] is not None and mn < spec[0] and not above

    def band(best_fail: bool, worst_fail: bool, ok: str, fail: str):
        if best_fail:
            return fail
        return "INDETERMINATE_FIRMWARE_UNCERTAINTY" if worst_fail else ok

    if kind == "SINGLE_BELOW_CEILING":
        if below_only:
            status = "NOT_APPLICABLE_COLD_EXCURSION"
        elif dur > limit["hours"] * 60:
            status = "EXCEEDS_STATED_LIMIT"
        else:
            status = band(max_band[0] >= limit["ceiling_c"], max_band[1] >= limit["ceiling_c"],
                          "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY", "EXCEEDS_STATED_LIMIT")
        unverifiable.append("'once only' requires the batch's full excursion history (not in pack)")
    elif kind == "SINGLE_ABOVE_THRESHOLD":
        status = "EXCEEDS_STATED_LIMIT" if dur > limit["hours"] * 60 else "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY"
        unverifiable.append("'once only' requires the batch's full excursion history (not in pack)")
    elif kind == "CUMULATIVE_ABOVE":
        status = "CUMULATIVE_UNVERIFIABLE"
        unverifiable.append(f"lifetime exposure above {limit['threshold_c']} °C for this batch is unknown; this event alone contributes up to {dur} min of {limit['hours']} h")
    elif kind == "CUMULATIVE_CEILING_DAYS":
        status = band(max_band[0] > limit["ceiling_c"], max_band[1] > limit["ceiling_c"], "CUMULATIVE_UNVERIFIABLE", "EXCEEDS_STATED_LIMIT")
        unverifiable.append("cumulative days at elevated temperature for this batch are unknown")
    elif kind == "CEILING":
        status = band(max_band[0] > limit["ceiling_c"], max_band[1] > limit["ceiling_c"],
                      "CEILING_NOT_EXCEEDED_BY_REPORTED_MAX", "EXCEEDS_STATED_LIMIT")
    elif kind == "CEILING_WITH_DURATION":
        if max_band[1] <= limit["ceiling_c"]:
            status = "CEILING_NOT_EXCEEDED_BY_REPORTED_MAX"
        elif dur <= limit["hours"] * 60:
            status = "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY" if max_band[0] > limit["ceiling_c"] or up == 0 else "INDETERMINATE_FIRMWARE_UNCERTAINTY"
            unverifiable.append("time above the ceiling is taken from the alert's duration_min, not a series")
        else:
            status = "EXCEEDS_STATED_LIMIT" if max_band[0] > limit["ceiling_c"] else "INDETERMINATE_FIRMWARE_UNCERTAINTY"
    elif kind == "NO_FREEZE":
        status = band(min_band[1] <= 0, min_band[0] <= 0, "NO_FREEZE_INDICATED_BY_REPORTED_MIN", "POSSIBLE_FREEZE_EXPOSURE")
    elif kind == "NONE_PERMITTED":
        status = "NO_ALLOWANCE_STATED"
    elif kind == "REFER_QA":
        status = "NOT_AN_ALLOWANCE"
    else:
        status = "NOT_EVALUATED"
    return {"limit": limit, "status": status, "reported": {"max_c": mx, "min_c": mn, "duration_min": dur},
            "firmware_band_c": {"max": list(max_band), "min": list(min_band)} if up else None,
            "unverifiable_conditions": unverifiable}


def excursion_direction(ev: dict[str, Any], spec: tuple | None, fw: dict | None) -> str:
    if spec is None:
        return "UNKNOWN_SPEC_UNPARSED"
    lo, hi = spec
    above = hi is not None and ev["max_temp_c"] > hi
    below = lo is not None and ev["min_temp_c"] < lo
    if above and below:
        return "ABOVE_AND_BELOW"
    if above:
        return "ABOVE"
    if below:
        return "BELOW"
    up = fw["magnitude_c_max"] if fw else 0.0
    if hi is not None and ev["max_temp_c"] + up > hi:
        return "WITHIN_REPORTED_BUT_POSSIBLY_ABOVE_AFTER_FIRMWARE_CORRECTION"
    return "WITHIN_SPEC_AS_REPORTED"


def telemetry_findings(ev: dict[str, Any], source_ref: str) -> list[Finding]:
    f = [Finding("TEMPERATURE_SERIES_NOT_AVAILABLE", BLOCKING, "telemetry",
                 "Only aggregate statistics (min/max/mean/duration) are available; the temperature series relied on must be retained for the disposition basis (AUD-2603). Telemetry archive is a stub in this prototype.",
                 (source_ref,), "Snapshot the raw series from the telemetry source into the evidence store")]
    gap, dur = ev["gateway_gap_min"], ev["duration_min"]
    if gap and gap >= dur:
        f.append(Finding("GATEWAY_GAP_SPANS_EXCURSION", BLOCKING, "telemetry",
                         f"Gateway gap of {gap} min is at least the excursion duration ({dur} min); the excursion may be an artefact of missing data.",
                         (source_ref,), "Obtain backfilled readings or treat as unproven"))
    elif gap:
        f.append(Finding("GATEWAY_GAP_IN_WINDOW", REVIEW, "telemetry", f"Gateway gap of {gap} min within the excursion window.", (source_ref,)))
    if ev["interpolated"] == "Y":
        f.append(Finding("INTERPOLATED_READINGS", REVIEW, "telemetry",
                         "Readings in the window are partly interpolated, i.e. not measured.", (source_ref,),
                         "Distinguish measured from interpolated readings"))
    if ev["readings_in_window"] is not None and ev["readings_in_window"] <= 1:
        f.append(Finding("SPARSE_READINGS", REVIEW, "telemetry", f"{ev['readings_in_window']} reading(s) in window.", (source_ref,)))
    if ev["dock_door_open_flag"] == "Y":
        f.append(Finding("DOCK_DOOR_ALIGNMENT_UNVERIFIED", INFO, "telemetry",
                         "Dock-door flag set; whether the door event precedes the excursion cannot be checked without the door log.", (source_ref,)))
    if ev["source_system"] == "SYS-03":
        f.append(Finding("BMS_TENANT_ATTRIBUTION_DERIVED", REVIEW, "attribution",
                         "Facility BMS telemetry carries no tenant tags (11_Systems_Inventory!R4); tenant/consignment attribution came from a TMS join that is not reproducible from the pack, and product-in-room is unverified.",
                         (source_ref, "11_Systems_Inventory!R4"), "Confirm product was loaded and owned by this tenant"))
    return f
