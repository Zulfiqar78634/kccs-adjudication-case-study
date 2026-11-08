# Covering note (reply to Sangeeta's 4 Nov 2026 "Case Study Instructions" email)

**To:** Sangeeta S · **Cc:** sudhanshu@fourkites.com (submission address in the brief, §10)
**Subject:** Re: Case Study Instructions — Zulfiqar's submission

Hi Sangeeta,

Thank you for sharing the case study. My submission is in this GitHub repository:

**https://github.com/Zulfiqar78634/kccs-adjudication-case-study**

The best place to start is `FINAL_REPORT.md`, which is a short overview of the whole submission. Below is where each of the four parts you asked for can be found.

**1. Where I land** (`docs/01_where_we_land.md`)
- **My view of the problem.** The hard part is not predicting a disposition. It is assembling a trustworthy, customer-separated, date-correct body of evidence that a named QA reviewer can sign against, and keeping it reproducible for seven years. The reviewer workshop questions, the 24 written override reasons and the six incidents in the pack all point this way.
- **Requirements.** A table of 16 requirements, each traced to the brief section or the workbook tab and row that led to it, with an acceptance test and a phase.
- **What I am deliberately not building, with reasons.**
  - Automated product disposition.
  - An immediate replacement of the rules engine.
  - Models or search indexes shared across customers.
  - A large master-data programme.
  - Microservices.
- **Phased rollout.**
  - The proposed first customer is **Kaveri Health Distribution**, live within 90 days of design sign-off.
  - Other customers follow in waves by constraint type, reaching all 34 within nine months.
  - Each phase has named readiness gates and rollback criteria. Unknowns are stated openly.
- **Where the brief is silent or contradictory, and my positions.** A register of these, for example:
  - The case example's alert time (06:31) differs from the excursion start (06:14).
  - Kaveri's product master points to a vial stability study for an insulin pen.
  - "Next business day" is recorded in the pack as 24 hours.
  - The largest customer has no excursion SOP indexed.
- **Board targets I challenge, with counter-proposals.**
  - The 70% automated-closure target needs a defined denominator, and must cover only closures that involve no product decision.
  - The median-time target hides the long tail of lab waits.
  - "No late notifications" cannot be guaranteed by software alone. I propose measurable commitments instead.

**2. The design** (`docs/02_architecture_hld.md`, `docs/03_detailed_design_lld.md`)
- **Architecture.** A modular monolith with background workers, deployed in regional cells (EU, India, Americas) to meet data-residency clauses. The reason for each component boundary is stated.
- **Data model.** Covers "valid time" and "known time", and supports "as at a date" queries. Nothing is ever overwritten: corrections create new versions, and the originally signed record is kept.
- **Case lifecycle.** A full state-transition table covering waiting for carrier or lab data, manual steps, dual signatures, concurrent reviewers, and reopening a case months later (for example after a sensor calibration bulletin).
- **Regulatory notification.** Runs as a separate clock that starts when the alert is received. Waiting on evidence never pauses it.
- **Degradation.** What happens when each component is unavailable, and how that affects the regulatory clock.
- **Versioning and deployment.**
  - Every change replays historical cases per customer before release.
  - QA approves the replay results.
  - Changes go through shadow mode, then a canary release, with rollback and emergency switch-off.
- **Cost.** Based on the tab 13 price list. The design uses about USD 575 of the roughly USD 2,940 monthly ceiling. It also explains why "no language model" is a supported option for customers who prohibit external model APIs.
- **Diagrams.** Architecture, assessment sequence, case lifecycle, notification lifecycle, and data relationships.

**3. Working prototype** (`src/`, `tests/`, `docs/05_validation_and_operations.md`)
- **What I built.** The component I consider hardest to get right: an evidence-resolution and replay engine. It runs against the supplied workbook, not dummy data. For any alert, it:
  - resolves product, site and carrier using only that customer's data;
  - selects the SOP revision in force on the date, and flags overlapping revisions as conflicts;
  - checks that stability studies belong to the customer, match the presentation and are readable;
  - produces a reproducible evidence package with integrity hashes;
  - declines to conclude where the evidence is insufficient.
- **The brief's own case.** For EXC-107133, the prototype reproduces the issues the reviewer faced, using the data alone.
- **Stubs.** External systems such as the temperature-series archive and document content are stubbed and clearly labelled.
- **Validation.**
  - 76 automated tests pass, covering customer isolation, date boundaries, replay without later knowledge, corrections, firmware uncertainty and notification deadlines.
  - The documentation explains how failures would be detected in production, six months from now.

**4. Working log** (`docs/06_working_log.md`)
- A step-by-step record of the session: discarded approaches, assumptions that proved wrong, how each was caught (for example a date-leak bug found by the replay check), and why direction changed.
- I used an AI coding assistant heavily, as the brief invited. The log is explicit about what it produced and where it was wrong.

**To run the prototype:** place the workbook in the `data/` folder and run `scripts/run_all.sh`. Full instructions are in the README. The confidential workbook itself is not included in the repository.

Time spent: **[fill in] hours.**

I look forward to the discussion. Please let me know if you have any trouble accessing the repository.

Best regards,
Zulfiqar
