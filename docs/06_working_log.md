# 06 — Working log (this session)

**Honesty statement.** This repository was produced in **one AI-assisted session on 2026-11-08** using an AI coding agent (Hoplite, model `claude-opus-5-5`) on Zulfiqar's instruction. The agent wrote the code, tests and documents. The entries below record what was actually done and observed in that session, from the tool outputs. They are not reconstructed from memory, and nothing is invented about earlier sessions. **Zulfiqar's own review, disagreements and time spent are not yet recorded.** Section 3 is for that, and it should be completed before submission. Chain-of-thought is not reproduced; only decisions and the evidence for them.

## 1. Session steps

| # | Question / hypothesis | Evidence examined | Considered | Kept / rejected and why | Mistake or uncertainty → how detected | Files / decisions |
|---|---|---|---|---|---|---|
| 1 | What is in the workspace? | repo listing, `git log` | Build on the existing scaffold vs replace it | **Replaced.** The scaffold (~1,300 lines) had a rules function that read `triage_outcome` as an input (outcome leakage) and invented confidence numbers | Found by reading `prototype/src/adjudication/rules/engine.py`; old code kept in git history (`9f98e8e`) | whole repo |
| 2 | What does the brief actually ask? | full PDF (8 pages) via `pdftotext` | — | Noted: deliverables A–D; the brief's contact is **sudhanshu@fourkites.com**. I first wrongly concluded "Sangeeta" was not involved; the candidate then shared her 4 Nov instructions email, so the cover note now replies to her and copies Sudhanshu | Tool condenser summarised long outputs; switched to small slices so the raw text was read | email draft |
| 3 | Is the core problem evidence, not prediction? | `09` (24 reasons), `14` (6 incidents), `10` (12 questions) | Prompt/model improvement vs evidence kernel | Hypothesis **kept with refinement**: evidence must be temporally qualified (AUD-2603 vs INC-2506) | ~20/24 is my reading of the reasons, not a computed figure; stated as such | `01` §1 |
| 4 | Profile all 15 tabs | per-sheet scripts in `scratch/` (inline heredocs were blocked by the sandbox) | pandas vs openpyxl | **openpyxl only**: keeps raw types and GTIN strings; fewer dependencies | — | `sources.py` |
| 5 | Interval convention for SOPs | `05` windows | closed vs half-open | **Half-open**: 115 hand-overs have `to == next from` | — | `temporal.py` |
| 6 | Can `07` aliases resolve products? | `07` has no tenant column; `12!R6` Cl.22 | use as lookup / use as hint / quarantine | **Quarantine product aliases**; facility/carrier aliases allowed as provisional hints | Trade-off: 81 product refs stay unresolved. Accepted and shown in the summary | `access.py`, config |
| 7 | EXC-107133 evidence chain | `02!R57`, `06!R105–108`, `05!R202–204`, `08` QL-02111 | — | Found: master references a vial accelerated study (STB-3584); pen study STB-2738 unreferenced; Rev 02/03 overlap; brief 09:30 UTC vs log 06:54 UTC | — | `04` |
| 8 | First full run over 420 events | smoke run | — | — | **Wrong assumption:** only "Temperature Excursion Management" governs excursions. 164 `NO_SOP_INDEXED` = all of T-VIRENT. Kept as a real finding; the message now lists the tenant's other titles without assuming them | `policy_sop.py` |
| 9 | Presentation check | EXC-107133 output | token set over the whole study text | — | **Bug:** brand token "SoloJet" made "Glucodyne SoloJet — vial" look like a pen. Detected because the expected mismatch was missing from STB-3584's rejection reasons. Fixed: explicit presentation words beat brand-derived tokens | `stability.py`, lexicon |
| 10 | Evaluate against override reasons | evaluation table | — | — | **Bug:** EXC-110497 NOT_SURFACED. "Rinvatec PFS 40 — vial" contains "PFS" in the product name. Fixed: a study's presentation comes from its suffix after "—" or the trailing parenthesis | `study_presentations()` |
| 11 | Same | evaluation table | — | — | **Self-serving check caught:** the EXC-110581 expectation accepted any `CARRIER_RESOLVED`, so it would "pass" whatever contract was picked. Changed to require CNT-2023-0441 (the GmbH) | `evaluation.py` |
| 12 | Conflict spike | case-specific blockers jumped to 150 after fix 10 | — | — | Product-master "Refer QA" was being compared as a competing limit. It is a deferral, already flagged separately; excluded from the conflict check (116 after the fix) | `stability.py` |
| 13 | Correction demo | `demo_run.json`: `replay_at_alert_after_correction_same_id: false` | — | — | **Temporal leak bug:** reconstructed replay read the store "as now", so a correction recorded on 2026-09-20 leaked into the at-alert replay. Fixed with a store cutoff of max(cutoff, baseline snapshot). Regression test added | `assessment.py`, `test_correction_produces_new_assessment…` |
| 14 | Test failures | pytest output | — | — | (a) Append-only trigger test passed vacuously on empty tables: insert rows first. (b) Strict mode could not see the alert itself: subject alert taken from the access-checked view. (c) "recommend" check matched the phrase "Not a recommendation": tightened to disposition values. (d) `"notes"` is a generic key: excluded from the static outcome-field scan | tests |
| 15 | Demo hygiene | `artifacts/packages` held 32 directories | — | — | Stale outputs from earlier runs: demo now clears its own subdirectories | `cli.py` |
| 16 | Remaining honest gaps | evaluation | retrofit expectations to pass | **Rejected retrofitting.** EXC-110476 stays NOT_SURFACED; EXC-110602 SURFACED_ONLY_GENERICALLY | — | `05` |
| 17 | Docs consistency | own numbers | — | — | Wrote "57 annexure revisions" in `04`; recount from the profile gave 102 (40+33+29). Corrected | `04` |
| 18 | Final check against a fresh clone | clean-clone `run_all.sh` artifacts | — | — | **Stale claims:** the docs said "every event has a case-specific blocker" (true before fix 12) and "42 packages". The clean run shows 8 events with only pack-wide gaps (4 T-CAMPOS, 4 T-PINNACLE) and 6 packages. Docs corrected from the clean-run output | `05`, `07`, `FINAL_REPORT.md` |

