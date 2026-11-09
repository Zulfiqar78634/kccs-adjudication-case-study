# Final report: KCCS Sentinel adjudication case study

**Candidate:** Zulfiqar · **Prepared:** 8 November 2026 · **For:** Kestrel Cold Chain Solutions, Platform Engineering (brief circulated 18 Sep 2026)
**Status:** a working prototype with a written design. It is not production software, and it makes no compliance claims.

---

## 1. Where I landed

The brief's own conclusion holds once tested against the pack. Kestrel does not need a better disposition predictor. It needs to **assemble an admissible, tenant-safe, temporally correct evidence basis** for a human decision, and to preserve that basis so it can be reproduced years later.

- **Overrides:** by my reading, about 20 of the 24 written override reasons are evidence failures, for example:
  - a withdrawn or overlapping SOP revision (EXC-110490);
  - a study for the wrong presentation (EXC-110497);
  - the wrong carrier legal entity (EXC-110581);
  - a cross-tenant precedent (EXC-110511).
- **Incidents:** all six are failures of evidence, version or isolation control.

I keep four things separate everywhere:
1. **Non-actionable alert closure.** No product decision is involved.
2. **Product disposition.** A regulated human decision, always signed by a person.
3. **Regulatory notification.** Its own clock, running from alert receipt; waits never pause it.
4. **Carrier liability.** It decides who pays, never what happens to the product.

**What I built (the part that would keep me up at night):** a tenant-scoped, temporally correct **evidence-resolution and replay kernel**, run against the real workbook. For any alert, at any knowledge cutoff, it produces a content-addressed assessment with:
- resolved and unresolved entities;
- selected and rejected evidence, with reasons;
- conflicts, missing inputs and required human actions;
- the notification deadline;
- an execution manifest.

It abstains rather than guesses. Corrections produce new assessments; nothing is ever edited.

**First customer:** **T-KAVERI**.
- It has no residency clause, permits model APIs (none are needed), needs a single signer and English output, and has the lowest-risk notification regime.
- It is the brief's own exemplar.
- Its overlapping SOP revisions and two handwritten annexures exercise the abstain-and-route path honestly.

Go-live is a reviewer aid plus evidence packages plus the notification ledger, within 90 days. Other tenants follow by constraint class over nine months (`docs/01` §6).

**Board targets challenged:**
- **70% closed without a person:** the denominator must be all alerts, and only closures with no product decision count. I propose a "safe closure" target measured by an audit sample.
- **Median below 24 h:** it hides the lab-wait tail, so report p90 and age per wait state alongside it.
- **No late notifications:** software cannot guarantee this. We commit to 100% obligation creation at receipt, deadline-first queues and measured breaches.
- **Cost ceiling and seven-year basis:** accepted. The design uses about $553–575 of the ~$2,939/month ceiling. "No LLM" is a supported route for API-prohibited tenants, because one always-on self-hosted GPU is $4,139/month.

## 2. What the prototype shows on the real data

**Why every alert abstains, and why that is the correct result.** The kernel is built to refuse unsupported conclusions. The pack lacks exactly the inputs a defensible disposition needs:
- the temperature series (only aggregates are provided);
- SOP acceptance-limit content (the pack is an index only);
- batch exposure history.

So abstaining is right. What matters is how much it still does. For every alert it resolves entities within the tenant, names the SOP revision in force (or the conflict), accepts or rejects each stability study with a reason, computes the notification deadline, lists the exact human actions needed, and stays replayable bit-for-bit.

**EXC-107133**, the brief's case, reproduced from data alone:
- **Product:** GTIN 08901234500035 resolves within T-KAVERI (`02!R57`). The same GTIN exists for 3 other tenants with different studies.
- **SOP:** SOP-KAV-9392 **Rev 02 and Rev 03 are both in force** on 2026-07-28 at the origin site (Asia/Kolkata). This is reported as a blocking conflict; no revision is chosen.
- **Stability:**
  - The product master points to **STB-3584**, which is a *vial*, *accelerated*, *partially readable* study. It is rejected.
  - **STB-2738** (pen, "one excursion up to 6 h below 15 °C") is offered as an unreferenced candidate.
  - Its limit conflicts with the master's "cumulative 72 h above 8 °C".
- **Reviewer arithmetic:** within the stated single-excursion limit *for this event only*. "Once only" and "cumulative" are unverifiable because there is no batch history.
- **Notification:** due 2026-08-12T06:31Z if notifiable (India 15-day regime from the alert time 06:31, not the 06:14 excursion start).
- **Result:** abstain, with named human actions, including signature by Site QA.

