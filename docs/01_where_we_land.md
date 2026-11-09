# 01 — Where we land

*Candidate: Zulfiqar. Drafted with heavy AI assistance (see `06_working_log.md`); every number below was produced by the code in this repository from the supplied workbook unless marked as an assumption.*

References: **B§n p.m** = brief section/page; **`NN!Rk`** = workbook tab and Excel row; event IDs are as in `01_Excursion_Events`.

## 1. The real problem

Kestrel's adjudication problem is **not** predicting a disposition. The brief says so (B§2 p.3: "The decisions are mostly not hard. Assembling enough evidence to be allowed to make them is the whole cost"), and the pack confirms it independently:

- Of the 24 written override reasons (`09`), most concern **evidence**: a withdrawn or overlapping SOP revision (EXC-110490), a study for the wrong presentation (EXC-110497), the wrong carrier legal entity (EXC-110581), interpolated readings across a gateway gap (EXC-110504), a precedent from another tenant (EXC-110511), "Refer QA" read as an allowance (EXC-110574). Only a few concern judgement (EXC-110560 expiry shortening; EXC-110455 distrust of a reefer unit).
- All six incidents (`14`) are failures of evidence, version or isolation control: an unversioned prompt (INC-2411), a queue without deadline awareness (INC-2502), a basis that could not be reproduced (AUD-2603), a late-known calibration fact (INC-2506), an unqualified model (INC-2509), and a cross-tenant index (INC-2512).
- Nine of the twelve reviewer questions (`10`) are lookups across systems. Q12, "can I reconstruct all of this in two years", is answered "No".

The hypothesis holds, with one refinement the pack forces. "Evidence" has to be **temporally qualified**: what was in force on the excursion date, and what we knew at a given moment, are two different questions. Both are needed for an inspection (AUD-2603) and for retrospective correction (INC-2506).

**Statement:** build a system that, for every alert, assembles a **tenant-scoped, temporally explicit, reproducible evidence basis**. It refuses to conclude where the evidence does not support a conclusion, it keeps the **regulatory notification clock independent** of the disposition, and it preserves every signed basis immutably for seven years. Humans sign every product disposition. Software may close only alerts that are demonstrably non-actionable.

Four concepts are kept separate throughout: **(a)** non-actionable alert closure (no product decision); **(b)** product disposition (a regulated human decision); **(c)** regulatory notification (its own clock, from alert receipt); **(d)** carrier liability and claims (who pays, never what happens to product).

## 2. Requirements traceability

