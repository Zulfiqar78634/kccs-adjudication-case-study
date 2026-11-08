# Covering note (draft — edit before sending)

**To:** sudhanshu@fourkites.com *(the address given in the brief, §10; the brief does not mention a "Sangeeta". Please confirm before sending)*
**Subject:** Adjudication case study submission — Zulfiqar

Hi Sudhanshu,

Please find attached my submission for the Sentinel adjudication case study as a single archive (`kccs_submission_zulfiqar.zip`). The workbook itself is not included.

Summary of where I landed:

- **The problem is evidence, not prediction.** I built the piece I think is hardest to get right: a tenant-scoped, temporally correct evidence-resolution and replay kernel. It runs against the supplied workbook, turns each alert into a reproducible assessment (or an explicit abstention with named reasons), and keeps the regulatory notification clock independent of the disposition.
- **It reproduces EXC-107133 from the data alone.** It resolves the GTIN within Kaveri, detects the SOP-KAV-9392 Rev 02/Rev 03 overlap, rejects the vial/accelerated study the product master points to, and surfaces the unreferenced pen study STB-2738 together with its conflict with the master's allowance.
- **Proposed first customer:** Kaveri. The submission also contains the HLD/LLD, a data-quality report, an honest working log (including where the AI was wrong), and a challenge to two board targets (the denominator for automated closure, and "no late notifications" as a software guarantee).

To run: place the workbook in `data/`, then run `scripts/run_all.sh`. The README lists the step-by-step commands.

Time spent: **[fill in honestly]** hours. I used an AI coding agent heavily, as the brief invited. `docs/06_working_log.md` records what it produced, what was corrected, and my own review notes.

Best regards,
Zulfiqar