**Time and corrections:**
- **Firmware bulletin:** a TT-2.14.3 alert raised before the 11 Apr 2026 bulletin shows no firmware finding at alert time. Viewed as at extract, it does, and a reopen review is recommended. The original assessment is unchanged.
- **Simulated correction:** a clearly labelled correction to the product master produces a new assessment that `supersedes` the old one. The old row's hash is unchanged, and an at-alert replay reproduces the original ID exactly.

**Isolation:**
- Cross-tenant reads are denied and audited.
- Stability ownership comes from `tenant_code`, never the folder. STB-4764 and STB-6586 are filed in each other's competitor folders.
- Untenanted product aliases are quarantined because of Meridian's Cl.22.

**Across all 420 alerts** (stratified evidence pack; **not** population accuracy or automation estimates):
- **Abstentions:** every alert abstains. Two gaps are pack-wide: no temperature series, and no SOP content. Setting those aside, **8 alerts** have no case-specific blocker (table below), and the other 412 each have at least one.
- **Most common case-specific blockers:**
  - no excursion SOP indexed for **T-VIRENT** (164);
  - inadmissible referenced study (153);
  - no admissible study (130);
  - master vs study conflict (116);
  - unresolved product (81).
- **Override reasons (24):** the concern is surfaced in 13, generically in 1 and missed in 1 (EXC-110476). The rest are out of scope or handled by another track.
- **Notification clock:** matches the pack's late/on-time flags on all 19 rows it can compute. It refuses to guess "next business day" for 9 rows.
- **Engine auto-closures:** 273 of the 275 engine AUTO_CLOSE rows have case-specific evidence gaps. These are candidates for a closure audit, not proof of error.

**The 8 alerts blocked only by pack-wide gaps** (at-alert view; each is reproducible from `artifacts/kernel.sqlite`). Each one has a resolved product, a resolved origin site, a single SOP revision in force and an admissible referenced stability study. Their stability check results differ, which is why a human still decides:

| Event | Tenant | SOP in force (origin) | Stability study | Check against the study's limit | Notification deadline |
|---|---|---|---|---|---|
| EXC-110091 | T-CAMPOS | SOP-CAM-2549 Rev 04 | STB-7140 | Exceeds stated limit | 2026-04-01T13:41Z (120 h) |
| EXC-110182 | T-CAMPOS | SOP-CAM-2549 Rev 04 | STB-7140 | Exceeds stated limit | 2026-04-06T04:57Z (120 h) |
| EXC-110595 | T-CAMPOS | SOP-CAM-2549 Rev 04 | STB-9763 | Cumulative limit, unverifiable | 2026-03-07T20:01Z (120 h) |
| EXC-112450 | T-CAMPOS | SOP-CAM-2549 Rev 04 | STB-9763 | Cumulative limit, unverifiable | 2025-12-30T23:22Z (120 h) |
| EXC-110406 | T-PINNACLE | SOP-PIN-5591 Rev 03 | STB-3324 | Not applicable (cold excursion) | not computed: "next business day" policy incomplete |
| EXC-110511 | T-PINNACLE | SOP-PIN-5591 Rev 03 | STB-3324 | Within stated limit, this event only | not computed |
| EXC-112219 | T-PINNACLE | SOP-PIN-5591 Rev 03 | STB-3324 | Within stated limit, this event only | not computed |
| EXC-112317 | T-PINNACLE | SOP-PIN-5591 Rev 03 | STB-3324 | Not applicable (cold excursion) | not computed |

## 3. Important workbook findings

The full list is in `docs/04`; the generated report is `artifacts/data_quality/report.md`.

**SOP index:**
- 27 overlapping SOP revision pairs across 10 documents.
- SOP-MER-5228 has three open-ended revisions, and Rev 05 takes effect before Rev 04.
- T-VIRENT, the largest tenant, has **no excursion SOP indexed**.

**Stability and product master:**
- 8 product-master study references point at a different presentation.
- 4 unreadable studies carry limit text, which contradicts the README.
- 11 GTINs are shared across tenants.

**Reviewer log:** 2 of 200 rows break the README's reconciliation rule (EXC-111001, EXC-111785).

**Time and narrative:**
- Memphis's timezone is wrong (Chicago, not New York); a second wrong site cannot be confirmed.
- The pack encodes "next business day" as 24 h, which is not equivalent.
- The brief's 06:14 is the excursion start, and the alert came at 06:31. Its 09:30 UTC pickup conflicts with log QL-02111 (06:54 UTC).

**Prior reviewer reasoning is not ground truth.** EXC-110448's "probably inside spec" does not follow: under-reporting means the true temperature was higher, and the event was a cold excursion that stays below 2 °C even with the full +1.8 °C.

**Observed facts vs system interpretations.** The facts come straight from the data. The interpretations are policies I chose for the prototype. Each is a versioned config or rule that QA or Regulatory Affairs must approve before production use.

