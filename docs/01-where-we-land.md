# Where We Land

## Position and scope
Build an evidence-first adjudication control plane, not an autonomous disposition engine. The production design below is a proposal; the local prototype is not a qualified production system.

## Requirements and traceability
| Requirement / attribute | Source | Design consequence |
|---|---|---|
| Human accountability | Brief sections 2, 4, 6 | Named authorised human signs product disposition; qualified non-actionable alert closure is a separate operation. |
| Time-correct notification | Brief sections 2, 4; pack 00_README, 01 | Retain alert timestamp; keep notification and disposition clocks separate; resolve market policy and business calendar explicitly. |
| Evidence reconstruction within one hour for seven years | Brief sections 3, 6, AUD-2603 | Preserve source snapshots, temperature data, SOP and stability versions, approver and decision provenance; test retrieval and retention. |
| Conservative identity resolution | Brief sections 2, 7; pack 00_README, 02, 03, 07 | Preserve raw identifiers; scope product resolution to tenant and presentation; treat aliases as observations, not authoritative mappings. |
| Temporal SOP applicability | Brief section 2; pack 05 | Resolve document, tenant, facility and effective date; expose overlaps and handwritten annexure uncertainty rather than guessing. |
| Re-adjudication | Brief section 3; pack 14, TT-CB-114 | Preserve original attempt and inputs; append corrected evidence, new attempt and downstream action records. |
| Tenant and regional isolation | Brief sections 3, 4; pack 12 | Enforce authorisation before retrieval; isolate indexes, caches and derived artefacts; keep EU-only data and processing in EU. |
| Resilience to alert storms | Brief section 3, INC-2502 | Independent deadline scheduler, tenant fairness, backpressure and escalation; dependency waits do not pause notification deadlines. |
| Qualified changes | Brief section 6; pack 14 | Historical-case comparisons before go-live and material changes, tenant-scoped canaries, rollback and versioned inputs/models/prompts/rules. |
| Cost control | Brief sections 4, 6; pack 13 | Price idle and peak operation separately; approve a worked model bill against USD 3,000/month before live model use. No priced model estimate is claimed here. |

## Deliberately not building
- Autonomous product disposition: incompatible with named-human accountability.
- Full enterprise MDM or replacement ERP/LIMS/Docuvault: preserve source ownership and add provenance-aware adapters instead.
- Generic document chatbot: it does not establish shipment-linked evidence.
- Automatic regulatory filing in the prototype: production needs an owned manual filing path and acknowledgement evidence.
- Full production UI, identity platform and durable archive in the local prototype: these remain production work.

## First customer and rollout
Select Kaveri Health Distribution (T-KAVERI) as the proposed first customer. Pack 12 records 4,300 shipments/month, Site QA signing, English output, no residency clause and permitted third-party APIs. This is a lower initial contractual integration burden than Virent's external-API prohibition and dual signatures or Aurastat's EU-only processing. This is a design choice, not an agreed customer commitment.

Kaveri is not clean data: two of six site annexures are paper scans with handwritten limit changes (pack 12). Initially enable assisted production only for sites/documents whose authority and effective limits QA has verified. Route unresolved annexures to manual review; never infer acceptance limits. Include those difficult cases in shadow evaluation.

| Time from design sign-off | Delivery and gate |
|---|---|
| Days 1-30 | Confirm pilot sponsor, signer authority and document ownership; implement scoped ingestion, deadline tracking and evidence snapshots; establish retrospective labelled cases. |
| Days 31-60 | Shadow operation; compare historical decisions and explain disagreements; test tenant boundaries, clock recovery, burst isolation and audit retrieval. No autonomous product decisions. |
| Days 61-90 | Limited assisted production for verified pilot scope, subject to QA acceptance, zero unexplained safety-critical evaluation failures and tested manual fallback. This is the first-customer-live milestone. |
| Months 4-6 | Expand verified pilot sites and small tenant cohorts after contractual, regional and qualification gates. |
| Months 7-9 | Target all 34 tenants only where readiness gates pass; report blockers instead of bypassing qualification. |

Six engineers should focus on ingestion/evidence, workflow/clock and reviewer/release workstreams. Access, authoritative documents and QA availability are prerequisites; the timeline is a gated proposal, not a delivery guarantee.

## Ambiguities and positions
- Brief EXC-107133 describes alerting at 06:14; pack 01 records alert 06:31 and excursion start 06:14. Use the workbook alert for replay and flag the narrative discrepancy.
- Missing or unreadable stability evidence means unknown evidence, not an unsafe product finding; an absent index row does not prove no study exists (00_README).
- Overlapping SOP revisions or annotations require document-owner resolution; preserve candidates and provenance.
- Missing notification evidence is not automatically a proven breach; distinguish not reportable, unknown, pending, timely and late.
- Next-business-day rules require verified jurisdiction, timezone, holiday calendar and cutoff; do not substitute 24 hours.
- The 420-event extract is stratified (00_README), not a population benchmark. Use pack 13 for population rates; historical outcomes are comparators, not unquestionable ground truth.

## Actual board commitments and qualifications
1. Under-24-hour median disposition: accept as an objective, but separate preparation time from laboratory/carrier/customer waits and report tail latency and case mix. Do not optimise the median by prematurely closing hard cases.
2. At least 70% automated alert closure: qualify against audited non-actionable cases and false-closure risk. The brief's 82% non-actionable population and 78% closure coverage explain approximately 64% overall today. Never count automated product disposition as alert closure.
3. One-hour reconstruction for seven years: accept; requires retained snapshots, access controls and restore/retrieval drills, not just a CSV export.
4. Cost ceiling: accept subject to a worked tab-13 bill including idle costs; no unsubstantiated cost-compliance claim.
5. No late notifications: accept as an operational objective with owned escalation and filing fallback, not a software-only guarantee when external filing or acknowledgement fails.
6. First live within 90 days/all tenants within nine months: use the gated plan above; quality and contractual readiness outrank calendar-driven expansion, consistent with the board's one-customer-first condition.

The board does not demand autonomous regulated dispositions, a full MDM rebuild or data cleanup before delivery. Earlier wording attributing those requests to the board was incorrect.
