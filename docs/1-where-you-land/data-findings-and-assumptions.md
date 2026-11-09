# 04 — Data findings, contradictions and assumptions

The full machine-generated report is `artifacts/data_quality/report.md` (+ `report.json`), produced by `kccs-evidence inspect`. This page summarises what matters for the design. All counts were computed by code from the workbook (sha256 prefix `9fe3fad7d0f77a5f`, extract 2026-09-14).

**Read first:** `01_Excursion_Events` is a **stratified evidence pack** (`00!R28`): 61 bulletin re-adjudications, 24 written overrides, 13 + 1 late notifications, 57 + 1 storm rows, 1 brief case and 264 random. The code reproduces the strata (61 reopened, all on firmware TT-2.14.3; 24 override IDs all present in 01; 14 late; 58 storm rows, 1 overlapping the overrides). **No ratio in this repository is a population estimate.**

## 1. Inventory

15 tabs; 420 alerts, 59 product-master rows, 70 facility records (14 physical sites × 5 names), 14 contracts, 203 SOP revisions of 62 documents, 107 stability studies, 207 alias observations, 200 reviewer-log rows, 24 override reasons, 12 questions, 9 systems, 9 tenant-constraint rows (8 tenants + "26 others"), and 6 incidents. The per-column missingness table is in the generated report.

## 2. Preservation

- All 36 GTINs are strings with a leading zero, and none of the event product references are numeric. Ingestion keeps raw cell values and an Excel row reference per record (e.g. EXC-107133 = `01!R221`).
- Timestamps in 01 are `YYYY-MM-DD HH:MM` without a zone; they are UTC per `00!R31`. The original strings are kept alongside the parsed instants.
- Missing / invalid / conflicting / unknown are kept distinct:
  - **MISSING_INPUT:** 42 blank product references.
  - **UNPARSED:** 3 storage-spec strings that cannot be read without assumption: "Controlled room temperature", "Cryogenic, vapour phase only", "LN2 vapour phase (-196 nominal)".
  - **CONFLICT:** e.g. overlaps.
  - **UNKNOWN:** e.g. timezone not trusted, notifiability.

## 3. Joins

| Join | Result (tenant-scoped, exact) | Meaning |
|---|---|---|
| Event product ref → own tenant master | 297 single match · 81 no match · 42 blank · 0 ambiguous | The 81 are mostly alias strings ("GLUCODYNE SOLOJET", "Thermelia 50"). They are not resolved because untenanted product aliases are quarantined |
| GTIN across tenants | 11 GTINs appear in 2–5 tenants' masters (e.g. 08901234500035: T-KAVERI, T-NORDIA, T-PINNACLE, T-VIRENT) with **different** study refs and allowances | Identity must be (tenant, identifier) |
| Facility refs (origin+dest, 840) | 539 match a registry site code · 248 match a registry record whose code is unlinked (F00231, KCCS-IN-BLR-02…) · 53 not in the registry | Unlinked codes can only be linked through reviewer aliases, which carry `confirmed_on` dates; many post-date the alerts |
| Carrier refs | 420/420 match exactly one contract's `names_seen` | Easy in this pack; subsidiaries (Aeroflux GmbH vs Pvt Ltd, TransPolar Inc vs do Brasil) are distinct contracts with 21 vs 30 and 30 vs 14 day claim windows |
| Alias observations | 207 rows, **no tenant column**; 4 explicit negatives (`07!R205–208`); comments include "Disputed by TMS owner" and "Reviewer note only, never written back" | Hints only; product aliases quarantined (Meridian Cl.22) |

## 4. SOP index

- **27 overlapping revision pairs in 10 documents** (SOP-AUR-6613, SOP-CAM-7820, SOP-KAV-2571, SOP-KAV-5329, SOP-KAV-9392, SOP-MER-2013, SOP-MER-5228, SOP-PIN-1059, SOP-PIN-8622, SOP-VIR-9115).
- 115 hand-overs with `to == next from`; hence half-open intervals.
- SOP-MER-5228 has **three open-ended revisions**, and Rev 05 takes effect before Rev 04.
- **T-VIRENT has no "Temperature Excursion Management" document**, although it has 164 of the 420 events.
- Annexure content and acceptance limits are never in the pack, only their location. 102 revisions locate limits in an annexure, 28 are scoped "Site-specific — see Annexure 1", and 17 are scans with handwritten annotations.
- EXC-107133: SOP-KAV-9392 Rev 02 `[2025-09-01, 2026-08-31)` and Rev 03 `[2026-05-16, open)` are both in force on 2026-07-28. This matches the brief's "three revisions with overlapping effective dates".

## 5. Stability