| ID | Requirement / attribute | Source | Implication | Acceptance criterion | Phase |
|---|---|---|---|---|---|
| R1 | Tenant-scoped resolution of product/site/carrier identities; never guess | B§7 p.6–7; `02` (GTIN 08901234500035 in 4 tenants); `07` untenanted | Identity = (tenant, identifier). Ambiguity is an output | `test_same_gtin_under_multiple_tenants…`; no fuzzy match in code | 1 |
| R2 | Reviewer mappings are hints until a human approves them | `00!R18`; `07` comments ("Disputed by TMS owner") | Versioned `mapping_assertion` with actor and recorded_at | `test_untrusted_alias_then_human_approved_mapping` | 1 |
| R3 | SOP revision in force at the site on the excursion date; overlaps are conflicts | B§2 p.2; `00!R39`; 27 overlapping pairs in 10 docs | Half-open local-date intervals; no "highest revision wins" | `test_overlap_is_a_conflict…`, `test_real_overlap_exc_107133` | 1 |
| R4 | Stability evidence: owner, presentation, readability, relevance, absence ≠ nonexistence | B§2 p.2; `00!R35,R37,R38,R42,R44`; EXC-110497 | Admissibility checks with stated reasons | `test_exc_107133…`, `test_exc_110497…`, `test_unreadable…` | 1 |
| R5 | Later-known facts must not leak into "what we knew then" | INC-2506; `00!R34` | Bitemporal store; knowledge cutoff on every query | `test_replay_excludes_bulletin…`, `test_alias_confirmed_after_alert…` | 1 |
| R6 | Full basis retrievable in < 1 h for 7 years | Board #3; AUD-2603 | Immutable, hashed evidence package per assessment and signature | `test_export_and_verify`, `test_tampering_detected`; retrieval SLO in ops | 1 |
| R7 | Notification clock from alert receipt, independent of disposition | B§2 p.2; `00!R43,R46`; `13!R22`; INC-2502 | Separate obligation state machine; waits never pause it | `test_obligations.py` (9 tests) | 1 |
| R8 | Storms must not starve other tenants' obligations | INC-2502 (4 breaches) | One obligation per alert; earliest-deadline-first | `test_storm_*` | 1 |
| R9 | Version traceability of every behaviour-affecting artefact; notify on change | B§4 p.4 (de Vries); INC-2411, INC-2509 | Execution manifest in every assessment; replay gate before change | manifest fields; `05` pipeline gates | 1 |
| R10 | No cross-tenant derived artefacts (Meridian Cl.22) | `12!R6`; INC-2512 | Per-tenant indexes, caches, eval sets; untenanted product aliases quarantined | `test_tenant_isolation.py` (12 tests) | 1 |
| R11 | Residency (EU-only, India-only), model API prohibitions | `12!R2,R3,R4`; 14 of 26 others residency, 6 API-prohibited (`12!R10`) | Regional cells; "no-LLM" is a supported route | Deployment design; route policy per tenant | 1–3 |
| R12 | Tenant signing rules (dual, Part 11, named individual, Responsável Técnico) | `12` who_signs_a_disposition | Signature policy per tenant | `disposition_authority` in every assessment; LLD signature guards | 1–2 |
| R13 | Portuguese regulator-facing output (T-CAMPOS) | `12!R8`; EXC-110595 | Human-approved pt-BR templates | Design only | 2 |
| R14 | Retrospective evaluation before go-live and every change | B§6 p.6 (Dr Rao) | Replay harness and per-tenant regression report | `evaluation.py` + `artifacts/evaluation/summary.md` | 1 |
| R15 | Quiet-day cost floor near zero; stay within ceiling | B§4 p.4 (Okoro); `13!R25–27` | Pay-per-use or no-model routes; no always-on GPU | `02` §cost | 1 |
| R16 | Missing evidence is never favourable | Dr Rao, B§4 p.4 | Abstention with reasons; status never READY with blockers | `test_never_a_disposition_across_all_events` | 1 |

## 3. Explicit non-goals

- **Automated product disposition.** Dr Rao's condition (B§6 p.6) and the January pilot (B§5 p.5). The kernel outputs a reviewer aid or an abstention; `is_disposition` is always false.
- **Replacing the 2,400-rule engine in phase 1.** It closes ~64% of alerts today (`13`). We wrap closure with an evidence check and an audit sample, and retire forks later.
- **Fine-tuning or shared embeddings across tenants.** This is forbidden by Cl.22 in practice, and not needed.
- **A master-data-management programme.** We build human-approved mappings incrementally, driven by cases.
- **Microservices, a graph DB, vector search or agents.** A modular monolith with workers and Postgres covers the access patterns.
- **Digitising the 11,040-PDF stability repository up front.** We index on demand per onboarded tenant.
- **Automated translation of regulator-facing text.** Templates are human-approved.

## 4. Key decisions and rejected alternatives

| Decision | Rejected alternative | Why |
|---|---|---|
| Prototype the evidence-resolution and replay kernel | A better recommendation prompt; a dashboard | By my reading ~20 of the 24 override reasons, and all 6 incidents, are evidence/version/isolation failures |
| Abstain on conflict (overlap, presentation, master vs study) | Pick latest or highest revision; rank candidates | `supersedes_text` is free text (`11!R8`); SOP-MER-5228 Rev 05 precedes Rev 04 |
| Half-open `[from, to)` site-local dates | Closed intervals, or UTC dates | 115 hand-overs have `to == next from`; closed intervals would make each one a one-day overlap |
| Quarantine untenanted product aliases | Use `07` as a lookup table | No tenant provenance, so we cannot prove an alias is not Meridian-derived (Cl.22) |
| Separate notification obligation ledger | Notification as a case state | EXC-110553: a reviewer released early to meet a 72 h window that a 9-day lab test would miss |
| "No LLM" as a first-class route | Self-hosting for prohibited tenants | One always-on g5.12xlarge is $4,139/month, above the whole $3,000 budget (see `02` §9) |