| Observed fact (from the pack) | System interpretation (current policy) | Approval needed from |
|---|---|---|
| SOP-KAV-9392 Rev 02 `[2025-09-01, 2026-08-31)` and Rev 03 `[2026-05-16, open)` both cover 2026-07-28 | Overlap is a **blocking** conflict; no revision is chosen by number or row order | Tenant document control / QA |
| 115 revision hand-overs have `effective_to` equal to the next `effective_from` | Effective dates are half-open `[from, to)` site-local calendar dates | QA |
| Scope texts such as "Bhiwandi and Kundli only" | Mapped to registry site codes in `config/sop_scope_rules.json` | QA |
| Study text "Rinvatec PFS 40 — vial"; label "Glucodyne SoloJet" | The study's presentation comes from its suffix; "SoloJet" means a pen (`config/reference_facts.json`) | Tenant QA |
| Bulletin TT-CB-114: TT-2.14.3 under-reports "by up to 1.8 °C"; incident dated 2026-04-11 | An interval [0, +1.8] °C, known from 2026-04-11, applied to all TT-2.14.3 readings | QA + vendor |
| Reportable rows carry `reg_window_hours` (72, 120, 360, 24) | Per-tenant regimes; "next business day" is not computed until a timezone and calendar are given | Regulatory Affairs |
| `07` product aliases have no tenant column | Quarantined (Meridian Cl.22); not used for resolution | Commercial Counsel / QA |

## 4. Implemented vs stubbed vs design-only

| Implemented and tested | Stubbed or simulated (labelled) | Design only |
|---|---|---|
| Ingestion with provenance; append-only bitemporal store; tenant access control and audit; resolution and human mappings; SOP temporal/site selection; stability admissibility; limit and firmware-band arithmetic; telemetry flags; strict and reconstructed replay; manifest and content-hash IDs; supersession; evidence packages; notification clock and state machine (in-memory reference); data-quality report; evaluation layer | Telemetry archive, document content, batch history, regulator gateway; one simulated correction; synthetic fixtures for missing edge cases | Case workflow, leases and dual signature; outbox and durable timers; regional cells; source connectors; LLM drafting route; per-tenant indexes; WORM; monitoring and runbooks |

## 5. Verification actually executed

The full end-to-end run is recorded in [`evidence/E2E_EVIDENCE.md`](evidence/E2E_EVIDENCE.md), with every log. Run `python scripts/e2e_check.py` (any OS) to repeat it. In summary:

- **Tests:** all 78 pass. Supported: Python 3.11–3.13 on Windows, macOS and Linux, checked on every commit by the cross-platform workflow; the recorded real-workbook run used 3.12 on Linux.
- **Demo:** it loads the workbook's 1,413 source records. Loading them again adds nothing, so repeat runs are safe. It builds 841 assessments: two knowledge views of each alert, plus one after a correction.
- **Evidence packages:** all are exported and re-verified. An edited package is rejected.
- **Isolation:** cross-tenant reads and exports are refused (exit code 3).
- **Clean install:** a fresh clone with a fresh virtual environment passes 25 of 25 checks.

Not executed: anything in the "design only" column, load and failover tests, and RPO/RTO drills. All thresholds and costs are proposals or assumptions.

## 6. Known limitations

- The pack lacks the inputs a real "ready" verdict needs (temperature series, SOP content, batch history), so the demo shows the quality of abstention, not throughput.
- Several interpretations need QA and Regulatory Affairs sign-off before production use: scope mapping, presentation lexicon, notification regimes and bulletin semantics (see the fact-versus-interpretation table in §3).
- The product-alias quarantine costs coverage by design: 81 alias-string references stay unresolved.
- Case workflow, regional deployment, source connectors and monitoring are designed (`docs/02`, `docs/03`, `docs/05`) but not built.

## 7. How to run and where to look

```bash
mkdir -p data && cp /path/to/KCCS_Sentinel_Reference_Data_Pack.xlsx data/
python3 scripts/e2e_check.py   # Windows: py -3.12 scripts\e2e_check.py   -> expect: checks: 25, failed: 0
```

Then read, in order:
1. `docs/1-where-you-land/where-we-land.md`
2. `evidence/results/EXC-107133_assessment_excerpt.json` (or `artifacts/e2e/cases/EXC-107133_at_alert.json` after a run)
3. `evidence/results/evaluation_summary.md`
4. `docs/02`–`05`
5. `docs/4-working-log/working-log.md`

`docs/3-prototype/how-to-run.md` runs each command on its own, with the expected output. `docs/review-walkthrough.md` is a 20-minute walkthrough, with five hard questions and a rehearsed change response.
