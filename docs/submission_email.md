# Covering note (draft — send as a reply to Sangeeta's 4 Nov 2026 email)

**To:** Sangeeta S (reply to the "Case Study Instructions" email)
**Cc:** sudhanshu@fourkites.com (the submission address given in the brief, §10)
**Subject:** Re: Case Study Instructions — Zulfiqar's submission

Hi Sangeeta,

Please find my case study submission attached as a single archive (`kccs_submission_zulfiqar.zip`). The confidential workbook is not included. It follows the four parts you listed:

1. **Where I land:** `docs/01_where_we_land.md`. It covers requirements mapped to the brief and pack, what I am deliberately not building, a phased rollout with Kaveri as the first customer, contradictions and the positions I took, and the board targets I challenge.
2. **The design:** `docs/02_architecture_hld.md` and `docs/03_detailed_design_lld.md`. These cover components and boundaries, the data model including "as at a date" queries, the case lifecycle and reopening, degradation and the regulatory clock, versioning and deployment, and diagrams.
3. **Working prototype:** `src/` and `tests/`. It is a tenant-scoped, time-correct evidence-resolution and replay kernel that runs against the supplied workbook, with 76 tests passing. Validation and monitoring are covered in `docs/05_validation_and_operations.md`.
4. **Working log:** `docs/06_working_log.md`. It records discarded approaches, assumptions that turned out wrong and how they were caught, and changes of direction.

`FINAL_REPORT.md` is a short overview. To run the prototype, place the workbook in `data/` and run `scripts/run_all.sh`.

Time spent: **[fill in honestly]** hours. I used an AI coding assistant heavily, as the brief invited. The working log records what it produced and where it was wrong.

Best regards,
Zulfiqar