- Master references: 47 indexed under the same tenant, 5 not indexed, 7 blank, and none owned by another tenant.
- **8 master references point to a study for a different presentation:** `02!R2`→STB-8597, R7→STB-4441, R16→STB-4417 (the EXC-110497 case), R26→STB-8113, R33→STB-4957, R48→STB-3695, R57→STB-3584, R60→STB-7388.
- Readability: 87 Y, 13 partial, 7 "scan of scan". Four unreadable rows nonetheless carry permitted-excursion text (STB-5652, STB-7265, STB-8989, STB-8772), which contradicts `00!R42`.
- 41 studies have no excursion limit by design (long-term, accelerated, in-use).
- Path vs owner: STB-4764 (owner T-MERIDIAN) is filed under `/T-PINNACLE/`, and STB-6586 (owner T-PINNACLE) under `/T-MERIDIAN/`. This is the competitor pair. STB-5414 (T-AURA) is under `/T-VIRENT/`, and 5 studies are under `/Shared/`.
- EXC-107133:
  - Product master `02!R57` says "Cumulative 72 h above 8 °C" and references **STB-3584 = vial, accelerated, partially readable**.
  - The pen excursion study **STB-2738** ("One excursion, up to 6 h below 15 °C") is in Kaveri's index but unreferenced. It is the study the brief describes.
  - STB-4400 is unreadable and STB-3312 is a vial study. Kernel result: candidate only, plus a master-vs-study conflict.

## 6. Time

- Detection latency (alert − excursion start), in minutes: SYS-01 median 15 (5–25), SYS-02 median 7 (1–86, out-of-order delivery), SYS-03 median 2 (0–4).
- Reviewer log: README's reconciliation (`00!R41`) holds within 15 minutes for **198 of 200** rows. QL-02165/EXC-111001 is off by 174.6 min and QL-02160/EXC-111785 by 133.2 min.
- Facility timezone: Memphis (MEM-CS-02) is America/Chicago, not America/New_York, so it is confirmed wrong. README says two sites are wrong. Indianapolis is the likely second (canonical America/Indiana/Indianapolis, but the same offsets), and it cannot be confirmed.
- Product-master `last_updated` post-dates some alerts. The kernel flags `PRODUCT_MASTER_UPDATED_AFTER_ALERT` because the at-time row is not in the pack (`00!R34`).

## 7. Notification rows (flagged reportable in 01)

There are 28 rows: T-AURA 72 h (5 late), T-NORDIA 72 h (3 late), T-PINNACLE 24 h (3 late / 2 on time), T-MERIDIAN 24 h (3 late / 1 on time), T-CAMPOS 120 h, and T-VIRENT/T-SAHYADRI/T-KAVERI 360 h (all on time). That is 14 late, all in the 72 h and "next business day" markets, consistent with `13!R23`. The kernel's clock agrees with the pack's late flag on every row it can compute. It refuses to compute the 9 "next business day" rows (encoded as 24 h in the pack) without a timezone and calendar.

## 8. Reviewer questions answerable from the pack

| Q | Answerable | Why |
|---|---|---|
| 1 SOP in force | Partial | windows and scope yes; content no; Virent missing |
| 2 Stability permits? | Partial | ~60% indexed; cumulative needs batch history |
| 3 Lane history | Partial | sample only; no equipment ID; latest-value outcomes |
| 4 Contract | Partial | legal entities yes; separately filed amendments absent |
| 5 Gap/interpolation | Partial | flags yes; gap position and series no |
| 6 Duplicate excursion | No | no physical excursion key |
| 7 Product in room | No | BMS untagged; TMS room mapping absent |
| 8 Batch history | No | no batch identity |
| 9 Who signs | Yes (8 tenants) | tab 12 |
| 10 Reportable, by when | Partial | windows yes; notifiability criteria and US calendar no |
| 11 Last time | Partial | 24 written reasons only |
| 12 Reconstruct in 2 years | No (today) | the gap this design closes |

## 9. Semantics caveats honoured in code

- `rules_engine_recommendation` is the **assistant's draft** since 2024 (`00!R45`).
- `case_opened = N` rows were never audited (`00!R36`): they are not ground truth.
- Aggregates are not a series. "Up to 1.8 °C" is an interval, not an offset.
- Absent study ≠ no study. Outcome fields are excluded from kernel inputs.

## 10. Assumptions register (beyond [where we land](where-we-land.md) §5)

| # | Assumption | Basis | If wrong |
|---|---|---|---|
| A1 | Pack rows were "recorded" at the extract date (2026-09-14 00:00 UTC) | no recorded-time history exists | strict replay abstains; reconstructed replay is labelled |
| A2 | Bulletin TT-CB-114 known from 2026-04-11 00:00 UTC; applies to all TT-2.14.3 readings | `14!R5` | earlier/later knowledge shifts reopen candidates |
| A3 | Scope strings map to site codes as in `config/sop_scope_rules.json` | registry names | wrong scope → wrong SOP; needs QA approval |
| A4 | "SoloJet" denotes a pen | brief p.2 | presentation check for Glucodyne |
| A5 | Notification regimes per tenant inferred from reportable rows | `01`, `13!R22` | wrong deadlines; RA must confirm |
| A6 | Facility and carrier entities are Kestrel-owned (sharing across tenants is allowed); products are tenant-owned | `12` contract summaries | if facility data is tenant-confidential, scope it |
| A7 | Ceilings are additive | sum ≈ $3,000 | budget is $2,255 |
