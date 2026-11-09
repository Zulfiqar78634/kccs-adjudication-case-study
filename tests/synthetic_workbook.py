"""Builds a small, entirely SYNTHETIC workbook with the same 15-sheet layout as the supplied pack.

No row comes from the confidential workbook: products, sites, carriers, events and SOPs are invented.
Used to run the full command-line flow on machines (CI on Windows/macOS) that do not have the real file.
It deliberately includes an overlapping SOP revision, non-ASCII text ("°", "—", "≤") and a second tenant.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

EVENT_COLS = ["event_id", "alert_ts_utc", "tenant_code", "shipment_ref", "leg_no", "source_system", "logger_id", "logger_vendor",
              "logger_fw", "product_ref_as_received", "origin_ref_as_received", "dest_ref_as_received", "lane_text",
              "carrier_ref_as_received", "mode", "excursion_start_utc", "excursion_end_utc", "duration_min", "min_temp_c",
              "max_temp_c", "mean_temp_c", "spec_text_as_received", "readings_in_window", "gateway_gap_min", "interpolated",
              "dock_door_open_flag", "prior_excursions_lane_90d", "consignment_value_usd", "case_opened", "triage_outcome",
              "rules_engine_recommendation", "final_disposition", "reviewer_id", "review_minutes", "systems_opened",
              "reviewer_overrode", "days_to_disposition", "regulator_reportable", "reg_window_hours", "hours_to_notification",
              "reported_within_window", "reopened_later", "notes"]


def _event(eid, tenant, ship, ts, start, end):
    base = dict.fromkeys(EVENT_COLS)
    base.update(event_id=eid, alert_ts_utc=ts, tenant_code=tenant, shipment_ref=ship, leg_no=1, source_system="SYS-01",
                logger_id="LG-00001", logger_vendor="ThermaTrace", logger_fw="TT-2.15.0", product_ref_as_received="09999999000011",
                origin_ref_as_received="Synthetic Hub North", dest_ref_as_received="SYN-CS-02", lane_text="Synthetic Hub North to SYN-CS-02",
                carrier_ref_as_received="Synthetic Freight", mode="ROAD", excursion_start_utc=start, excursion_end_utc=end,
                duration_min=20, min_temp_c=5.0, max_temp_c=10.5, mean_temp_c=7.9, spec_text_as_received="2-8 °C",
                readings_in_window=5, gateway_gap_min=0, interpolated="N", dock_door_open_flag="N", prior_excursions_lane_90d=0,
                consignment_value_usd=10000, case_opened="Y", triage_outcome="ACTIONABLE — excursion confirmed",
                rules_engine_recommendation="RELEASE", final_disposition="RELEASE", reviewer_overrode="N",
                days_to_disposition=1.0, regulator_reportable="N", reopened_later="N")
    return [base[c] for c in EVENT_COLS]


SHEETS: dict[str, list[list]] = {
    "01_Excursion_Events": [EVENT_COLS,
                            _event("EXC-900001", "T-KAVERI", "SHP-KAV-900001", "2026-07-15 06:30", "2026-07-15 06:10", "2026-07-15 06:30"),
                            _event("EXC-900002", "T-PINNACLE", "SHP-PIN-900002", "2026-07-16 08:00", "2026-07-16 07:40", "2026-07-16 08:00")],
    "02_Product_Master": [["erp_source", "tenant_code", "brand_as_labelled", "generic_inn", "internal_sku", "gtin", "legacy_code",
                           "storage_spec_text", "mkt_tolerance_text", "permitted_excursion_text", "stability_study_ref",
                           "light_sensitive", "last_updated"],
                          ["Synthetic ERP", "T-KAVERI", "Synthexa 10mg pen", "synthexamab", "SKU-SYN-0001", "09999999000011", None,
                           "2-8 °C", "MKT ≤ 8 °C over 30 d", "≤ 6 h to 15 °C, once only", "STB-0001", "N", "2025-01-01"],
                          ["Synthetic ERP", "T-PINNACLE", "Synthexa 10mg pen", "synthexamab", "SKU-SYN-0001", "09999999000011", None,
                           "2-8 °C", "MKT ≤ 8 °C over 30 d", "≤ 6 h to 15 °C, once only", "STB-0002", "N", "2025-01-01"]],
    "03_Facility_Registry": [["source_system", "record_id", "name_in_source", "code_in_source", "country", "timezone_in_source",
                              "cold_rooms", "gmp_licence_ref", "bms_room_tags", "record_created", "active"],
                             ["SYS-04 Sentinel TMS", "SYN-0001", "Synthetic Hub North", "SYN-CS-01", "IN", "Asia/Kolkata", 2, "GMP-00001", None, "2020-01-01", "Y"],
                             ["SYS-07 Docuvault", "SYN-0002", "SYN-CS-01", "SYN-CS-01", "IN", "Asia/Kolkata", 2, "GMP-00001", None, "2020-01-01", "Y"],
                             ["SYS-04 Sentinel TMS", "SYN-0003", "Synthetic Store South", "SYN-CS-02", "IN", "Asia/Kolkata", 1, None, None, "2020-01-01", "Y"],
                             ["SYS-07 Docuvault", "SYN-0004", "SYN-CS-02", "SYN-CS-02", "IN", "Asia/Kolkata", 1, None, None, "2020-01-01", "Y"]],
    "04_Carrier_Contracts": [["contract_id", "counterparty_legal_entity", "names_seen_on_documents", "parent_of", "effective_from",
                              "effective_to", "governing_law", "cold_chain_clause", "liability_summary", "liability_cap",
                              "claim_window_days", "amendment_docs"],
                             ["CNT-SYN-01", "Synthetic Freight Ltd", "Synthetic Freight | SYNF", None, "2024-01-01", "evergreen",
                              "India", "Schedule 4", "Carrier liable — synthetic", "USD 1", 30, None]],
    "05_SOP_Index": [["doc_id", "tenant_code", "title", "revision", "effective_from", "effective_to", "supersedes_text",
                      "applies_to_facilities_text", "format", "pages", "language", "acceptance_limits_location"],
                     ["SOP-KAV-0001", "T-KAVERI", "Temperature Excursion Management", "Rev 01", "2026-01-01", "2026-08-31", None,
                      "All sites", "Native PDF", 10, "en", "Section 7.3 table"],
                     ["SOP-KAV-0001", "T-KAVERI", "Temperature Excursion Management", "Rev 02", "2026-06-01", None, "supersedes rev1",
                      "All sites", "Native PDF", 10, "en", "Section 7.3 table"],
                     ["SOP-PIN-0001", "T-PINNACLE", "Temperature Excursion Management", "Rev 01", "2026-01-01", None, None,
                      "All sites", "Native PDF", 10, "en", "Section 7.3 table"]],
    "06_Stability_Index": [["study_ref", "product_text_as_written", "tenant_code", "study_type", "temps_tested_text", "duration_tested",
                            "outcome_text", "permitted_excursion_text", "file_path_text", "pages", "indexed_by", "readable"],
                           ["STB-0001", "Synthexa 10mg — pen", "T-KAVERI", "Excursion / thermal cycling", "2-8 °C then 15 °C", "6 h",
                            "Single excursion of up to 6 h", "One excursion, up to 6 h below 15 °C", "/Stability/T-KAVERI/STB0001.pdf", 10, "synthetic", "Y"],
                           ["STB-0002", "Synthexa 10mg — pen", "T-PINNACLE", "Excursion / thermal cycling", "2-8 °C then 15 °C", "6 h",
                            "Single excursion of up to 6 h", "One excursion, up to 6 h below 15 °C", "/Stability/T-PINNACLE/STB0002.pdf", 10, "synthetic", "Y"]],
    "07_Alias_Observations": [["entity_kind", "string_a", "string_b", "same_real_world_thing", "times_seen_a", "times_seen_b",
                               "confirmed_by", "confirmed_on", "comment"],
                              ["FACILITY", "SYN-CS-01", "Synth Hub N", "Y", 1, 1, "QA-SYN-01", "2025-01-01", None]],
    "08_Reviewer_Queue_Log": [["log_id", "case_ref", "reviewer_id", "reviewer_region", "reviewer_utc_offset", "local_start", "local_end",
                               "active_minutes", "systems_opened", "systems_list", "action", "queue_wait_hours", "interrupted_count", "shift"],
                              ["QL-SYN-1", "EXC-900001", "QA-SYN-01", "APAC", "+05:30", "2026-07-16 12:00", "2026-07-16 12:30", 30, 3,
                               "Docuvault", "ACCEPTED_RECOMMENDATION", 1, 0, "Day"]],
    "09_Override_Reasons": [["case_ref", "reviewer_id", "engine_said", "reviewer_decided", "verbatim_reason"],
                            ["EXC-900001", "QA-SYN-01", "RELEASE", "RELEASE", "Synthetic row"]],
    "10_Reviewer_Questions": [["#", "question_as_asked", "where_the_answer_lives_today", "typical_minutes", "how_often_needed"],
                              [1, "Synthetic question?", "Nowhere", 1, "Every case"]],
    "11_Systems_Inventory": [["system_id", "system", "what_it_holds", "access_method", "freshness", "rate_limit",
                              "ordering_and_backfill", "measured_availability", "known_problems"],
                             ["SYS-01", "Synthetic telemetry", "Readings", "REST", "15 min", "n/a", "n/a", "99%", "none"]],
    "12_Tenant_Constraints": [["tenant_code", "tenant_name", "country", "region", "shipments_per_month", "data_residency_position",
                               "third_party_model_apis", "who_signs_a_disposition", "output_language", "sop_ownership", "other"],
                              ["T-KAVERI", "Synthetic Tenant K", "IN", "APAC", 1, "No clause", "Permitted", "Site QA", "English", "Tenant", None],
                              ["T-PINNACLE", "Synthetic Tenant P", "US", "AMER", 1, "No clause", "Permitted", "QA Director", "English", "Tenant", None]],
    "14_Incident_Log": [["ref", "date", "title", "severity", "what_happened", "consequence"],
                        ["INC-SYN", "2026-01-01", "Synthetic incident", "P3", "None", "None"]],
}
KEY_VALUE = {
    "00_README": [["Synthetic workbook — NOT the KCCS data pack", None], [None, None], ["Extract date", "2026-09-14"]],
    "13_Volume_And_Cost": [["Synthetic volume and cost", None], ["Consignments moved per month", "1"]],
}


def build(path: str | Path) -> Path:
    path = Path(path)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    order = ["00_README", "01_Excursion_Events", "02_Product_Master", "03_Facility_Registry", "04_Carrier_Contracts",
             "05_SOP_Index", "06_Stability_Index", "07_Alias_Observations", "08_Reviewer_Queue_Log", "09_Override_Reasons",
             "10_Reviewer_Questions", "11_Systems_Inventory", "12_Tenant_Constraints", "13_Volume_And_Cost", "14_Incident_Log"]
    for name in order:
        ws = wb.create_sheet(name)
        for row in (KEY_VALUE.get(name) or SHEETS[name]):
            ws.append(row)
    wb.save(path)
    return path
