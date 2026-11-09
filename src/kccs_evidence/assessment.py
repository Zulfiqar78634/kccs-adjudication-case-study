"""Assessment builder: turns one alert into a reproducible evidence assessment.

Leakage control
---------------
Only ALLOWED_EVENT_FIELDS of the alert are read (they exist at alert receipt).
OUTCOME_FIELDS are never passed to the evidence logic; they are used only by
evaluation.py. Prior cases on the same lane may show their disposition only if
it was signed before the knowledge cutoff and the case was never reopened
(the pack keeps only the latest value, so an original value cannot be recovered).

Output is a reviewer aid or an explicit abstention, never a disposition.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import metadata, resources
from typing import Any, TypeVar

from . import ASSESSMENT_SCHEMA_VERSION, RULESET_VERSION, STORE_SCHEMA_VERSION, __version__
from .access import Principal, TenantView, system_clock
from .config_loader import config_manifest, load_config
from .model import BLOCKING, INFO, REVIEW, Finding, Resolution, norm
from .obligations import PolicyIncomplete, Regime, compute_due_at
from .policy_sop import select_sop
from .resolution import resolve_carrier, resolve_facility, resolve_product
from .signals import excursion_direction, firmware_uncertainty, parse_spec_range, telemetry_findings
from .sources import canonical_json, sha256_text
from .stability import assess_stability
from .store import Store, VersionedRecord
from .temporal import iso, parse_date, parse_effective_to, parse_iso_utc, parse_pack_utc

ALLOWED_EVENT_FIELDS = (
    "event_id",
    "alert_ts_utc",
    "tenant_code",
    "shipment_ref",
    "leg_no",
    "source_system",
    "logger_id",
    "logger_vendor",
    "logger_fw",
    "product_ref_as_received",
    "origin_ref_as_received",
    "dest_ref_as_received",
    "lane_text",
    "carrier_ref_as_received",
    "mode",
    "excursion_start_utc",
    "excursion_end_utc",
    "duration_min",
    "min_temp_c",
    "max_temp_c",
    "mean_temp_c",
    "spec_text_as_received",
    "readings_in_window",
    "gateway_gap_min",
    "interpolated",
    "dock_door_open_flag",
    "prior_excursions_lane_90d",
    "consignment_value_usd",
)
OUTCOME_FIELDS = (
    "case_opened",
    "triage_outcome",
    "rules_engine_recommendation",
    "final_disposition",
    "reviewer_id",
    "review_minutes",
    "systems_opened",
    "reviewer_overrode",
    "days_to_disposition",
    "regulator_reportable",
    "reg_window_hours",
    "hours_to_notification",
    "reported_within_window",
    "reopened_later",
    "notes",
)
TENANT_PREFIX = {
    "T-AURA": "AUR",
    "T-VIRENT": "VIR",
    "T-NORDIA": "NOR",
    "T-PINNACLE": "PIN",
    "T-MERIDIAN": "MER",
    "T-SAHYADRI": "SAH",
    "T-CAMPOS": "CAM",
    "T-KAVERI": "KAV",
}
DISPOSITION_DIMENSIONS = {"identity", "policy", "stability", "telemetry", "firmware", "attribution", "knowledge"}
EXCURSION_AGGREGATE_FIELDS = (
    "max_temp_c",
    "min_temp_c",
    "duration_min",
    "gateway_gap_min",
    "interpolated",
    "readings_in_window",
    "dock_door_open_flag",
    "source_system",
)
LANE_HISTORY_WINDOW = timedelta(days=90)
MISSING_INPUT_SUFFIXES = ("UNAVAILABLE", "MISSING", "NOT_IN_TENANT_INDEX", "UNRESOLVED")
CITABLE_SHEETS = ("02_Product_Master", "05_SOP_Index", "06_Stability_Index")
# A new assessment that adds any of these findings may invalidate an earlier human review.
REOPEN_TRIGGER_FINDINGS = {"FIRMWARE_BULLETIN_APPLIES", "POSSIBLE_UNDETECTED_EXCURSION", "LIMIT_CHECK_FLIPS_WITHIN_FIRMWARE_BAND"}
READY = "READY_FOR_QA_REVIEW"
RECONSTRUCTED_BASIS = (
    "Evidence is the ingested snapshot, restricted by every knowledge date the pack provides "
    "(alias confirmed_on, bulletin dates, human mapping recorded_at, precedent signature times). "
    "The pack carries no recorded-time history for SOP/stability/master rows, so this is a "
    "retrospective reconstruction ('what do we conclude now about then'), not proof of what was known then."
)

T = TypeVar("T")
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class AlertInput:
    """The alert restricted to fields that exist at alert receipt."""

    fields: dict[str, Any]
    source_ref: str

    @classmethod
    def from_record(cls, rec: VersionedRecord) -> AlertInput:
        return cls({k: rec.get(k) for k in ALLOWED_EVENT_FIELDS}, rec.source_ref)

    def __getitem__(self, k: str) -> Any:
        return self.fields[k]

    @property
    def fields_sha256(self) -> str:
        return sha256_text(canonical_json(self.fields))


def code_fingerprint() -> str:
    """SHA-256 over the package's .py files, so an assessment records the exact code that produced it."""
    # Line endings are normalised so a Windows checkout (CRLF) fingerprints the same code identically.
    h = hashlib.sha256()
    pkg = resources.files("kccs_evidence")
    for name in sorted(p.name for p in pkg.iterdir() if p.name.endswith(".py")):
        h.update(name.encode())
        h.update(pkg.joinpath(name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def resolve_cutoff(spec: str, alert_ts: datetime, clock: Clock) -> datetime:
    """Turn a knowledge-cutoff spec ('alert', 'now' or ISO-8601 UTC) into an instant."""
    if spec == "alert":
        return alert_ts
    if spec == "now":
        return clock()
    cutoff = parse_iso_utc(spec)
    if cutoff < alert_ts:
        raise ValueError("knowledge cutoff precedes alert receipt; the alert itself was not yet known")
    return cutoff


def _collect(findings: list[Finding], result: tuple[T, list[Finding]]) -> T:
    """Append a step's findings and return its value (steps return ``(value, findings)``)."""
    value, new = result
    findings.extend(new)
    return value


# ---------------- knowledge time ----------------
def _store_cutoff(store: Store, cutoff: datetime, mode: str) -> str:
    if mode != "RECONSTRUCTED":
        return iso(cutoff)
    # The initial snapshot is backfilled as if known at the cutoff (its true history is not in the pack);
    # anything recorded after that baseline (corrections, later snapshots) is visible only if recorded <= cutoff.
    baseline = min((s["recorded_at"] for s in store.snapshots()), default=iso(cutoff))
    return max(iso(cutoff), baseline)


def _alert_record(view: TenantView, probe: TenantView, event_id: str) -> VersionedRecord:
    # The alert is the subject of the assessment; in strict mode it may itself post-date the cutoff in this
    # store (the pack was recorded at extract), in which case the evidence check abstains.
    known = next((r for r in view.tenant_records("01_Excursion_Events") if r.record_key == event_id), None)
    return known or probe.event(event_id)


def _knowledge_basis(view: TenantView, mode: str, cutoff: datetime, cutoff_spec: str, store_cutoff: str) -> tuple[dict[str, Any], list[Finding]]:
    knowledge = {"mode": mode, "cutoff_utc": iso(cutoff), "cutoff_spec": cutoff_spec, "store_cutoff_utc": store_cutoff}
    if mode == "RECONSTRUCTED":
        knowledge["basis"] = RECONSTRUCTED_BASIS
        return knowledge, [Finding("KNOWLEDGE_TIME_RECONSTRUCTED", INFO, "knowledge", RECONSTRUCTED_BASIS, ())]
    if not view.tenant_records("05_SOP_Index"):
        return knowledge, [
            Finding(
                "KNOWLEDGE_HISTORY_UNAVAILABLE",
                BLOCKING,
                "knowledge",
                f"Strict replay: no evidence was recorded in this system at or before {iso(cutoff)}.",
                (),
                "Use a reconstructed replay and label it as such",
            )
        ]
    return knowledge, []


# ---------------- alert-level checks ----------------
def _check_attribution(alert: AlertInput, tenant: str) -> tuple[bool, list[Finding]]:
    prefix = str(alert["shipment_ref"] or "").split("-")
    if len(prefix) > 1 and TENANT_PREFIX.get(tenant) == prefix[1]:
        return True, []
    return False, [
        Finding(
            "TENANT_ATTRIBUTION_CONFLICT",
            BLOCKING,
            "attribution",
            f"shipment_ref {alert['shipment_ref']!r} does not carry the prefix expected for {tenant}.",
            (alert.source_ref,),
            "Quarantine for attribution; do not use tenant-scoped evidence",
        )
    ]


def _resolve_entities(view: TenantView, alert: AlertInput, cutoff: datetime) -> tuple[dict[str, Resolution], list[Finding]]:
    findings: list[Finding] = []
    knowledge_date = cutoff.date()
    entities = {
        "product": _collect(findings, resolve_product(view, alert["product_ref_as_received"])),
        "origin": _collect(findings, resolve_facility(view, alert["origin_ref_as_received"], "origin", knowledge_date)),
        "destination": _collect(findings, resolve_facility(view, alert["dest_ref_as_received"], "destination", knowledge_date)),
        "carrier": _collect(findings, resolve_carrier(view, alert["carrier_ref_as_received"], knowledge_date)),
    }
    return entities, findings


def _spec_findings(alert: AlertInput, spec: tuple | None, product: Resolution, alert_ts: datetime) -> list[Finding]:
    findings = []
    if spec is None:
        findings.append(
            Finding(
                "SPEC_UNPARSED",
                REVIEW,
                "stability",
                f"Specification {alert['spec_text_as_received']!r} could not be parsed without assumption.",
                (alert.source_ref,),
            )
        )
    if not product.usable:
        return findings
    master_spec = parse_spec_range(product.attributes.get("storage_spec_text"))
    if spec and master_spec and spec != master_spec:
        findings.append(
            Finding(
                "SPEC_DISAGREES_WITH_CURRENT_MASTER",
                REVIEW,
                "stability",
                f"Spec at alert {alert['spec_text_as_received']!r} vs current master {product.attributes.get('storage_spec_text')!r}.",
                (alert.source_ref, product.resolved_id),
                "Confirm which specification governed at alert time",
            )
        )
    last_updated = parse_date(product.attributes.get("last_updated"))
    if last_updated and last_updated > alert_ts.date():
        findings.append(
            Finding(
                "PRODUCT_MASTER_UPDATED_AFTER_ALERT",
                REVIEW,
                "knowledge",
                f"Product-master row last updated {last_updated}, after the alert; the version in force at alert time is not in the pack.",
                (product.resolved_id,),
                "Retrieve the product-master version effective at alert time",
            )
        )
    return findings


def _firmware_and_direction_findings(alert: AlertInput, fw: dict | None, direction: str) -> list[Finding]:
    findings = []
    if fw:
        findings.append(
            Finding(
                "FIRMWARE_BULLETIN_APPLIES",
                REVIEW,
                "firmware",
                f"Logger firmware {alert['logger_fw']} is subject to {fw['bulletin_id']}: under-reports by up to {fw['magnitude_c_max']} °C. "
                f"Treated as an uncertainty interval [+0, +{fw['magnitude_c_max']}] °C, not a fixed correction.",
                (fw["source"],),
                "Re-evaluate temperatures under the uncertainty band",
            )
        )
        if direction.startswith("WITHIN_REPORTED_BUT_POSSIBLY_ABOVE"):
            findings.append(
                Finding(
                    "POSSIBLE_UNDETECTED_EXCURSION",
                    BLOCKING,
                    "firmware",
                    "Reported values are within spec but may exceed it after the firmware correction band.",
                    (fw["source"],),
                )
            )
    if direction in ("BELOW", "ABOVE_AND_BELOW"):
        findings.append(
            Finding(
                "COLD_EXCURSION",
                REVIEW,
                "stability",
                "Excursion below the labelled range; freeze damage is not assessed by warm-excursion allowances (cf. EXC-110483).",
                (alert.source_ref,),
                "Assess freeze sensitivity for this product",
            )
        )
    return findings


def _select_sops(view: TenantView, entities: dict[str, Resolution], exc_start: datetime) -> tuple[dict[str, list], list[Finding]]:
    scope = load_config("sop_scope_rules.json")
    origin_sops, findings = select_sop(view, scope["excursion_titles"], entities["origin"], "origin", exc_start)
    dest_sops, dest_findings = select_sop(view, scope["excursion_titles"], entities["destination"], "destination", exc_start)
    # The origin SOP governs the disposition; destination SOP problems are surfaced for review only.
    findings += [
        Finding(x.code, REVIEW if x.severity == BLOCKING else x.severity, x.dimension, "[destination] " + x.message, x.source_refs, x.human_action)
        for x in dest_findings
    ]
    notification_sops, _ = select_sop(view, scope["notification_titles"], entities["origin"], "origin", exc_start)
    return {"sop_origin": origin_sops, "sop_destination": dest_sops, "sop_notification": notification_sops}, findings


# ---------------- side tracks: liability, history, notification ----------------
def _liability(carrier: Resolution, event_ts: datetime) -> tuple[dict, list[Finding]]:
    out: dict[str, Any] = {"carrier": carrier.to_dict(), "note": "Liability/claims track only; never affects product disposition."}
    findings: list[Finding] = []
    if not carrier.usable:
        return out, findings
    contract = carrier.attributes
    event_date = event_ts.date()
    start, end = parse_date(contract.get("effective_from")), parse_effective_to(contract.get("effective_to"))
    out["contract_in_force_on_event_date_utc"] = start <= event_date < end
    if not out["contract_in_force_on_event_date_utc"]:
        findings.append(
            Finding(
                "CONTRACT_NOT_IN_FORCE_ON_EVENT_DATE",
                REVIEW,
                "liability",
                f"{carrier.resolved_id} window [{contract.get('effective_from')}, {contract.get('effective_to')}) does not cover {event_date}.",
                tuple(carrier.source_refs),
            )
        )
    if "none" in str(contract.get("cold_chain_clause") or "").lower():
        findings.append(
            Finding(
                "CONTRACT_NO_COLD_CHAIN_CLAUSE",
                REVIEW,
                "liability",
                f"{carrier.resolved_id} has no cold-chain schedule; affects who pays, not what happens to product.",
                tuple(carrier.source_refs),
            )
        )
    if "separately" in str(contract.get("amendment_docs") or ""):
        findings.append(
            Finding(
                "CONTRACT_AMENDMENTS_FILED_SEPARATELY",
                INFO,
                "liability",
                f"{carrier.resolved_id}: amendments filed separately and not in the pack.",
                tuple(carrier.source_refs),
            )
        )
    out["claim_window_days"] = contract.get("claim_window_days")
    out["claim_window_trigger"] = "NOT_STATED_IN_PACK"
    return out, findings


def _lane_match(prior: VersionedRecord, alert: AlertInput) -> str | None:
    """'lane' or 'carrier+origin' if the earlier event shares the alert's lane, else None."""
    same_origin = norm(prior.get("origin_ref_as_received")) == norm(alert["origin_ref_as_received"])
    same_lane = norm(prior.get("lane_text")) == norm(alert["lane_text"]) or (
        same_origin and norm(prior.get("dest_ref_as_received")) == norm(alert["dest_ref_as_received"])
    )
    if same_lane:
        return "lane"
    if norm(prior.get("carrier_ref_as_received")) == norm(alert["carrier_ref_as_received"]) and same_origin:
        return "carrier+origin"
    return None


def _disposition_at_cutoff(prior: VersionedRecord, prior_ts: datetime, cutoff: datetime) -> str:
    # Precedent gate: a prior disposition is visible only if signed before the cutoff and never reopened.
    disposition, days = prior.get("final_disposition"), prior.get("days_to_disposition")
    if disposition is None:
        return "NO_HUMAN_DISPOSITION_RECORDED"
    if prior.get("reopened_later") == "Y":
        return "UNKNOWABLE_AT_CUTOFF (case later reopened; pack keeps only the latest value)"
    if days is not None and prior_ts + timedelta(days=float(days)) <= cutoff:
        return disposition
    return "NOT_YET_SIGNED_AT_CUTOFF"


def _lane_history(view: TenantView, alert: AlertInput, alert_ts: datetime, cutoff: datetime) -> tuple[list[dict], list[Finding]]:
    history = []
    for prior in view.tenant_records("01_Excursion_Events"):
        if prior.record_key == alert["event_id"]:
            continue
        prior_ts = parse_pack_utc(prior.get("alert_ts_utc"))
        if prior_ts >= alert_ts or prior_ts > cutoff or alert_ts - prior_ts > LANE_HISTORY_WINDOW:
            continue
        match = _lane_match(prior, alert)
        if match is None:
            continue
        history.append(
            {
                "event_id": prior.record_key,
                "ref": prior.source_ref,
                "alert_ts_utc": prior.get("alert_ts_utc"),
                "match": match,
                "disposition_at_cutoff": _disposition_at_cutoff(prior, prior_ts, cutoff),
            }
        )
    findings = []
    if history:
        findings.append(
            Finding(
                "LANE_HISTORY_PRESENT",
                REVIEW,
                "history",
                f"{len(history)} earlier alert(s) for this tenant on the same lane or carrier+origin within 90 days (pack sample only; not exhaustive).",
                tuple(h["ref"] for h in history),
                "Review prior events for a pattern (equipment, carrier, batch)",
            )
        )
    findings.append(
        Finding(
            "BATCH_EXPOSURE_HISTORY_UNAVAILABLE",
            REVIEW,
            "history",
            "No batch identity or lifetime exposure history in the pack; cumulative and once-only conditions cannot be verified.",
            (),
            "Obtain batch excursion history before relying on a cumulative/once-only allowance",
        )
    )
    return history, findings


def _notification_track(tenant: str, alert_ts: datetime) -> tuple[dict, list[Finding]]:
    cfg = load_config("reference_facts.json")["notification_regimes"].get(tenant)
    track: dict[str, Any] = {
        "clock_start_utc": iso(alert_ts),
        "clock_basis": "alert_ts_utc: when the reading reached Sentinel (00_README!R43)",
        "independent_of_disposition": True,
        "paused_by_evidence_waits": False,
        "notifiability": "UNDETERMINED: a human determination is required; the kernel does not decide it",
        "submission_status": "NOT_VISIBLE_TO_KERNEL",
    }
    if cfg is None:
        track.update(status="REGIME_UNKNOWN", due_at_utc=None)
        return track, [
            Finding(
                "NOTIFICATION_REGIME_UNKNOWN",
                REVIEW,
                "notification",
                "No notification regime configured for this tenant.",
                (),
                "Regulatory Affairs to configure the regime",
            )
        ]
    track["regime"] = cfg
    try:
        due = compute_due_at(alert_ts, Regime.from_config(cfg))
    except PolicyIncomplete as exc:
        track.update(status="POLICY_INCOMPLETE_ESCALATE", due_at_utc=None, error=str(exc))
        return track, [
            Finding(
                "NOTIFICATION_DEADLINE_NOT_COMPUTABLE",
                REVIEW,
                "notification",
                f"Deadline cannot be computed: {exc}. Escalate immediately; do not assume 24 h.",
                (cfg["source"],),
                "Regulatory Affairs to determine the deadline now",
            )
        ]
    track.update(status="DEADLINE_COMPUTED", due_at_utc=iso(due))
    return track, [
        Finding(
            "NOTIFICATION_DETERMINATION_DUE",
            REVIEW,
            "notification",
            f"If notifiable, notification is due by {iso(due)} ({cfg['kind']} {cfg.get('hours')} h from alert receipt). Evidence waits do not pause this clock.",
            (cfg["source"],),
            f"Determine notifiability before {iso(due)}",
        )
    ]


def _disposition_authority(view: TenantView) -> dict[str, Any]:
    constraints = next((r.payload for r in view.tenant_records("12_Tenant_Constraints")), {})
    signer = constraints.get("who_signs_a_disposition")
    return {
        "who_signs": signer,
        "dual_signature_required": "dual" in str(signer).lower(),
        "output_language": constraints.get("output_language"),
        "data_residency": constraints.get("data_residency_position"),
        "third_party_model_apis": constraints.get("third_party_model_apis"),
        "source": "12_Tenant_Constraints",
    }


# ---------------- outcome ----------------
def _evidence_status(blocking: list[Finding], attribution_ok: bool) -> str:
    if not attribution_ok:
        return "QUARANTINED_FOR_ATTRIBUTION"
    if any(x.code == "KNOWLEDGE_HISTORY_UNAVAILABLE" for x in blocking):
        return "ABSTAIN_KNOWLEDGE_HISTORY_UNAVAILABLE"
    if blocking:
        return "ABSTAIN_BLOCKING_EVIDENCE_GAPS"
    return READY


def _required_human_actions(findings: list[Finding], authority: dict[str, Any]) -> list[dict[str, Any]]:
    actions, seen = [], set()
    for x in findings:
        if x.human_action and (x.code, x.human_action) not in seen:
            seen.add((x.code, x.human_action))
            actions.append({"action": x.human_action, "because": x.code, "severity": x.severity})
    two_signatures = " (two signatures)" if authority["dual_signature_required"] else ""
    actions.append(
        {
            "action": f"Sign or decline the disposition: {authority['who_signs']}" + two_signatures,
            "because": "DISPOSITION_IS_A_HUMAN_DECISION",
            "severity": "REQUIRED",
        }
    )
    return actions


def _reviewer_aid(stability: dict[str, Any]) -> dict[str, Any]:
    items = [
        {
            "statement": f"Against {chk['source']} limit {chk['limit'].get('text')!r}: {chk['status']}",
            "reported": chk["reported"],
            "firmware_band_c": chk["firmware_band_c"],
            "unverifiable_conditions": chk["unverifiable_conditions"],
        }
        for chk in stability["limit_checks"]
        if chk["status"] != "NOT_EVALUATED"
    ]
    return {"note": "Arithmetic and evidence pointers for the reviewer. Not a recommendation and not a disposition.", "items": items}


def _manifest(store: Store, view: TenantView, cited_evidence: Any) -> dict[str, Any]:
    cited_text = canonical_json(cited_evidence)
    cited = sorted(
        {
            f"{r.sheet}/{r.record_key}@v{getattr(r, 'version', 1)}:{r.row_hash[:16]}"
            for sheet in CITABLE_SHEETS
            for r in view.tenant_records(sheet)
            if r.source_ref in cited_text
        }
    )
    return {
        "kernel_version": __version__,
        "ruleset_version": RULESET_VERSION,
        "store_schema_version": STORE_SCHEMA_VERSION,
        "code_sha256": code_fingerprint(),
        "config": config_manifest(),
        "workbook_snapshots": [{k: s[k] for k in ("snapshot_id", "file_sha256", "extract_date")} for s in store.snapshots()],
        "cited_source_versions": cited,
        "model": {"route": "NONE", "reason": "deterministic kernel; no language model or embedding invoked"},
        "stubs": {
            "telemetry_archive": "NOT_AVAILABLE",
            "document_content_store": "NOT_AVAILABLE",
            "batch_exposure_history": "NOT_AVAILABLE",
            "regulator_gateway": "NOT_INVOKED",
        },
    }


def build_assessment(
    store: Store, principal: Principal, tenant: str, event_id: str, *, knowledge_cutoff: str = "alert", mode: str = "RECONSTRUCTED", clock: Clock = system_clock
) -> dict[str, Any]:
    """Build (but do not store) the evidence assessment of one alert as knowable at the knowledge cutoff."""
    probe = TenantView(store, principal, tenant, None, clock)  # access check before anything else
    alert_ts = parse_pack_utc(probe.event(event_id).get("alert_ts_utc"))
    cutoff = resolve_cutoff(knowledge_cutoff, alert_ts, clock)
    store_cutoff = _store_cutoff(store, cutoff, mode)
    view = TenantView(store, principal, tenant, store_cutoff, clock, knowledge_cutoff=iso(cutoff))
    alert = AlertInput.from_record(_alert_record(view, probe, event_id))
    exc_start = parse_pack_utc(alert["excursion_start_utc"])

    # Finding order is part of the output: knowledge, attribution, identity, spec, firmware, policy, stability, ...
    findings: list[Finding] = []
    knowledge = _collect(findings, _knowledge_basis(view, mode, cutoff, knowledge_cutoff, store_cutoff))
    attribution_ok = _collect(findings, _check_attribution(alert, tenant))
    entities = _collect(findings, _resolve_entities(view, alert, cutoff))
    spec = parse_spec_range(alert["spec_text_as_received"])
    findings += _spec_findings(alert, spec, entities["product"], alert_ts)
    aggregates = {k: alert[k] for k in EXCURSION_AGGREGATE_FIELDS}
    fw = firmware_uncertainty(alert["logger_fw"], alert["logger_vendor"], cutoff)
    direction = excursion_direction(aggregates, spec, fw)
    findings += _firmware_and_direction_findings(alert, fw, direction)
    sops = _collect(findings, _select_sops(view, entities, exc_start))
    stability = _collect(findings, assess_stability(view, entities["product"], aggregates, spec, fw))
    findings += telemetry_findings(aggregates, alert.source_ref)
    liability = _collect(findings, _liability(entities["carrier"], exc_start))
    history = _collect(findings, _lane_history(view, alert, alert_ts, cutoff))
    notification = _collect(findings, _notification_track(tenant, alert_ts))

    authority = _disposition_authority(view)
    blocking = [x for x in findings if x.severity == BLOCKING and x.dimension in DISPOSITION_DIMENSIONS]
    cited_evidence = [entities["product"].to_dict(), sops["sop_origin"], sops["sop_destination"], stability]
    payload: dict[str, Any] = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "event": {
            "event_id": event_id,
            "tenant_code": tenant,
            "source_ref": alert.source_ref,
            "allowed_input_fields": alert.fields,
            "allowed_fields_sha256": alert.fields_sha256,
            "excluded_outcome_fields": list(OUTCOME_FIELDS),
        },
        "time_semantics": {
            "valid_at": iso(exc_start),
            "alert_received_at": iso(alert_ts),
            "knowledge_cutoff": iso(cutoff),
            "knowledge": knowledge,
            "policy_date_convention": "date-only effective dates as half-open [from, to) local calendar dates at the governed site",
        },
        "disposition_evidence_status": _evidence_status(blocking, attribution_ok),
        "is_disposition": False,
        "blocking_reasons": sorted({x.code for x in blocking}),
        "entities": {role: resolution.to_dict() for role, resolution in entities.items()},
        "excursion": {
            "direction_vs_spec_as_received": direction,
            "spec_as_received": alert["spec_text_as_received"],
            "spec_range_c": list(spec) if spec else None,
            "aggregates_only": True,
            "firmware_bulletin": fw["bulletin_id"] if fw else None,
        },
        "evidence": {**sops, "stability": stability, "lane_history": history},
        "liability_track": liability,
        "notification_track": notification,
        "disposition_authority": authority,
        "findings": [x.to_dict() for x in findings],
        "missing_inputs": sorted({x.code for x in findings if x.code.endswith(MISSING_INPUT_SUFFIXES)}),
        "required_human_actions": _required_human_actions(findings, authority),
        "reviewer_aid": _reviewer_aid(stability),
        "manifest": _manifest(store, view, cited_evidence),
    }
    payload["assessment_id"] = "ASM-" + sha256_text(canonical_json(payload))[:24]
    payload["runtime"] = {"python": platform.python_version(), "openpyxl": metadata.version("openpyxl"), "requested_by": principal.actor_id}
    return payload


def _change_from_superseded(previous: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    old = {f["code"] for f in previous["findings"]}
    new = {f["code"] for f in payload["findings"]}
    old_status, new_status = previous["disposition_evidence_status"], payload["disposition_evidence_status"]
    return {
        "added_findings": sorted(new - old),
        "removed_findings": sorted(old - new),
        "status": [old_status, new_status],
        "knowledge_cutoff": [previous["time_semantics"]["knowledge_cutoff"], payload["time_semantics"]["knowledge_cutoff"]],
        "reopen_review_recommended": bool((new - old) & REOPEN_TRIGGER_FINDINGS) or (old_status == READY and new_status != READY),
    }


def assess_and_store(
    store: Store, principal: Principal, tenant: str, event_id: str, *, knowledge_cutoff: str = "alert", mode: str = "RECONSTRUCTED", clock: Clock = system_clock
) -> tuple[dict[str, Any], bool]:
    """Build, link to the previous assessment of the same event, and store (idempotent)."""
    payload = build_assessment(store, principal, tenant, event_id, knowledge_cutoff=knowledge_cutoff, mode=mode, clock=clock)
    prior = [a for a in store.assessments_for_event(tenant, event_id) if a["assessment_id"] != payload["assessment_id"]]
    if prior:
        previous = json.loads(prior[-1]["payload_json"])
        payload["supersedes"] = previous["assessment_id"]
        payload["change_from_superseded"] = _change_from_superseded(previous, payload)
    aid, inserted = store.put_assessment(payload, iso(clock()))
    store.audit(
        at=iso(clock()),
        actor=principal.actor_id,
        tenant=tenant,
        action="ASSESSMENT_BUILD",
        target=aid,
        outcome="STORED" if inserted else "IDEMPOTENT_EXISTING",
        detail={"event_id": event_id},
    )
    return payload, inserted
