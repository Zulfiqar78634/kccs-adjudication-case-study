# 05 — Validation and operations

## 1. How we know it works today

Executed (the full output is regenerated into `evidence/logs/02_pytest.log` by `python scripts/e2e_check.py`):

```
python -m pytest -v      → 78 passed (Python 3.12.3, openpyxl 3.1.5, pytest 8.3.5)
kccs-evidence demo …     → 420 events × 2 knowledge views = 840 assessments (+1 after the simulated correction);
                           6 evidence packages (selected real cases) exported and re-verified OK; cross-tenant read denied and audited
```

### Test → requirement map

| Required validation | Test (file::name) | Data |
|---|---|---|
| Same identifier under multiple tenants | `test_tenant_isolation::test_same_gtin_under_multiple_tenants_resolves_within_tenant` | real: GTIN 08901234500035 |
| Unauthorised cross-tenant access | `::test_cross_tenant_view_is_denied_and_audited`, `::test_cross_tenant_assessment_denied`, `::test_package_export_denied_for_other_tenant`, `::test_event_of_other_tenant_is_not_found_rather_than_revealed` | real |
| Misleading stability file path | `::test_stability_ownership_from_tenant_code_not_path` | real: STB-4764, STB-6586 |
| Wrong product presentation | `test_stability_and_signals::test_exc_110497_pfs_product_vial_study_rejected`, `::test_exc_107133_…` | real |
| Missing / unreadable stability evidence | `::test_missing_and_unindexed_study_refs_are_explicit`, `::test_unreadable_study_with_index_limit_text_is_not_relied_on` | real: `02!R55`, STB-5652 |
| Overlapping SOP revisions | `test_temporal::test_real_overlap_exc_107133`, `::test_overlap_is_a_conflict_not_resolved_by_revision_number` | real + synthetic |
| Policy interval boundaries | `::test_half_open_boundary_in_site_local_date` (4 cases) | synthetic |
| Ambiguous site scope / timezone | `::test_site_scope_unknown_when_site_unresolved`, `::test_untrusted_timezone_near_boundary_is_ambiguous_not_guessed` | synthetic |
| Missing product reference | `test_assessment::test_missing_product_reference_abstains` | real |
| Untrusted alias mapping | `::test_untrusted_alias_then_human_approved_mapping`, `test_tenant_isolation::test_product_aliases_are_quarantined_for_every_tenant` | real: F00231 |
| Historical replay without future knowledge | `test_temporal::test_replay_excludes_bulletin_learned_after_alert`, `::test_alias_confirmed_after_alert_is_not_used_in_replay`, `::test_strict_mode_abstains…` | real |
| Repeated execution / idempotency | `test_assessment::test_repeated_execution_is_idempotent`, `test_ingestion_and_store::test_reingest_is_idempotent` | real |
| Source correction, immutable old assessment | `test_assessment::test_correction_produces_new_assessment_and_old_is_immutable`, `test_ingestion_and_store::test_append_only_tables_reject_update_and_delete` | real + labelled simulated correction |
| Affected firmware, uncertain correction | `test_stability_and_signals::test_firmware_up_to_1_8_is_an_interval_not_a_fixed_offset`, `::test_exc_110448_cold_excursion_with_affected_firmware`, `test_assessment::test_bulletin_reassessment_recommends_reopen…` | real + synthetic values |
| Conflicting inputs fail safely | `test_assessment::test_conflicting_tenant_attribution_is_quarantined`, `::test_product_ambiguity_synthetic` | simulated / synthetic |
| Historical outcome ≠ prototype input | `test_assessment::test_outcome_fields_are_not_inputs`, `::test_evidence_logic_modules_never_mention_outcome_fields` | real |
| Missing evidence never favourable; never a disposition | `test_assessment::test_never_a_disposition_across_all_events` (all 420) | real |
| Clock starts at alert receipt | `test_obligations::test_clock_starts_at_alert_receipt…` | real: EXC-110553 |
| Waits do not pause the clock | `::test_evidence_waits_do_not_move_the_deadline` | synthetic times |
| Next business day needs tz + calendar | `::test_next_business_day_requires_explicit_timezone_and_calendar`, `::test_pinnacle_meridian_deadline_not_guessed_as_24h` | synthetic calendar + real |
| Failed delivery ≠ success | `::test_failed_or_queued_delivery_is_not_success` | synthetic |
| Storm cannot discard obligations | `::test_storm_keeps_every_obligation_real_inc_2502_rows` (58 real), `::test_storm_of_1912_synthetic_alerts…` | real + synthetic |
| Concurrent reviewer actions | `::test_concurrent_transition_rejected_by_version` (obligations) | synthetic; case leases are design-only |
| Package integrity | `test_package::*` (3) | real |

**Design-level acceptance tests (not implemented; listed so nobody assumes they are):**
- case-workflow leases and dual signature;
- outbox delivery under crash;
- durable-timer recovery after failover;
- per-tenant index isolation for embeddings;
- pt-BR template approval;
- RPO/RTO drills;
- duplicate physical-excursion detection (Q6);
- product-in-room verification (Q7).

### Workbook-wide results (`artifacts/evaluation/summary.md`)

> These are **not** population accuracy, automation or closure estimates. The pack is stratified, the kernel never outputs a disposition, and prior outcomes are not ground truth.

