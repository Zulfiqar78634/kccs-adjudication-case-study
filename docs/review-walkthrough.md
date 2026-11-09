# 07 — Review walkthrough, hard questions, change response

## 20-minute walkthrough

| Min | Show | File / command |
|---|---|---|
| 0–3 | The problem is evidence, not prediction; the four separate concepts | [where we land](1-where-you-land/where-we-land.md) §1 |
| 3–6 | EXC-107133 end to end: GTIN → Kaveri row R57 → overlap Rev 02/03 → STB-3584 rejected (vial, accelerated, partial) → STB-2738 candidate → master-vs-study conflict → abstain with human actions | `artifacts/cases/EXC-107133_at_alert.json` |
| 6–9 | Time: at-alert vs at-extract for a TT-2.14.3 alert; the bulletin appears only in the later view; the original assessment is unchanged; simulated correction → new ID, supersedes link, at-alert replay reproduces the old ID | `artifacts/demo_run.json` → `correction_demo` |
| 9–11 | Tenant isolation: same GTIN in 4 tenants; STB-4764/STB-6586 path trap; denial audited; product aliases quarantined (Cl.22) | `tests/test_tenant_isolation.py` |
| 11–13 | Notification clock: separate state machine; waits don't move it; next business day refuses to guess; storm keeps 1,912 obligations | `tests/test_obligations.py` |
| 13–16 | Workbook summary and override evaluation, including what we miss (EXC-110476, EXC-110602) | `artifacts/evaluation/summary.md` |
| 16–18 | Architecture, cells, first customer Kaveri, gates and rollback | [architecture](2-design/architecture.md), [where we land](1-where-you-land/where-we-land.md) §6 |
| 18–20 | Board targets: denominators, tail latency, "no late notifications" as a measured commitment | [where we land](1-where-you-land/where-we-land.md) §7 |

## Five hard questions

**1. "Everything abstains. What use is a system that says no 420 times?"**
Two blockers (no series, no SOP content) are artefacts of the pack; in production the series is snapshotted at ingest and SOP limits are transcribed once per revision. With only those two gaps closed, 8 of the 420 would already be READY_FOR_QA_REVIEW. The remaining blockers are real, specific and actionable: "Rev 02 and Rev 03 overlap", "master points at the vial study". Today they cost Priya 100 minutes per case to rediscover. Abstention with a named reason is the deliverable. After per-tenant curation, abstentions become the exception. Their rate is a metric we report, not hide.

**2. "Why not let the LLM read the SOP and decide?"**
The January pilot did exactly that and cited withdrawn revisions (B§5). The evidence must be right before anyone reasons over it. An LLM may draft prose from a finished assessment, under a versioned route and replay gate. It is optional, and the system is fully functional without it.

**3. "Half-open site-local dates: what if Docuvault meant the end date inclusively?"**
Then the 115 hand-overs where `to == next from` would each be one-day overlaps, which contradicts the supersession texts ("Rev 01 withdrawn"). If a tenant's SOP says otherwise, the convention is a versioned per-tenant policy. Replay shows exactly which assessments change.

**4. "Your evaluation says SURFACED for 13 overrides. Couldn't you have tuned it?"**
The expectation table was written from the verbatim reasons. One expectation that could not fail (EXC-110581) was caught and tightened, and the misses are reported. It is a coverage check of reviewer concerns, not accuracy. The real gate is Dr Rao's review of the replay diff.

**5. "How do you stop a Meridian fact reaching Pinnacle through a cache, log or embedding?"**
The `TenantView` is required for every read, with SQL filtering by tenant. Caches live on the view. Indexes are per tenant per cell. Logs never carry payloads. Untenanted derived data (`07` product aliases) is unreadable. In production, canary strings are planted per tenant and searched for in every other tenant's outputs, logs and indexes, and a hit auto-disables precedent search and the model route.

## Change-response example (unseen change rehearsal)

**Change:** "Brazil's regulator moves to 3 calendar days, counted to 23:59 local on day 3, effective 2027-01-01; and ThermaTrace revises TT-CB-114 to say the error is exactly +1.2 °C for builds before 2026-03-01."

1. **Regime:** add `tenant_policy_version` for T-CAMPOS with `valid_from = 2027-01-01` (half-open), kind `CALENDAR_DAYS_END_OF_DAY`, tz `America/Sao_Paulo`. Alerts received before 2027-01-01 keep the 120 h regime, because obligations store `regime_version` and `due_at` is never recomputed. Add a unit test for the day-3 23:59 boundary.
2. **Bulletin:** append a new bulletin version (`exact_correction_known = true`, magnitude 1.2, applicability by build date, `known_from` = receipt time). Nothing is edited.
3. **Replay:** run the per-tenant replay at `knowledge_cutoff = now`. The diff lists every assessment whose findings change. Signed cases with a changed conclusion become REOPEN_CANDIDATEs, with the original signatures and packages intact. Carrier invoices flagged for withdrawal go to the liability follow-up.
4. **Approval & rollout:** QA approves the diff, then shadow, then canary, as in [detailed design](2-design/detailed-design.md) §7. "What did we know then?" stays answerable because the older bulletin version remains recorded with its own `known_from`.