## 5. Contradictions and assumptions register (top items; full list in `04`)

| Evidence | Conflict or gap | Position taken | Risk | Who resolves |
|---|---|---|---|---|
| B§2 p.2 "At 06:14 UTC… reported 11.2 °C" vs `01!R221` alert 06:31 | 06:14 is `excursion_start_utc` | The clock runs from the alert (06:31) per `00!R43` | 17 min of deadline | Regulatory Affairs |
| B§2 p.2 pickup 09:30 UTC vs `08` QL-02111 local_start 12:24 +05:30 = 06:54 UTC | Narrative and log disagree | Trust the log for metrics; the brief is illustrative | Low | Sudhanshu (factual Q) |
| `02!R57` Kaveri pen: "Cumulative 72 h above 8 °C", ref STB-3584 | STB-3584 is a **vial, accelerated, partially readable** study (`06!R108`); pen study STB-2738 says "one excursion ≤ 6 h below 15 °C" (matches brief) | BLOCKING conflict; STB-2738 offered only as a candidate | Wrong allowance on insulin | Kaveri QA |
| 8 product-master refs point at another presentation | e.g. R16→STB-4417, R57→STB-3584 | Reject; list as human action | Wrong tolerance | Tenant QA |
| T-VIRENT (164 of 420 events) has no "Temperature Excursion Management" SOP in `05` | Governing procedure unknown | NO_SOP_INDEXED (blocking); other titles listed but not assumed | Largest tenant blocked | Virent document control |
| `00!R42` "readable=N rows carry no outcome" | STB-5652, STB-7265, STB-8989, STB-8772 carry permitted-excursion text | Never relied on | Invented allowance | QA |
| `00!R41` queue-log reconciliation | Holds for 198/200; EXC-111001 off 174.6 min, EXC-111785 off 133.2 min | Report; do not use those timings | Metric error | Data Services |
| `13!R22` "next business day (1 US state)" vs `01` reg_window_hours = 24 | 24 h ≠ next business day; state, timezone and calendar unknown | Deadline **not computed**; escalate (POLICY_INCOMPLETE) | Late filing | Regulatory Affairs |
| `03` timezone wrong for two sites (`00!R31`) | Only MEM-CS-02 (Chicago, not New York) is certainly wrong | Flag MEM confirmed, IND suspect; evaluate all plausible dates near boundaries | Wrong revision | Data Services |
| EXC-110448 reasoning "real max probably inside spec" | Under-reporting means the true temperature is **higher**. This was a cold excursion (min 0 °C); even +1.8 °C leaves 1.8 < 2 °C | Firmware treated as an interval [0, +1.8]; still a cold excursion | Prior outcomes not ground truth | QA (review candidate) |
| `13!R25–26` ceilings | $0.06 × 11,400 + $1.10 × 2,050 = $684 + $2,255 = **$2,939** ≈ the $3,000 CFO figure | Treat as additive sub-budgets | If overlapping, budget is $2,255 | CFO |

## 6. Phased rollout

**First customer: T-KAVERI (Kaveri Health Distribution).**
- Its constraints are favourable: no residency clause, model APIs permitted (none needed), single signer "Site QA", English output (`12!R9`).
- The clock is lower-risk to pilot: India 15-day window for notifiable products, with 0 late in the pack.
- It has moderate volume (4,300 shipments/month) and is the brief's own exemplar (EXC-107133).
- Its real problems are a fair test: 3 of its SOP documents have overlapping revisions (SOP-KAV-2571, -5329, -9392), and 2 of 6 site annexures are handwritten scans. These are exactly what the kernel must handle by abstaining and routing to a human. For those 2 sites the pilot runs with a manual-transcription step whose transcription is signed and versioned.