- **Status:** all 420 alerts abstain in both views. Two gaps are **pack-wide**: no temperature series, and no SOP content. Setting those aside, **8 events** (T-CAMPOS: EXC-110091, EXC-110182, EXC-110595, EXC-112450; T-PINNACLE: EXC-110406, EXC-110511, EXC-112219, EXC-112317) have no case-specific blocker. They would reach READY_FOR_QA_REVIEW once the series and SOP limit are captured. The other 412 each have at least one case-specific blocker.
- **Most frequent case-specific blockers (at alert):**

  | Blocker | Events |
  |---|---|
  | NO_SOP_INDEXED (all T-VIRENT) | 164 |
  | STABILITY_REFERENCED_STUDY_INADMISSIBLE | 153 |
  | STABILITY_NO_ADMISSIBLE_STUDY | 130 |
  | STABILITY_NOT_SELECTABLE (product unresolved/missing) | 123 |
  | STABILITY_MASTER_VS_STUDY_CONFLICT | 116 |
  | ORIGIN_FACILITY_UNRESOLVED (at-alert; 0 at extract, because reviewer aliases confirmed later become visible) | 82 |
  | PRODUCT_UNRESOLVED | 81 |
  | GATEWAY_GAP_SPANS_EXCURSION | 62 |
  | SOP_REVISION_OVERLAP | 13 |

- **Firmware TT-2.14.3:** 91 events. 19 are flagged in the at-alert view (alerts after 2026-04-11) and all 91 in the at-extract view; 61 were historically reopened. The difference is the knowledge-time control working.
- **Written overrides (24):** the kernel surfaces the reviewer's concern in 13 and only generically in 1 (EXC-110602, handwritten annexure: it says "content unavailable" but cannot see the note). It does not surface 1: EXC-110476 abstains on product identity instead of explaining the cross-tenant duplicate SKU. 6 are out of scope (setpoint CSV, packaging, duplicates, dry-ice log, expiry shortening, missing leg). 1 is prevented by construction (EXC-110511 cross-tenant precedent). 2 are handled by other tracks (pt-BR authority field; separate notification clock).
- **Engine AUTO_CLOSE rows (275 in the pack):** 273 have case-specific evidence gaps. These are **review candidates** for a closure audit, not proof of wrong closures.
- **Notification check:** the kernel's clock agrees with the pack's late/on-time flag for all 19 computable reportable rows, and refuses the 9 "next business day" rows.

## 2. How we would know it stopped working at 3 a.m., six months from now [DESIGN]

**Structured log fields (every line):** `ts`, `cell`, `tenant_code`, `event_id`, `case_id`, `assessment_id`, `obligation_id`, `actor`, `action`, `outcome`, `code_sha`, `ruleset_version`, `config_sha`, `model_route`, `knowledge_cutoff`, `latency_ms`, `error_code`. Never evidence payloads.

| Signal | Metric | Proposed alert threshold (unmeasured) | Owner |
|---|---|---|---|
| Deadline risk | open obligations with `due_at − now < 6 h`; policy-incomplete obligations | any → page RA on-call; T−1 h → RA manager | Regulatory Affairs + SRE |
| Obligation completeness | alerts ingested − obligations created (per tenant, per hour) | ≠ 0 for 5 min → page | SRE |
| Tenant-leak control | cross-tenant denial count; **canary records** (synthetic "Meridian-canary" strings planted in each tenant) found in any other tenant's output, log, index or cache | any canary hit → P1, auto-disable model route + precedent search for both tenants | Security + platform lead |
| Abstention / conflict spike | per tenant, rate of each blocking code vs trailing 28-day baseline | > 3σ or 2× → ticket; > 5× → page | QA data steward |
| Source freshness | age of last record per source per tenant (SYS-05 nightly, SYS-01 15 min) | > 2× expected interval | Integrations |
| Replay drift | nightly re-run of a frozen 200-case set per tenant with pinned versions; assessment IDs must match bit-for-bit | any mismatch → page; block deploys | Platform |
| Package integrity | nightly random-sample `verify_package` + WORM object checksum | any failure → P1 | SRE |
| Dependencies | Docuvault 60 req/min and SYS-01 300 req/min throttling; model provider error rate; deprecation-notice feed | throttle > 10% for 15 min; any deprecation notice → ticket for re-qualification | Integrations |
| Queue health | per-tenant queue depth and oldest item age; storm detector firing | oldest > 2 h for a tenant with 72 h regimes | Ops lead |

**Runbook: "abstention spike for T-KAVERI, STABILITY_REFERENCED_STUDY_INADMISSIBLE ×6"**
1. Check the deploy log and the `config_sha` in the spiking assessments. If it changed in the last 24 h, compare replay diffs; roll back the config pointer if unexplained.
2. Check source freshness for SYS-05 (ERP nightly). A product-master batch may have re-pointed study references. Diff `source_record_version` for `02` in the window.
3. If the source changed legitimately, open data-quality tickets to the tenant QA; the kernel is behaving correctly by abstaining.
4. Never "fix" by relaxing rules at night. Escalate to the QA data steward in the morning unless obligations are at risk.

**Runbook: "obligation completeness ≠ 0"**
1. Stop deploys.
2. Run reconciliation (`alerts` minus `obligations`) for the window.
3. Create the missing obligations with `clock_start = alert_received_at` (never "now").
4. Page RA for any obligation that is already within T−24 h.
5. Post-incident: find the transaction or outbox fault.

**Escalation:** on-call SRE → platform lead → Head of Platform. Regulatory exposure → RA manager. Leak → Security + Commercial Counsel (Cl.22 notice obligations).

**Rollback:** version pointers for code, config and model route are per tenant. Existing assessments stay valid historical records under their manifests.
