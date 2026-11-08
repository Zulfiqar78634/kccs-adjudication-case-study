# Submission checklist: evaluator expectations → evidence

| Expectation | Where | Status |
|---|---|---|
| **A. Where you land** | | |
| Requirements mapped to brief/workbook evidence | `docs/01` §2 | done |
| What we will not build, and why | `docs/01` §3 | done |
| Phased rollout, first customer, timeline, gates, rollback | `docs/01` §6 | done (Kaveri) |
| Silence/contradictions/assumptions/positions | `docs/01` §5, `docs/04` §10 | done |
| Board requests challenged with reasoning | `docs/01` §7 | done |
| **B. Design** | | |
| Architecture, components, boundaries | `docs/02` §1–2 | done |
| Data model incl. "as at" queries | `docs/03` §1–2; `store.records(as_known_at=…)` | done |
| Lifecycle, waiting, manual actions, reopen months later | `docs/03` §4 | design |
| Degradation; outages vs regulatory clocks | `docs/02` §4, `docs/03` §5–6 | design + obligation tests |
| Versioning and deployment pipeline | `docs/03` §7 | design; manifest implemented |
| Diagrams (system, sequence, case, notification, data) | `docs/02` §1, §3, §6; `docs/03` §4–5 | Mermaid |
| Cost and sizing from tab 13 | `docs/02` §9 | done (assumptions labelled) |
| **C. Working prototype** | | |
| Hardest component, justified | `FINAL_REPORT.md` §1, `docs/01` §4 | evidence kernel |
| Runs on the actual workbook | `scripts/run_all.sh`; `artifacts/` | executed |
| External dependencies stubbed explicitly | manifest `stubs`; README table | done |
| Correctness now | 76 tests, `docs/05` §1 | passing (see `artifacts/test_output.txt`) |
| Long-term reliability / 3 a.m. | `docs/05` §2 | design |
| **D. Working log** | `docs/06` | AI session recorded; **candidate section to complete** |
| **Before sending (candidate)** | | |
| Fill in time spent | `docs/06` §3, `docs/submission_email.md` | ☐ |
| Read and own every position in `docs/01` | | ☐ |
| Attach the session export or state it is unavailable | `docs/06` §3 | ☐ |
| Reply to Sangeeta's 4 Nov email, cc **sudhanshu@fourkites.com** (brief §10) | `docs/submission_email.md` | ☐ |
| Merge PR #1 so the repository link shows this work; the workbook is not committed (git-ignored) | GitHub PR #1 | ☐ |