Why not the tempting alternatives:
- **T-AURA** has a conditional renewal and needs exactly our traceability, but it requires the EU cell, a named-signer e-signature, and has 5 late notifications in the pack. A wobble there costs the renewal. It goes second, once the replay gate has run for a quarter.
- **T-VIRENT** is the largest, but it is India-only with API prohibition, needs dual signature, has untagged BMS feeds, and has **no excursion SOP indexed**.
- **T-PINNACLE / T-MERIDIAN** are a competitor pair (Cl.22) with an unresolved next-business-day calendar.
- **T-SAHYADRI** is the runner-up (KCCS owns its SOPs) but needs Hindi/Marathi site output on shared terminals.

| Phase | When (from design sign-off) | Scope | Exit gate |
|---|---|---|---|
| 0 Foundations | weeks 0–6 | Kernel in production form; source snapshotting (telemetry series at ingest, since SYS-01 keeps raw only 30 days); India cell; obligation ledger; Kaveri SOP/stability curation and mapping approvals | G0: isolation suite + leak canaries green; replay of Kaveri history reproducible bit-for-bit |
| 1 Kaveri shadow | weeks 6–10 | Assess every Kaveri alert; reviewers work as today; obligations created in parallel | G1: Dr Rao signs the replay report (disagreements explained); 100% obligation creation; packages retrieved < 1 h |
| 1 Kaveri live | by day 90 | Reviewer aid + evidence package + notification ledger live; rules engine still closes | Rollback: any cross-tenant artefact, any missed obligation, or unexplained replay drift → disable kernel output (feature flag) and revert to current process |
| 2 | months 4–6 | EU cell: T-AURA, T-NORDIA; T-CAMPOS (pt-BR templates); T-SAHYADRI | Per-tenant replay report + QA sign-off each |
| 3 | months 6–9 | T-VIRENT (no-LLM route, dual signature); T-PINNACLE/T-MERIDIAN (separate indexes, calendar policy); remaining 26 in waves by constraint class | Same gates; waves pause on any G-criterion breach |

**Unknowns for "all 34 in nine months":** SOP index quality for the 26 unlisted tenants; how many have no excursion SOP indexed (as Virent); US state calendar; stability coverage (~60%); the six API-prohibited tenants' regions. All 34 can be *onboarded to evidence assembly and the obligation ledger* in nine months with a six-person team, if per-tenant curation averages two weeks of one data engineer plus QA time. **Live with READY_FOR_QA_REVIEW rates that are useful** for all 34 depends on curation we cannot size from the pack.

## 7. The board's targets

1. **Median < 24 h to signed disposition.** Disposition latency is not notification latency. Medians hide the tail: a lab result takes 9 days (EXC-110553), so a target met on the median can coexist with month-old quarantines. Report **p50, p90 and max age per wait state** (carrier data, lab, document control). Exclude externally-blocked time from *our* latency but never from the obligation clock.
2. **≥ 70% closed without a person.** The denominator must be **all alerts**. Today 64% = 78% × 82%. Reaching 70% means closing ~85% of non-actionables. Allowed only for closures with **no product decision** (verified duplicate, verified no-product-in-room, sensor artefact with corroboration), with an audited false-closure rate. The auto-closed population has never been audited (`00!R36`). In this pack, 273 of 275 engine AUTO_CLOSE rows had case-specific evidence gaps in the kernel (stratified sample: a reason to audit, not an estimate). **We challenge the target as an incentive:** pressure to close more invites disguising product release as "closure". Counter-proposal: 70% *safe* closure, measured by a monthly blind audit sample of closures.
3. **Basis within the hour, seven years.** We accept this; it is the prototype's core.
4. **Cost ceiling.** We accept it with headroom. The design spends ~$575/month of $2,939 (`02` §9).
5. **No late notifications.** Software cannot guarantee this alone: notifiability is a human determination, and transport and acknowledgement depend on regulators. We commit to **100% obligation creation at alert receipt**, earliest-deadline-first queues isolated from storms, escalation at proposed T-24 h / T-6 h / T-1 h, and acknowledgement-based completion, and we report breaches transparently.
6. **First customer in 90 days; all 34 in nine months.** The first is feasible (above). For all 34 we commit to onboarding, not to equal maturity.
