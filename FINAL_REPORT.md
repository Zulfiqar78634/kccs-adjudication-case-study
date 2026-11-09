# Final report: KCCS Sentinel adjudication case study

**Candidate:** Zulfiqar · **For:** Kestrel Cold Chain Solutions, Platform Engineering · **Prepared:** 8–9 November 2026
**Status:** a working prototype and a written design. It is not production software and makes no compliance claims.

This report follows the four sections of the case-study instructions, in the same order and with the same sub-points. Each answer is short; it links to the full document and to the proof.

---

## Start here: check this submission in four steps

| Step | Do this | Time | What you will see |
|---|---|---|---|
| 1 | Read the [answer map](#answer-map) below | 2 min | Every requested item, where it is answered, and its proof |
| 2 | Open [evidence/E2E_EVIDENCE.md](evidence/E2E_EVIDENCE.md) | 3 min | A recorded end-to-end run on the supplied workbook: **25 of 25 checks passed** |
| 3 | Open [the brief's own case, EXC-107133](evidence/results/EXC-107133_assessment_excerpt.json) | 3 min | What the prototype found, explained in [§3.2](#32-running-on-the-real-workbook-the-briefs-case) |
| 4 | Run it yourself ([how-to-run.md](docs/3-prototype/how-to-run.md)) | 2 min | `python scripts/e2e_check.py` → `checks: 25, failed: 0`, on Windows, macOS or Linux |

## Answer map

| Requested item | Short answer | Full detail | Proof |
|---|---|---|---|
| **1. Where you land** | | | |
| Requirements mapped to the brief and pack | [§1.1](#11-requirements-and-where-each-one-comes-from) | [where-we-land.md §2](docs/1-where-you-land/where-we-land.md) (R1–R16) | each row names its test |
| What I am deliberately not building | [§1.2](#12-what-i-am-deliberately-not-building) | [where-we-land.md §3–4](docs/1-where-you-land/where-we-land.md) | — |
| Phased rollout, first customer, timeline | [§1.3](#13-phased-rollout-and-first-customer) | [where-we-land.md §6](docs/1-where-you-land/where-we-land.md) | tenant facts from tab `12` |
| Where the brief is silent or contradictory | [§1.4](#14-where-the-brief-is-silent-or-contradictory) | [where-we-land.md §5](docs/1-where-you-land/where-we-land.md), [data-findings](docs/1-where-you-land/data-findings-and-assumptions.md) | [data_quality_report.md](evidence/results/data_quality_report.md) |
| Board items I believe are wrong | [§1.5](#15-board-targets-i-challenge) | [where-we-land.md §7](docs/1-where-you-land/where-we-land.md) | — |
| **2. The design** | | | |
| Complete architecture | [§2.1](#21-architecture) | [architecture.md](docs/2-design/architecture.md) | 5 diagrams, rendered on GitHub |
| Components and why each boundary | [§2.2](#22-components-and-why-each-boundary-exists) | [architecture.md §2](docs/2-design/architecture.md) | — |
| Data model and "as at a date" queries | [§2.3](#23-data-model-and-as-at-a-date-queries) | [detailed-design.md §1–2](docs/2-design/detailed-design.md) | `tests/test_temporal.py`, `tests/test_assessment.py` |
| Case lifecycle: states, waits, manual steps, reopening | [§2.4](#24-case-lifecycle) | [detailed-design.md §4](docs/2-design/detailed-design.md) | state diagram |
| Degradation and the regulatory clock | [§2.5](#25-degradation-what-happens-when-something-is-down) | [architecture.md §4](docs/2-design/architecture.md), [detailed-design.md §5–6](docs/2-design/detailed-design.md) | `tests/test_obligations.py` |
| Versioning and deployment pipeline | [§2.6](#26-versioning-and-deployment-pipeline) | [detailed-design.md §7](docs/2-design/detailed-design.md) | manifest in every assessment |
| **3. Working prototype** | | | |
| The most critical component, built | [§3.1](#31-what-i-built-and-why-this-component) | [src/kccs_evidence/](src/kccs_evidence/) | 78 tests |
| Run on the provided workbook, with stubs | [§3.2–3.4](#32-running-on-the-real-workbook-the-briefs-case) | [how-to-run.md](docs/3-prototype/how-to-run.md) | [E2E_EVIDENCE.md](evidence/E2E_EVIDENCE.md) |
| Validation today and long-term | [§3.5](#35-validation-how-correctness-is-checked-today-and-over-time) | [validation.md](docs/3-prototype/validation.md) | [evaluation_summary.md](evidence/results/evaluation_summary.md) |
| **4. Working log** | | | |
| Discarded ideas, wrong assumptions, changes of direction | [§4](#4-working-log) | [working-log.md](docs/4-working-log/working-log.md) | each entry names the evidence that caught it |

---

## 1. Where you land

**My position in one sentence:** Kestrel does not need a better disposition predictor. It needs to **assemble an admissible, tenant-safe, time-correct evidence basis** for each human decision, and keep that basis so it can be reproduced years later.

The brief says so ("Assembling enough evidence to be allowed to make them is the whole cost", §2 p.3), and the workbook confirms it:
- about 20 of the 24 written override reasons (tab `09`) are evidence failures, such as an overlapping SOP revision (EXC-110490), a study for the wrong presentation (EXC-110497), or the wrong carrier legal entity (EXC-110581). This is my reading of the reasons, not a computed figure;
- all six incidents (tab `14`) are failures of evidence, version or isolation control;
- nine of the twelve reviewer questions (tab `10`) are lookups across systems.

I keep four things separate everywhere: **(a)** closing non-actionable alerts (no product decision); **(b)** product disposition, always signed by a person; **(c)** regulatory notification, whose clock runs from alert receipt and never pauses; **(d)** carrier liability, which decides who pays, never what happens to the product.

### 1.1 Requirements, and where each one comes from

Sixteen requirements, each traced to the brief or a workbook cell and to the test that checks it. The most important:

| ID | Requirement | Comes from | Checked by |
|---|---|---|---|
| R1 | Resolve product, site and carrier **within one tenant**; never guess | Brief §7; GTIN 08901234500035 exists in 4 tenants (tab `02`) | `test_same_gtin_under_multiple_tenants…` |
| R3 | Use the SOP revision **in force at that site on that date**; overlaps are conflicts | Brief §2; 27 overlapping revision pairs (tab `05`) | `test_real_overlap_exc_107133` |
| R4 | Stability evidence must match owner, presentation and readability | `00!R35–R44`; EXC-110497 | `test_exc_107133…`, `test_exc_110497…` |
| R5 | Facts learned later must not leak into "what we knew then" | INC-2506 | `test_replay_excludes_bulletin…` |
| R6 | The full basis is retrievable in under 1 hour for 7 years | Board #3; AUD-2603 | `test_export_and_verify`, `test_tampering_detected` |
| R7 | The notification clock runs from alert receipt, independent of disposition | Brief §2; `00!R43`; INC-2502 | `tests/test_obligations.py` |
| R10 | No cross-tenant derived data (Meridian clause 22) | `12!R6`; INC-2512 | `tests/test_tenant_isolation.py` |
| R16 | Missing evidence is never treated as favourable | Dr Rao, brief §4 | `test_never_a_disposition_across_all_events` |

All 16, with implications and phases: [where-we-land.md §2](docs/1-where-you-land/where-we-land.md).

### 1.2 What I am deliberately not building

| Not building | Why |
|---|---|
| Automated product disposition | Dr Rao's condition and the January pilot. The prototype's `is_disposition` is always false |
| Replacing the 2,400-rule engine in phase 1 | It closes about 64% of alerts today. I wrap closure with an evidence check and audit sample first |
| Cross-tenant fine-tuning or shared embeddings | Forbidden in practice by clause 22, and not needed |
| Microservices, a graph database, vector search or agents | A modular monolith with Postgres covers the access patterns for six engineers |
| Digitising all 11,040 stability PDFs up front | Index on demand per onboarded tenant |
| Ranking or fuzzy-matching ambiguous evidence | It hides exactly the conflicts a reviewer must see |

### 1.3 Phased rollout and first customer

**First customer: T-KAVERI.** It has no residency clause, a single signer (Site QA), English output, a lower-risk 15-day notification regime with no late notifications in the pack, and moderate volume. It is also the brief's own example (EXC-107133). Its real problems (three SOPs with overlapping revisions, two handwritten annexures) are a fair test of the abstain-and-route path.

Why not the alternatives: **T-AURA** needs the EU cell and named e-signatures and is up for renewal, so a stumble there is costly; it goes second. **T-VIRENT** is largest but India-only, API-prohibited, dual-signature, and has no excursion SOP indexed at all.

| Phase | When | Scope | Gate to continue |
|---|---|---|---|
| 0 Foundations | weeks 0–6 | Kernel in production form, India cell, obligation ledger, Kaveri curation | Isolation suite and leak canaries green; Kaveri history replays bit-for-bit |
| 1 Shadow | weeks 6–10 | Assess every Kaveri alert; reviewers work as today | Dr Rao signs the replay report; 100% obligation creation |
| 1 Live | by day 90 | Reviewer aid, evidence packages, notification ledger | Any leak, missed obligation or replay drift → feature flag off |
| 2 | months 4–6 | EU cell (T-AURA, T-NORDIA), T-CAMPOS (Portuguese), T-SAHYADRI | Per-tenant replay report and QA sign-off |
| 3 | months 6–9 | T-VIRENT (no-LLM route), Pinnacle/Meridian, the rest in waves | Same gates |

The timeline rests on one stated assumption: about two weeks of curation per tenant. All 34 tenants can be onboarded in nine months; equal maturity for all 34 cannot be promised from the pack.

### 1.4 Where the brief is silent or contradictory

| Issue | Position I took | Who should confirm |
|---|---|---|
| The brief's "06:14" is the excursion start; the alert arrived at 06:31 | The clock runs from the alert (06:31), per `00!R43` | Regulatory Affairs |
| Kaveri pen product points to study STB-3584, which is a **vial**, accelerated, partly unreadable study | Rejected; the matching pen study STB-2738 is offered only as a candidate | Kaveri QA |
| SOP-KAV-9392 Rev 02 and Rev 03 are both in force on 28 July | Blocking conflict; no revision chosen | Kaveri document control |
| T-VIRENT (164 of 420 alerts) has no excursion SOP indexed | Blocking; other titles listed but not assumed | Virent document control |
| "Next business day" is stored as 24 hours | Not equivalent: deadline not computed, escalated | Regulatory Affairs |
| Product aliases (tab `07`) have no tenant column | Quarantined: cannot prove they are not Meridian-derived | Commercial Counsel |
| Brief pickup 09:30 UTC vs log 06:54 UTC | Trust the log for metrics | Brief author |

Full register with risks: [where-we-land.md §5](docs/1-where-you-land/where-we-land.md) and [data-findings-and-assumptions.md](docs/1-where-you-land/data-findings-and-assumptions.md).

### 1.5 Board targets I challenge

| Board target | My counterargument | What I propose instead |
|---|---|---|
| 70% closed without a person | Pressure to close invites disguising product release as "closure". The auto-closed population has never been audited, and 273 of 275 engine auto-closures in the pack had evidence gaps | 70% **safe** closure over **all** alerts, only for closures with no product decision, measured by a monthly blind audit |
| Median under 24 h to signed disposition | A median hides the lab-wait tail (a 9-day lab test in EXC-110553) | Report p50, p90 and maximum age per wait state |
| No late notifications | Software alone cannot guarantee it: notifiability is a human call and regulators control acknowledgement | 100% obligation creation at receipt, deadline-first queues, escalation at T−24/6/1 h, breaches reported |
| Basis within an hour for 7 years | Accepted | It is the prototype's core |
| Cost ceiling (~$2,939/month) | Accepted, with headroom | The design uses about $575/month; a "no LLM" route is supported because one self-hosted GPU alone costs $4,139/month |

---

## 2. The design

### 2.1 Architecture

A **modular monolith per regional cell** (EU, India, Americas), with background workers. Each cell has its own Postgres, object store and workers, which satisfies the residency clauses in tab `12`. A thin global control plane holds only non-tenant data (routing, release metadata, vendor bulletins); no tenant evidence crosses cells.

Why not microservices: about 11,400 alerts a month with bursts of 1,912 in 38 minutes is moderate, transactional, audit-heavy work for six engineers. Microservices would add distributed-consistency problems without a scaling need.

**Diagrams** (all render on GitHub): system architecture, evidence-assessment sequence and data model in [architecture.md](docs/2-design/architecture.md); case lifecycle and notification lifecycle state diagrams in [detailed-design.md](docs/2-design/detailed-design.md).

### 2.2 Components and why each boundary exists

| Component | Why it is its own boundary |
|---|---|
| Ingestion and source snapshots | Sources lose data (SYS-01 keeps 30 days; SYS-03 never backfills). Without our own copy, AUD-2603 recurs |
| Tenant attribution | BMS feeds carry no tenant tags; guessing risks cross-tenant leakage |
| Entity resolution | Mappings are reviewers' tacit knowledge and need ownership, versioning and approval |
| Temporal policy selection | The hardest rule to get right, and the root cause of EXC-110490 |
| **Assessment kernel** (built) | The reproducible unit that Dr Rao evaluates |
| Case workflow | Where human accountability lives |
| Notification obligations | Must keep running when the case workflow is blocked (INC-2502) |
| Precedent store | Same tenant only, filtered before retrieval (INC-2512) |
| Evidence package | Hashed, write-once, kept 7 years (board #3) |
| Optional LLM drafting | Writes reviewer prose only; never decides; removable without loss of function |

### 2.3 Data model and "as at a date" queries

Every fact carries **two times**: when it applied in the world (*valid time*, for example an SOP's `[effective_from, effective_to)`), and when *we learned it* (*recorded time*). Records are append-only; corrections add versions and never edit.

So the system can answer both questions an inspector asks:
- **"What did you know when you decided?"**: only versions recorded before the cutoff.
- **"What do we now know about that day?"**: the same valid date with a later cutoff.

The [worked example](docs/2-design/detailed-design.md#worked-example-an-as-at-a-date-query) shows the actual SQL and how it gives EXC-107133's SOP conflict. Tenant filtering is inside that query, so isolation happens before retrieval, not after.

### 2.4 Case lifecycle

`RECEIVED` → `ASSEMBLING` → `READY_FOR_REVIEW` or `NEEDS_HUMAN_EVIDENCE` → signed → closed or follow-up. The full state diagram is in [detailed-design.md §4](docs/2-design/detailed-design.md).

- **Waiting** on carrier data, a lab or document control is an explicit state with its own age metric. It **never pauses** the notification clock.
- **Manual steps:** approving mappings, resolving conflicts, transcribing handwritten annexures, signing (dual signature where the tenant requires a different second signer).
- **Concurrency:** a 30-minute renewable review lease; signing against an outdated assessment is refused.
- **Reopened months later:** new information (for example a firmware bulletin published after the alert) creates a reopen candidate. On QA acceptance a new case revision is created; the original signature and its evidence are never changed. The prototype demonstrates this with firmware bulletin TT-CB-114.

### 2.5 Degradation: what happens when something is down

| Failure | Behaviour | Effect on the regulatory clock |
|---|---|---|
| Telemetry source down or gap | Marked as a blocking gap; no guessing across gaps | None: the clock started at alert receipt |
| Document store down | Use the last registered version if known by the cutoff; otherwise abstain | None |
| Model provider down | Drafting falls back to templates; nothing else depends on it | None |
| Database failover | Proposed RPO ≤ 5 min, RTO ≤ 1 h; timers rebuilt from data | Timers resume; anything within 6 h escalated to a person |
| Whole cell down | Regulatory Affairs manual runbook; reconcile on recovery | The deadline never moves; breaches are reported, not hidden |
| Alert storm | One obligation per alert; per-tenant, earliest-deadline-first queues | Other tenants' 72-hour obligations stay at the front (tested with 1,912 alerts) |

### 2.6 Versioning and deployment pipeline

Everything that can change a conclusion is versioned and recorded in each assessment's **manifest**: code fingerprint, rule set, configuration hashes, source record versions, mappings and model route.

Pipeline: CI → **historical replay per tenant with a diff report** → QA approval → one-week shadow → three-day canary → progressive rollout. Rollback moves a version pointer; earlier assessments stay valid under their own manifests. This is the direct answer to INC-2411, where a prompt change silently altered 31 tenants: a change must now name every tenant whose replay differs.

---

## 3. Working prototype

### 3.1 What I built, and why this component

The **evidence-resolution and replay kernel**: given an alert, a tenant and a knowledge cutoff, it produces a content-addressed assessment containing:
- resolved and unresolved entities;
- selected and rejected evidence, with reasons;
- conflicts, missing inputs and the exact human actions needed;
- the notification deadline;
- a manifest that lets anyone reproduce it.

I chose it because it is the part every override and incident in the pack traces back to, and the hardest part to get right. It is not the most visual part. The prototype **abstains instead of guessing** and never makes a product decision.

| Built and tested | Stubbed (labelled) | Design only |
|---|---|---|
| Ingestion with provenance; append-only two-time store; tenant access control and audit; entity resolution with human mappings; SOP selection by site and date; stability admissibility; firmware-bulletin arithmetic; strict and reconstructed replay; content-hash IDs and manifests; supersession; evidence packages; notification clock; data-quality report; evaluation over all alerts | Telemetry archive, document content, batch history, regulator gateway; one clearly labelled simulated correction | Case workflow, leases and signatures; durable timers; regional cells; source connectors; LLM drafting; monitoring |

### 3.2 Running on the real workbook: the brief's case

**EXC-107133**, reproduced from the workbook alone ([excerpt](evidence/results/EXC-107133_assessment_excerpt.json)):

| Question | What the prototype found |
|---|---|
| Which product? | GTIN 08901234500035 resolved **within T-KAVERI** to `02_Product_Master!R57`, although the same GTIN exists for 3 other tenants |
| Which SOP? | SOP-KAV-9392 **Rev 02 and Rev 03 are both in force** on 28 July at the site → blocking conflict, no revision chosen |
| Which stability study? | Referenced **STB-3584 rejected**: vial (not pen), accelerated, partly unreadable. **STB-2738** (pen, "one excursion up to 6 h below 15 °C") offered as a candidate |
| Notification deadline? | **2026-08-12T06:31:00Z** if notifiable: 15 days from the alert (06:31), not the excursion start (06:14) |
| Can it decide? | **No.** It lists the human actions needed, ending with "Sign or decline the disposition: Site QA" |

### 3.3 Across all 420 alerts

The 420 alerts are a **stratified** pack, not a random sample, so none of these numbers is an accuracy or automation rate.

- **Every alert abstains, correctly.** The pack has no temperature series, no SOP content and no batch history, so no defensible "ready" verdict is possible. What matters is the quality of each abstention.
- Setting those pack-wide gaps aside, **8 alerts** have no case-specific blocker; the other 412 each have at least one. Most common: no excursion SOP for T-VIRENT (164), inadmissible referenced study (153), no admissible study (130).
- **Reviewer overrides:** of the 24 written reasons, the concern is surfaced in 13, generically in 1, and **missed in 1** (EXC-110476, left as a recorded miss rather than retrofitted).
- **Notification clock:** matches all 19 late/on-time flags it can compute, and refuses to guess "next business day" for 9.
- **Time travel:** an alert raised before firmware bulletin TT-CB-114 shows no firmware finding "as known then", and does "as known later". The original assessment is unchanged.

Full results: [evaluation_summary.md](evidence/results/evaluation_summary.md). Workbook problems found: [data_quality_report.md](evidence/results/data_quality_report.md).

### 3.4 Stubs

The workbook does not contain telemetry series, SOP text, batch history or a regulator gateway. These are stubbed and named in every assessment's manifest (`stubs`), so no output pretends to have used them.

### 3.5 Validation: how correctness is checked today and over time

**Today (executed):**
- **78 automated tests**, each tied to a requirement. 45 use the real workbook; 33 run anywhere, including a full command-line run on an invented workbook. [What the tests prove](README.md#what-the-78-tests-prove).
- **Recorded end-to-end run** on the supplied workbook: fresh install, tests, demo, the brief's case, isolation, tamper detection, **25 of 25 checks passed** ([evidence](evidence/E2E_EVIDENCE.md)).
- **Every commit** is tested on **Windows, macOS and Linux** with Python 3.11, 3.12 and 3.13 (9 machines), and all 9 must produce the identical assessment ID ([workflow](.github/workflows/cross-platform.yml)). Those machines use an invented workbook because the confidential one is never uploaded.
- **Code quality:** lint-clean (`ruff`), small single-purpose functions, type hints and docstrings on public functions ([§3.6](#36-code-structure)).

**Over time (designed):** a nightly replay of a frozen 200-case set per tenant whose IDs must match bit-for-bit; planted canary records that page if they appear in another tenant's output; obligation-completeness checks (alerts minus obligations must be 0); abstention-spike alerts against a 28-day baseline; nightly evidence-package verification. Runbooks and owners: [validation.md §2](docs/3-prototype/validation.md).

### 3.6 Code structure

```
src/kccs_evidence/
  sources.py        read the workbook, keep provenance (sheet, row, hash) for every record
  store.py          append-only two-time store; "as at" queries; audit log
  access.py         tenant-scoped views: every read is checked and filtered in SQL
  resolution.py     product / site / carrier resolution within a tenant; human mappings
  temporal.py       half-open date intervals and site-local dates
  policy_sop.py     which SOP revision was in force; overlaps become conflicts
  stability.py      is a stability study admissible for this product and presentation?
  signals.py        telemetry flags and firmware-bulletin arithmetic
  obligations.py    the notification clock, independent of the case
  assessment.py     assembles one reproducible assessment from the steps above
  package.py        export and verify tamper-evident evidence packages
  evaluation.py     results across all 420 alerts
  inspection.py     workbook data-quality report
  cli.py            the `kccs-evidence` command
```

Each module has one job, and dependencies point one way: `cli` → `assessment` → the evidence modules → `access` → `store`. Every tenant-scoped read goes through `access.py`, so isolation cannot be bypassed by a new module.

---

## 4. Working log

The full log, with the evidence behind every entry, is [working-log.md](docs/4-working-log/working-log.md). The most instructive entries:

**Assumptions that were wrong, and how they were caught**

| Wrong assumption | How it was caught | What changed |
|---|---|---|
| One SOP title governs excursions for every tenant | The first full run showed 164 alerts with no SOP, all T-VIRENT | Kept as a real finding; the message lists the tenant's other titles without assuming them |
| A study's presentation can be read from any word in its text | EXC-107133's expected "wrong presentation" rejection was missing ("SoloJet" brand looked like a pen) | Explicit presentation words now beat brand-derived words |
| Replay "as known at the alert" was leak-free | The correction demo's own reproducibility check failed: a September correction leaked into a July replay | Store reads are now cut off at the knowledge time; regression test added |
| An evaluation check could fail | It accepted any carrier match, so it could never fail | Now requires the exact contract (CNT-2023-0441) |

**Discarded approaches**
- **Rank ambiguous candidates, or pick the latest revision:** it hides conflicts, and SOP-MER-5228 Rev 05 actually takes effect before Rev 04.
- **Fuzzy product matching:** this is exactly how the wrong presentation gets chosen.
- **Use the alias table as a lookup:** no tenant provenance, so it could leak Meridian-derived data.
- **Treat 1.8 °C as a fixed correction:** the bulletin says "up to", so it is an interval.
- **Build a dashboard:** the brief asks for the hardest part, not the most demonstrable.
- **Self-host a model for API-prohibited tenants:** one GPU instance is above the whole budget.

**Changes of direction**
- **Replaced the starting scaffold** because it read the recorded outcome as an input (outcome leakage) and invented confidence numbers.
- **Refused to retrofit** evaluation expectations to make the remaining miss (EXC-110476) pass.
- **After review:** made each test claim visible, explained up front why every alert abstains, separated observed facts from my interpretations, and added recorded end-to-end proof, then Windows/macOS support and a code clean-up.

---

## 5. Honest limits

- The pack lacks the inputs a real "ready" verdict needs, so the prototype demonstrates the **quality of abstention**, not throughput.
- Several interpretations (SOP scope mapping, presentation words, notification regimes, bulletin meaning) are **my policies**, each needing QA or Regulatory Affairs sign-off. They are listed with their approver in [data-findings-and-assumptions.md](docs/1-where-you-land/data-findings-and-assumptions.md).
- Case workflow, regional deployment, source connectors and monitoring are designed but not built. Load, failover and recovery-time tests were not run. Costs and thresholds are proposals.
- The real workbook was run on Linux. Windows and macOS are tested on every commit with an invented workbook of the same layout.
- This work was produced with heavy AI assistance under my direction; the [working log](docs/4-working-log/working-log.md) states this and records what was checked and corrected.