Discarded approaches, with reasons:
- **Ranking ambiguous candidates:** it hides conflicts the reviewer must see.
- **Fuzzy product matching:** this is exactly how the wrong presentation gets picked.
- **Treating 1.8 °C as a fixed correction:** the bulletin says "up to".
- **Using `reg_window_hours=24` as "next business day":** it is not equivalent.
- **Shipping a dashboard:** the brief asks for the hardest part, not the most demonstrable.
- **Self-hosted model for prohibited tenants:** one instance is $4,139/month, above the budget.

## 2. Where the AI was confidently wrong (and how it was caught)

1. Assumed a single SOP title governs excursions for all tenants. Caught by the 164-count spike on T-VIRENT (step 8).
2. Presentation logic was wrong twice, in two different ways (steps 9 and 10). Caught by reading a real case output and by the override evaluation.
3. Believed reconstructed replay was leak-free. Caught by the correction demo's own reproducibility check (step 13).
4. Wrote evaluation expectations that could not fail (step 11), and a test that passed vacuously (step 14a).
5. Stated a wrong count in a document (step 17).

Pattern: every error was caught by a check that compared the output against **a specific real record** or **a reproducibility invariant**, not by re-reading code.

## 3. Candidate review (to complete by Zulfiqar before submission)

- [ ] Time actually spent (hours): ______
- [ ] Sections I disagree with and my position: ______
- [ ] Where I overruled the AI, and where I was wrong to: ______
- [ ] Chat/session export attached? Export this conversation from the Hoplite thread, redact nothing confidential that the brief did not already contain, and save it as `docs/session_export.md` (or state that it is unavailable).
